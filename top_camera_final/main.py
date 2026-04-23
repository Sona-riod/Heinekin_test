# main.py
# =============================================================================
# Application entry point for the GPU-Accelerated Top Camera Palletiser.
#
# Startup sequence
# ────────────────
#   1. Parse CLI flags (--recover)
#   2. Configure Kivy window before any Kivy import triggers the display
#   3. Show splash screen immediately
#   4. Background thread: GPU check → camera → models → WebSocket
#   5. Switch to main HMI once everything is ready
#
# Crash safety
# ────────────
#   • sys.excepthook  – catches any unhandled exception on the main thread
#   • threading.excepthook – catches unhandled exceptions on worker threads
#   • SIGTERM / SIGINT    – clean shutdown (camera released, WS closed)
#   • _write_crash_log()  – writes crash.log next to main.py so operators
#                           can inspect what went wrong after a hard restart
#   • Heartbeat file      – updated every second; an external watchdog can
#                           restart the process if the file goes stale
# =============================================================================

import sys
import signal
import threading
import time
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

# ── crash log (written before anything else is imported) ─────────────────────
_BASE_DIR   = Path(__file__).parent
_CRASH_LOG  = _BASE_DIR / 'crash.log'
_HEARTBEAT  = _BASE_DIR / 'heartbeat.txt'


