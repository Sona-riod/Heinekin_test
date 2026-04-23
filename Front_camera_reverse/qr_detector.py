#
"""
GPU-Accelerated QR Detector
Uses GPU for image preprocessing and CPU for QR decoding.
"""

import cv2
import numpy as np
import json
from typing import Tuple, List, Dict, Any
from pyzbar import pyzbar
from utils import ForkliftLogger, CONFIG, TRACKER, RECENT_CACHE
from gpu_utils import init_gpu, get_gpu_processor, is_gpu_available, get_gpu_logger

class QRDetectorError(Exception):
    pass

class QRDetector:
    def __init__(self, config: Dict[str, Any] = CONFIG):
        self.config = config
        self.logger = ForkliftLogger.setup(config['system']['log_level'])
        self.gpu_logger = get_gpu_logger()
        
        self.gpu_info = init_gpu()
        self.gpu_processor = get_gpu_processor()
        self.use_gpu = is_gpu_available()
        
        self._print_detector_status()
        self.logger.info("Initialized QRDetector with pyzbar")
    
    def _print_detector_status(self):
        print("\n--- QR Detector GPU Configuration ---")
        if self.use_gpu:
            print("GPU Preprocessing: ENABLED")
            self.gpu_logger.info("QR Detector using GPU preprocessing")
        else:
            print("GPU Preprocessing: DISABLED")
            self.gpu_logger.info("QR Detector using CPU only")
        print("-"*40 + "\n")
    
    def _preprocess_frame_gpu(self, frame: np.ndarray) -> np.ndarray:
        if not self.use_gpu:
            if len(frame.shape) == 3:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return frame
        try:
            if len(frame.shape) == 3:
                return self.gpu_processor.cvt_color_gpu(frame, cv2.COLOR_BGR2GRAY)
            return frame
        except Exception as e:
            self.gpu_logger.warning(f"GPU preprocessing failed: {e}")
            if len(frame.shape) == 3:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return frame

    def _log_detection_start(self):
        if hasattr(self, '_detection_count'):
            self._detection_count += 1
        else:
            self._detection_count = 1
            mode = "GPU preprocessing active" if self.use_gpu else "CPU processing"
            print(f"[QR_DETECTOR] First detection - {mode}")

    def _extract_qr_data(self, obj) -> Tuple[str, List[Any], Tuple[int, int, int, int]]:
        try:
            data_str = obj.data.decode('utf-8')
            try:
                data = json.loads(data_str)
                pallet_id = data.get('pallet_id', 'UNKNOWN')
                kegs = data.get('kegs', [])
            except json.JSONDecodeError:
                pallet_id = data_str
                kegs = []
        except Exception:
            pallet_id = "UNKNOWN"
            kegs = []
            
        rect = obj.rect
        x1, y1 = int(rect.left), int(rect.top)
        x2, y2 = int(rect.left + rect.width), int(rect.top + rect.height)
        
        return pallet_id, kegs, (x1, y1, x2, y2)

    def _draw_stats(self, frame, total_detected, stable_count):
        gpu_indicator = "[GPU]" if self.use_gpu else "[CPU]"
        cv2.putText(frame, f"{gpu_indicator} QRs: {total_detected}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(frame, f"Stable: {stable_count}", (10, 60),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    def _get_roi_bounds(self, frame_h: int, frame_w: int) -> Tuple[int, int, int, int]:
        """Calculate pixel ROI bounds from the config percentage values."""
        roi = self.config['camera'].get('roi_active_zone', (0.5, 0.5, 1.0, 1.0))
        cx_pct, cy_pct, w_pct, h_pct = roi
        roi_w = int(frame_w * w_pct)
        roi_h = int(frame_h * h_pct)
        roi_x1 = max(0, int(frame_w * cx_pct - roi_w / 2))
        roi_y1 = max(0, int(frame_h * cy_pct - roi_h / 2))
        roi_x2 = min(frame_w, roi_x1 + roi_w)
        roi_y2 = min(frame_h, roi_y1 + roi_h)
        return roi_x1, roi_y1, roi_x2, roi_y2

    def _draw_roi_overlay(self, frame, roi_x1, roi_y1, roi_x2, roi_y2):
        """Draw a dashed cyan rectangle to show the active ROI zone."""
        color = (0, 255, 255)
        dash_len = 20
        gap_len = 10
        # Top and bottom edges
        for edge_y in (roi_y1, roi_y2):
            x = roi_x1
            draw = True
            while x < roi_x2:
                end_x = min(x + dash_len, roi_x2)
                if draw:
                    cv2.line(frame, (x, edge_y), (end_x, edge_y), color, 2)
                x = end_x + gap_len
                draw = not draw
        # Left and right edges
        for edge_x in (roi_x1, roi_x2):
            y = roi_y1
            draw = True
            while y < roi_y2:
                end_y = min(y + dash_len, roi_y2)
                if draw:
                    cv2.line(frame, (edge_x, y), (edge_x, end_y), color, 2)
                y = end_y + gap_len
                draw = not draw
        cv2.putText(frame, "ACTIVE ZONE", (roi_x1 + 8, roi_y1 + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    def _draw_qr_annotation(self, frame, bbox, is_selected):
        """Draw bounding box and label for a detected QR."""
        x1, y1, x2, y2 = bbox
        label_y = y1 if y1 > 30 else y1 + 30
        
        if is_selected:
            # GREEN — pallet is selected (default state)
            box_color = (0, 220, 80)
            label_bg  = (0, 180, 60)
            label_text = "SELECTED"
            text_color = (255, 255, 255)
        else:
            # ORANGE — operator has deselected this pallet
            box_color = (0, 200, 255)
            label_bg  = (0, 200, 255)
            label_text = "TAP TO RE-SELECT"
            text_color = (0, 0, 0)

        cv2.rectangle(frame, (x1, label_y - 30), (x2, label_y), label_bg, -1)
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 3)
        cv2.putText(frame, label_text, (x1 + 5, label_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)

    def detect_and_filter_qrs(self, frame: np.ndarray, selected_ids: set = None) -> Tuple[List[Dict[str, Any]], int, np.ndarray]:
        """
        Detect QR codes in the configured ROI.
        selected_ids: set of pallet_id strings currently selected (auto-selected on detection).
                      Selected QRs are drawn in GREEN; deselected ones in ORANGE.
        """
        if selected_ids is None:
            selected_ids = set()
            
        try:
            detected_qrs, candidate_ids = [], set()
            h, w = frame.shape[:2]
            roi_x1, roi_y1, roi_x2, roi_y2 = self._get_roi_bounds(h, w)
            min_area = self.config['camera'].get('min_qr_area', 3500)

            gray = self._preprocess_frame_gpu(frame)
            self._log_detection_start()
            decoded_objects = pyzbar.decode(gray)

            for obj in decoded_objects:
                pallet_id, kegs, bbox = self._extract_qr_data(obj)
                x1, y1, x2, y2 = bbox
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                # ROI FILTER
                if not (roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2):
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 80, 80), 1)
                    continue

                if (x2 - x1) * (y2 - y1) <= min_area:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (128, 128, 128), 1)
                    continue

                # Valid QR in ROI: update state and draw annotations
                is_selected = pallet_id in selected_ids
                self._draw_qr_annotation(frame, bbox, is_selected)
                
                detected_qrs.append({
                    'pallet_id': pallet_id, 'kegs': kegs, 'position': (x1, y1),
                    'confidence': 1.0, 'bbox': bbox
                })
                candidate_ids.add(pallet_id)

            self._draw_roi_overlay(frame, roi_x1, roi_y1, roi_x2, roi_y2)
            stable_ids = TRACKER.is_stable(candidate_ids)
            self._draw_stats(frame, len(decoded_objects), len(stable_ids))
            
            return detected_qrs, len(stable_ids), frame

        except Exception as e:
            self.logger.error(f"Detection Error: {e}")
            cv2.putText(frame, "Detection Error", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            return [], 0, frame