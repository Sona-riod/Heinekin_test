# config.py - Centralized Configuration for Top Camera Palletizer System
# =============================================================================
# DEPLOY MODE SWITCH
# Set to "PC" for laptop/desktop testing, "JETSON" for ICAM-540 on Jetson Orin
# =============================================================================
import os
import logging
from pathlib import Path

DEPLOY_MODE = "PC"   

# =============================================================================
# BASE PATHS
# =============================================================================
BASE_DIR    = Path(__file__).parent
SAVE_FOLDER = BASE_DIR / "top_camera_frames"
DB_PATH     = BASE_DIR / "top_camera_detection.db"
MODEL_DIR   = BASE_DIR / "model"
LOG_FILE    = BASE_DIR / "top_camera.log"

# Create required directories on startup
SAVE_FOLDER.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# =============================================================================
# MODEL PATHS
# Both models must exist at these paths before running.
# QR Code model   : Detects and crops QR code regions on kegs
# Product model   : Detects cola packs and water packs (bulk)
# =============================================================================
QRCODE_MODEL_PATH  = MODEL_DIR / "best.pt"           # YOLOv8 – QR detector
PRODUCT_MODEL_PATH = BASE_DIR  / "best_new.pt"     # YOLOv8 – cola/water detector

# =============================================================================
# SYSTEM / DEVICE IDENTITY
# =============================================================================
SYSTEM_CONFIG = {
    # Unique forklift identifier sent to the cloud with every batch
    'forklift_id': "TOP-CAM-001",

    # MAC address of this device – used as the personal WebSocket channel
    # Run `ip link show` on Jetson or `ipconfig` on Windows to find yours
    'mac_id': "3C:6D:66:01:5A:F0",

    # Python logging level: DEBUG | INFO | WARNING | ERROR
    'log_level': "INFO",

    # When True the app skips real API calls (useful for UI-only testing)
    'test_mode': True,
}

# =============================================================================
# CAMERA CONFIGURATION
# PC  : Standard USB webcam (OpenCV index or /dev/videoX)
# JETSON : ICAM-540 via V4L2 at /dev/video10  (1920×1080 @ 30 fps)
# =============================================================================
if DEPLOY_MODE == "JETSON":
    TOP_CAMERA_CONFIG = {
        'type':    'v4l2',
        'device':  10,           # /dev/video10 for ICAM-540
        'width':   1920,
        'height':  1080,
        'fps':     30,
        'purpose': 'top_camera',

        # ICAM-540 V4L2 extra controls (set via v4l2-ctl or OpenCV props)
        'autofocus':   False,
        'focus':       0,        # Manual focus value (0 = far, 255 = near)
        'exposure':   -6,        # Auto-exposure target bias
        'brightness':  50,       # 0-100
        'contrast':    50,       # 0-100
    }
else:
    TOP_CAMERA_CONFIG = {
        'type':    'opencv',
        'device':  0,            # 0 for default internal webcam
        'width':   1280,
        'height':  720,
        'fps':     30,
        'purpose': 'webcam',
    }
# =============================================================================
# GPU CONFIGURATION
# Controls CUDA usage for YOLO inference and OpenCV operations.
# On Jetson Orin CUDA is almost always available; on a PC it depends on GPU.
# =============================================================================
GPU_CONFIG = {
    # CUDA device index (0 = first / only GPU)
    'device': 0,

    # Use FP16 half-precision – faster on Jetson, may slightly reduce accuracy
    'half_precision': False,

    # Max fraction of total GPU memory this process may allocate
    'memory_fraction': 0.8,

    # Run a small warm-up tensor op at startup so first inference is not slow
    'warmup_enabled': True,

    # Force CPU even when CUDA is present (for debugging only)
    'force_cpu': False,
}

# =============================================================================
# YOLO DETECTION PARAMETERS
# =============================================================================
DETECTION_CONFIG = {
    # ---- QR code detector (model 1) ----
    'qr_conf':        0.50,   # Minimum YOLO confidence to accept a QR detection
    'qr_iou':         0.45,   # NMS IoU threshold for QR boxes
    'qr_max_det':     50,     # Maximum simultaneous QR detections per frame

    # ---- Product detector (model 2: cola / water packs) ----
    'product_conf':   0.50,   # Higher threshold to reduce false product hits
    'product_iou':    0.45,
    'product_max_det': 20,

    # ---- Crop & decode settings ----
    'crop_pad':       10,     # Pixel padding around each detected QR bounding box
    'decode_max_size': 300,   # Resize crop to this max dimension before decoding

    # ---- QReader fallback ----
    'qreader_model_size': 's',        
    'qreader_min_confidence': 0.50,
}

BBOX_COLORS = {
    'qr_decoded':   (0, 220, 100),    # Green  – QR successfully read
    'qr_scanning':  (0,  60, 220),    # Red    – detected but not yet decoded
    'cola':         (0, 165, 255),    # Orange – cola pack
    'water':        (255, 100,  0),   # Blue   – water pack
    'text_bg':      (0,   0,   0),    # Black  – label background
}

