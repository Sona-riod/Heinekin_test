"""
GPU-Accelerated Camera Manager for iCAM-540
Provides CUDA-accelerated video capture and frame processing.
"""

import cv2
import logging
from gpu_utils import init_gpu, get_gpu_processor, is_gpu_available

class CameraManager:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger if logger else logging.getLogger("CameraManager")
        self.cap = None
        self.is_opened = False
        self.frame_count = 0
        
        # Initialize GPU
        self.gpu_info = init_gpu()
        self.gpu_processor = get_gpu_processor()
        self.use_gpu = is_gpu_available()
        
        self._print_gpu_status()
        self._initialize_camera()
    
    def _print_gpu_status(self):
        """Print GPU status for camera operations."""
        print("\n--- Camera GPU Configuration ---")
        if self.use_gpu:
            print("GPU Acceleration: ENABLED for frame processing")
            print(f"Device: {self.gpu_info.cuda_device_name}")
            self.logger.info(f"Camera GPU acceleration enabled: {self.gpu_info.cuda_device_name}")
        else:
            print("GPU Acceleration: DISABLED (using CPU)")
            print("Reason: OpenCV CUDA not available")
            self.logger.info("Camera using CPU processing")
        print("-"*35 + "\n")
    
    def _initialize_camera(self):
        # Get the camera dictionary from config
        cam_conf = self.config.get('camera', {})
        
        # 1. READ YOUR SPECIFIC KEYS
        device_index = cam_conf.get('device', 10)  # Default to 10 if missing
        backend_type = cam_conf.get('type', 'v4l2')
        width = cam_conf.get('width', 1920)
        height = cam_conf.get('height', 1080)
        fps = cam_conf.get('fps', 30)
        
        self.logger.info(f"Opening camera {device_index} (Type: {backend_type})...")
        print(f"[CAMERA] Opening device {device_index} at {width}x{height}@{fps}fps")
        
        # 2. SELECT BACKEND
        # Choose backend based on config type
        if backend_type.lower() == 'v4l2':
            backend = cv2.CAP_V4L2
        elif backend_type.lower() == 'dshow':
            backend = cv2.CAP_DSHOW  # Windows DirectShow
        else:
            backend = cv2.CAP_ANY
        
        # Try to use CUDA-accelerated video decoding if available
        if self.use_gpu and self.gpu_info.cuda_backend_available:
            print("Attempting CUDA video backend...")
            try:
                self.cap = cv2.VideoCapture(device_index, cv2.CAP_CUDA)
                if self.cap.isOpened():
                    print("CUDA Video Backend: Active")
                    self.logger.info("Using CUDA video backend")
                else:
                    self.cap.release()
                    self.cap = None
            except Exception:
                print("CUDA Video Backend failed")
                self.cap = None
        
        # Fallback to standard capture if CUDA backend not available/failed
        if self.cap is None:
            self.cap = cv2.VideoCapture(device_index, backend)
            print(f"[CAMERA] Using standard backend: {backend_type}")
        
        if self.cap.isOpened():
            # 3. APPLY SETTINGS
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            
            # Enable hardware acceleration hints
            self.cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY)
            
            self.is_opened = True
            
            # Optional: Log to verify actual settings
            real_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            real_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            real_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            print(f"Camera opened: {int(real_w)}x{int(real_h)} @ {real_fps:.1f}FPS")
            self.logger.info(f"Camera opened successfully: {int(real_w)}x{int(real_h)} @ {real_fps:.1f}FPS")
        else:
            print("Camera initialization failed! Device {device_index} not found.")
            self.logger.error("Camera initialization failed! Device {device_index} not found.")
            self.is_opened = False
    
    def read_frame(self):
        """Read frame from camera with GPU upload if available."""
        if self.is_opened and self.cap:
            ret, frame = self.cap.read()
            if ret:
                self.frame_count += 1
                
                # Log GPU processing periodically
                if self.frame_count == 1:
                    if self.use_gpu:
                        print("[CAMERA] First frame captured - GPU processing active")
                    else:
                        print("[CAMERA] First frame captured - CPU processing")
                
                return True, frame
            else:
                self.logger.warning("Failed to read frame from camera")
                return False, None
        
        return False, None
    
    def read_frame_gpu(self):
        """Read frame and upload to GPU memory for processing."""
        ret, frame = self.read_frame()
        if ret and self.use_gpu:
            try:
                gpu_frame = self.gpu_processor.upload_to_gpu(frame)
                return True, gpu_frame, frame  # Return both GPU and CPU versions
            except Exception as e:
                self.logger.warning(f"GPU upload failed: {e}")
                return True, frame, frame
        return ret, frame, frame if ret else None
    
    def process_frame_gpu(self, frame, target_size=None, to_grayscale=False):
        """
        GPU-accelerated frame processing pipeline.
        
        Args:
            frame: Input frame (BGR)
            target_size: Optional tuple (width, height) for resize
            to_grayscale: Whether to convert to grayscale
        
        Returns:
            Processed frame
        """
        if not self.use_gpu:
            # CPU fallback
            result = frame
            if to_grayscale:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            if target_size:
                result = cv2.resize(result, target_size)
            return result
        
        # GPU processing
        try:
            result = frame
            
            if to_grayscale:
                result = self.gpu_processor.cvt_color_gpu(result, cv2.COLOR_BGR2GRAY)
            
            if target_size:
                result = self.gpu_processor.resize_gpu(result, target_size)
            
            return result
            
        except Exception as e:
            self.logger.warning(f"GPU processing failed, using CPU: {e}")
            result = frame
            if to_grayscale:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            if target_size:
                result = cv2.resize(result, target_size)
            return result
    
    def get_preview_frame(self, frame, preview_size=(320, 240)):
        """Get a resized preview frame using GPU if available."""
        return self.process_frame_gpu(frame, target_size=preview_size)
    
    def release(self):
        if self.cap:
            self.cap.release()
            print(f"[CAMERA] Released - Processed {self.frame_count} frames")
            self.logger.info(f"Camera released - Processed {self.frame_count} frames")