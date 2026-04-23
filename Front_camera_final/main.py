import cv2
import time
import threading
import traceback
from typing import Dict, Any
from kivy.clock import Clock

# --- STRICT IMPORTS (No Mocks) ---
from utils import CONFIG, ForkliftLogger, RECENT_CACHE, ACCUMULATED_TRACKER, fetch_customer_details
from qr_detector import QRDetector
from websocket_client import CloudWebSocket
from camera import CameraManager
from hmi import ForkliftHMIApp

# --- GPU ACCELERATION ---
from gpu_utils import init_gpu, is_gpu_available, get_gpu_processor

# Constants
STORAGE_AREA = "Storage Area"
DISPATCH_AREA = "Dispatch Area"

class ForkliftFrontSystem:
    def __init__(self):
        self.config = CONFIG
        self.logger = ForkliftLogger.setup(self.config['system']['log_level'])
        
        self.gpu_info = None
        self.gpu_processor = None
        self.use_gpu = False
        self.camera_manager = None
        self.qr_detector = None
        self.ws = None
        
        self.last_qrs = []
        self.last_count = 0
        self.current_location = "neutral"
        self.detection_active = False # Default to False (Manual Mode)
        self.hmi = None
        self.running = True
        
    def initialize_components(self):
        """Heavy initialization to run in background thread"""
        self.logger.info("Initializing components...")
        
        # 1. GPU Initialization
        if self.hmi: self.hmi.update_splash_status("Initializing GPU...")
        self.logger.info("Initializing GPU...")
        print("\n" + "="*60)
        print("    FORKLIFT FRONT CAMERA SYSTEM - GPU INITIALIZATION")
        print("="*60)
        self.gpu_info = init_gpu()
        self.gpu_processor = get_gpu_processor()
        self.use_gpu = is_gpu_available()
        self._print_gpu_summary()
        time.sleep(1) # Visual delay for splash
        
        # 2. Camera Initialization
        if self.hmi: self.hmi.update_splash_status("Starting Camera...")
        self.logger.info("Starting Camera...")
        self.camera_manager = CameraManager(self.config, self.logger)
        time.sleep(0.5)
        
        # 3. QR Detector Initialization
        if self.hmi: self.hmi.update_splash_status("Loading AI Models...")
        self.logger.info("Loading QR Detector...")
        try:
            self.qr_detector = QRDetector(self.config)
        except Exception as e:
            self.logger.critical(f"Failed to initialize QR detector: {e}")
            raise e
        time.sleep(0.5)

        # 4. WebSocket Initialization
        if self.hmi: self.hmi.update_splash_status("Connecting to Cloud...")
        self.logger.info("Connecting to Cloud...")
        try:
            self.ws = CloudWebSocket(self.config, self.ws_response, self.ws_status)
        except Exception as e:
            self.logger.error(f"Failed to initialize WebSocket: {e}")
            self.ws = None
        time.sleep(0.5)
        
        # 5. Fetch customers
        if self.hmi: self.hmi.update_splash_status("Fetching Data...")
        self._fetch_and_update_customers()
        
        self.logger.info("Initialization Complete.")

        
        self.fps_counter = 0
        self.fps_start_time = time.time()
        self.current_fps = 0
        

    # --- WEBSOCKET HANDLERS ---
    def ws_response(self, data: Dict[str, Any]):
        """Handle messages FROM Cloud"""
        try:
            self.logger.info(f"Cloud message: {data}")
            
            msg_type = data.get("type")
            
            if msg_type == "location_update":
                self._handle_location_update(data)
            
            elif msg_type == "confirmation_request":
                self._handle_confirmation_request(data)
            
            elif data.get("status"):
                self.logger.info(f"Server response: {data['status']}")
                
        except Exception as e:
            self.logger.error(f"Error processing WebSocket response: {e}")

    def _handle_location_update(self, data: Dict[str, Any]):
        new_loc = data.get("location", "neutral")
        old_loc = self.current_location
        
        self.current_location = new_loc
        
        if self.hmi and self.hmi.root_widget:
            # Update Zone Indicator
            Clock.schedule_once(lambda dt: self.hmi.root_widget.update_zone_status(new_loc))
            
            # LOGIC: Storage Popup (Only if location CHANGED)
            if new_loc == STORAGE_AREA and old_loc != STORAGE_AREA:
                self.logger.info("Entering Storage - Triggering Location Popup")
                Clock.schedule_once(lambda dt: self.hmi.root_widget.show_storage_popup(self.last_count, show_details=False))
            
            # LOGIC: Dispatch Popup (Only if location CHANGED)
            elif new_loc == DISPATCH_AREA and old_loc != DISPATCH_AREA:
                self.logger.info("Entering Dispatch - Triggering Location Popup")
                Clock.schedule_once(lambda dt: self.hmi.root_widget.show_dispatch_popup())

    def _handle_confirmation_request(self, data: Dict[str, Any]):
        zone = data.get("zone", "storage")
        if self.hmi and self.hmi.root_widget:
            if zone == "storage" or zone == STORAGE_AREA:
                Clock.schedule_once(lambda dt: self.hmi.root_widget.show_storage_popup(self.last_count))
            elif zone == "dispatch":
                Clock.schedule_once(lambda dt: self.hmi.root_widget.show_dispatch_popup())
    
    def ws_confirm(self, data: Dict[str, Any]):
        """Handle 'Submit' button click"""
        try:
            # Cache QRs to prevent immediate re-detection
            for qr in self.last_qrs:
                RECENT_CACHE.add(qr.get('pallet_id'))
            
            from utils import get_mac_address
            data["mac_id"] = get_mac_address()
            data["forklift_id"] = self.config['system']['forklift_id']
            data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            data["location"] = self.current_location
            
            if self.ws and self.ws.send_pallet_data(data):
                self.logger.info("Confirmation sent to cloud")
                return True
            else:
                self.logger.warning("Failed to send confirmation")
                return False
        except Exception as e:
            self.logger.error(f"Error sending confirmation: {e}")
            return False
    
    def ws_status(self, status):
        if self.hmi and self.hmi.root_widget:
            Clock.schedule_once(lambda dt: self.hmi.root_widget.update_connection_status(status))

    def startup_wrapper(self):
        try:
            self.initialize_components()
            
            # Start Processing Threads
            self.frame_lock = threading.Lock()
            self.latest_frame = None
            self.new_frame_event = threading.Event()
            
            self.capture_thread = threading.Thread(target=self.run_capture_loop, daemon=True)
            self.detection_thread = threading.Thread(target=self.run_detection_loop, daemon=True)
            
            self.capture_thread.start()
            self.detection_thread.start()
            
            # Switch UI to Main
            if self.hmi:
                self.hmi.update_splash_status("Ready!")
                time.sleep(0.5)
                self.hmi.switch_to_main()
                
        except Exception as e:
            self.logger.error(f"Startup Failed: {e}")
            if self.hmi: self.hmi.update_splash_status(f"Error: {e}")

    
    def _fetch_and_update_customers(self):
        def fetch_thread():
            try:
                customers = fetch_customer_details()
                if self.hmi and self.hmi.root_widget:
                    Clock.schedule_once(lambda dt: self.hmi.root_widget.update_customer_list(customers))
            except Exception as e:
                self.logger.error(f"Error fetching customers: {e}")
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _print_gpu_summary(self):
        """Print final GPU configuration summary."""
        print("\n" + "="*60)
        print("         GPU ACCELERATION STATUS SUMMARY")
        print("="*60)
        
        if self.use_gpu:
            print("GPU ACCELERATION: ACTIVE")
            print(f"Device: {self.gpu_info.cuda_device_name}")
            print(f"OpenCV CUDA: {self.gpu_info.opencv_cuda_enabled}")
            print(f"CuPy Available: {self.gpu_info.cupy_available}")
            print("")
            print("Accelerated Operations:")
            print("    • Camera frame resize: GPU")
            print("    • Color conversion: GPU")
            print("    • Image preprocessing: GPU")
            print("    • QR Decoding: CPU (pyzbar)")
        else:
            print("GPU ACCELERATION: INACTIVE")
            print("All operations running on CPU")
            print("")
            print("To enable GPU acceleration:")
            print("1. Install NVIDIA CUDA Toolkit")
            print("2. Build OpenCV with CUDA support")
            print("3. Install cupy: pip install cupy-cuda12x")
        
        print("="*60)
        print("    System ready. Starting camera loop...")
        print("="*60 + "\n")
    
    def calculate_fps(self):
        self.fps_counter += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed >= 1.0:
            self.current_fps = self.fps_counter / elapsed
            self.logger.debug(f"FPS: {self.current_fps:.1f}")
            self.fps_counter = 0
            self.fps_start_time = time.time()
    
    def run_capture_loop(self):
        """Thread 1: High-speed camera capture (30 FPS)"""
        self.logger.info("[THREAD] Starting Capture Loop")
        consecutive_failures = 0
        
        while self.running:
            try:
                ret, frame = self.camera_manager.read_frame()
                
                if not ret:
                    consecutive_failures = self._handle_capture_error(consecutive_failures)
                    time.sleep(0.1)
                    continue
                
                consecutive_failures = 0
                self._update_camera_status(None) # Clear error
                
                # Update shared frame safely
                with self.frame_lock:
                    self.latest_frame = frame.copy() if frame is not None else None
                
                # Signal new frame available
                self.new_frame_event.set()
                
                # Update Preview
                self._update_preview(frame)
                
                self.calculate_fps()
                # Cap at ~30 FPS
                time.sleep(0.015) 

                
            except Exception as e:
                self.logger.error(f"Capture Loop Error: {e}")
                time.sleep(0.5)
        
        self.logger.info("[THREAD] Capture Loop Stopped")

    def _handle_capture_error(self, consecutive_failures):
        consecutive_failures += 1
        if consecutive_failures > 5:
            self._update_camera_status("CAMERA NOT INITIALIZED")
        return consecutive_failures

    def _update_preview(self, frame):
        """Update UI preview if detection is not active"""
        if self.detection_active:
            return
            
        frame_num = self.camera_manager.frame_count
        
        if self.hmi and self.hmi.root_widget:
            if frame_num % 30 == 1:
                print(f"[DEBUG] Capture Loop: Sending frame #{frame_num} to UI, shape: {frame.shape}")
            Clock.schedule_once(lambda dt, f=frame: self.hmi.root_widget.update_camera_feed(f))
        else:
            if frame_num % 30 == 1:
                print("[DEBUG] Capture Loop: hmi.root_widget is None, cannot send frame")

    def run_detection_loop(self):
        """Thread 2: Heavy detection processing (Best Effort)"""
        self.logger.info("[THREAD] Starting Detection Loop")
        
        while self.running:
            try:
                frame_to_process = self._wait_for_next_frame()
                if frame_to_process is None:
                    continue
                
                # Heavy Processing
                qrs, count, annotated_frame = self._run_detection(frame_to_process)
                
                # Update UI with results (Main Thread)
                self._update_ui_with_results(annotated_frame, count, qrs)
                
            except Exception as e:
                self.logger.error(f"Detection Loop Error: {e}")
                time.sleep(0.5)
        
        self.logger.info("[THREAD] Detection Loop Stopped")

    def _wait_for_next_frame(self):
        """Waits for a new frame and returns it if available."""
        if not self.new_frame_event.wait(timeout=0.1):
            return None
        
        self.new_frame_event.clear()
        
        # Get latest frame safely
        frame_to_process = None
        with self.frame_lock:
            if self.latest_frame is not None:
                frame_to_process = self.latest_frame.copy()
        
        if frame_to_process is None or not self.detection_active:
            time.sleep(0.05)
            return None
            
        return frame_to_process

    def _run_detection(self, frame):
        """Runs QR detection on the frame."""
        qrs, count = [], 0
        annotated_frame = frame

        if self.qr_detector:
            try:
                # Read the operator's current selection from the UI (thread-safe: set read)
                selected_ids = set()
                if self.hmi and self.hmi.root_widget:
                    selected_ids = set(self.hmi.root_widget.selected_pallet_ids)

                qrs, count, annotated_frame = self.qr_detector.detect_and_filter_qrs(
                    frame, selected_ids=selected_ids
                )
                for qr in qrs:
                    ACCUMULATED_TRACKER.add_detection(qr)
            except Exception as e:
                self.logger.warning(f"Detection Error: {e}")

        return qrs, count, annotated_frame

    def _update_ui_with_results(self, annotated_frame, count, qrs):
        """Updates the UI with detection results."""
        accumulated_count = ACCUMULATED_TRACKER.get_count()
        accumulated_qrs = ACCUMULATED_TRACKER.get_all_qrs()
        
        if self.hmi and self.hmi.root_widget:
            # Send annotated frame with bounding boxes to UI
            Clock.schedule_once(lambda dt, f=annotated_frame: self.hmi.root_widget.update_camera_feed(f))
            Clock.schedule_once(lambda dt, c=count, q=qrs, ac=accumulated_count, aq=accumulated_qrs: 
                               self.hmi.root_widget.update_info(c, q, ac, aq))

    def _update_camera_status(self, error_msg):
        if self.hmi and self.hmi.root_widget:
            if error_msg:
                 Clock.schedule_once(lambda dt: self.hmi.root_widget.set_camera_error(error_msg))
            else:
                 Clock.schedule_once(lambda dt: self.hmi.root_widget.clear_camera_error())

    def start(self):
        try:
            self.logger.info("Starting System...")
            
            # Initialize HMI
            mac_id = self.config['system'].get('mac_id', 'UNKNOWN')
            
            # Callbacks for HMI
            def start_capture_session():
                self.logger.info("Starting Capture Session")
                # NOTE: Do NOT reset ACCUMULATED_TRACKER here.
                # Pallets should persist across CAPTURE/STOP cycles.
                # Only the RESET button should clear them.
                self.detection_active = True
                
            def stop_capture_session():
                self.logger.info("Stopping Capture Session")
                self.detection_active = False

            self.hmi = ForkliftHMIApp(
                on_confirm=self.ws_confirm, 
                on_start_capture=start_capture_session, 
                on_stop_capture=stop_capture_session, 
                startup_callback=self.startup_wrapper,
                mac_id=mac_id
            )
            
            self.hmi.run()
        except KeyboardInterrupt:
            pass # Shutdown handled in finally
        except Exception as e:
            self.logger.error(traceback.format_exc())
            #self.logger.error(f"Fatal error: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        self.logger.info("Shutting down...")
        self.running = False
        
        # Stop Threads
        if self.camera_manager:
            self.camera_manager.release()
            
        # Close WebSocket
        if self.ws:
            self.ws.close()

if __name__ == "__main__":
    system = ForkliftFrontSystem()
    system.start()