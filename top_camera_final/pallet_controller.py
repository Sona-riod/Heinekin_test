# pallet_controller.py
# =============================================================================
# Owns all business logic for a single pallet assembly session.
#
# Real-world workflow
# ───────────────────
#   1. Forklift is loaded: kegs scanned by QR, cola/water packets counted
#      by the product detector. Everything seen is counted ONCE.
#   2. Cloud sends a location popup → operator confirms.
#   3. On confirmation, product counting is FROZEN. The forklift is now
#      moving; we don't want to re-count the same bottles while in transit.
#   4. Operator (or auto-submit) dispatches. The full load — keg IDs,
#      cola count, water count, customer, area — is sent to the cloud.
#
# Product-count deduplication (IoU tracking)
# ──────────────────────────────────────────
#   The camera sees the same physical bottles across hundreds of frames.
#   We track each detected bbox with an age counter. If a new detection
#   overlaps an already-tracked bbox by ≥ IOU_THRESHOLD it is the SAME
#   bottle — skip. Otherwise it is NEW — count once and start tracking.
#   Bboxes not seen for PRODUCT_MAX_AGE frames are expired (bottle removed).
#
# Thread safety
# ─────────────
#   process_frame() runs in the detector thread.
#   remove_keg() / freeze_product_counts() run from the Kivy UI thread.
#   _keg_lock guards the three keg sets.
#   _counts_frozen is a threading.Event – safe to set/check from any thread.
# =============================================================================

import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any, Tuple, Set

from api_sender import get_api_client
from detector import KegDetector
from database import get_database
from config import logger, QRCODE_MODEL_PATH

# ── tuning constants ──────────────────────────────────────────────────────────
# Fraction of overlap above which two bboxes are the same physical object.
IOU_THRESHOLD: float = 0.30

# Frames without a match before a tracked bbox is expired (~10 s at 30 fps).
# This provides "sticky" tracking even during vibrations or occlusions.
PRODUCT_MAX_AGE: int = 300


# =============================================================================
# IoU helper
# =============================================================================

def _iou(a: Tuple[int,int,int,int], b: Tuple[int,int,int,int]) -> float:
    """Intersection-over-Union for two (x1,y1,x2,y2) boxes. Result in [0,1]."""
    ix1 = max(a[0], b[0]);  iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]);  iy2 = min(a[3], b[3])
    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter   = inter_w * inter_h
    if inter == 0:
        return 0.0
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    union  = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class _TrackedProduct:
    """One already-counted product bbox with an age counter."""
    __slots__ = ('bbox', 'age')

    def __init__(self, bbox: Tuple[int,int,int,int]):
        self.bbox: Tuple[int,int,int,int] = bbox
        self.age:  int = 0


# =============================================================================
# CustomPalletController
# =============================================================================

