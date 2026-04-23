# gpu_utils.py - GPU Detection and Acceleration Utilities
"""
GPU Utilities for Top Camera YOLO Detection System
Detects and configures NVIDIA GPU acceleration for:
- PyTorch (YOLO, QReader)
- OpenCV CUDA
- CuPy (NumPy GPU acceleration)
"""

import os
import sys

# ========== GPU DETECTION RESULTS ==========
GPU_STATUS = {
    'cuda_available': False,
    'gpu_name': 'N/A',
    'gpu_memory': 'N/A',
    'torch_device': 'cpu',
    'opencv_cuda': False,
    'cupy_available': False
}

def detect_gpu():
    """
    Detect and print GPU capabilities for all frameworks.
    Call this at application startup.
    """
    print("\n" + "="*60)
    print("GPU DETECTION - NVIDIA CUDA CHECK")
    print("="*60)
    
    # ===== 1. PyTorch/CUDA Detection (for YOLO & QReader) =====
    try:
        import torch
        GPU_STATUS['cuda_available'] = torch.cuda.is_available()
        
        if GPU_STATUS['cuda_available']:
            GPU_STATUS['gpu_name'] = torch.cuda.get_device_name(0)
            GPU_STATUS['gpu_memory'] = f"{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB"
            GPU_STATUS['torch_device'] = 'cuda'
            
            print("PyTorch CUDA: AVAILABLE")
            print(f"   GPU Name: {GPU_STATUS['gpu_name']}")
            print(f"   GPU Memory: {GPU_STATUS['gpu_memory']}")
            print(f"   CUDA Version: {torch.version.cuda}")
            print(f"   PyTorch Version: {torch.__version__}")
        else:
            print("PyTorch CUDA: NOT AVAILABLE (will use CPU)")
            
    except ImportError:
        print("PyTorch: NOT INSTALLED")
    except Exception as e:
        print(f"PyTorch Error: {e}")
    
    # ===== 2. OpenCV CUDA Detection =====
    try:
        import cv2
        cuda_devices = cv2.cuda.getCudaEnabledDeviceCount()
        GPU_STATUS['opencv_cuda'] = cuda_devices > 0
        
        if GPU_STATUS['opencv_cuda']:
            print(f"OpenCV CUDA: AVAILABLE ({cuda_devices} device(s))")
        else:
            print("OpenCV CUDA: NOT AVAILABLE (using CPU for image ops)")
            
    except AttributeError:
        print("OpenCV CUDA: Module not available (standard opencv-python)")
    except Exception as e:
        print(f"OpenCV CUDA: {e}")
    
    # ===== 3. CuPy Detection (GPU NumPy) =====
    try:
        import cupy as cp
        GPU_STATUS['cupy_available'] = True
        print("CuPy: AVAILABLE (GPU-accelerated NumPy)")
    except ImportError:
        print("CuPy: NOT INSTALLED (using standard NumPy)")
    except Exception as e:
        print(f"CuPy: {e}")
    
    # ===== Summary =====
    print("\n" + "-"*60)
    print("GPU ACCELERATION SUMMARY")
    print("-"*60)
    
    if GPU_STATUS['cuda_available']:
        print(f"PRIMARY DEVICE: {GPU_STATUS['gpu_name']}")
        print("   YOLO Inference: GPU ")
        print("   QReader (PyTorch): GPU ")
        print(f"   OpenCV CUDA: {'GPU ' if GPU_STATUS['opencv_cuda'] else 'CPU '}")
    else:
        print("NO GPU DETECTED - Running on CPU (slower performance)")
    
    print("="*60 + "\n")
    
    return GPU_STATUS


def get_torch_device():
    """Get the best available torch device."""
    try:
        import torch
        if torch.cuda.is_available():
            device = torch.device('cuda')
            print(f"Using GPU: {torch.cuda.get_device_name(0)}")
            return device
        else:
            print("Using CPU for inference")
            return torch.device('cpu')
    except ImportError:
        return None


def print_gpu_memory_usage():
    """Print current GPU memory usage."""
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / 1024**2
            reserved = torch.cuda.memory_reserved(0) / 1024**2
            print(f"GPU Memory - Allocated: {allocated:.1f}MB, Reserved: {reserved:.1f}MB")
    except Exception:
        pass


def warm_up_gpu():
    """
    Warm up the GPU by running a small tensor operation.
    This ensures GPU is ready for YOLO inference.
    """
    try:
        import torch
        if torch.cuda.is_available():
            print("Warming up GPU...")
            # Small tensor operation to initialize CUDA context
            dummy = torch.zeros(1, 3, 640, 640).cuda()
            _ = dummy * 2
            del dummy
            torch.cuda.synchronize()
            print("GPU warmed up and ready!")
            return True
    except Exception as e:
        print(f"GPU warmup failed: {e}")
    return False


# Run detection on module import
if __name__ == "__main__":
    detect_gpu()
    warm_up_gpu()
    print_gpu_memory_usage()
