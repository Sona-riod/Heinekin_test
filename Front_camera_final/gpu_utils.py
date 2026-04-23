"""
GPU Utilities for Front Camera System
Provides GPU detection, initialization, and acceleration utilities for NVIDIA GPUs.
"""

import cv2
import logging
import os
import sys

# Initialize logger
_gpu_logger = None

def get_gpu_logger() -> logging.Logger:
    global _gpu_logger
    if _gpu_logger is None:
        _gpu_logger = logging.getLogger("GPU_Utils")
        _gpu_logger.setLevel(logging.INFO)
        if not _gpu_logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - [GPU] - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            _gpu_logger.addHandler(handler)
        _gpu_logger.propagate = False
    return _gpu_logger


class GPUInfo:
    """Singleton class to store GPU information and status."""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.cuda_available = False
        self.cuda_device_count = 0
        self.cuda_device_name = "N/A"
        self.opencv_cuda_enabled = False
        self.cupy_available = False
        self.cuda_backend_available = False
        
        self._detect_gpu()
        self._initialized = True
    
    def _detect_gpu(self):
        """Detect GPU capabilities and log results."""
        logger = get_gpu_logger()
        
        print("\n" + "="*60)
        print("GPU DETECTION AND INITIALIZATION")
        print("="*60)
        
        # 1. Check OpenCV CUDA support
        try:
            cuda_count = cv2.cuda.getCudaEnabledDeviceCount()
            self.cuda_device_count = cuda_count
            
            if cuda_count > 0:
                self.opencv_cuda_enabled = True
                self.cuda_available = True
                
                # Get device name
                cv2.cuda.setDevice(0)
                device_props = cv2.cuda.getDevice()
                self.cuda_device_name = f"CUDA Device {device_props}"
                
                print("OpenCV CUDA: ENABLED")
                print(f"CUDA Devices Found: {cuda_count}")
                print(f"Active Device: {self.cuda_device_name}")
                logger.info(f"OpenCV CUDA enabled with {cuda_count} device(s)")
            else:
                print("OpenCV CUDA: NOT AVAILABLE")
                print("OpenCV compiled WITHOUT CUDA support")
                logger.warning("OpenCV CUDA not available - using CPU fallback")
                
        except Exception as e:
            print(f"OpenCV CUDA: ERROR - {e}")
            logger.error(f"OpenCV CUDA detection failed: {e}")
        
        # 2. Check CUDA backend for video
        try:
            # Check if CUDA backend is available for VideoCapture
            backends = cv2.videoio_registry.getBackendName(cv2.CAP_CUDA)
            self.cuda_backend_available = backends is not None
            if self.cuda_backend_available:
                print("CUDA Video Backend: AVAILABLE")
            else:
                print("CUDA Video Backend: Not detected (using CPU decoding)")
        except Exception as e:
            print(f"CUDA Video Backend: Check failed - {e}")
        
        # 3. Check for CuPy (GPU NumPy alternative)
        try:
            import cupy as cp
            self.cupy_available = True
            
            # Get GPU memory info

            device = cp.cuda.Device(0)
            total_mem = device.mem_info[1] / (1024**3)  # GB
            free_mem = device.mem_info[0] / (1024**3)   # GB
            
            print("CuPy: AVAILABLE")
            print(f"GPU Memory: {free_mem:.2f} GB free / {total_mem:.2f} GB total")
            logger.info(f"CuPy available - GPU Memory: {free_mem:.2f}/{total_mem:.2f} GB")
            
        except ImportError:
            print("CuPy: NOT INSTALLED (pip install cupy-cuda12x)")
            logger.info("CuPy not installed - using NumPy (CPU)")
        except Exception as e:
            print(f"CuPy: ERROR - {e}")
            logger.warning(f"CuPy detection failed: {e}")
        
        # 4. Check NVIDIA drivers
        try:
            nvidia_smi = os.popen('nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader').read().strip()
            if nvidia_smi:
                parts = nvidia_smi.split(',')
                if len(parts) >= 3:
                    print("NVIDIA Driver: DETECTED")
                    print(f"GPU: {parts[0].strip()}")
                    print(f"Driver: {parts[1].strip()}")
                    print(f"VRAM: {parts[2].strip()}")
                    self.cuda_device_name = parts[0].strip()
        except Exception as e:
            print(f"nvidia-smi: Could not query - {e}")
        
        # Summary
        print("-"*60)
        if self.cuda_available:
            print("GPU ACCELERATION: ENABLED")
            print(f"         Using: {self.cuda_device_name}")
        else:
            print("[RESULT] GPU ACCELERATION: DISABLED (CPU Fallback)")
            print("         To enable GPU, install opencv-python with CUDA support")
        print("="*60 + "\n")
        
        logger.info(f"GPU Detection Complete - CUDA Available: {self.cuda_available}")
    
    def print_status(self):
        """Print current GPU status."""
        print("\n--- GPU Status ---")
        print(f"CUDA Available: {self.cuda_available}")
        print(f"CUDA Devices: {self.cuda_device_count}")
        print(f"Device Name: {self.cuda_device_name}")
        print(f"OpenCV CUDA: {self.opencv_cuda_enabled}")
        print(f"CuPy Available: {self.cupy_available}")
        print("-"*20)


