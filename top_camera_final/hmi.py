# hmi.py  –  Professional Top-Camera HMI
# =============================================================================
# Layout  : Left = camera feed (65%)   |   Right = control panel (35%)
# Submit gate: ALL THREE must be satisfied before SUBMIT is enabled:
#   1. At least one keg scanned
#   2. A customer is selected
#   3. The location pop-up has been confirmed
# Customers are refreshed automatically every CUSTOMER_REFRESH_INTERVAL seconds
# and also on demand with the refresh button.
# Pallet ID is managed internally by the controller – not shown in the UI.
#
# Changes vs previous version:
#   • Stat bar shows cumulative cola/water counts (not per-frame)
#   • Each scanned-keg row has a ✕ delete button for mis-detections
#   • controller.remove_keg() called on delete; UI refreshes immediately
# =============================================================================

import cv2
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.color_definitions import colors as md_colors
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import (MDFlatButton, MDIconButton, MDRaisedButton,
                                MDRectangleFlatButton)
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.spinner import MDSpinner

try:
    from config import (COLOR_SCHEME, SYSTEM_CONFIG, UI_CONFIG,
                        BBOX_COLORS, BBOX_LINE_WIDTH, BBOX_FONT_SCALE,
                        BBOX_FONT_THICK, BBOX_LABEL_OFFSET, logger)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("HMI")
    COLOR_SCHEME = {}
    SYSTEM_CONFIG = {'forklift_id': 'TOP-CAM-001'}
    UI_CONFIG = {'camera_fps': 30, 'notification_duration': 4, 'min_kegs_to_save': 1}
    BBOX_COLORS = {
        'qr_decoded': (0, 220, 100), 'qr_scanning': (0, 60, 220),
        'cola': (0, 165, 255), 'water': (255, 100, 0),
    }
    BBOX_LINE_WIDTH = 2
    BBOX_FONT_SCALE = 0.55
    BBOX_FONT_THICK = 2
    BBOX_LABEL_OFFSET = 12

# ─── UI text constants ────────────────────────────────────────────────────────
_DEFAULT_CUSTOMER = '— Select Customer —'
_WAITING_TEXT     = 'Awaiting detections…'
_SUBMIT_TEXT      = 'SUBMIT TO CLOUD'
_SENDING_TEXT     = 'SENDING…'

CUSTOMER_REFRESH_INTERVAL = 60


# =============================================================================
# Helper: colour shorthand
# =============================================================================
def _c(key, fallback=(1, 1, 1, 1)):
    return COLOR_SCHEME.get(key, fallback)


# =============================================================================
# Keg ID row widget
# Includes a ✕ delete button so operators can remove mis-detected kegs.
# on_delete callback: fn(keg_id: str) → None
# =============================================================================
class KegIDRow(MDBoxLayout):
    def __init__(self, index: int, keg_id: str,
                 is_new: bool = False,
                 on_delete=None,
                 **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(32),
            spacing=dp(4),
            padding=[dp(4), 0, dp(2), 0],
            **kwargs
        )
        self._keg_id    = keg_id
        self._on_delete = on_delete

        idx_lbl = MDLabel(
            text=f"{index:02d}",
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            size_hint_x=None,
            width=dp(26),
            halign='right',
            valign='middle',
        )
        id_lbl = MDLabel(
            text=str(keg_id),
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('accent_teal'),
            halign='left',
            valign='middle',
        )
        self.add_widget(idx_lbl)
        self.add_widget(id_lbl)

        if is_new:
            badge = MDLabel(
                text='NEW',
                font_style='Overline',
                theme_text_color='Custom',
                text_color=_c('accent_teal'),
                size_hint_x=None,
                width=dp(30),
                halign='center',
                valign='middle',
            )
            self.add_widget(badge)

        # ✕ delete button
        del_btn = MDIconButton(
            icon='close-circle-outline',
            theme_text_color='Custom',
            text_color=_c('danger'),
            icon_size=dp(18),
            size_hint_x=None,
            width=dp(32),
            pos_hint={'center_y': 0.5},
        )
        del_btn.bind(on_release=self._handle_delete)
        self.add_widget(del_btn)

    def _handle_delete(self, instance):
        if self._on_delete:
            self._on_delete(self._keg_id)


