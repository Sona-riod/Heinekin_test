# detector.py - GPU-Accelerated QR Code Detection
import cv2
import numpy as np
from ultralytics import YOLO
from pyzbar.pyzbar import decode, ZBarSymbol
from qreader import QReader
from config import logger, QRCODE_MODEL_PATH, PRODUCT_MODEL_PATH, DETECTION_CONFIG
from gpu_utils import detect_gpu, get_torch_device, print_gpu_memory_usage, GPU_STATUS

class KegDetector:
    def __init__(self, model_path=None, product_model_path=None):
        self.logger = logger
        self.model = None
        self.product_model = None
        self.device = None
        
        # ===== GPU DETECTION AT STARTUP =====
        print("\n" + "="*60)
        print("INITIALIZING GPU-ACCELERATED KEG DETECTOR")
        print("="*60)
        
        # Run GPU detection
        detect_gpu()
        
        # Use the passed path or fallback to the config path
        self.model_path = str(model_path) if model_path else str(QRCODE_MODEL_PATH)
        self.product_model_path = str(product_model_path) if product_model_path else str(PRODUCT_MODEL_PATH)
        
        # ===== LOAD MODELS WITH GPU =====
        try:
            print(f"Loading YOLO (QR) model from: {self.model_path}")
            self.model = YOLO(self.model_path)
            
            print(f"Loading YOLO (Product) model from: {self.product_model_path}")
            self.product_model = YOLO(self.product_model_path)
            
            # Force GPU if available
            if GPU_STATUS['cuda_available']:
                self.device = 'cuda'
                self.model.to('cuda')
                self.product_model.to('cuda')
                print(f"Models loaded on GPU: {GPU_STATUS['gpu_name']}")
            else:
                self.device = 'cpu'
                print("Models loaded on CPU (No GPU available)")
                
            self.logger.info(f"YOLO models loaded successfully on {self.device.upper()}")
            print_gpu_memory_usage()
            
        except Exception as e:
            self.logger.error(f"Failed to load YOLO models: {e}")
            print(f"YOLO Model Load FAILED: {e}")
            
        # ===== INITIALIZE QREADER WITH GPU =====
        try:
            print("\nLoading QReader model...")
            self.reader = QReader(model_size='s', min_confidence=0.5)
            self.logger.info("QReader model loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load QReader: {e}")
            self.reader = None
        
        print("\n" + "="*60)
        print("DETECTOR INITIALIZATION COMPLETE")
        print(f"YOLO Device: {self.device.upper() if self.device else 'FAILED'}")
        print(f"QReader: {'LOADED' if self.reader else 'FAILED'}")
        print(f"GPU Acceleration: {'ENABLED' if GPU_STATUS['cuda_available'] else 'DISABLED'}")
        print("="*60 + "\n")

    def _resize_crop(self, crop, max_size=300):
        """Resizes crop to speed up decoding if it's too huge."""
        h, w = crop.shape[:2]
        if max(h, w) <= max_size:
            return crop
        scale = max_size / max(h, w)
        return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

    def _gpu_preprocess(self, frame):
        """
        GPU-accelerated preprocessing using OpenCV CUDA if available.
        Falls back to CPU if not available.
        """
        if GPU_STATUS['opencv_cuda']:
            try:
                # Upload to GPU
                gpu_frame = cv2.cuda_GpuMat()
                gpu_frame.upload(frame)
                
                # Convert to grayscale on GPU
                gpu_gray = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY)
                
                # Download back to CPU
                gray = gpu_gray.download()
                return gray
            except Exception as e:
                self.logger.debug(f"GPU preprocess fallback to CPU: {e}")
                
        # CPU fallback
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def detect_and_decode(self, frame):
        if self.model is None or frame is None:
            return frame, [], [], {}

        detected_ids = set()
        results_list = []
        product_counts = {'cola': 0, 'water': 0}
        
        try:
            # 1. Run QR Detector
            qr_results = self.model(frame, verbose=False, conf=DETECTION_CONFIG['qr_conf'], device=self.device)
            for result in qr_results:
                for box in result.boxes:
                    if not len(box.xyxy):   # skip empty boxes
                        continue
                    bbox = list(map(int, box.xyxy[0]))
                    detection_data = self._process_detection(frame, bbox)
                    
                    if detection_data:
                        detected_ids.add(str(detection_data['data']))
                        results_list.append(detection_data)
                    else:
                        results_list.append({
                            'bbox': bbox,
                            'data': None,
                            'type': 'qr'
                        })

            # 2. Run Product Detector
            if self.product_model:
                prod_results = self.product_model(frame, verbose=False, conf=DETECTION_CONFIG['product_conf'], device=self.device)
                for result in prod_results:
                    for box in result.boxes:
                        if not len(box.xyxy):   # skip empty boxes
                            continue
                        bbox = list(map(int, box.xyxy[0]))
                        cls_idx = int(box.cls[0])
                        label = self.product_model.names[cls_idx].lower() # 'cola' or 'water'
                        
                        if label in product_counts:
                            product_counts[label] += 1
                            self.logger.info(f"Product detected: {label.upper()}")
                        
                        results_list.append({
                            'bbox': bbox,
                            'data': label.upper(),
                            'type': 'product',
                            'label': label
                        })
                                       
        except Exception as e:
            self.logger.error(f"Error during detection: {e}")
            
        return frame, list(detected_ids), results_list, product_counts

    def _process_detection(self, frame, bbox):
        """Process a single detection box."""
        x1, y1, x2, y2 = bbox
        
        # Crop logic
        crop_img = self._extract_crop(frame, x1, y1, x2, y2)
        
        if crop_img.size > 0:
            # Optimization: Resize heavy crops
            crop_opt = self._resize_crop(crop_img)
            
            # Preprocess for barcode readers (Grayscale)
            gray = self._gpu_preprocess(crop_opt)
            
            # Try decoding
            current_text = self._decode_qr(gray)
            
            if current_text:
                return {
                    'bbox': (x1, y1, x2, y2),
                    'data': current_text,
                    'type': 'qr'
                }
        return None

    def _extract_crop(self, frame, x1, y1, x2, y2):
        """Extract crop with padding."""
        h, w, _ = frame.shape
        pad = 10
        crop_y1, crop_y2 = max(0, y1-pad), min(h, y2+pad)
        crop_x1, crop_x2 = max(0, x1-pad), min(w, x2+pad)
        return frame[crop_y1:crop_y2, crop_x1:crop_x2]

    def _decode_qr(self, gray_img):
        """Attempt to decode QR code using Pyzbar then QReader."""
        # 1. Try Pyzbar First (Fast, CPU-only)
        text = self._try_pyzbar(gray_img)
        if text:
            return text
            
        # 2. Try QReader Secondary (GPU-accelerated via PyTorch)
        if self.reader:
            text = self._try_qreader(gray_img)
            if text:
                return text
                
        return None

    def _try_pyzbar(self, img):
        """Attempt decoding with Pyzbar."""
        try:
            pyzbar_res = decode(img, symbols=[ZBarSymbol.QRCODE])
            for obj in pyzbar_res:
                text = obj.data.decode("utf-8")
                if text:
                    return text
        except Exception:
            pass
        return None

    def _try_qreader(self, img):
        """Attempt decoding with QReader."""
        try:
            qreader_texts = self.reader.detect_and_decode(image=img)
            for text in qreader_texts:
                if text:
                    gpu_tag = "(GPU)" if GPU_STATUS['cuda_available'] else "(CPU)"
                    self.logger.info(f"QReader detected {gpu_tag}: {text}")
                    return str(text)
        except Exception:
            pass
        return None
    
    def get_gpu_status(self):
        """Return current GPU status for display."""
        return {
            'gpu_enabled': GPU_STATUS['cuda_available'],
            'gpu_name': GPU_STATUS['gpu_name'],
            'device': self.device
        }