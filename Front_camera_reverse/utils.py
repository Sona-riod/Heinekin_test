import logging
import json
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Deque, Optional, Union
import uuid
from collections import deque
from cryptography.fernet import Fernet
from config import CONFIG
import re

# Singleton logger
_logger = None
def get_logger(level: str = "INFO") -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("ForkliftFront")
        _logger.setLevel(getattr(logging, level))
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        _logger.addHandler(handler)
        _logger.propagate = False
    return _logger

class ForkliftLogger:
    @staticmethod
    def setup(level: str = "INFO") -> logging.Logger:
        return get_logger(level)

def get_mac_address() -> str:
    """Returns the MAC address in format 00:11:22:33:44:55"""
    # Check config first
    configured_mac = CONFIG['system'].get('mac_id')
    if configured_mac and configured_mac != "00:00:00:00:00:00":
        return configured_mac

    mac = uuid.getnode()
    return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))

def aggregate_pallet_data(qrs_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not qrs_data:
        return {"error": "No QR data"}
    
    pallet_ids = list({d['pallet_id'] for d in qrs_data})
    all_kegs = []
    total_kegs = 0
    for d in qrs_data:
        all_kegs.extend(d['kegs'])
        total_kegs += sum(keg.get('count', 0) for keg in d['kegs'])
    
    return {
        "pallet_ids": pallet_ids,
        "total_kegs": total_kegs,
        "keg_details": all_kegs,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "forklift_id": CONFIG['system']['forklift_id']
    }

def _extract_customer_info(item: Any) -> Optional[Dict[str, str]]:
    """Helper to extract customer name and ID from a dictionary item."""
    if not isinstance(item, dict):
        return None
        
    name = item.get('name') or item.get('customer_name') or item.get('customerName')
    cust_id = item.get('_id') or item.get('id') or item.get('customerId') or ''
    
    if name:
        return {'name': str(name), '_id': str(cust_id)}
    return None

def _get_customer_list(data: Any) -> List[Any]:
    """Helper to normalize response data into a list of items."""
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get('customers') or data.get('data') or data.get('result') or []
    return []

def fetch_customer_details() -> List[Dict[str, str]]:
    """Fetch customer details from cloud API."""
    logger = get_logger()
    
    try:
        api_url = CONFIG.get('api', {}).get('customer_api_url', '')
        timeout = CONFIG.get('api', {}).get('api_timeout', 10)
        
        if not api_url:
            logger.warning("Customer API URL not configured")
            return []
        
        logger.info(f"Fetching customer details from: {api_url}")
        
        payload = {"macId": get_mac_address()}
        response = requests.post(api_url, json=payload, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        raw_list = _get_customer_list(data)
        
        customers = []
        for item in raw_list:
            cust = _extract_customer_info(item)
            if cust:
                customers.append(cust)
        
        logger.info(f"Fetched {len(customers)} customers")
        return customers
        
    except Exception as e:
        logger.error(f"Error fetching customer details: {e}")
        return []

def send_camera_update_palette(pallet_id: str, area_name: str, customer_id: str = "") -> Dict[str, Any]:
    """Send HTTP POST to camera-update-palette API for each pallet."""
    logger = get_logger()
    api_url = CONFIG.get('api', {}).get('end_point_api_url', '')
    
    if not api_url:
        logger.warning("end_point_api_url not configured")
        return {"error": "API URL not configured"}
    
    payload = {
        "paletteId": pallet_id,
        "macId": get_mac_address(),
        "areaName": area_name,
        "customerId": customer_id
    }
    
    try:
        logger.info(f"Sending camera-update-palette: {payload}")
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        
        response_data = response.json()
        logger.info(f"API Response for {pallet_id}: {response_data}")
        return response_data
    except requests.exceptions.RequestException as e:
        logger.error(f"camera-update-palette failed for {pallet_id}: {e}")
        return {"error": str(e)}

def encrypt_payload(payload: Dict[str, Any], key: bytes) -> str:
    f = Fernet(key)
    json_str = json.dumps(payload)
    return f.encrypt(json_str.encode()).decode()

class TemporalTracker:
    def __init__(self, buffer_size: int = 5):
        self.buffer: Deque[set] = deque(maxlen=buffer_size)
        self.stable_threshold = buffer_size * 0.6
    
    def is_stable(self, pallet_ids: set) -> set:
        self.buffer.append(pallet_ids)
        sets_list = [b for b in self.buffer if b]
        if not sets_list:
            return set()
        stable = sets_list[0].intersection(*sets_list[1:])
        return stable if len(stable) >= self.stable_threshold else set()

class RecentPalletCache:
    def __init__(self, max_size: int = 10):
        self.cache: Deque[str] = deque(maxlen=max_size)
    
    def add(self, pallet_id: str):
        self.cache.append(pallet_id)
    
    def validate(self, pallet_id: str) -> bool:
        return pallet_id in self.cache

def is_valid_pallet_id(pallet_id: str) -> bool:
    """Check if the pallet_id matches the expected pallet format."""
    if not pallet_id:
        return False
    clean_id = pallet_id.replace("RAW:", "").strip()
    pattern = r'^\d{4}-\d{2}-\d{6}-pallette$'
    return bool(re.match(pattern, clean_id, re.IGNORECASE))

import threading

class AccumulatedPalletTracker:
    def __init__(self):
        self.accumulated_qrs = {}
        self.session_start = None
        self.lock = threading.Lock()
    
    def add_detection(self, qr_data: Dict[str, Any]):
        with self.lock:
            pallet_id = qr_data.get('pallet_id')
            if not pallet_id or pallet_id == 'UNKNOWN':
                return
            
            # Restore validation
            if not is_valid_pallet_id(pallet_id):
                return
            
            if not self.accumulated_qrs:
                self.session_start = datetime.now()
            
            # Update existing or new (keep highest confidence or latest position)
            self.accumulated_qrs[pallet_id] = qr_data
    
    def get_count(self):
        with self.lock:
            return len(self.accumulated_qrs)
    
    def get_all_qrs(self):
        with self.lock:
            return list(self.accumulated_qrs.values())
    
    def get_pallet_ids(self):
        with self.lock:
            return list(self.accumulated_qrs.keys())

    def reset(self):
        with self.lock:
            self.accumulated_qrs = {}
            self.session_start = None

TRACKER = TemporalTracker(CONFIG['camera']['temporal_buffer_size'])
RECENT_CACHE = RecentPalletCache(CONFIG['system']['recent_pallet_cache_size'])
ACCUMULATED_TRACKER = AccumulatedPalletTracker()

def extract_pallet_sequence(pallet_id: str) -> Union[int, float]:
    try:
        clean_id = pallet_id.replace("RAW:", "").strip()
        parts = clean_id.split('-')
        if len(parts) >= 3 and parts[2].isdigit():
            return int(parts[2])
        return float('inf')
    except Exception:
        return float('inf')

def sort_pallet_data(qrs_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(qrs_list, key=lambda x: extract_pallet_sequence(x.get('pallet_id', '')))

def fetch_pallet_keg_counts(pallet_ids: List[str]) -> Dict[str, int]:
    """Fetches the keg count for each pallet ID from the API."""
    logger = get_logger()
    api_url = CONFIG.get('api', {}).get('keg_count_api_url', '')
    
    if not api_url:
        logger.warning("Keg Count API URL not configured")
        return {} # STRICT: No mock data
        
    try:
        results = {}
        logger.info(f"Fetching keg counts for {len(pallet_ids)} pallets")
         
        payload = {
            "paletteIds": pallet_ids,
            "macId": CONFIG['system']['mac_id']
        }
        response = requests.post(api_url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        results = data.get("counts") or data.get("data") or data
        if not isinstance(results, dict):
             logger.warning(f"Unexpected keg count response format: {type(results)}")
             return {}
        return results
    except Exception as e:
        logger.error(f"Error fetching keg counts: {e}")
        return {}