# =============================================================================
# Stat card widget
# =============================================================================
class StatCard(MDCard):
    def __init__(self, label: str, value: str = '0', value_color=None, **kwargs):
        super().__init__(
            orientation='vertical',
            padding=[dp(10), dp(8)],
            spacing=dp(2),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=_c('bg_darkest'),
            **kwargs
        )
        self._val_color = value_color or _c('text_primary')
        self._lbl = MDLabel(
            text=label,
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            halign='center',
            size_hint_y=None,
            height=dp(16),
        )
        self._val = MDLabel(
            text=value,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=self._val_color,
            halign='center',
            bold=True,
        )
        self.add_widget(self._lbl)
        self.add_widget(self._val)

    def set_value(self, v: str):
        self._val.text = str(v)

    def set_color(self, color):
        self._val.text_color = color


# =============================================================================
# MAIN HMI SCREEN
# =============================================================================
class ProfessionalTopCameraHMI(MDScreen):

    def __init__(self, top_camera, controller, printer=None, **kwargs):
        super().__init__(**kwargs)
        self.top_camera  = top_camera
        self.controller  = controller
        self.printer     = printer

        self.customer_map: dict[str, str] = {}
        self.confirmed_location: str | None = None
        self.pending_location:   str | None = None
        self._dialog       = None
        self._menu         = None
        self._notify_event = None
        self._ignore_cam   = False

        self._executor     = ThreadPoolExecutor(max_workers=1, thread_name_prefix='Detector')
        self._det_future   = None
        self._last_results = []

        self._build_ui()

        fps_interval = 1.0 / UI_CONFIG.get('camera_fps', 30)
        Clock.schedule_interval(self._tick_camera, fps_interval)

        Clock.schedule_once(lambda _: self._bg_refresh_customers(), 1.0)
        Clock.schedule_interval(
            lambda _: self._bg_refresh_customers(),
            CUSTOMER_REFRESH_INTERVAL
        )

    # =========================================================================
    # UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        root = MDBoxLayout(
            orientation='horizontal',
            padding=dp(12),
            spacing=dp(12),
            md_bg_color=_c('bg_darkest'),
        )
        root.add_widget(self._build_left_panel())
        root.add_widget(self._build_right_panel())
        self.add_widget(root)

    def _build_left_panel(self):
        panel = MDBoxLayout(orientation='vertical', size_hint_x=0.65, spacing=dp(10))

        hdr = MDBoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        title = MDLabel(
            text='PALLETIZER',
            font_style='H6',
            theme_text_color='Custom',
            text_color=_c('accent_amber'),
            bold=True,
            halign='left',
            valign='center',
        )
        sub = MDLabel(
            text=f"TOP CAMERA  ·  {SYSTEM_CONFIG.get('forklift_id', '')}",
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            halign='left',
            valign='center',
        )
        title_col = MDBoxLayout(orientation='vertical')
        title_col.add_widget(title)
        title_col.add_widget(sub)

        self._ws_label = MDLabel(
            text='● WS',
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('accent_teal'),
            size_hint_x=None,
            width=dp(70),
            halign='center',
            valign='center',
        )
        exit_btn = MDIconButton(
            icon='close-box',
            theme_text_color='Custom',
            text_color=_c('danger'),
            icon_size=dp(32),
            pos_hint={'center_y': 0.5},
        )
        exit_btn.bind(on_release=self._on_exit)

        hdr.add_widget(title_col)
        hdr.add_widget(self._ws_label)
        hdr.add_widget(exit_btn)
        panel.add_widget(hdr)

        cam_card = MDCard(
            elevation=3,
            radius=[dp(10)],
            padding=dp(2),
            md_bg_color=_c('bg_dark'),
        )
        self._cam_img = Image(fit_mode='contain')
        cam_card.add_widget(self._cam_img)
        panel.add_widget(cam_card)

        panel.add_widget(self._build_stat_bar())

        self._notify_lbl = MDLabel(
            text='System Ready',
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('accent_teal'),
            halign='center',
            size_hint_y=None,
            height=dp(22),
        )
        panel.add_widget(self._notify_lbl)
        return panel

    def _build_stat_bar(self):
        """
        4-card stat bar: Kegs Scanned | Cola Packs | Water Packs | Session
        Cola and Water show CUMULATIVE session totals, not per-frame counts.
        """
        bar = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(70),
            spacing=dp(8),
        )
        self._stat_kegs   = StatCard('KEGS SCANNED', '0',          _c('accent_amber'))
        self._stat_cola   = StatCard('COLA PACKS',   '0',          _c('cola_color'))
        self._stat_water  = StatCard('WATER PACKS',  '0',          _c('water_color'))
        self._stat_status = StatCard('SESSION',      'ASSEMBLING', _c('accent_teal'))
        for card in (self._stat_kegs, self._stat_cola, self._stat_water, self._stat_status):
            bar.add_widget(card)
        return bar

    def _build_right_panel(self):
        panel = MDCard(
            orientation='vertical',
            size_hint_x=0.35,
            padding=dp(16),
            spacing=dp(12),
            radius=[dp(12)],
            elevation=4,
            md_bg_color=_c('bg_dark'),
        )

        count_card = MDCard(
            orientation='vertical',
            size_hint_y=None,
            height=dp(100),
            radius=[dp(8)],
            padding=[dp(8), dp(6)],
            elevation=0,
            md_bg_color=_c('bg_darkest'),
        )
        self._keg_count_lbl = MDLabel(
            text='0',
            font_style='H3',
            theme_text_color='Custom',
            text_color=_c('accent_amber'),
            halign='center',
            bold=True,
        )
        self._count_sub = MDLabel(
            text='LIVE KEG COUNT',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            halign='center',
            size_hint_y=None,
            height=dp(18),
        )
        count_card.add_widget(self._keg_count_lbl)
        count_card.add_widget(self._count_sub)
        panel.add_widget(count_card)

        prod_row = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        self._cola_card  = StatCard('COLA PACKS',  '0', _c('cola_color'))
        self._water_card = StatCard('WATER PACKS', '0', _c('water_color'))
        prod_row.add_widget(self._cola_card)
        prod_row.add_widget(self._water_card)
        panel.add_widget(prod_row)

        self._cust_row = MDBoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self._cust_btn = MDRectangleFlatButton(
            text=_DEFAULT_CUSTOMER,
            pos_hint={'center_y': 0.5},
            size_hint_x=0.85,
            font_size='13sp',
        )
        self._cust_btn.bind(on_release=self._open_customer_menu)
        self._refresh_btn = MDIconButton(
            icon='refresh',
            theme_text_color='Custom',
            text_color=_c('accent_teal'),
            icon_size=dp(22),
            pos_hint={'center_y': 0.5},
        )
        self._refresh_btn.bind(on_release=lambda _: self._on_refresh_click())
        self._cust_row.add_widget(self._cust_btn)
        self._cust_row.add_widget(self._refresh_btn)

        panel.add_widget(MDLabel(
            text='CUSTOMER',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            size_hint_y=None,
            height=dp(16),
        ))
        panel.add_widget(self._cust_row)

        panel.add_widget(MDLabel(
            text='LOCATION',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            size_hint_y=None,
            height=dp(16),
        ))
        self._loc_card = MDCard(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(38),
            radius=[dp(6)],
            padding=[dp(10), dp(4)],
            elevation=0,
            md_bg_color=_c('bg_darkest'),
        )
        self._loc_lbl = MDLabel(
            text='Awaiting location from cloud…',
            font_style='Body2',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            halign='left',
            valign='center',
        )
        self._loc_card.add_widget(self._loc_lbl)
        panel.add_widget(self._loc_card)

        # scanned IDs header
        list_hdr = MDBoxLayout(size_hint_y=None, height=dp(22), spacing=dp(6))
        list_hdr_lbl = MDLabel(
            text='SCANNED IDs',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
        )
        self._scan_badge = MDLabel(
            text='0 ITEMS',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=_c('accent_amber'),
            halign='right',
        )
        list_hdr.add_widget(list_hdr_lbl)
        list_hdr.add_widget(self._scan_badge)
        panel.add_widget(list_hdr)

        # scanned IDs scroll list
        scroll_bg = MDCard(
            md_bg_color=_c('bg_darkest'),
            radius=[dp(8)],
            padding=dp(6),
            elevation=0,
        )
        self._id_scroll = ScrollView()
        self._id_list_box = MDBoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=dp(2),
        )
        self._id_list_box.bind(minimum_height=self._id_list_box.setter('height'))
        self._empty_lbl = MDLabel(
            text=_WAITING_TEXT,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_c('text_hint'),
            halign='center',
            size_hint_y=None,
            height=dp(40),
        )
        self._id_list_box.add_widget(self._empty_lbl)
        self._id_scroll.add_widget(self._id_list_box)
        scroll_bg.add_widget(self._id_scroll)
        panel.add_widget(scroll_bg)

        # action buttons
        btn_row = MDBoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        self._reset_btn = MDRectangleFlatButton(
            text='RESET',
            theme_text_color='Custom',
            text_color=_c('accent_amber'),
            line_color=_c('accent_amber'),
            disabled=True,
            font_size='14sp',
            size_hint_x=None,
            width=dp(90),
            pos_hint={'center_y': 0.5},
        )
        self._reset_btn.bind(on_release=self._on_reset)
        self._submit_btn = MDRaisedButton(
            text=_SUBMIT_TEXT,
            md_bg_color=_c('text_hint'),
            disabled=True,
            font_size='15sp',
            size_hint_x=1,
            size_hint_y=None,
            height=dp(48),
            pos_hint={'center_y': 0.5},
            elevation=2,
        )
        self._submit_btn.bind(on_press=self._on_submit)
        btn_row.add_widget(self._reset_btn)
        btn_row.add_widget(self._submit_btn)
        panel.add_widget(btn_row)

        return panel

    # =========================================================================
    # CAMERA TICK
    # =========================================================================

    def _tick_camera(self, dt):
        try:
            if not self.top_camera.is_active:
                return
            ret, frame = self.top_camera.get_overhead_view()
            if not ret or frame is None:
                return
            vis = frame.copy()
            self._collect_detection(vis)
            if self._det_future is None:
                self._det_future = self._executor.submit(
                    self.controller.process_frame, frame.copy()
                )
            self._draw_overlay(vis)
            self._push_texture(vis)
        except Exception as exc:
            logger.error(f"Camera tick error: {exc}")

    def _collect_detection(self, frame):
        if self._det_future is None or not self._det_future.done():
            return
        try:
            _, count, _, results_list = self._det_future.result()
            self._last_results = results_list
            if self._ignore_cam:
                return
            # Read CUMULATIVE counts from controller, not per-frame
            cola  = self.controller.cumulative_product_counts.get('cola',  0)
            water = self.controller.cumulative_product_counts.get('water', 0)
            scanned = self.controller.get_scanned_list()
            n = len(scanned)
            Clock.schedule_once(
                lambda _: self._refresh_ui(n, cola, water, scanned), 0
            )
        except Exception as exc:
            logger.error(f"Detection result error: {exc}")
        finally:
            self._det_future = None

    # =========================================================================
    # UI REFRESH
    # =========================================================================

    def _refresh_ui(self, keg_count, cola, water, scanned_list):
        self._keg_count_lbl.text = str(keg_count)
        self._stat_kegs.set_value(str(keg_count))
        self._stat_cola.set_value(str(cola))
        self._stat_water.set_value(str(water))
        self._cola_card.set_value(str(cola))
        self._water_card.set_value(str(water))
        self._scan_badge.text = f"{keg_count} ITEMS"
        self._rebuild_id_list(scanned_list)
        self._update_button_states(keg_count)

    def _rebuild_id_list(self, scanned_list: list[str]):
        self._id_list_box.clear_widgets()
        if not scanned_list:
            self._id_list_box.add_widget(self._empty_lbl)
            return
        for i, kid in enumerate(reversed(scanned_list)):
            self._id_list_box.add_widget(
                KegIDRow(
                    index=len(scanned_list) - i,
                    keg_id=kid,
                    is_new=(i == 0),
                    on_delete=self._on_delete_keg,
                )
            )

    def _update_button_states(self, keg_count: int):
        has_kegs     = keg_count >= UI_CONFIG.get('min_kegs_to_save', 1)
        has_customer = self._cust_btn.text != _DEFAULT_CUSTOMER
        has_location = self.confirmed_location is not None
        self._reset_btn.disabled = not has_kegs

        # Conditionality based on Area type
        is_dispatch = "dispatch" in str(self.confirmed_location).lower()
        
        if is_dispatch:
            # Dispatch requires Customer selection
            all_ready = has_kegs and has_location and has_customer
        else:
            # Storage/Other only requires Location acknowledgement
            all_ready = has_kegs and has_location

        self._submit_btn.disabled = not all_ready
        self._submit_btn.md_bg_color = (
            _c('accent_amber') if all_ready else _c('text_hint')
        )

    # =========================================================================
    # DELETE KEG  (mis-detection removal)
    # =========================================================================

    def _on_delete_keg(self, keg_id: str):
        """Tap ✕ on a row → confirm dialog → remove from session."""
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='REMOVE KEG?',
            text=(
                f"Remove [b]{keg_id}[/b] from this session?\n\n"
                "This keg will not be included in the submission "
                "and will not be re-added if the camera sees it again."
            ),
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='REMOVE',
                    md_bg_color=_c('danger'),
                    on_release=lambda _: self._confirm_delete_keg(keg_id),
                ),
            ],
        )
        self._dialog.open()

    def _confirm_delete_keg(self, keg_id: str):
        self._dismiss_dialog()
        removed = self.controller.remove_keg(keg_id)
        if removed:
            scanned = self.controller.get_scanned_list()
            n     = len(scanned)
            cola  = self.controller.cumulative_product_counts.get('cola',  0)
            water = self.controller.cumulative_product_counts.get('water', 0)
            self._refresh_ui(n, cola, water, scanned)
            self._notify(f"Removed: {keg_id}", color=_c('warning'))
        else:
            self._notify(f"Could not remove {keg_id}", color=_c('danger'))

    # =========================================================================
    # BOUNDING BOX OVERLAY
    # =========================================================================

    def _draw_overlay(self, frame):
        for det in self._last_results:
            bbox = det.get('bbox')
            if not bbox:
                continue
            x1, y1, x2, y2 = bbox
            dtype = det.get('type', 'qr')
            data  = det.get('data')

            if dtype == 'product':
                label_name = det.get('label', '')
                color = BBOX_COLORS.get(label_name, BBOX_COLORS.get('cola'))
                label_text = data or label_name.upper()
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, BBOX_LINE_WIDTH)
            else:
                if data:
                    color = BBOX_COLORS['qr_decoded']
                    label_text = data
                else:
                    color = BBOX_COLORS['qr_scanning']
                    label_text = 'Scanning…'
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, BBOX_LINE_WIDTH)
                self._draw_corner_brackets(frame, x1, y1, x2, y2, color)

            (tw, th), _ = cv2.getTextSize(
                label_text, cv2.FONT_HERSHEY_SIMPLEX,
                BBOX_FONT_SCALE, BBOX_FONT_THICK
            )
            lx, ly = x1, max(y1 - BBOX_LABEL_OFFSET, th + 4)
            cv2.rectangle(frame, (lx, ly - th - 4), (lx + tw + 8, ly + 2),
                          (0, 0, 0), -1)
            cv2.putText(frame, label_text, (lx + 4, ly),
                        cv2.FONT_HERSHEY_SIMPLEX, BBOX_FONT_SCALE,
                        color, BBOX_FONT_THICK)

    @staticmethod
    def _draw_corner_brackets(frame, x1, y1, x2, y2, color, length=14, thick=3):
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        dirs    = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
        for (cx, cy), (dx, dy) in zip(corners, dirs):
            cv2.line(frame, (cx, cy), (cx + dx * length, cy), color, thick)
            cv2.line(frame, (cx, cy), (cx, cy + dy * length), color, thick)

    # =========================================================================
    # TEXTURE PUSH
    # =========================================================================

    def _push_texture(self, frame):
        frame = cv2.flip(frame, 0)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w  = frame.shape[:2]
        tex = self._cam_img.texture
        if tex is None or tex.size != (w, h):
            tex = Texture.create(size=(w, h), colorfmt='rgb')
            self._cam_img.texture = tex
        tex.blit_buffer(frame.tobytes(), colorfmt='rgb', bufferfmt='ubyte')
        self._cam_img.canvas.ask_update()

    # =========================================================================
    # CUSTOMER MANAGEMENT
    # =========================================================================

    def _bg_refresh_customers(self):
        threading.Thread(target=self._fetch_customers_thread, daemon=True).start()

    def _fetch_customers_thread(self):
        try:
            customers = self.controller.get_customers()
            Clock.schedule_once(lambda _: self._apply_customers(customers), 0)
        except Exception as exc:
            logger.error(f"Customer fetch error: {exc}")
            Clock.schedule_once(
                lambda _: self._notify('Network error – customer list not updated',
                                       color=_c('danger')), 0
            )

    def _apply_customers(self, customers: list[dict]):
        if not customers:
            self._notify('No customers returned from API', color=_c('warning'))
            return
        self.customer_map = {c['name']: c['id'] for c in customers}
        if self._cust_btn.text not in self.customer_map:
            self._cust_btn.text = _DEFAULT_CUSTOMER
        self._notify(f"{len(customers)} customers loaded",
                     color=_c('accent_teal'), duration=3)

    def _open_customer_menu(self, instance):
        if not self.customer_map:
            self._notify('No customers loaded – tap refresh', color=_c('warning'))
            return
        if self._menu:
            self._menu.dismiss()
        items = [
            {
                'text': name,
                'viewclass': 'OneLineListItem',
                'on_release': (lambda n=name: self._select_customer(n)),
            }
            for name in self.customer_map
        ]
        self._menu = MDDropdownMenu(
            caller=self._cust_btn,
            items=items,
            width=dp(260),
            max_height=dp(320),
        )
        self._menu.open()

    def _select_customer(self, name: str):
        if self._menu:
            self._menu.dismiss()
        self._cust_btn.text = name
        cid = self.customer_map.get(name, '')
        threading.Thread(
            target=lambda: self.controller.set_customer(cid), daemon=True
        ).start()
        self._notify(f"Customer: {name}", color=_c('accent_teal'), duration=3)
        self._update_button_states(len(self.controller.scanned_kegs))

    def _on_refresh_click(self):
        self._notify('Refreshing customers…', color=_c('warning'))
        self._bg_refresh_customers()

    # =========================================================================
    # WEBSOCKET LOCATION POPUP
    # =========================================================================

    def on_websocket_message(self, data: dict):
        new_loc = data.get('location', 'Unknown')
        if self.confirmed_location == new_loc or self.pending_location == new_loc:
            return
        self.pending_location = new_loc
        Clock.schedule_once(lambda _: self._show_location_popup(new_loc), 0)

    def _show_location_popup(self, location_name: str):
        self._dismiss_dialog()
        
        content = MDBoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None, height=dp(80))
        msg_lbl = MDLabel(
            text=(
                f"The forklift has arrived at a new location:\n\n"
                f"[b]{location_name}[/b]\n\n"
                "Acknowledge to enable submission."
            ),
            markup=True,
            font_style='Body1',
            theme_text_color='Custom',
            text_color=_c('text_primary', (1, 1, 1, 1)),
            halign='center'
        )
        content.add_widget(msg_lbl)
        
        self._dialog = MDDialog(
            title='LOCATION ARRIVED',
            type="custom",
            content_cls=content,
            buttons=[
                MDRaisedButton(
                    text='OK',
                    md_bg_color=_c('accent_teal'),
                    on_release=lambda _: self._on_location_confirm(),
                ),
            ],
        )
        self._dialog.open()

    def _on_location_confirm(self):
        self._dismiss_dialog()
        self.confirmed_location = self.pending_location
        loc = self.confirmed_location or ''

        # ── freeze product counts ──────────────────────────────────────────
        # The forklift is now moving to the dispatch area. Stop accumulating
        # cola/water detections so the same bottles aren't re-counted in transit.
        self.controller.freeze_product_counts()
        self._mark_product_counts_frozen()

        self._loc_lbl.text = f"✔  {loc}"
        self._loc_lbl.text_color = _c('accent_teal')
        self._loc_card.md_bg_color = (0.0, 0.2, 0.18, 1)
        self._stat_status.set_value('READY')
        self._stat_status.set_color(_c('accent_teal'))
        self._notify(
            f"Location confirmed: {loc} – product counts locked",
            color=_c('accent_teal'),
        )
        self._update_button_states(len(self.controller.scanned_kegs))
        if not self._submit_btn.disabled:
            self._notify('Ready to submit — press SUBMIT TO CLOUD', color=_c('accent_amber'))
        else:
            is_dispatch = "dispatch" in loc.lower()
            if is_dispatch and self._cust_btn.text == _DEFAULT_CUSTOMER:
                self._notify('Select a customer to enable submission', color=_c('warning'))

    def _mark_product_counts_frozen(self) -> None:
        """
        Visually indicate that cola/water counts are locked.
        Appends '(locked)' to the stat-card and right-panel card labels
        so the operator can see the counts will no longer change.
        """
        for card in (self._stat_cola, self._cola_card):
            card._lbl.text = 'COLA PACKS  ·  LOCKED'
        for card in (self._stat_water, self._water_card):
            card._lbl.text = 'WATER PACKS  ·  LOCKED'

    def _mark_product_counts_active(self) -> None:
        """Restore product card labels to their normal (unlocked) state."""
        for card in (self._stat_cola, self._cola_card):
            card._lbl.text = 'COLA PACKS'
        for card in (self._stat_water, self._water_card):
            card._lbl.text = 'WATER PACKS'

    def _on_location_cancel(self):
        self._dismiss_dialog()
        self._notify('Location cancelled', color=_c('danger'))

    # =========================================================================
    # RESET
    # =========================================================================

    def _on_reset(self, instance):
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='RESET SESSION?',
            text=(
                f"This will clear all {len(self.controller.scanned_kegs)} scanned kegs "
                "and start a new pallet.\n\nThis action cannot be undone."
            ),
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='RESET',
                    md_bg_color=_c('danger'),
                    on_release=lambda _: self._confirm_reset(),
                ),
            ],
        )
        self._dialog.open()

    def _confirm_reset(self):
        self._dismiss_dialog()
        self.confirmed_location = None
        self.pending_location   = None
        self._loc_lbl.text = 'Awaiting location from cloud…'
        self._loc_lbl.text_color = _c('text_hint')
        self._loc_card.md_bg_color = _c('bg_darkest')
        self._stat_status.set_value('ASSEMBLING')
        self._stat_status.set_color(_c('accent_teal'))
        # Restore product card labels to active state (counts will reset to 0)
        self._mark_product_counts_active()
        threading.Thread(target=self._do_reset_bg, daemon=True).start()

    def _do_reset_bg(self):
        try:
            self.controller.reset_session()
            cid = self.customer_map.get(self._cust_btn.text)
            if cid:
                self.controller.set_customer(cid)
        except Exception as exc:
            logger.error(f"Reset error: {exc}")
        Clock.schedule_once(lambda _: self._post_reset_ui(), 0)

    def _post_reset_ui(self):
        self._ignore_cam = True
        self._refresh_ui(0, 0, 0, [])
        self._notify('Session reset – new pallet started', color=_c('accent_teal'))
        Clock.schedule_once(lambda _: setattr(self, '_ignore_cam', False), 2.0)

    # =========================================================================
    # SUBMIT
    # =========================================================================

    def _on_submit(self, instance):
        self._submit_btn.disabled = True
        self._submit_btn.text     = _SENDING_TEXT
        self._stat_status.set_value('SENDING')
        self._stat_status.set_color(_c('warning'))
        self._notify('Dispatching batch to cloud…', color=_c('accent_amber'))
        threading.Thread(target=self._submit_thread, daemon=True).start()

    def _submit_thread(self):
        try:
            area = self.confirmed_location or 'Unknown'
            result = self.controller.submit_batch(area_name=area)
            Clock.schedule_once(lambda _: self._post_submit_ui(result), 0)
        except Exception as exc:
            logger.error(f"Submit thread error: {exc}")
            Clock.schedule_once(
                lambda _: self._submit_failed({'error': str(exc)}), 0
            )

    def _post_submit_ui(self, result: dict):
        if result.get('success'):
            self._stat_status.set_value('DISPATCHED')
            self._stat_status.set_color(_c('success'))
            self._notify('Batch dispatched successfully!', color=_c('success'))
            
            # --- PRINTER TRIGGER ---
            try:
                # result['data'] is the response text from api_sender.py
                response_str = result.get('data')
                if response_str:
                    resp = json.loads(response_str)
                    pallet_id = (resp.get('paletteId')
                                 or resp.get('palletId')
                                 or resp.get('id'))
                    
                    if pallet_id and self.printer:
                        self._notify(f"Printing Pallet {pallet_id}...", color=_c('accent_teal'))
                        
                        def _do_print_bg():
                            ok, msg = self.printer.print_pallet_qr(pallet_id)
                            Clock.schedule_once(lambda _: self._notify(
                                f"Pallet {pallet_id} Printed!" if ok else f"Printer Error: {msg}",
                                color=_c('success') if ok else _c('danger')
                            ), 0)
                        
                        threading.Thread(target=_do_print_bg, name='PrinterThread', daemon=True).start()
            except Exception as e:
                logger.warning(f"Failed to trigger printer logic: {e}")
            # -----------------------

            self._confirm_reset()
        else:
            self._submit_failed(result)

    def _submit_failed(self, result: dict):
        self._submit_btn.text     = _SUBMIT_TEXT
        self._submit_btn.disabled = False
        self._stat_status.set_value('ERROR')
        self._stat_status.set_color(_c('danger'))
        self._notify('Submission failed – see dialog', color=_c('danger'))
        err = result.get('error', 'Unknown network error')
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='SUBMISSION FAILED',
            text=f"Could not dispatch batch to cloud.\n\nReason: {err}",
            buttons=[
                MDRaisedButton(
                    text='CLOSE',
                    md_bg_color=_c('danger'),
                    on_release=lambda _: self._dismiss_dialog(),
                ),
            ],
        )
        self._dialog.open()

    # =========================================================================
    # EXIT
    # =========================================================================

    def _on_exit(self, instance):
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='EXIT APPLICATION?',
            text='Shut down the Top Camera System?\n\nSession data is safe in the local database.',
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='SHUT DOWN',
                    md_bg_color=_c('danger'),
                    on_release=lambda _: self._confirm_exit(),
                ),
            ],
        )
        self._dialog.open()

    def _confirm_exit(self):
        self._dismiss_dialog()
        try:
            MDApp.get_running_app().stop()
            Window.close()
        except Exception as exc:
            logger.error(f"Exit error: {exc}")

    # =========================================================================
    # NOTIFICATION BAR
    # =========================================================================

    def _notify(self, text: str, color=None, duration: int | None = None):
        def _do(dt):
            self._notify_lbl.text = text
            self._notify_lbl.text_color = color or _c('accent_teal')
            if self._notify_event:
                self._notify_event.cancel()
            d = duration if duration is not None else UI_CONFIG.get('notification_duration', 4)
            if d > 0:
                self._notify_event = Clock.schedule_once(self._clear_notify, d)
        Clock.schedule_once(_do, 0)

    def _clear_notify(self, dt):
        self._notify_lbl.text       = 'System Ready'
        self._notify_lbl.text_color = _c('accent_teal')

    # =========================================================================
    # WEBSOCKET STATUS
    # =========================================================================

    def set_ws_status(self, status: str):
        def _do(dt):
            if status == 'connected':
                self._ws_label.text       = '● WS'
                self._ws_label.text_color = _c('accent_teal')
            elif status == 'connecting':
                self._ws_label.text       = '○ WS'
                self._ws_label.text_color = _c('warning')
            else:
                self._ws_label.text       = '✕ WS'
                self._ws_label.text_color = _c('danger')
        Clock.schedule_once(_do, 0)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _dismiss_dialog(self):
        if self._dialog:
            try:
                self._dialog.dismiss()
            except Exception:
                pass
            self._dialog = None