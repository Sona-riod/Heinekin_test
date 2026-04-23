
import socketio
import json
import threading
import time
from typing import Callable, Optional, Dict, Any
from utils import ForkliftLogger, CONFIG, get_mac_address

class WebSocketError(Exception):
    pass

class CloudWebSocket:
    def __init__(self, config: Dict[str, Any], on_response: Callable[[Dict[str, Any]], None], on_connection_change: Optional[Callable[[str], None]] = None):
        self.config = config
        # CRITICAL: Use polling first to avoid 'rsv not implemented' (compression) errors
        self.sio = socketio.Client(logger=True, engineio_logger=True, request_timeout=10)
        self.url = config['websocket']['url'] 
        self.on_response = on_response
        self.on_connection_change = on_connection_change
        self.logger = ForkliftLogger.setup(config['system']['log_level'])
        self.is_connected = False
        
        self._setup_callbacks()
        self._start_connection_thread()
    
    def _setup_callbacks(self):
        @self.sio.event
        def connect():
            self.logger.info(f"Connected to server at {self.url}")
            self.is_connected = True
            if self.on_connection_change:
                self.on_connection_change("connected")
            
            self._register()
            
        @self.sio.event
        def disconnect():
            self.logger.warning("Disconnected from server")
            self.is_connected = False
            if self.on_connection_change:
                self.on_connection_change("disconnected")
        
        @self.sio.event
        def connect_error(data):
            self.logger.error(f"Connection error: {data}")
            self.is_connected = False
            if self.on_connection_change:
                self.on_connection_change("disconnected")

        @self.sio.on('message')
        def on_message(data):
            self.logger.debug(f"Received message: {data}")
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass
            self.on_response(data)
            
        @self.sio.on('response') # Handle specific event if server uses it
        def on_response_event(data):
            on_message(data)

        # Listen to personal channel (MAC address)
        mac_address = get_mac_address()
        @self.sio.on(mac_address)
        def on_personal_message(data):
            self.logger.info(f"Received personal message on {mac_address}: {data}")
            # Normalize string messages (like "Storage Area") to location updates
            if isinstance(data, str):
                normalized = {
                    "type": "location_update",
                    "location": data
                }
                self.on_response(normalized)
            else:
                self.on_response(data)

    def _register(self):
        mac_address = get_mac_address()
        forklift_id = self.config['system']['forklift_id']
        
        register_payload = {
            "type": "register",
            "forklift_id": forklift_id,
            "mac_id": mac_address,
            "device_type": "forklift_camera"
        }
        # Send as 'message' event which is standard for send()
        try:
            self.sio.send(register_payload)
            self.logger.info(f"Registered as {forklift_id}")
        except Exception as e:
            self.logger.error(f"Registration failed: {e}")

    def _attempt_connection(self):
        """Helper to handle connection attempt."""
        if self.on_connection_change:
            self.on_connection_change("connecting")
        
        # CRITICAL FIX: Add 'polling' to transports list to fix 'rsv' error
        self.sio.connect(self.url, transports=['polling', 'websocket'])
        self.sio.wait()

    def _handle_connection_error(self, e: Exception):
        """Helper to handle connection errors and cleanup."""
        self.logger.error(f"Connection failed: {e}")
        if self.on_connection_change:
            self.on_connection_change("disconnected")
        
        try:
            self.sio.disconnect()
        except Exception:
            pass

    def _connection_loop(self):
        """Main connection loop running in thread."""
        while True:
            if not self.is_connected:
                try:
                    self._attempt_connection()
                except Exception as e:
                    self._handle_connection_error(e)
                    time.sleep(5) # Reconnect delay
            else:
                time.sleep(1)

    def _start_connection_thread(self):
        t = threading.Thread(target=self._connection_loop, daemon=True)
        t.start()
    
    def send_pallet_data(self, data: Dict[str, Any]) -> bool:
        if not self.is_connected:
            self.logger.warning("WebSocket not connected")
            return False
        
        try:
            if "timestamp" not in data:
                import time
                data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Send as message event
            self.sio.send(data)
            self.logger.info(f"Sent pallet data: {data.get('action', 'unknown')}")
            return True
        except Exception as e:
            self.logger.error(f"Send failed: {e}")
            # Force reconnection on send failure to prevent zombie state
            self.logger.warning("Triggering reconnection due to send failure")
            self.is_connected = False
            try:
                self.sio.disconnect()
            except Exception:
                pass
            return False

    def close(self):
        """Close the WebSocket connection and stop the thread."""
        self.is_connected = False
        try:
            self.sio.disconnect()
            self.logger.info("WebSocket connection closed by user.")
        except Exception as e:
            self.logger.warning(f"Error closing WebSocket: {e}")

if __name__ == "__main__":
    config = CONFIG
    def mock_response(data):
        print(f"Mock response: {data}")
    
    ws = CloudWebSocket(config, mock_response)
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
