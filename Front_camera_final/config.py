#
CONFIG = {
    "camera": {
        # --- Jetson Orin Configuration (Active) ---
        'type': 'v4l2',    # Jetson typically uses v4l2
        'device': 10,       # Default to 10 for ICAM-540
        'width': 1920,     # ICAM-540 max resolution
        'height': 1080,
        'fps': 30,
        
        # --- NEW PRECISION SETTINGS ---
        # Defines the Active Zone box: (center_x, center_y, width, height) in percentages
        "roi_active_zone": (0.5, 0.45, 0.5, 0.8),
        
        # Minimum pixel area to prevent detecting distant background pallets
        "min_qr_area": 3500, 
        
        # --- Algorithm Settings ---
        "yolo_model_path": "best.pt",
        "yolo_conf_threshold": 0.5,
        "frame_delay": 0.1,
        "temporal_buffer_size": 5,
        "dynamic_roi_enabled": False,
    },
    
    "websocket": {
        "url": "https://api2.checkology-cloud.io",
    },
    
    "api": {
        "customer_api_url": "https://api2.checkology-cloud.io/api/kegs/customers-for-cam",
        "keg_count_api_url": "https://api2.checkology-cloud.io/api/pallette/get-kegs-for-multiple-palettes",
        "end_point_api_url": "https://api2.checkology-cloud.io/api/kegs/camera-update-palette",
        "api_timeout": 10,
    },
    
    "system": {
        "forklift_id": "FORK001",
        "mac_id": "3C:6D:66:01:5A:F0",  
        "log_level": "INFO",
        "location_sim_interval": 10,
        "recent_pallet_cache_size": 10,
        "test_mode": False,
    },
    
    "hmi": {
        "screen_width": 1920,
        "screen_height": 1080,
        "button_size": (250, 100), 
    }
}