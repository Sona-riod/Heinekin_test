from kivy.config import Config
Config.set('graphics', 'width', '1920')
Config.set('graphics', 'height', '1080')
Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'show_cursor', '1')
Config.write()

from kivy.core.window import Window
Window.show_cursor = True
Window.fullscreen = 'auto'

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.floatlayout import MDFloatLayout
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivy.uix.screenmanager import FadeTransition

from kivymd.uix.button import MDRaisedButton, MDIconButton, MDRectangleFlatButton, MDFillRoundFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem, MDList
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.spinner import MDSpinner
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.toolbar import MDTopAppBar
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import ObjectProperty, StringProperty, BooleanProperty
import cv2
import threading
import time
import logging

# --- CUSTOM WIDGETS ---

class ClickableImage(Image):
    """Custom Image widget that captures touch coordinates"""
    def __init__(self, touch_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.touch_callback = touch_callback

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.touch_callback:
                self.touch_callback(self, touch)
            return True # Consume the touch
        return super().on_touch_down(touch)



class CameraPreview(MDCard):
    """Camera preview container with Touch Mapping."""
    def __init__(self, main_screen=None, **kwargs):
        super().__init__(**kwargs)
        self.main_screen = main_screen
        self.radius = [15, 15, 15, 15]
        self.elevation = 2
        self.md_bg_color = (0.1, 0.1, 0.1, 1)
        self.padding = dp(0)
        
        self.layout = MDFloatLayout()
        
        # New Clickable Image for Live Feed
        self.camera_img = ClickableImage(
            touch_callback=self._handle_image_touch, 
            allow_stretch=True, 
            keep_ratio=True
        )
        self.layout.add_widget(self.camera_img)
        
        self.overlay = MDLabel(
            text='Initializing Camera...',
            halign='center',
            theme_text_color='Custom',
            text_color=(1, 1, 1, 0.7),
            font_style='H5',
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        self.layout.add_widget(self.overlay)
        self.add_widget(self.layout)

    def _handle_image_touch(self, instance, touch):
        if not self.main_screen or not self.main_screen.current_qrs:
            return

        # Map UI touch coords → actual frame pixel coords (uses stored frame size)
        frame_w = self.main_screen.frame_w
        frame_h = self.main_screen.frame_h

        draw_w, draw_h = self.camera_img.norm_image_size
        draw_x = self.camera_img.center_x - draw_w / 2
        draw_y = self.camera_img.center_y - draw_h / 2

        if draw_x <= touch.x <= draw_x + draw_w and draw_y <= touch.y <= draw_y + draw_h:
            rel_x = (touch.x - draw_x) / draw_w
            rel_y = 1.0 - ((touch.y - draw_y) / draw_h)  # Kivy → OpenCV Y-axis

            frame_x = int(rel_x * frame_w)
            frame_y = int(rel_y * frame_h)

            self.main_screen.check_touch_selection(frame_x, frame_y)

    def show_error(self, message):
        self.overlay.text = message
        self.overlay.opacity = 1
        
    def hide_error(self):
        self.overlay.opacity = 0

    def update_frame(self, frame):
        try:
            buf = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
            texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
            self.camera_img.texture = texture
            
            if self.overlay.text == 'Initializing Camera...' and self.overlay.opacity > 0:
                 self.overlay.opacity = 0
        except Exception:
            self.show_error('Camera Error')

class StatusCard(MDCard):
    def __init__(self, title, icon="package-variant-closed", **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(12) # Reduced padding
        self.spacing = dp(5)
        self.radius = [10] # Standardized radius
        self.elevation = 2
        self.size_hint_y = None
        self.height = dp(90) # Significantly reduced from 140dp
        self.md_bg_color = (0.18, 0.18, 0.18, 1) 
        
        title_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(25), spacing=dp(8))
       
        title_lbl = MDLabel(text=title.upper(), theme_text_color="Secondary", font_style="Subtitle2", valign='center')
        title_box.add_widget(title_lbl)
        self.add_widget(title_box)
        
        self.value_label = MDLabel(
            text="0", 
            halign='left', 
            theme_text_color="Custom", 
            text_color=(0, 0.85, 0.9, 1),
            font_style="H4", # Scaled down from H2
            bold=True
        )
        self.add_widget(self.value_label)

    def update_value(self, value):
        self.value_label.text = str(value)

class ZoneIndicator(MDCard):
    def __init__(self, touch_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.touch_callback = touch_callback
        self.padding = dp(12)
        self.spacing = dp(15)
        self.radius = [10]
        self.elevation = 2
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(70) # Reduced from 100dp
        self.md_bg_color = (0.15, 0.15, 0.15, 1)

        self.icon_btn = MDIconButton(
            icon="map-marker",
            theme_text_color="Custom",
            text_color=(0.5, 0.5, 0.5, 1),
            pos_hint={'center_y': 0.5}
        )
        self.icon_btn.font_size = "32sp" # Reduced from 48sp
        self.add_widget(self.icon_btn)
        
        txt_box = MDBoxLayout(orientation='vertical', padding=(0, 5))
        txt_box.add_widget(MDLabel(text="CURRENT ZONE", theme_text_color="Secondary", font_style="Caption"))
        self.zone_value = MDLabel(
            text="WAITING...", 
            theme_text_color="Primary", 
            font_style="H6", # Scaled down from H5
            bold=True
        )
        txt_box.add_widget(self.zone_value)
        self.add_widget(txt_box)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.touch_callback:
                self.touch_callback()
            return True
        return super().on_touch_down(touch)

    def set_zone(self, zone):
        zone_lower = zone.lower()
        if "storage" in zone_lower:
            self.icon_btn.text_color = (0.2, 0.8, 0.2, 1) 
            self.icon_btn.icon = "warehouse"
            self.zone_value.text = "STORAGE AREA"
        elif "dispatch" in zone_lower:
            self.icon_btn.text_color = (1, 0.6, 0, 1) 
            self.icon_btn.icon = "truck-delivery"
            self.zone_value.text = "DISPATCH AREA"
        else:
            self.icon_btn.text_color = (0, 0.7, 1, 1) 
            self.icon_btn.icon = "transit-connection-variant"
            self.zone_value.text = "IN TRANSIT"

class SplashScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = (0.1, 0.1, 0.1, 1) 
        
        layout = MDFloatLayout()
        
        self.icon_label = MDIconButton(
            icon="forklift",
            theme_text_color="Custom",
            text_color=(0, 0.8, 0.9, 1),
            pos_hint={'center_x': 0.5, 'center_y': 0.6},
            icon_size="96sp",
        )
        layout.add_widget(self.icon_label)
        
        self.title_label = MDLabel(
            text="FORKLIFT CAMERA SYSTEM",
            halign="center",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            font_style="H4",
            pos_hint={'center_x': 0.5, 'center_y': 0.45}
        )
        layout.add_widget(self.title_label)
        
        self.status_label = MDLabel(
            text="Initializing System...",
            halign="center",
            theme_text_color="Custom",
            text_color=(0.7, 0.7, 0.7, 1),
            font_style="Subtitle1",
            pos_hint={'center_x': 0.5, 'center_y': 0.35}
        )
        layout.add_widget(self.status_label)
        
        self.spinner = MDSpinner(
            size_hint=(None, None),
            size=(dp(46), dp(46)),
            pos_hint={'center_x': 0.5, 'center_y': 0.25},
            active=True,
            palette=[
                [0, 0.8, 0.9, 1], 
                [1, 0.6, 0, 1],   
            ]
        )
        layout.add_widget(self.spinner)
        self.add_widget(layout)

    def update_status(self, text):
        self.status_label.text = text

# --- MAIN UI LAYOUT ---

class MainScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        
        self.root_box = MDBoxLayout(orientation='vertical', padding=dp(10), spacing=dp(10))
        self.root_box.md_bg_color = (0.1, 0.1, 0.12, 1) 
        self.add_widget(self.root_box)
        
        self.current_count = 0
        self.current_qrs = []          # All QRs currently detected in ROI
        self.all_detected_qrs = []     # Full detected list (used internally)
        self.selected_pallet_ids = set()  # Operator-selected pallets
        self.frame_w = 1920            # Actual camera frame width (updated each frame)
        self.frame_h = 1080            # Actual camera frame height (updated each frame)
        self.customer_data = {}
        self.dialog = None
        self.location_confirmed = False   # True only after WS location popup is confirmed
        self.is_capturing = False         # Tracks whether CAPTURE is active
        self.previous_detected_ids = set() # Track IDs seen in previous frame for persistence

        # --- HEADER ---
        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(60), padding=(10, 0))
        
        self.status_icon = MDIconButton(icon="wifi-off", theme_text_color="Error")
        self.status_icon.font_size = "32sp"
        header.add_widget(self.status_icon)
        
        self.status_label = MDLabel(
            text="DISCONNECTED", 
            theme_text_color="Error", 
            font_style="H6",
            bold=True,
            valign='center'
        )
        header.add_widget(self.status_label)
        
        exit_btn = MDIconButton(icon="power-standby", theme_text_color="Error")
        exit_btn.font_size = "32sp"
        exit_btn.bind(on_release=self.show_exit_dialog)
        header.add_widget(exit_btn)
        
        self.root_box.add_widget(header)

        self.zone_indicator = ZoneIndicator(size_hint_y=None, height=dp(70), touch_callback=self._on_zone_indicator_pressed)
        self.root_box.add_widget(self.zone_indicator)

        # --- MAIN CONTENT AREA ---
        self.main_content = self._build_main_layout()
        self.root_box.add_widget(self.main_content)

    def _build_main_layout(self):
        layout = MDBoxLayout(orientation='horizontal', padding=dp(15), spacing=dp(15))
        
        self.cam_prev = CameraPreview(main_screen=self, size_hint_x=0.75)
        layout.add_widget(self.cam_prev)
        
        right_panel = MDBoxLayout(orientation='vertical', size_hint_x=0.25, spacing=dp(10))
        
        self.card_qr_count = StatusCard(title="Pallets Detected", icon="package-variant")
        right_panel.add_widget(self.card_qr_count)
        
        right_panel.add_widget(MDLabel(text="Live Feed", theme_text_color="Secondary", font_style="Caption", size_hint_y=None, height=dp(20)))
        
        list_bg = MDCard(radius=[10], md_bg_color=(0.15, 0.15, 0.15, 1))
        self.scroll_live = MDScrollView()
        self.live_list = MDList()
        self.scroll_live.add_widget(self.live_list)
        list_bg.add_widget(self.scroll_live)
        right_panel.add_widget(list_bg)
        
        controls = MDGridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(90))
        
        self.btn_capture = MDFillRoundFlatButton(
            text="CAPTURE",
            font_size="14sp",
            md_bg_color=(0, 0.55, 0.75, 1),
            size_hint=(1, 1)
        )
        self.btn_capture.bind(on_release=self._on_capture_pressed)

        self.btn_stop = MDFillRoundFlatButton(
            text="STOP",
            font_size="14sp",
            md_bg_color=(0.8, 0.2, 0.2, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_stop.bind(on_release=self._on_stop_pressed)

        self.btn_reset = MDFillRoundFlatButton(
            text="RESET",
            font_size="14sp",
            md_bg_color=(0.7, 0.45, 0.0, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_reset.bind(on_release=self._on_reset_pressed)

        controls.add_widget(self.btn_capture)
        controls.add_widget(self.btn_stop)
        controls.add_widget(self.btn_reset)
        
        right_panel.add_widget(controls)

        # --- SUBMIT & CUSTOMER SELECTION (NEW) ---
        self.btn_cust_select = MDRectangleFlatButton(
            text="Select Customer",
            font_size="14sp",
            size_hint=(1, None),
            height=dp(50),
            line_color=(0.5, 0.5, 0.5, 1),
            text_color=(0.9, 0.9, 0.9, 1),
            opacity=1, # Always visible
            disabled=True
        )
        self.btn_cust_select.bind(on_release=self.open_customer_menu)
        right_panel.add_widget(self.btn_cust_select)

        self.btn_submit = MDFillRoundFlatButton(
            text="SUBMIT",
            font_size="16sp",
            size_hint=(1, None),
            height=dp(60),
            md_bg_color=(0.15, 0.65, 0.3, 1),
            disabled=True,
            opacity=1 # Always visible
        )
        self.btn_submit.bind(on_release=self._on_main_submit_pressed)
        right_panel.add_widget(self.btn_submit)

        layout.add_widget(right_panel)
        return layout

    # --- ACTIONS & LOGIC ---

    def check_touch_selection(self, touch_x, touch_y):
        """Tap to deselect a QR code. All detected QRs are auto-selected."""
        padding = 50
        for qr in self.current_qrs:
            x1, y1, x2, y2 = qr['bbox']
            if (x1 - padding) <= touch_x <= (x2 + padding) and (y1 - padding) <= touch_y <= (y2 + padding):
                pallet_id = qr['pallet_id']
                if pallet_id in self.selected_pallet_ids:
                    self.selected_pallet_ids.discard(pallet_id)
                    self.show_toast(f"Deselected: {pallet_id[:14]}")
                else:
                    self.selected_pallet_ids.add(pallet_id)
                    self.show_toast(f"Re-selected: {pallet_id[:14]}")
                self._refresh_side_panel()
                return
        # Nothing found — helpful debug hint
        self.show_toast(f"No QR at ({touch_x},{touch_y}) — try clicking on the box")

    def _on_capture_pressed(self, instance):
        if self.app.on_start_capture:
            self.app.on_start_capture()
        self.is_capturing = True
        self.update_button_states(capturing=True)
        self.show_toast("Capture Started")

    def _on_stop_pressed(self, instance):
        if self.app.on_stop_capture:
            self.app.on_stop_capture()
        self.is_capturing = False
        self.update_button_states(capturing=False)
        self.show_toast("Capture Stopped")

    def _on_reset_pressed(self, instance):
        from utils import ACCUMULATED_TRACKER
        ACCUMULATED_TRACKER.reset()
        self.current_count = 0
        self.current_qrs = []
        self.all_detected_qrs = []
        self.selected_pallet_ids.clear()
        self.previous_detected_ids.clear() # Clear tracking state on RESET
        self.location_confirmed = False  # Re-require location confirmation after reset
        self.is_capturing = False
        self.card_qr_count.update_value("0")
        self.live_list.clear_widgets()
        self.update_button_states(capturing=False)
        self.show_toast("Reset Successful")

    def update_button_states(self, capturing=False):
        has_pallets = self.current_count > 0
        selected_count = len(self.selected_pallet_ids)
        zone = self.zone_indicator.zone_value.text.upper()

        # Capture / Stop
        self.btn_capture.disabled = capturing
        self.btn_stop.disabled = not capturing

        # Reset: enabled only when QR(s) detected
        self.btn_reset.disabled = not has_pallets

        # --- SUBMIT & CUSTOMER (NEW LOGIC) ---
        is_storage = "STORAGE" in zone
        is_dispatch = "DISPATCH" in zone
        is_stopped = not capturing

        # Visibility
        if is_dispatch:
            self.btn_cust_select.text_color = (0.9, 0.9, 0.9, 1)
        else:
            self.btn_cust_select.text_color = (0.3, 0.3, 0.3, 1) # Dimmed if not in dispatch

        # Enabled States
        if is_storage:
            self.btn_cust_select.disabled = True
            # Storage: Storage Area + Stopped + Has Pallets
            self.btn_submit.disabled = not (is_stopped and has_pallets)
        elif is_dispatch:
            self.btn_cust_select.disabled = False
            # Dispatch: Dispatch Area + Stopped + Has Pallets + Customer Selected
            customer_selected = self.btn_cust_select.text != "Select Customer"
            self.btn_submit.disabled = not (is_stopped and has_pallets and customer_selected)
        else:
            self.btn_cust_select.disabled = True
            self.btn_submit.disabled = True

    def _on_main_submit_pressed(self, instance):
        zone = self.zone_indicator.zone_value.text.upper()
        if "STORAGE" in zone:
            self._on_storage_popup_confirmed()
        elif "DISPATCH" in zone:
            self._on_dispatch_popup_confirmed()

    def _on_zone_indicator_pressed(self):
        zone = self.zone_indicator.zone_value.text.upper()
        if "STORAGE" in zone:
            self.show_storage_popup()
        elif "DISPATCH" in zone:
            self.show_dispatch_popup()
        else:
            self.show_toast("Must be in Storage or Dispatch area to store/dispatch.")

    def update_camera_feed(self, frame):
        # Always record the real frame dimensions for touch coordinate mapping
        if frame is not None and frame.ndim >= 2:
            self.frame_h, self.frame_w = frame.shape[:2]

        self.cam_prev.update_frame(frame)

    def update_info(self, current_count, current_qrs, accumulated_count=None, accumulated_qrs=None):
        """Called by the detection thread. Stores detected QRs and refreshes the side panel."""
        if accumulated_count is not None:
            total_count = accumulated_count
            all_detected = accumulated_qrs or []
        else:
            total_count = current_count
            all_detected = current_qrs or []

        self.current_count = total_count
        self.all_detected_qrs = all_detected
        self.current_qrs = all_detected

        # Logic for auto-selecting NEW QR codes while respecting manual manual deselection
        detected_ids = {q.get('pallet_id') for q in all_detected if q.get('pallet_id')}
        
        # 1. NEWLY DETECTED: Automatic select
        newly_seen = detected_ids - self.previous_detected_ids
        self.selected_pallet_ids.update(newly_seen)
        
        # 2. DISAPPEARED: Automatic remove
        disappeared = self.previous_detected_ids - detected_ids
        self.selected_pallet_ids.difference_update(disappeared)
        
        # 3. Update previous tracking
        self.previous_detected_ids = detected_ids

        self._refresh_side_panel()
        self.update_button_states(capturing=self.is_capturing)

    def _refresh_side_panel(self):
        """Rebuild the side panel lists to show only operator-selected pallets."""
        from utils import sort_pallet_data

        sel_count = len(self.selected_pallet_ids)
        self.card_qr_count.update_value(f"{sel_count} Selected")
        
        # Ensure buttons react to selection changes (e.g. enabling SUBMIT)
        self.update_button_states(capturing=self.is_capturing)

        # Filter to only selected QRs
        selected_qrs = [q for q in self.all_detected_qrs
                        if q.get('pallet_id') in self.selected_pallet_ids]
        sorted_data = sort_pallet_data(selected_qrs)

        self.live_list.clear_widgets()

        for qr in sorted_data:
            pid = qr.get('pallet_id', 'UNKNOWN')

            def _make_row(pallet_id):
                row = MDBoxLayout(
                    orientation='horizontal',
                    size_hint_y=None,
                    height=dp(44),
                    padding=(dp(12), dp(4)),
                    spacing=dp(4),
                )
                lbl = MDLabel(
                    text=pallet_id,
                    theme_text_color="Custom",
                    text_color=(0.2, 1.0, 0.4, 1),
                    font_style="Body2",
                    valign='center',
                )
                remove_btn = MDIconButton(
                    icon="close-circle-outline",
                    theme_text_color="Custom",
                    text_color=(0.9, 0.3, 0.3, 1),
                    size_hint=(None, None),
                    size=(dp(36), dp(36)),
                    pos_hint={'center_y': 0.5},
                )
                remove_btn.bind(on_release=lambda x, p=pallet_id: self._deselect_from_list(p))
                row.add_widget(lbl)
                row.add_widget(remove_btn)
                return row

            self.live_list.add_widget(_make_row(pid))

    def _deselect_from_list(self, pallet_id):
        """Remove a pallet from selection by tapping its list item."""
        self.selected_pallet_ids.discard(pallet_id)
        self.show_toast(f"Deselected: {pallet_id[:12]}...")
        self._refresh_side_panel()

    def update_zone_status(self, zone):
        # Only reset if the zone ACTUALLY changed to a different area
        current_zone_text = self.zone_indicator.zone_value.text.upper()
        new_zone_upper = zone.upper()
        
        zone_changed = False
        if "STORAGE" in new_zone_upper and "STORAGE" not in current_zone_text:
            zone_changed = True
        elif "DISPATCH" in new_zone_upper and "DISPATCH" not in current_zone_text:
            zone_changed = True
            # Reset customer selection when entering Dispatch
            self.btn_cust_select.text = "Select Customer"
        elif ("TRANSIT" in new_zone_upper or "NEUTRAL" in new_zone_upper) and ("STORAGE" in current_zone_text or "DISPATCH" in current_zone_text):
            zone_changed = True
            
        self.zone_indicator.set_zone(zone)
        
        if zone_changed:
            logging.getLogger("ForkliftFront").info(f"Zone changed to {zone} - Updating UI")
            self.location_confirmed = False
        
        # Always refresh button states on zone update
        self.update_button_states(capturing=self.is_capturing)

    def update_connection_status(self, status):
        if status == "connected":
            self.status_label.text = "CONNECTED"
            self.status_label.theme_text_color = "Custom"
            self.status_label.text_color = (0, 0.8, 0.4, 1)
            self.status_icon.icon = "wifi"
            self.status_icon.theme_text_color = "Custom"
            self.status_icon.text_color = (0, 0.8, 0.4, 1)
        elif status == "connecting":
            self.status_label.text = "CONNECTING..."
            self.status_label.theme_text_color = "Custom"
            self.status_label.text_color = (1, 0.8, 0, 1)
            self.status_icon.icon = "wifi-arrow-up-down"
            self.status_icon.theme_text_color = "Custom"
            self.status_icon.text_color = (1, 0.8, 0, 1)
        else:
            self.status_label.text = "DISCONNECTED"
            self.status_label.theme_text_color = "Error"
            self.status_icon.icon = "wifi-off"
            self.status_icon.theme_text_color = "Error"

    def set_camera_error(self, message):
         self.cam_prev.show_error(message)

    def clear_camera_error(self):
         self.cam_prev.hide_error()

    # --- CUSTOMER SELECTION ---
    def update_customer_list(self, customers):
        self.customer_data = {}
        for c in customers:
            if isinstance(c, dict):
                name = c.get('name', '')
                cust_id = c.get('_id', '')
                if name:
                    self.customer_data[name] = cust_id
        
        self._rebuild_customer_menu()

    def _rebuild_customer_menu(self):
        menu_items = []
        for name in self.customer_data.keys():
            menu_items.append({
                "viewclass": "OneLineListItem",
                "text": name,
                "on_release": lambda x=name: self.select_customer(x),
            })
        
        if hasattr(self, 'btn_cust_select'):
            self.customer_menu = MDDropdownMenu(
                caller=self.btn_cust_select,
                items=menu_items,
                width_mult=4,
                max_height=dp(300),
            )

    def open_customer_menu(self, instance):
        if hasattr(self, 'customer_menu'):
            self.customer_menu.open()
            
    def select_customer(self, name):
        self.btn_cust_select.text = name
        self.customer_menu.dismiss()
        self.update_button_states(capturing=self.is_capturing)
        
    def _on_refresh_customers(self, instance):
        threading.Thread(target=self.app._fetch_and_update_customers, daemon=True).start()
        self.show_toast("Refreshed Customers")

    # --- DIALOGS (SINGLE AND MULTIPLE) ---

    def show_toast(self, text):
        from kivymd.toast import toast
        toast(text)

    def dismiss_dialog(self, *args):
        """Safely dismiss the current dialog."""
        if self.dialog:
            try:
                self.dialog.dismiss()
            except Exception:
                pass
            self.dialog = None

    def safe_open_dialog(self, dialog):
        """Dismiss any existing dialog before opening a new one."""
        self.dismiss_dialog()
        self.dialog = dialog
        self.dialog.open()

    def show_success_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[
                MDRaisedButton(
                    text="OK",
                    md_bg_color=(0.15, 0.65, 0.3, 1),
                    on_release=lambda x: self.dismiss_dialog()
                )
            ]
        )
        self.safe_open_dialog(dialog)

    def show_exit_dialog(self, instance):
        dialog = MDDialog(
            title="Exit Application?",
            text="Are you sure you want to shut down the system?",
            buttons=[
                MDRaisedButton(text="CANCEL", on_release=self.dismiss_dialog),
                MDRaisedButton(text="EXIT", md_bg_color=(1, 0, 0, 1), on_release=lambda x: self.app.stop()),
            ],
        )
        self.safe_open_dialog(dialog)

    # --- LOCATION ARRIVAL POPUPS (called by WebSocket location_update) ---

    def show_storage_popup(self, count=0, show_details=True):
        """Show arrival acknowledgement dialog for Storage Area."""
        dialog = MDDialog(
            title="Arrived: Storage Area",
            text=f"Forklift is now in the Storage Area. Confirm to proceed.",
            buttons=[
                MDRaisedButton(
                    text="OK",
                    md_bg_color=(0.15, 0.65, 0.3, 1),
                    on_release=lambda x: self.dismiss_dialog()
                )
            ],
        )
        self.safe_open_dialog(dialog)
        self.update_button_states(capturing=self.is_capturing)

    def show_dispatch_popup(self):
        """Show arrival acknowledgement dialog for Dispatch Area."""
        dialog = MDDialog(
            title="Arrived: Dispatch Area",
            text="Forklift is now in the Dispatch Area. Confirm to proceed.",
            buttons=[
                MDRaisedButton(
                    text="OK",
                    md_bg_color=(0.15, 0.65, 0.3, 1),
                    on_release=lambda x: self.dismiss_dialog()
                )
            ],
        )
        self.safe_open_dialog(dialog)
        self._fetch_customers_async()
        self.update_button_states(capturing=self.is_capturing)

    def _fetch_customers_async(self):
        threading.Thread(target=self.app._fetch_and_update_customers, daemon=True).start()

    def _on_storage_popup_confirmed(self):
        """Logic for Storage submission."""
        if not self.selected_pallet_ids:
            self.show_toast("Select at least one pallet first")
            return
        
        from utils import sort_pallet_data
        sorted_qrs = sort_pallet_data(
            [q for q in self.all_detected_qrs if q.get('pallet_id') in self.selected_pallet_ids]
        )
        self._do_store(sorted_qrs)

    def _do_store(self, sorted_qrs):
        self.dismiss_dialog()
        
        self.location_confirmed = False 

        def store_thread():
            pallet_ids = [q.get('pallet_id') for q in sorted_qrs if q.get('pallet_id')]
            from utils import send_camera_update_palette, ACCUMULATED_TRACKER, RECENT_CACHE
            success = True
            
            for pid in pallet_ids:
                res = send_camera_update_palette(pallet_id=pid, area_name="Storage Area", customer_id="")
                if "error" in res:
                    success = False
                else:
                    # Cache successful ones so they don't pop back up immediately
                    RECENT_CACHE.add(pid)

            def on_finished(dt):
                if success:
                    self.show_success_dialog("Storage Success", "Pallets successfully updated to Storage Area!")
                    self.selected_pallet_ids.clear()
                    ACCUMULATED_TRACKER.reset()
                    self.update_info(0, [], 0, [])
                else:
                    self.show_toast("Storage Failed - Check Connection")
                    # Re-enable if failed so they can try again
                    self.location_confirmed = True
                    self.update_button_states(capturing=self.is_capturing)

            Clock.schedule_once(on_finished)

        threading.Thread(target=store_thread, daemon=True).start()

    # MULTIPLE DISPATCH
    def _on_dispatch_popup_confirmed(self):
        if not self.selected_pallet_ids:
            self.show_toast("Select at least one pallet first")
            return
        
        if not hasattr(self, 'btn_cust_select'):
            self.show_toast("Customer selection missing")
            return
            
        cust_name = self.btn_cust_select.text
        if cust_name == "Select Customer":
            self.show_toast("Please select a customer first")
            return
            
        from utils import sort_pallet_data
        sorted_qrs = sort_pallet_data(
            [q for q in self.all_detected_qrs if q.get('pallet_id') in self.selected_pallet_ids]
        )
        
        self._do_dispatch(sorted_qrs, cust_name)

    def _do_dispatch(self, sorted_qrs, cust_name):
        self.dismiss_dialog()
        self.location_confirmed = False

        def dispatch_thread():
            cust_id = self.customer_data.get(cust_name, "")
            pallet_ids = [q.get('pallet_id') for q in sorted_qrs if q.get('pallet_id')]
            from utils import send_camera_update_palette, ACCUMULATED_TRACKER, RECENT_CACHE
            success = True
            
            for pid in pallet_ids:
                res = send_camera_update_palette(pallet_id=pid, area_name="Dispatch Area", customer_id=cust_id)
                if "error" in res:
                    success = False
                else:
                    # Cache successful ones
                    RECENT_CACHE.add(pid)

            def on_finished(dt):
                if success:
                    self.show_success_dialog("Dispatch Success", f"Pallets successfully dispatched to {cust_name}!")
                    self.selected_pallet_ids.clear()
                    ACCUMULATED_TRACKER.reset()
                    self.update_info(0, [], 0, [])
                else:
                    self.show_toast("Dispatch Failed")
                    # Re-enable if failed
                    self.location_confirmed = True
                    self.update_button_states(capturing=self.is_capturing)

            Clock.schedule_once(on_finished)

        threading.Thread(target=dispatch_thread, daemon=True).start()

# --- APP CLASS ---

class ForkliftHMIApp(MDApp):
    def __init__(self, on_confirm, on_start_capture, on_stop_capture, startup_callback=None, mac_id="UNKNOWN", **kwargs):
        super().__init__(**kwargs)
        self.on_confirm = on_confirm
        self.on_start_capture = on_start_capture
        self.on_stop_capture = on_stop_capture
        self.startup_callback = startup_callback
        self.mac_id = mac_id
        
        self.sm = None
        self.splash_screen = None
        self.main_screen = None
        self.root_widget = None

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Cyan"
        self.theme_cls.accent_palette = "Orange"
        
        self.sm = MDScreenManager(transition=FadeTransition())
        
        self.splash_screen = SplashScreen(name="splash")
        self.sm.add_widget(self.splash_screen)
        
        self.main_screen = MainScreen(self, name="main")
        self.root_widget = self.main_screen 
        self.sm.add_widget(self.main_screen)
        
        return self.sm

    def on_start(self):
        if self.startup_callback:
            threading.Thread(target=self.startup_callback, daemon=True).start()

    def update_splash_status(self, text):
        if self.splash_screen:
            Clock.schedule_once(lambda dt: self.splash_screen.update_status(text))

    def switch_to_main(self):
        def _switch(dt):
            if self.sm.current != "main":
                self.sm.current = "main"
        Clock.schedule_once(_switch)

    def _fetch_and_update_customers(self):
        from utils import fetch_customer_details
        try:
            customers = fetch_customer_details()
            Clock.schedule_once(lambda dt: self.root_widget.update_customer_list(customers))
        except Exception:
            pass