BBOX_LINE_WIDTH   = 2    # px – bounding box stroke
BBOX_FONT_SCALE   = 0.55
BBOX_FONT_THICK   = 2
BBOX_LABEL_OFFSET = 12   # px above box top for label text

# =============================================================================
# CLOUD API ENDPOINTS
# =============================================================================
API_CONFIG = {
    # POST {macId} → returns list of customers assigned to this device
    'customer_api_url':  "https://api2.checkology-cloud.io/api/kegs/customers-for-cam",

    # POST batch dispatch payload → confirms pallet to cloud
    'pallet_create_url': "https://api2.checkology-cloud.io/api/kegs/custom-palette-dispatch",

    # Seconds to wait before timing out a request
    'api_timeout':  10,

    # Number of retry attempts on network failure before giving up
    'max_retries':  3,

    # Seconds between retries
    'retry_delay':  2,
}

# =============================================================================
# WEBSOCKET CONFIGURATION
# The cloud sends location pop-ups via Socket.IO to the personal MAC channel.
# =============================================================================
WEBSOCKET_CONFIG = {
    # Socket.IO server base URL (no trailing slash)
    'url': "https://api2.checkology-cloud.io",

    # Seconds to wait between reconnect attempts
    'reconnection_delay': 5,

    # Socket.IO connection wait timeout (seconds)
    'connect_timeout': 5,
}

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DB_CONFIG = {
    # SQLite busy-wait timeout in seconds
    'timeout': 10.0,

    # Table names – change here to rename without touching other files
    'custom_pallet_table': 'custom_pallets',
    'custom_keg_table':    'custom_keg_locations',
}

# =============================================================================
# UI / HMI CONFIGURATION
# =============================================================================
UI_CONFIG = {
    # Camera feed target frame-rate for Kivy texture updates
    'camera_fps': 30,

    # Kivy fullscreen mode: 'auto' | '0' (windowed) | '1' (borderless)
    'fullscreen': 'auto',

    # Show mouse cursor (useful on PC, set False for touch-only kiosk)
    'show_cursor': True,

    # Minimum kegs required to enable the Save button
    'min_kegs_to_save': 1,

    # Seconds the notification bar message stays visible (0 = permanent)
    'notification_duration': 4,

    # Splash screen minimum display time in seconds
    'splash_min_time': 1.5,
}

# Kivy KivyMD theme
THEME_CONFIG = {
    'theme_style':      'Dark',
    'primary_palette':  'Cyan',
    'accent_palette':   'Amber',
}

# Color values in Kivy RGBA format  (0.0–1.0 per channel)
# Deep-space industrial palette — matches enhanced hmi.py
COLOR_SCHEME = {
    # Backgrounds
    'bg_darkest':     (0.04, 0.05, 0.07, 1),   # #0A0D12 void black
    'bg_dark':        (0.07, 0.09, 0.12, 1),   # #121720 deep panels
    'bg_card':        (0.10, 0.13, 0.18, 1),   # #1A212E card surfaces
    'bg_elevated':    (0.13, 0.17, 0.23, 1),   # #222B3B elevated elements
    # Primary accent — electric cyan
    'primary':        (0.00, 0.90, 1.00, 1),   # #00E5FF electric cyan
    'accent_amber':   (1.00, 0.70, 0.00, 1),   # #FFB300 warm amber
    'accent_teal':    (0.00, 0.90, 1.00, 1),   # alias for cyan
    # Status
    'danger':         (1.00, 0.27, 0.23, 1),   # #FF453A vivid red
    'success':        (0.06, 0.85, 0.49, 1),   # #10D97D vivid green
    'warning':        (1.00, 0.62, 0.04, 1),   # #FF9E0A orange-amber
    # Text
    'text_primary':   (0.82, 0.87, 0.95, 1),
    'text_secondary': (0.52, 0.60, 0.72, 1),
    'text_hint':      (0.32, 0.38, 0.48, 1),
    # Product
    'cola_color':     (1.00, 0.25, 0.10, 1),   # #FF4019 bold cola red
    'water_color':    (0.20, 0.65, 1.00, 1),   # #33A6FF sky blue water
}

def setup_logging() -> logging.Logger:
    log_level = getattr(logging, SYSTEM_CONFIG['log_level'], logging.INFO)
    fmt = '%(asctime)s [%(levelname)-8s] %(name)s – %(message)s'
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
    ]
    logging.basicConfig(level=log_level, format=fmt, handlers=handlers, force=True)
    return logging.getLogger('TopCamera')

logger = setup_logging()
logger.info(f"Config loaded – DEPLOY_MODE={DEPLOY_MODE} | "
            f"Camera={TOP_CAMERA_CONFIG['type']}:{TOP_CAMERA_CONFIG['device']} | "
            f"QR model={QRCODE_MODEL_PATH.name} | "
            f"Product model={PRODUCT_MODEL_PATH.name}")