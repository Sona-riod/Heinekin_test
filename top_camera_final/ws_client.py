# ws_client.py
# =============================================================================
# Maintains a persistent Socket.IO connection to the cloud.
#
# Reliability features
# ────────────────────
#   • Exponential back-off  – 5 s → 10 s → 20 s … capped at 60 s
#   • _stop_event           – clean shutdown on app exit (no zombie threads)
#   • Re-registers on every reconnect so the server always knows our MAC
#   • Wraps all callbacks in try/except so a bad message can't kill the loop
#   • Bug fix: original used self.logger which doesn't exist; uses module
#     logger throughout
# =============================================================================

import threading
import time
from typing import Callable, Dict, Any, Optional

import socketio

from config import WEBSOCKET_CONFIG, SYSTEM_CONFIG, logger

_BACKOFF_BASE    = 5    # seconds before first retry
_BACKOFF_MAX     = 60   # maximum wait between retries
_BACKOFF_FACTOR  = 2    # multiply wait by this after each failure


class CloudWebSocket:

    def __init__(
        self,
        on_response:           Callable[[Dict[str, Any]], None],
        on_connection_change:  Optional[Callable[[str], None]] = None,
    ):
        self.url          = WEBSOCKET_CONFIG['url']
        self.mac_id       = SYSTEM_CONFIG['mac_id']
        self.forklift_id  = SYSTEM_CONFIG['forklift_id']

        self.on_response          = on_response
        self.on_connection_change = on_connection_change

        self.is_connected = False
        self._stop_event  = threading.Event()
        self._backoff     = _BACKOFF_BASE

        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self._register_sio_events()

        t = threading.Thread(
            target=self._connection_loop,
            name='WS-ConnectionLoop',
            daemon=True,
        )
        t.start()

    # =========================================================================
    # SOCKET.IO EVENT HANDLERS
    # =========================================================================

    def _register_sio_events(self) -> None:

        @self.sio.event
        def connect():
            self.is_connected = True
            self._backoff     = _BACKOFF_BASE   # reset on success
            logger.info(f"WebSocket: connected to {self.url}")
            self._notify_status('connected')
            self._register_device()

        @self.sio.event
        def disconnect():
            self.is_connected = False
            logger.warning("WebSocket: disconnected")
            self._notify_status('disconnected')

        @self.sio.event
        def connect_error(data):
            self.is_connected = False
            logger.error(f"WebSocket: connection error – {data}")
            self._notify_status('disconnected')

        @self.sio.on('message')
        def on_broadcast(data):
            logger.debug(f"WebSocket broadcast: {data}")
            self._handle_message(data)

        # Personal channel keyed by MAC address – cloud sends location popups here
        @self.sio.on(self.mac_id)
        def on_personal(data):
            logger.info(f"WebSocket personal msg: {data}")
            self._handle_message(data)

    # =========================================================================
    # MESSAGE HANDLING
    # =========================================================================

    def _handle_message(self, data) -> None:
        """
        Normalise incoming data and forward to the UI callback.
        Strings are treated as bare location names.
        """
        try:
            if isinstance(data, str):
                payload = {'type': 'location_update', 'location': data}
            else:
                payload = data
            self.on_response(payload)
        except Exception as exc:
            logger.error(f"WebSocket message handler error: {exc}")

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    def _register_device(self) -> None:
        """Tell the server who we are so it can route location popups to us."""
        try:
            self.sio.send({
                'type':        'register',
                'forklift_id': self.forklift_id,
                'mac_id':      self.mac_id,
                'device_type': 'top_camera',
            })
            logger.info(f"WebSocket: registered as {self.forklift_id} / {self.mac_id}")
        except Exception as exc:
            logger.error(f"WebSocket: registration failed – {exc}")

    # =========================================================================
    # CONNECTION LOOP  (background thread)
    # =========================================================================

    def _connection_loop(self) -> None:
        """
        Keep the connection alive until stop() is called.
        Uses exponential back-off after each failed attempt.
        """
        while not self._stop_event.is_set():
            if self.is_connected:
                time.sleep(1)
                continue

            self._notify_status('connecting')
            try:
                self.sio.connect(
                    self.url,
                    wait_timeout=WEBSOCKET_CONFIG.get('connect_timeout', 5),
                )
                self.sio.wait()   # blocks until disconnect

            except Exception as exc:
                logger.error(f"WebSocket: connect attempt failed – {exc}")
                self._notify_status('disconnected')
                self._safe_disconnect()

            # Exponential back-off before next retry
            if not self._stop_event.is_set():
                logger.info(f"WebSocket: retrying in {self._backoff} s…")
                self._stop_event.wait(timeout=self._backoff)
                self._backoff = min(self._backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    def _safe_disconnect(self) -> None:
        try:
            self.sio.disconnect()
        except Exception:
            pass

    # =========================================================================
    # STATUS HELPER
    # =========================================================================

    def _notify_status(self, status: str) -> None:
        if self.on_connection_change:
            try:
                self.on_connection_change(status)
            except Exception as exc:
                logger.error(f"WebSocket status callback error: {exc}")

    # =========================================================================
    # SHUTDOWN
    # =========================================================================

    def stop(self) -> None:
        """Signal the connection loop to exit and close the socket cleanly."""
        logger.info("WebSocket: stopping…")
        self._stop_event.set()
        self._safe_disconnect()