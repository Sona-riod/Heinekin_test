# camera.py - Top Camera Management
import cv2
import numpy as np
import time
import os
import threading
import queue
from config import TOP_CAMERA_CONFIG, logger

# Import GPU status
try:
    from gpu_utils import GPU_STATUS
except ImportError:
    GPU_STATUS = {'cuda_available': False}

class TopCameraManager:
    """Manages the ICAM-540 top-mounted camera with Threaded Capture"""
    
    def __init__(self):
        self.config = TOP_CAMERA_CONFIG
        self.logger = logger
        self.cap = None
        self.is_active = False
        self.frame_count = 0
        
        # Threaded Capture
        self.frame_queue = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.capture_thread = None
        
        # Initialize based on updated config
        # self._initialize_camera() # Moved to start() to control timing
    
    def _list_available_devices(self):
        """Helper to scan devices if connection fails"""
        self.logger.info("Scanning for available video devices...")
        available = []
        for i in range(20):  # Check video0 to video19
            if os.path.exists(f"/dev/video{i}"):
                available.append(i)
        self.logger.info(f"Available video devices: {available}")
        return available

    def _initialize_camera(self):
        """Initialize the top camera with ICAM-540 specific settings"""
        try:
            device = self.config.get('device', 10)
            width = self.config.get('width', 1920)
            height = self.config.get('height', 1080)
            fps = self.config.get('fps', 30)
            
            self.logger.info(f"Initializing ICAM-540 at /dev/video{device}: {width}x{height} @ {fps}fps")
            
            # Use appropriate backend based on config
            if self.config.get('type') == 'v4l2':
                backend = cv2.CAP_V4L2
            else:
                backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
                
            self.cap = cv2.VideoCapture(device, backend)
            
            if not self.cap.isOpened():
                self.logger.error(f"Failed to open camera at device {device}")
                # List available devices to help debug
                available_devs = self._list_available_devices()
                self.logger.warning(f"Did you mean one of these? {available_devs}")
                
                self._create_dummy_cap()
                return
            
            # Apply ICAM-540 Settings
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            
            # Verify settings
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            self.logger.info(f"Camera initialized: {actual_width}x{actual_height} @ {actual_fps:.1f}fps")
            self.is_active = True
            
        except Exception as e:
            self.logger.error(f"Top camera initialization error: {e}")
            self._create_dummy_cap()
    
    def _create_dummy_cap(self):
        """Create dummy camera for fallback"""
        self.logger.warning("Using DUMMY camera mode.")
        class DummyCap:
            def __init__(self, manager):
                self.manager = manager
                self.frame_count = 0
            
            def read(self):
                self.frame_count += 1
                time.sleep(0.033) # Simulate 30fps
                # Create black frame matching configured resolution
                h = self.manager.config.get('height', 1080)
                w = self.manager.config.get('width', 1920)
                frame = np.zeros((h, w, 3), dtype=np.uint8)
                
                # Add error text
                cv2.putText(frame, "CAMERA CONNECT FAIL", (100, 300),
                            cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
                cv2.putText(frame, "Check /dev/video10", (100, 450),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                return True, frame
            
            def is_opened(self): return True
            
            def release(self):
                """Release resources - nothing to do for dummy camera"""
                pass
                
            def set(self, prop, val):
                """Store property value"""
                if not hasattr(self, 'props'):
                    self.props = {}
                self.props[prop] = val
                return True
                
            def get(self, prop):
                """Retrieve property value"""
                if not hasattr(self, 'props'):
                    return 0
                return self.props.get(prop, 0)
        
        self.cap = DummyCap(self)
        self.is_active = False # Keep false to indicate issue, but it works
    
    def reinitialize(self):
        """Gracefully release and re-acquire the camera, specifically for ICAM-540."""
        self.logger.info("Attempting to reinitialize top camera...")
        print("[CAMERA] Attempting to reinitialize top camera...")
        
        # Release existing if any
        if self.cap and hasattr(self.cap, 'release'):
            try:
                self.cap.release()
            except:
                pass
            
        self.cap = None
        self.is_active = False
        
        # Small delay for hardware reset
        import time
        time.sleep(2.0)
        
        self._initialize_camera()
        return self.is_active

    def _capture_loop(self):
        """Background thread to continuously read frames"""
        self.logger.info("Starting Camera Capture Thread")
        consecutive_failures = 0
        dummy_retry_counter = 0
        
        while not self.stop_event.is_set():
            if self._is_camera_ready():
                ret = self._process_frame()
                if not ret:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                    
                if consecutive_failures > 5:
                    self.logger.warning("Multiple capture failures detected. Reinitializing...")
                    self.reinitialize()
                    time.sleep(1.0)
                    if self.is_active:
                        consecutive_failures = 0
                    else:
                        consecutive_failures = 3
                        
                # If we are running on dummy camera, periodically try to reconnect
                if not self.is_active:
                    dummy_retry_counter += 1
                    if dummy_retry_counter > 150:  # Roughly 5 seconds at 30fps
                        self.logger.info("Periodic retry to find real camera...")
                        self.reinitialize()
                        dummy_retry_counter = 0
            else:
                self.logger.warning("Camera not ready. Attempting to reinitialize...")
                self.reinitialize()
                time.sleep(2.0)

    def _is_camera_ready(self):
        """Check if camera is initialized and open"""
        if not self.cap:
            return False
        if hasattr(self.cap, 'is_opened'):
            return self.cap.is_opened()
        return self.cap.isOpened()
    
    def _process_frame(self):
        """Read and process a single frame"""
        ret, frame = self.cap.read()
        if ret and frame is not None:
            self._enqueue_frame(frame)
            return True
        else:
            self.logger.warning("Camera read failed")
            time.sleep(0.1)
            return False

    def _enqueue_frame(self, frame):
        """Update frame queue keeping only the latest frame"""
        if not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
        self.frame_queue.put(frame)
        self.frame_count += 1
                
    def start(self):
        """Start camera capture"""
        if self.cap is None:
            self._initialize_camera()
            
        if not self.capture_thread:
            self.stop_event.clear()
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
        return self._is_camera_ready()
    
    def get_overhead_view(self):
        """Get overhead view frame from latest queue item (Non-blocking)"""
        try:
            # Non-blocking get
            frame = self.frame_queue.get_nowait()
            return True, frame
        except queue.Empty:
            return False, None
    
    def stop(self):
        """Stop camera capture"""
        self.stop_event.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)
            
        if self.cap and hasattr(self.cap, 'release'):
            self.cap.release()
        self.cap = None
        self.is_active = False
        self.logger.info("Top camera stopped")