def _write_crash_log(exc_type, exc_value, exc_tb) -> None:
    """Append a timestamped traceback to crash.log."""
    try:
        with _CRASH_LOG.open('a', encoding='utf-8') as f:
            f.write('\n' + '=' * 60 + '\n')
            f.write(f"CRASH  {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    except Exception:
        pass   # if we can't even write the crash log, give up silently


def _global_exception_handler(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook – handles uncaught exceptions on the main thread."""
    _write_crash_log(exc_type, exc_value, exc_tb)
    print(f"\nCRITICAL: unhandled exception – {exc_value}", file=sys.stderr)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_exception_handler(args) -> None:
    """threading.excepthook – handles uncaught exceptions on worker threads."""
    _write_crash_log(args.exc_type, args.exc_value, args.exc_traceback)
    print(
        f"\nCRITICAL: unhandled exception in thread "
        f"'{args.thread.name}' – {args.exc_value}",
        file=sys.stderr,
    )


sys.excepthook        = _global_exception_handler
threading.excepthook  = _thread_exception_handler

# ─────────────────────────────────────────────────────────────────────────────

import argparse

parser = argparse.ArgumentParser(description='Top Camera Palletiser')
parser.add_argument(
    '--recover', action='store_true',
    help='Restore the last interrupted pallet session on startup',
)
args, _ = parser.parse_known_args()
RECOVER_MODE: bool = args.recover

# ── GPU + config (before Kivy) ────────────────────────────────────────────────
from gpu_utils import detect_gpu, warm_up_gpu, GPU_STATUS
from config import UI_CONFIG, THEME_CONFIG, SYSTEM_CONFIG, logger

# ── Kivy display config (must happen before any Kivy window import) ───────────
from kivy.config import Config

_fs = UI_CONFIG.get('fullscreen', 'auto')
Config.set('graphics', 'fullscreen', str(_fs))
Config.set('graphics', 'show_cursor',
           '1' if UI_CONFIG.get('show_cursor', True) else '0')
Config.set('input', 'mouse', 'mouse,disable_multitouch')
Config.write()

# ── Kivy / KivyMD ─────────────────────────────────────────────────────────────
from kivy.clock import Clock
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from splash import SplashScreen
from camera import TopCameraManager
from pallet_controller import CustomPalletController
from hmi import ProfessionalTopCameraHMI
from ws_client import CloudWebSocket
from printer import ZebraPrinter


# =============================================================================
# Heartbeat  (external watchdog reads this file)
# =============================================================================

def _heartbeat_loop() -> None:
    while True:
        try:
            _HEARTBEAT.write_text(str(time.time()))
        except Exception as exc:
            logger.warning(f"Heartbeat write failed: {exc}")
        time.sleep(1)


# =============================================================================
# Application
# =============================================================================

class TopCameraApp(MDApp):

    def build(self):
        self.theme_cls.theme_style     = THEME_CONFIG['theme_style']
        self.theme_cls.primary_palette = THEME_CONFIG['primary_palette']
        self.theme_cls.accent_palette  = THEME_CONFIG['accent_palette']

        self.sm     = MDScreenManager()
        self.splash = SplashScreen(name='splash')
        self.sm.add_widget(self.splash)

        # Initialise these to None so on_stop() guards are safe
        self.top_camera: TopCameraManager | None   = None
        self.controller: CustomPalletController | None = None
        self.ws_client:  CloudWebSocket | None     = None
        self.hmi:        ProfessionalTopCameraHMI | None = None
        self.printer:    ZebraPrinter | None       = None

        threading.Thread(
            target=self._startup_thread,
            name='StartupThread',
            daemon=True,
        ).start()
        threading.Thread(
            target=_heartbeat_loop,
            name='HeartbeatThread',
            daemon=True,
        ).start()

        return self.sm

    # ── startup sequence ──────────────────────────────────────────────────

    def _startup_thread(self) -> None:
        try:
            # 1. GPU
            self._splash('Checking GPU…')
            detect_gpu()
            if GPU_STATUS['cuda_available']:
                warm_up_gpu()
                self._splash(f"GPU ready: {GPU_STATUS['gpu_name']}")
            else:
                self._splash('Running on CPU')
            time.sleep(UI_CONFIG.get('splash_min_time', 1.5) * 0.4)

            # 2. Camera
            self._splash('Initialising camera…')
            self.top_camera = TopCameraManager()
            if not self.top_camera.start():
                logger.warning('Camera start failed – dummy mode active')
                self._splash('Camera error – using dummy feed')
            else:
                self._splash('Camera ready')

            # 3. AI models + session state
            self._splash(f"Loading AI models… (recover={RECOVER_MODE})")
            self.controller = CustomPalletController(recover=RECOVER_MODE)
            self._splash('Detection models loaded')

            # 4. Printer
            self._splash('Initialising printer…')
            self.printer = ZebraPrinter()

            # 5. WebSocket
            self._splash('Connecting to cloud…')
            self._init_websocket()

            # 6. Launch HMI
            self._splash('Building interface…')
            Clock.schedule_once(
                self._switch_to_main,
                UI_CONFIG.get('splash_min_time', 1.5) * 0.6,
            )

        except Exception as exc:
            logger.critical(f'Startup failed: {exc}', exc_info=True)
            self._splash(f'Startup error: {exc}')

    def _splash(self, text: str) -> None:
        if hasattr(self, 'splash') and self.splash:
            self.splash.update_status(text)

    def _switch_to_main(self, dt) -> None:
        try:
            self.hmi = ProfessionalTopCameraHMI(
                top_camera=self.top_camera,
                controller=self.controller,
                printer=self.printer,
                name='main',
            )
            self.sm.add_widget(self.hmi)
            self.sm.current = 'main'
            logger.info('Application ready.')
        except Exception as exc:
            logger.critical(f'Failed to launch HMI: {exc}', exc_info=True)
            self._splash(f'UI error: {exc}')

    # ── WebSocket ─────────────────────────────────────────────────────────

    def _init_websocket(self) -> None:

        def on_message(data: dict) -> None:
            try:
                if data.get('type') == 'location_update' or 'location' in data:
                    logger.info(f'WS location update: {data}')
                    if self.hmi:
                        self.hmi.on_websocket_message(data)
            except Exception as exc:
                logger.error(f'WS message handler error: {exc}')

        def on_status(status: str) -> None:
            logger.info(f'WS status: {status}')
            if self.hmi:
                self.hmi.set_ws_status(status)

        self.ws_client = CloudWebSocket(
            on_response=on_message,
            on_connection_change=on_status,
        )

    # ── clean shutdown ────────────────────────────────────────────────────

    def on_stop(self) -> None:
        logger.info('Application shutting down…')
        if self.ws_client:
            self.ws_client.stop()
        if self.top_camera:
            self.top_camera.stop()
        logger.info('Shutdown complete.')


# =============================================================================
# Signal handlers  (SIGTERM / SIGINT from OS or watchdog)
# =============================================================================

def _handle_signal(signum, frame) -> None:
    sig_name = signal.Signals(signum).name
    logger.warning(f'Received {sig_name} – requesting clean shutdown…')
    try:
        app = MDApp.get_running_app()
        if app:
            app.stop()
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# =============================================================================
# Entry point
# =============================================================================

if __name__ == '__main__':
    logger.info(
        f'Starting Top Camera Palletiser  '
        f'(recover={RECOVER_MODE}, '
        f'device={SYSTEM_CONFIG.get("forklift_id")})'
    )
    try:
        TopCameraApp().run()
    except Exception as exc:
        logger.critical(f'Unhandled top-level exception: {exc}', exc_info=True)
        sys.exit(1)