class CustomPalletController:

    def __init__(self, recover: bool = False):
        self.api_client = get_api_client()
        self.db         = get_database()
        self.detector   = KegDetector(model_path=QRCODE_MODEL_PATH)

        # ── session identifiers ────────────────────────────────────────────
        self.selected_customer_id: str | None = None
        self.current_pallet_id:    str | None = None

        # ── product counts ─────────────────────────────────────────────────
        # per-frame: used only for bounding-box overlay labels (not stored)
        self.product_counts: Dict[str, int] = {'cola': 0, 'water': 0}

        # cumulative session totals: updated by IoU tracker, persisted to DB
        self.cumulative_product_counts: Dict[str, int] = {'cola': 0, 'water': 0}

        # When True, no new product counts are accepted (forklift in transit)
        self._counts_frozen = threading.Event()

        # IoU tracker state (detector thread only – no lock needed)
        self._tracked_products: Dict[str, List[_TrackedProduct]] = {
            'cola': [], 'water': [],
        }

        # ── keg sets (guarded by _keg_lock) ───────────────────────────────
        self._keg_lock    = threading.Lock()
        self.scanned_kegs: Set[str] = set()
        self.saved_kegs:   Set[str] = set()
        self.removed_kegs: Set[str] = set()

        # ── frame counter for periodic logging ────────────────────────────
        self._frame_idx = 0

        if recover:
            self._recover_session()
        else:
            self._reset_session()

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def _reset_session(self) -> None:
        with self._keg_lock:
            self.scanned_kegs.clear()
            self.saved_kegs.clear()
            self.removed_kegs.clear()

        self.cumulative_product_counts = {'cola': 0, 'water': 0}
        self.product_counts            = {'cola': 0, 'water': 0}
        self._tracked_products         = {'cola': [], 'water': []}
        self._counts_frozen.clear()
        # Include seconds and a short UUID suffix to guarantee uniqueness during rapid resets
        self.current_pallet_id = datetime.now().strftime('%d%m%y_%H%M%S') + '_' + uuid.uuid4().hex[:4]

        self.db.create_pallet(
            pallet_id=self.current_pallet_id,
            customer_name=None,  # name set later via set_customer()
        )
        logger.info(f"New session started – pallet {self.current_pallet_id}")

    def reset_session(self) -> None:
        """Public alias called by the HMI Reset button."""
        self._reset_session()

    def _recover_session(self) -> None:
        logger.info("Recovery mode: looking for interrupted session…")
        recent = self.db.get_recent_pallets(limit=10)
        target = next((p for p in recent if p['status'] == 'assembling'), None)

        if not target:
            logger.warning("No interrupted session found – starting fresh.")
            self._reset_session()
            return

        self.current_pallet_id    = target['pallet_id']
        self.selected_customer_id = target['customer_name']
        self.cumulative_product_counts = {
            'cola':  target.get('cola_count',  0) or 0,
            'water': target.get('water_count', 0) or 0,
        }
        self._tracked_products = {'cola': [], 'water': []}
        self._counts_frozen.clear()   # resume counting after recovery

        keg_entries = self.db.get_keg_entries(self.current_pallet_id)
        with self._keg_lock:
            for entry in keg_entries:
                for qr in entry.get('keg_qrs', []):
                    self.scanned_kegs.add(qr)
                    self.saved_kegs.add(qr)

        logger.info(
            f"Recovered pallet {self.current_pallet_id} – "
            f"{len(self.scanned_kegs)} kegs, "
            f"cola={self.cumulative_product_counts['cola']}, "
            f"water={self.cumulative_product_counts['water']}"
        )

    # =========================================================================
    # CUSTOMER
    # =========================================================================

    def get_customers(self) -> List[Dict[str, str]]:
        return self.api_client.fetch_customers()

    def set_customer(self, customer_id: str) -> None:
        self.selected_customer_id = customer_id
        if customer_id and self.current_pallet_id:
            self.db.update_pallet_status(
                self.current_pallet_id,
                status='assembling',
                customer_name=customer_id,
            )

    # =========================================================================
    # FREEZE  (called by HMI when location is confirmed)
    # =========================================================================

    def freeze_product_counts(self) -> None:
        """
        Stop accepting new product detections.
        Called the moment the operator confirms the location popup —
        the forklift is now moving to the dispatch area and the camera
        should no longer update cola/water totals.
        Keg QR scanning continues normally (kegs are QR-identified, not
        position-tracked, so there is no risk of re-counting them).
        """
        self._counts_frozen.set()
        logger.info(
            f"Product counts frozen – "
            f"cola={self.cumulative_product_counts['cola']}, "
            f"water={self.cumulative_product_counts['water']}"
        )

    @property
    def counts_are_frozen(self) -> bool:
        return self._counts_frozen.is_set()

    # =========================================================================
    # FRAME PROCESSING  (detector thread)
    # =========================================================================

    def process_frame(self, frame):
        """
        Detect kegs and products in one frame.
        • Keg QRs: always tracked (QR uniqueness prevents re-counting).
        • Products: tracked via IoU; ignored once counts are frozen.
        Returns: (annotated_frame, keg_count, False, results_list)
        """
        annotated_frame, new_ids, results_list, frame_counts = \
            self.detector.detect_and_decode(frame)

        # Per-frame counts for bounding-box overlay labels (always updated)
        self.product_counts = frame_counts

        # Product deduplication – skip entirely if counts are frozen
        if not self._counts_frozen.is_set():
            self._update_product_counts(results_list)

        # Keg deduplication (QR-based)
        newly_added = []
        with self._keg_lock:
            for kid in new_ids:
                if kid in self.removed_kegs:
                    continue
                if kid not in self.scanned_kegs:
                    self.scanned_kegs.add(kid)
                    newly_added.append(kid)

        for kid in newly_added:
            logger.info(f"New keg: {kid} – auto-saving…")
            self._save_keg(kid)

        self._frame_idx += 1
        if self._frame_idx % 300 == 0:
            c_tracked = len(self._tracked_products['cola'])
            w_tracked = len(self._tracked_products['water'])
            logger.info(
                f"Tracking Audit [Frame {self._frame_idx}]: "
                f"kegs={len(self.scanned_kegs)}, cola_tracked={c_tracked}, water_tracked={w_tracked}"
            )

        return annotated_frame, len(self.scanned_kegs), False, results_list

    # ── IoU product tracker ───────────────────────────────────────────────

    def _update_product_counts(self, results_list: list) -> None:
        """
        For each product bbox in the current frame:
          • IoU ≥ threshold with a tracked bbox → same bottle, refresh age.
          • IoU < threshold for all tracked bboxes → new bottle, count once.
        Tracked bboxes not seen for PRODUCT_MAX_AGE frames are expired.
        """
        # Group detections by label
        frame_bboxes: Dict[str, List[Tuple[int,int,int,int]]] = {
            'cola': [], 'water': [],
        }
        for det in results_list:
            if det.get('type') != 'product':
                continue
            label = det.get('label', '')
            bbox  = det.get('bbox')
            if label in frame_bboxes and bbox:
                frame_bboxes[label].append(tuple(bbox))

        newly_counted = False

        for label, bboxes in frame_bboxes.items():
            tracked = self._tracked_products[label]
            matched = [False] * len(tracked)

            for bbox in bboxes:
                best_iou, best_idx = 0.0, -1
                for i, tp in enumerate(tracked):
                    score = _iou(bbox, tp.bbox)
                    if score > best_iou:
                        best_iou, best_idx = score, i

                if best_iou >= IOU_THRESHOLD:
                    # Same bottle – refresh position and reset age
                    tracked[best_idx].bbox = bbox
                    tracked[best_idx].age  = 0
                    matched[best_idx]      = True
                else:
                    # New bottle – count immediately independent of kegs
                    tracked.append(_TrackedProduct(bbox))
                    matched.append(True)   # keep matched in sync with tracked
                    self.cumulative_product_counts[label] += 1
                    newly_counted = True
                    logger.info(
                        f"New {label} counted – "
                        f"total: {self.cumulative_product_counts[label]}"
                    )

            # Age out unmatched entries
            new_tracked = []
            for i, tp in enumerate(tracked):
                if matched[i]:
                    new_tracked.append(tp)
                else:
                    tp.age += 1
                    if tp.age < PRODUCT_MAX_AGE:
                        new_tracked.append(tp)
            self._tracked_products[label] = new_tracked

        if newly_counted and self.current_pallet_id:
            self.db.update_product_counts(
                pallet_id=self.current_pallet_id,
                cola=self.cumulative_product_counts['cola'],
                water=self.cumulative_product_counts['water'],
            )

    # =========================================================================
    # KEG LIST
    # =========================================================================

    def get_scanned_list(self) -> List[str]:
        with self._keg_lock:
            return sorted(str(k) for k in self.scanned_kegs if k is not None)

    def remove_keg(self, keg_id: str) -> bool:
        """Operator-initiated removal of a mis-detected keg."""
        with self._keg_lock:
            if keg_id not in self.scanned_kegs:
                logger.warning(f"remove_keg: {keg_id} not in session")
                return False
            self.scanned_kegs.discard(keg_id)
            self.saved_kegs.discard(keg_id)
            self.removed_kegs.add(keg_id)
        logger.info(f"Operator removed keg: {keg_id}")
        return True

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _save_keg(self, keg_id: str) -> None:
        success = self.db.add_keg_entry(
            pallet_id=self.current_pallet_id,
            location='TopCamera',
            qr_codes=[keg_id],
        )
        if success:
            with self._keg_lock:
                self.saved_kegs.add(keg_id)
            self.db.update_product_counts(
                pallet_id=self.current_pallet_id,
                cola=self.cumulative_product_counts['cola'],
                water=self.cumulative_product_counts['water'],
            )

    def save_locally(self) -> int:
        """Safety sweep: flush any kegs not yet written to SQLite."""
        with self._keg_lock:
            pending = list(self.scanned_kegs - self.saved_kegs)

        count = 0
        for kid in pending:
            self.db.add_keg_entry(
                pallet_id=self.current_pallet_id,
                location='TopCamera',
                qr_codes=[kid],
            )
            with self._keg_lock:
                self.saved_kegs.add(kid)
            count += 1

        if count:
            self.db.update_product_counts(
                pallet_id=self.current_pallet_id,
                cola=self.cumulative_product_counts['cola'],
                water=self.cumulative_product_counts['water'],
            )
            logger.info(f"save_locally flushed {count} pending keg(s)")
        return count


    def submit_batch(self, area_name: str) -> Dict[str, Any]:
        """
        Flush remaining kegs then send the complete forklift load to the cloud:
        keg IDs + cola count + water count + customer + area.
        """
        self.save_locally()

        is_dispatch = "dispatch" in area_name.lower()
        customer_id = self.selected_customer_id

        # Customer selection is MANDATORY for Dispatch areas
        if is_dispatch and not customer_id:
            logger.warning(f"Submit blocked: Area '{area_name}' requires a customer.")
            return {'success': False, 'error': 'Customer selection required for Dispatch'}

        # If no customer selected in non-dispatch area, use empty string
        if not customer_id:
            customer_id = ""

        with self._keg_lock:
            keg_list = list(self.scanned_kegs)

        if not keg_list:
            return {'success': False, 'error': 'No kegs in session'}

        response = self.api_client.send_dispatch(
            keg_ids=keg_list,
            customer_id=customer_id,
            area_name=area_name,
            cola_count=self.cumulative_product_counts['cola'],
            water_count=self.cumulative_product_counts['water'],
        )

        if response.get('success'):
            logger.info(
                f"Dispatched – area: {area_name}, kegs: {len(keg_list)}, "
                f"cola: {self.cumulative_product_counts['cola']}, "
                f"water: {self.cumulative_product_counts['water']}"
            )
            self.db.update_pallet_status(self.current_pallet_id, 'dispatched')
        else:
            logger.error(f"Dispatch failed: {response.get('error')}")
            self.db.update_pallet_status(self.current_pallet_id, 'error_dispatch')

        return response