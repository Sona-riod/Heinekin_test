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
from kivymd.uix.tab import MDTabsBase
from kivymd.uix.tab import MDTabs
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


class Tab(MDFloatLayout, MDTabsBase):
    '''Class implementing content for a tab.'''
    pass

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
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

        # --- CONTENT AREA (Tabs) ---
        self.tabs = MDTabs(
            background_color=(0.15, 0.15, 0.15, 1),
            text_color_normal=(0.6, 0.6, 0.6, 1),
            text_color_active=(0, 0.8, 0.9, 1), 
            indicator_color=(0, 0.8, 0.9, 1)
        )
        self.tabs.bind(on_tab_switch=self.on_tab_switch)
        
        self.tab_storage = Tab(title="STORAGE")
        self.tab_storage.add_widget(self._build_storage_layout())
        self.tabs.add_widget(self.tab_storage)
        
        self.tab_dispatch = Tab(title="DISPATCH")
        self.tab_dispatch.add_widget(self._build_dispatch_layout())
        self.tabs.add_widget(self.tab_dispatch)
        
        self.root_box.add_widget(self.tabs)
        
        self.zone_indicator = ZoneIndicator(size_hint_y=None, height=dp(70))
        self.root_box.add_widget(self.zone_indicator)

    def on_tab_switch(self, instance_tabs, instance_tab, instance_tab_label, tab_text):
        """
        Called when the user switches tabs. 
        Current implementation does not require specific actions here as tab-specific 
        logic (e.g., camera feed switching) is handled in the main update loop.
        """
        pass 

    def _build_storage_layout(self):
        layout = MDBoxLayout(orientation='horizontal', padding=dp(15), spacing=dp(15))
        
        # Give Camera Preview more space so it aligns better (75% width)
        self.cam_prev_store = CameraPreview(main_screen=self, size_hint_x=0.75)
        layout.add_widget(self.cam_prev_store)
        
        # Side panel gets the remaining 25% width
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
        
        # Reduced button grid height from 120dp to 90dp
        controls = MDGridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(90))
        
        # Standardized button font sizes to 14sp
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

        self.btn_manual_store = MDFillRoundFlatButton(
            text="SUBMIT",
            font_size="14sp",
            md_bg_color=(0.15, 0.65, 0.3, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_manual_store.bind(on_release=lambda x: self.show_storage_dialog())

        controls.add_widget(self.btn_capture)
        controls.add_widget(self.btn_stop)
        controls.add_widget(self.btn_reset)
        controls.add_widget(self.btn_manual_store)
        
        right_panel.add_widget(controls)
        layout.add_widget(right_panel)
        return layout

    def _build_dispatch_layout(self):
        layout = MDBoxLayout(orientation='horizontal', padding=dp(15), spacing=dp(15))
        
        # Give Camera Preview more space
        self.cam_prev_disp = CameraPreview(main_screen=self, size_hint_x=0.75)
        layout.add_widget(self.cam_prev_disp)
        
        right_panel = MDBoxLayout(orientation='vertical', size_hint_x=0.25, spacing=dp(10))
        
        self.card_disp_count = StatusCard(title="Ready for Dispatch", icon="truck-check")
        right_panel.add_widget(self.card_disp_count)
        
        # Main container for the customer section
        cust_box = MDBoxLayout(orientation='vertical', size_hint_y=None, height=dp(65), spacing=dp(2))
        
        # 1. Top Line: Just the "CUSTOMER" label
        header_line = MDBoxLayout(size_hint_y=None, height=dp(20))
        header_line.add_widget(MDLabel(text="CUSTOMER", theme_text_color="Secondary", font_style="Caption"))
        cust_box.add_widget(header_line)
        
        # 2. Bottom Line: Dropdown button AND Refresh icon side-by-side
        select_line = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40), spacing=dp(5))
        
        self.btn_cust_select = MDRectangleFlatButton(
            text="Select Customer",
            font_size="14sp",
            size_hint_x=1,  # Tells Kivy to let the button stretch to fill available space
            line_color=(0.5, 0.5, 0.5, 1),
            text_color=(0.9, 0.9, 0.9, 1)
        )
        self.btn_cust_select.bind(on_release=self.open_customer_menu)
        select_line.add_widget(self.btn_cust_select)
        
        self.btn_refresh_cust = MDIconButton(
            icon="refresh", 
            theme_text_color="Custom", 
            text_color=(1, 0.6, 0, 1),
            pos_hint={'center_y': 0.5}  # Centers the icon perfectly with the dropdown button
        )
        self.btn_refresh_cust.font_size = "20sp"
        self.btn_refresh_cust.bind(on_release=self._on_refresh_customers)
        select_line.add_widget(self.btn_refresh_cust)
        
        cust_box.add_widget(select_line)
        right_panel.add_widget(cust_box)
        
        list_bg = MDCard(radius=[10], md_bg_color=(0.15, 0.15, 0.15, 1))
        self.scroll_live_disp = MDScrollView()
        self.live_list_disp = MDList()
        self.scroll_live_disp.add_widget(self.live_list_disp)
        list_bg.add_widget(self.scroll_live_disp)
        right_panel.add_widget(list_bg)

        # Reduced button grid height from 120dp to 90dp
        controls = MDGridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(90))
        
        # Standardized button font sizes to 14sp
        self.btn_capture_disp = MDFillRoundFlatButton(
            text="CAPTURE",
            font_size="14sp",
            md_bg_color=(0, 0.55, 0.75, 1),
            size_hint=(1, 1)
        )
        self.btn_capture_disp.bind(on_release=self._on_capture_pressed)

        self.btn_stop_disp = MDFillRoundFlatButton(
            text="STOP",
            font_size="14sp",
            md_bg_color=(0.8, 0.2, 0.2, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_stop_disp.bind(on_release=self._on_stop_pressed)

        self.btn_reset_disp = MDFillRoundFlatButton(
            text="RESET",
            font_size="14sp",
            md_bg_color=(0.7, 0.45, 0.0, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_reset_disp.bind(on_release=self._on_reset_pressed)

        self.btn_dispatch = MDFillRoundFlatButton(
            text="SUBMIT",
            font_size="14sp",
            md_bg_color=(0.15, 0.65, 0.3, 1),
            size_hint=(1, 1),
            disabled=True
        )
        self.btn_dispatch.bind(on_release=self.confirm_dispatch)

        controls.add_widget(self.btn_capture_disp)
        controls.add_widget(self.btn_stop_disp)
        controls.add_widget(self.btn_reset_disp)
        controls.add_widget(self.btn_dispatch)
        
        right_panel.add_widget(controls)
        layout.add_widget(right_panel)
        return layout

    # --- ACTIONS & LOGIC ---

    def check_touch_selection(self, touch_x, touch_y):
        """Toggle selection of a tapped QR code. Does NOT send to cloud."""
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
                    self.show_toast(f"Selected: {pallet_id[:14]}")
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
        self.location_confirmed = False  # Re-require location confirmation after reset
        self.is_capturing = False
        self.card_qr_count.update_value("0")
        self.card_disp_count.update_value("0")
        self.live_list.clear_widgets()
        self.live_list_disp.clear_widgets()
        self.update_button_states(capturing=False)
        self.show_toast("Reset Successful")

    def update_button_states(self, capturing=False):
        has_pallets = self.current_count > 0
        selected_count = len(self.selected_pallet_ids)

        # Capture / Stop
        self.btn_capture.disabled = capturing
        self.btn_stop.disabled = not capturing
        self.btn_capture_disp.disabled = capturing
        self.btn_stop_disp.disabled = not capturing

        # Reset: enabled only when QR(s) detected
        self.btn_reset.disabled = not has_pallets
        self.btn_reset_disp.disabled = not has_pallets

        # Submit: ONLY enabled after operator confirms the location popup AND capture is stopped AND pallets are selected
        can_submit = self.location_confirmed and not capturing and selected_count > 0
        
        self.btn_manual_store.disabled = not can_submit
        self.btn_dispatch.disabled = not can_submit

    def update_camera_feed(self, frame):
        # Always record the real frame dimensions for touch coordinate mapping
        if frame is not None and frame.ndim >= 2:
            self.frame_h, self.frame_w = frame.shape[:2]

        tab = self.tabs.get_current_tab()
        current_tab_title = getattr(tab, 'title', None) or getattr(tab, 'text', '')
        if current_tab_title == "STORAGE":
            self.cam_prev_store.update_frame(frame)
        else:
            self.cam_prev_disp.update_frame(frame)

    def update_info(self, current_count, current_qrs, accumulated_count=None, accumulated_qrs=None):
        """Called by the detection thread. Stores detected QRs and refreshes the side panel."""
        if accumulated_count is not None:
            self.current_count = accumulated_count
            self.all_detected_qrs = accumulated_qrs or []
        else:
            self.current_count = current_count
            self.all_detected_qrs = current_qrs or []

        # Keep current_qrs in sync (used by touch handler for bbox lookup)
        self.current_qrs = self.all_detected_qrs

        # Remove selected IDs that are no longer detected
        detected_ids = {q.get('pallet_id') for q in self.all_detected_qrs}
        self.selected_pallet_ids.intersection_update(detected_ids)

        self._refresh_side_panel()

        # Always refresh button states so RESET reacts to QR count changes
        self.update_button_states(capturing=self.is_capturing)

    def _refresh_side_panel(self):
        """Rebuild the side panel lists to show only operator-selected pallets."""
        from utils import sort_pallet_data

        sel_count = len(self.selected_pallet_ids)
        self.card_qr_count.update_value(f"{sel_count} Selected")
        self.card_disp_count.update_value(f"{sel_count} Selected")
        
        # Ensure buttons react to selection changes (e.g. enabling SUBMIT)
        self.update_button_states(capturing=self.is_capturing)

        # Filter to only selected QRs
        selected_qrs = [q for q in self.all_detected_qrs
                        if q.get('pallet_id') in self.selected_pallet_ids]
        sorted_data = sort_pallet_data(selected_qrs)

        self.live_list.clear_widgets()
        self.live_list_disp.clear_widgets()

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
            self.live_list_disp.add_widget(_make_row(pid))

    def _deselect_from_list(self, pallet_id):
        """Remove a pallet from selection by tapping its list item."""
        self.selected_pallet_ids.discard(pallet_id)
        self.show_toast(f"Deselected: {pallet_id[:12]}...")
        self._refresh_side_panel()

    def update_zone_status(self, zone):
        # Only reset confirmation if the zone ACTUALLY changed to a different area
        current_zone_text = self.zone_indicator.zone_value.text.upper()
        new_zone_upper = zone.upper()
        
        # Simple logical check: if we are in STORAGE AREA and receive "Storage Area", don't reset.
        zone_changed = False
        if "STORAGE" in new_zone_upper and "STORAGE" not in current_zone_text:
            zone_changed = True
        elif "DISPATCH" in new_zone_upper and "DISPATCH" not in current_zone_text:
            zone_changed = True
        elif "TRANSIT" in new_zone_upper and "TRANSIT" not in current_zone_text:
            zone_changed = True
            
        self.zone_indicator.set_zone(zone)
        
        if zone_changed:
            logging.getLogger("ForkliftFront").info(f"Zone changed to {zone} - Resetting location confirmation")
            self.location_confirmed = False
            self.update_button_states(capturing=self.is_capturing)
        
        zone_lower = zone.lower()
        try:
            if "storage" in zone_lower:
                self.tabs.switch_tab("STORAGE", search_by="title")
            elif "dispatch" in zone_lower:
                self.tabs.switch_tab("DISPATCH", search_by="title")
        except Exception as e:
            logging.getLogger("ForkliftFront").warning(f"Tab switch failed (non-fatal): {e}")

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
         self.cam_prev_store.show_error(message)
         self.cam_prev_disp.show_error(message)

    def clear_camera_error(self):
         self.cam_prev_store.hide_error()
         self.cam_prev_disp.hide_error()

    # --- CUSTOMER SELECTION ---
    def update_customer_list(self, customers):
        self.customer_data = {}
        menu_items = []
        for c in customers:
            if isinstance(c, dict):
                name = c.get('name', '')
                cust_id = c.get('_id', '')
                if name:
                    self.customer_data[name] = cust_id
                    menu_items.append({
                        "viewclass": "OneLineListItem",
                        "text": name,
                        "on_release": lambda x=name: self.select_customer(x),
                    })
        
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
        """Show arrival confirmation when forklift enters Storage Area.
        Operator must press CONFIRM here to unlock the SUBMIT button."""
        self.location_confirmed = False
        self.update_button_states(capturing=self.is_capturing)
        count_line = f"{count} pallet(s) currently detected.\n\n" if show_details else ""
        dialog = MDDialog(
            title="Arrived: Storage Area",
            text=f"{count_line}Confirm location to enable the SUBMIT button.",
            buttons=[
                MDRaisedButton(text="CANCEL", on_release=self.dismiss_dialog),
                MDRaisedButton(
                    text="CONFIRM",
                    md_bg_color=(0.15, 0.65, 0.3, 1),
                    on_release=lambda x: self._on_location_confirmed()
                ),
            ],
        )
        self.safe_open_dialog(dialog)

    def show_dispatch_popup(self):
        """Show arrival confirmation when forklift enters Dispatch Area.
        Operator must press CONFIRM here to unlock the SUBMIT button."""
        self.location_confirmed = False
        self.update_button_states(capturing=self.is_capturing)
        self._fetch_customers_async()
        dialog = MDDialog(
            title="Arrived: Dispatch Area",
            text="Forklift is at Dispatch Area.\nConfirm location to enable the SUBMIT button.",
            buttons=[
                MDRaisedButton(text="CANCEL", on_release=self.dismiss_dialog),
                MDRaisedButton(
                    text="CONFIRM",
                    md_bg_color=(0.15, 0.65, 0.3, 1),
                    on_release=lambda x: self._on_location_confirmed()
                ),
            ],
        )
        self.safe_open_dialog(dialog)

    def _on_location_confirmed(self):
        """Called when operator confirms the arrival popup — unlocks SUBMIT."""
        self.dismiss_dialog()
        self.location_confirmed = True
        self.update_button_states(capturing=self.is_capturing)
        self.show_toast("Location confirmed — SUBMIT enabled")

    def _fetch_customers_async(self):
        threading.Thread(target=self.app._fetch_and_update_customers, daemon=True).start()

    # MULTIPLE STORE
    def show_storage_dialog(self):
        if not self.selected_pallet_ids:
            self.show_toast("Select at least one pallet first")
            return
        from utils import sort_pallet_data
        sorted_qrs = sort_pallet_data(
            [q for q in self.all_detected_qrs if q.get('pallet_id') in self.selected_pallet_ids]
        )
        count = len(sorted_qrs)
        content_text = f"{count} Selected Pallet(s):\n" + "\n".join(
            q.get('pallet_id','?') for q in sorted_qrs
        ) + "\n\nConfirm storage entry?"
        dialog = MDDialog(
            title="Confirm Storage",
            text=content_text,
            buttons=[
                MDRaisedButton(text="CANCEL", on_release=self.dismiss_dialog),
                MDRaisedButton(text="CONFIRM", md_bg_color=(0, 0.7, 0.3, 1), on_release=lambda x: self._do_store(sorted_qrs)),
            ],
        )
        self.safe_open_dialog(dialog)

    def _do_store(self, sorted_qrs):
        self.dismiss_dialog()
        
        # Disable buttons immediately to prevent double-submit
        self.btn_manual_store.disabled = True
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
                    self.show_toast("Stored Successfully")
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
    def confirm_dispatch(self, instance):
        if not self.selected_pallet_ids:
            self.show_toast("Select at least one pallet first")
            return
        cust_name = self.btn_cust_select.text
        if cust_name == "Select Customer":
            self.show_toast("Please select a customer first")
            return
        from utils import sort_pallet_data
        sorted_qrs = sort_pallet_data(
            [q for q in self.all_detected_qrs if q.get('pallet_id') in self.selected_pallet_ids]
        )
        count = len(sorted_qrs)
        content_text = f"{count} Selected Pallet(s) → {cust_name}:\n" + "\n".join(
            q.get('pallet_id','?') for q in sorted_qrs
        )
        dialog = MDDialog(
            title="Confirm Dispatch",
            text=content_text,
            buttons=[
                MDRaisedButton(text="CANCEL", on_release=self.dismiss_dialog),
                MDRaisedButton(text="DISPATCH", md_bg_color=(0, 0.7, 0.3, 1), on_release=lambda x: self._do_dispatch(sorted_qrs, cust_name)),
            ],
        )
        self.safe_open_dialog(dialog)

    def _do_dispatch(self, sorted_qrs, cust_name):
        self.dismiss_dialog()
        
        # Disable buttons immediately
        self.btn_dispatch.disabled = True
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
                    self.show_toast(f"Dispatched to {cust_name}")
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