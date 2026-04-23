# api_sender.py
# =============================================================================
# REST API client for the Top-Camera Palletiser.
#
# Changes from original
# ─────────────────────
#   • Fixed self.logger bug (class never defined it – now uses module logger)
#   • send_dispatch() replaces send_keg_batch():
#       – includes colaCount and waterCount in the payload alongside kegIds
#       – this matches the real dispatch scenario where the cloud needs to
#         know everything on the forklift, not just keg IDs
# =============================================================================

import json
import requests
from typing import List, Dict, Any

from config import API_CONFIG, SYSTEM_CONFIG, logger


class APIClient:

    def __init__(self):
        self.mac_id           = SYSTEM_CONFIG['mac_id']
        self.timeout          = API_CONFIG['api_timeout']
        self.customer_api_url = API_CONFIG['customer_api_url']
        self.pallet_create_url = API_CONFIG['pallet_create_url']
        self.headers = {
            'Content-Type': 'application/json',
            'Accept':        'application/json',
        }

    # =========================================================================
    # CUSTOMERS
    # =========================================================================

    def fetch_customers(self) -> List[Dict[str, str]]:
        """Fetch the customer list assigned to this device from the cloud."""
        payload = {'macId': self.mac_id}
        try:
            resp = requests.post(
                self.customer_api_url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return self._parse_customers(resp.json())
            logger.warning(
                f"Customer API returned {resp.status_code}: {resp.text[:200]}"
            )
            return []
        except Exception as exc:
            logger.error(f"fetch_customers error: {exc}")
            return []

    def _parse_customers(self, data) -> List[Dict[str, str]]:
        items = data if isinstance(data, list) else (
            data.get('data') or data.get('customers') or []
        )
        customers = []
        for item in items:
            name = item.get('customerName') or item.get('name')
            cid  = item.get('_id') or item.get('id')
            if name and cid:
                customers.append({'name': str(name), 'id': str(cid)})
        return customers

    # =========================================================================
    # DISPATCH
    # =========================================================================

    def send_dispatch(
        self,
        keg_ids:     List[str],
        customer_id: str,
        area_name:   str,
        cola_count:  int,
        water_count: int,
    ) -> Dict[str, Any]:
        """
        Send the full forklift load to the cloud.

        Payload
        ───────
        {
            "macId":       "<device MAC>",
            "customerId":  "<selected customer _id>",
            "areaName":    "<confirmed dispatch location>",
            "kegIds":      ["KEG-001", "KEG-002", ...],
            "colaCount":   6,
            "waterCount":  3
        }
        """
        payload = {
            'macId':      self.mac_id,
            'customerId': customer_id,
            'areaName':   area_name,
            'kegIds':     keg_ids,
            'colaCount':  cola_count,
            'waterCount': water_count,
        }
        logger.info(f"Dispatching payload: {json.dumps(payload)}")

        try:
            resp = requests.post(
                self.pallet_create_url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                logger.info("Dispatch accepted by cloud.")
                return {'success': True, 'data': resp.text}

            logger.error(
                f"Dispatch API error {resp.status_code}: {resp.text[:200]}"
            )
            return {'success': False, 'error': resp.text}

        except Exception as exc:
            logger.error(f"Dispatch network error: {exc}")
            return {'success': False, 'error': str(exc)}


# ── singleton ─────────────────────────────────────────────────────────────────

_api_instance: APIClient | None = None


def get_api_client() -> APIClient:
    global _api_instance
    if _api_instance is None:
        _api_instance = APIClient()
    return _api_instance