# Global GPU info instance
GPU_INFO = None

def init_gpu():
    """Initialize GPU and return GPU info."""
    global GPU_INFO
    if GPU_INFO is None:
        GPU_INFO = GPUInfo()
    return GPU_INFO

def is_gpu_available() -> bool:
    """Check if GPU acceleration is available."""
    global GPU_INFO
    if GPU_INFO is None:
        GPU_INFO = GPUInfo()
    return GPU_INFO.cuda_available

def is_cupy_available() -> bool:
    """Check if CuPy is available for GPU array operations."""
    global GPU_INFO
    if GPU_INFO is None:
        GPU_INFO = GPUInfo()
    return GPU_INFO.cupy_available


class GPUImageProcessor:
    """GPU-accelerated image processing utilities."""
    
    def __init__(self):
        self.gpu_available = is_gpu_available()
        self.logger = get_gpu_logger()
        
        if self.gpu_available:
            self.logger.info("GPUImageProcessor initialized with CUDA acceleration")
        else:
            self.logger.info("GPUImageProcessor initialized with CPU fallback")
    
    def upload_to_gpu(self, frame):
        """Upload frame to GPU memory."""
        if not self.gpu_available:
            return frame
        
        try:
            gpu_frame = cv2.cuda_GpuMat()
            gpu_frame.upload(frame)
            return gpu_frame
        except Exception as e:
            self.logger.warning(f"GPU upload failed: {e}")
            return frame
    
    def download_from_gpu(self, gpu_frame):
        """Download frame from GPU memory."""
        if not self.gpu_available:
            return gpu_frame
        
        try:
            if isinstance(gpu_frame, cv2.cuda_GpuMat):
                return gpu_frame.download()
            return gpu_frame
        except Exception as e:
            self.logger.warning(f"GPU download failed: {e}")
            return gpu_frame
    
    def cvt_color_gpu(self, frame, code):
        """GPU-accelerated color conversion."""
        if not self.gpu_available:
            return cv2.cvtColor(frame, code)
        
        try:
            if not isinstance(frame, cv2.cuda_GpuMat):
                gpu_frame = cv2.cuda_GpuMat()
                gpu_frame.upload(frame)
            else:
                gpu_frame = frame
            
            result = cv2.cuda.cvtColor(gpu_frame, code)
            return result.download()
        except Exception as e:
            self.logger.warning(f"GPU cvtColor failed, using CPU: {e}")
            if isinstance(frame, cv2.cuda_GpuMat):
                frame = frame.download()
            return cv2.cvtColor(frame, code)
    
    def resize_gpu(self, frame, size):
        """GPU-accelerated resize."""
        if not self.gpu_available:
            return cv2.resize(frame, size)
        
        try:
            if not isinstance(frame, cv2.cuda_GpuMat):
                gpu_frame = cv2.cuda_GpuMat()
                gpu_frame.upload(frame)
            else:
                gpu_frame = frame
            
            result = cv2.cuda.resize(gpu_frame, size)
            return result.download()
        except Exception as e:
            self.logger.warning(f"GPU resize failed, using CPU: {e}")
            if isinstance(frame, cv2.cuda_GpuMat):
                frame = frame.download()
            return cv2.resize(frame, size)
    
    def gaussian_blur_gpu(self, frame, ksize=(5, 5)):
        """GPU-accelerated Gaussian blur."""
        if not self.gpu_available:
            return cv2.GaussianBlur(frame, ksize, 0)
        
        try:
            if not isinstance(frame, cv2.cuda_GpuMat):
                gpu_frame = cv2.cuda_GpuMat()
                gpu_frame.upload(frame)
            else:
                gpu_frame = frame
            
            # Create Gaussian filter
            gaussian_filter = cv2.cuda.createGaussianFilter(
                gpu_frame.type(), -1, ksize, 0
            )
            result = gaussian_filter.apply(gpu_frame)
            return result.download()
        except Exception as e:
            self.logger.warning(f"GPU GaussianBlur failed, using CPU: {e}")
            if isinstance(frame, cv2.cuda_GpuMat):
                frame = frame.download()
            return cv2.GaussianBlur(frame, ksize, 0)


# Create global image processor
GPU_PROCESSOR = None

def get_gpu_processor() -> GPUImageProcessor:
    """Get the global GPU image processor instance."""
    global GPU_PROCESSOR
    if GPU_PROCESSOR is None:
        GPU_PROCESSOR = GPUImageProcessor()
    return GPU_PROCESSOR


if __name__ == "__main__":
    # Test GPU detection
    print("Testing GPU Utilities...")
    gpu_info = init_gpu()
    gpu_info.print_status()
    
    # Test image processing
    import numpy as np
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    processor = get_gpu_processor()
    
    # Test operations
    gray = processor.cvt_color_gpu(test_frame, cv2.COLOR_BGR2GRAY)
    resized = processor.resize_gpu(test_frame, (320, 240))
    blurred = processor.gaussian_blur_gpu(test_frame)
    
    print(f"Gray shape: {gray.shape}")
    print(f"Resized shape: {resized.shape}")
    print(f"Blurred shape: {blurred.shape}")
    print("\nGPU Utilities test completed!")
