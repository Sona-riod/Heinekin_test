# hmi.py  –  Professional Top-Camera HMI  (Enhanced UI Edition)
# =============================================================================
# Layout  : Left = camera feed (65%)   |   Right = control panel (35%)
#
# UI Design Philosophy
# ────────────────────
# • Deep space dark theme with electric cyan (#00E5FF) + amber (#FFB300) accents
# • Glassmorphism-style cards with subtle borders and glow effects
# • Colour-coded status system: Cyan=active, Amber=attention, Green=success, Red=danger
# • Bold industrial typography with monospaced keg IDs for readability
# • Animated pulse indicators for live detection status
# • Gradient-enhanced primary action buttons
# • Rounded corners throughout for a modern, approachable aesthetic
#
# Submit gate: ALL THREE must be satisfied before SUBMIT is enabled:
#   1. At least one keg scanned
#   2. A customer is selected
#   3. The location pop-up has been confirmed
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
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from kivymd.app import MDApp
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
_WAITING_TEXT     = 'No kegs detected yet…'
_SUBMIT_TEXT      = '  SUBMIT TO CLOUD  '
_SENDING_TEXT     = '  SENDING…  '

CUSTOMER_REFRESH_INTERVAL = 60

# =============================================================================
# Enhanced Color Palette
# Deep space industrial theme
# =============================================================================
C = {
    # Backgrounds — layered depth
    'bg_void':       (0.04, 0.05, 0.07, 1),    # #0A0D12 – deepest background
    'bg_deep':       (0.07, 0.09, 0.12, 1),    # #121720 – panel backgrounds
    'bg_surface':    (0.10, 0.13, 0.18, 1),    # #1A212E – card surfaces
    'bg_elevated':   (0.13, 0.17, 0.23, 1),    # #222B3B – elevated cards
    'bg_input':      (0.08, 0.10, 0.14, 1),    # #141924 – input fields

    # Primary accents
    'cyan':          (0.00, 0.90, 1.00, 1),    # #00E5FF – electric cyan (primary)
    'cyan_dim':      (0.00, 0.60, 0.72, 1),    # #0099B8 – dimmed cyan
    'cyan_glow':     (0.00, 0.90, 1.00, 0.15), # cyan tint for backgrounds

    'amber':         (1.00, 0.70, 0.00, 1),    # #FFB300 – warm amber (attention)
    'amber_dim':     (0.80, 0.54, 0.00, 1),    # #CC8A00
    'amber_glow':    (1.00, 0.70, 0.00, 0.12), # amber tint

    # Status colours
    'success':       (0.06, 0.85, 0.49, 1),    # #10D97D – vivid green
    'success_dim':   (0.04, 0.55, 0.32, 1),
    'success_glow':  (0.06, 0.85, 0.49, 0.12),

    'danger':        (1.00, 0.27, 0.23, 1),    # #FF453A – clear red
    'danger_dim':    (0.72, 0.18, 0.15, 1),
    'danger_glow':   (1.00, 0.27, 0.23, 0.12),

    'warning':       (1.00, 0.62, 0.04, 1),    # #FF9E0A – orange-amber
    'warning_glow':  (1.00, 0.62, 0.04, 0.12),

    # Product colours
    'cola':          (1.00, 0.25, 0.10, 1),    # #FF4019 – bold red-orange (cola)
    'water':         (0.20, 0.65, 1.00, 1),    # #33A6FF – clear sky blue (water)

    # Text hierarchy
    'text_bright':   (0.96, 0.98, 1.00, 1),    # near-white
    'text_primary':  (0.82, 0.87, 0.95, 1),    # primary text
    'text_secondary':(0.52, 0.60, 0.72, 1),    # secondary
    'text_muted':    (0.32, 0.38, 0.48, 1),    # hints/labels

    # Border/divider
    'border':        (0.18, 0.23, 0.32, 1),    # subtle border
    'border_bright': (0.25, 0.32, 0.45, 1),    # hover/active border
    'border_cyan':   (0.00, 0.55, 0.65, 0.5),  # cyan-tinted border
}

def _c(key, fallback=(1, 1, 1, 1)):
    """Resolve from enhanced palette first, then legacy COLOR_SCHEME."""
    if key in C:
        return C[key]
    return COLOR_SCHEME.get(key, fallback)


# =============================================================================
# GlowCard — MDCard with optional coloured border glow
# =============================================================================
class GlowCard(MDCard):
    """Card with a coloured left-border accent stripe."""
    def __init__(self, accent_color=None, **kwargs):
        self._accent = accent_color   # must be set BEFORE super().__init__
        self._accent_rect  = None     # RoundedRectangle instruction (created once)
        kwargs.setdefault('elevation', 0)
        kwargs.setdefault('radius', [dp(10)])
        super().__init__(**kwargs)

        # Create canvas instructions ONCE after the widget is fully initialised.
        # Never clear and recreate – updating .pos/.size in-place is the safe pattern.
        if self._accent:
            with self.canvas.before:
                Color(*self._accent)
                self._accent_rect = RoundedRectangle(
                    pos=(self.x, self.y),
                    size=(dp(3), self.height),
                    radius=[dp(2)],
                )

    def on_size(self, *a):
        self._redraw()

    def on_pos(self, *a):
        self._redraw()

    def _redraw(self):
        if self._accent_rect is None:
            return
        # Update geometry in-place – never clear() during a render cycle
        self._accent_rect.pos  = (self.x, self.y)
        self._accent_rect.size = (dp(3), self.height)


# =============================================================================
# SectionLabel — standardised section header label
# =============================================================================
def _section_label(text: str) -> MDLabel:
    return MDLabel(
        text=f'  {text}',
        font_style='Overline',
        theme_text_color='Custom',
        text_color=C['text_muted'],
        size_hint_y=None,
        height=dp(20),
        bold=True,
    )


# =============================================================================
# StatCard — metric display card
# =============================================================================
class StatCard(MDCard):
    def __init__(self, label: str, value: str = '0',
                 value_color=None, icon: str = None, **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('padding', [dp(10), dp(8)])
        kwargs.setdefault('spacing', dp(1))
        kwargs.setdefault('radius', [dp(10)])
        kwargs.setdefault('elevation', 0)
        kwargs.setdefault('md_bg_color', C['bg_surface'])
        super().__init__(**kwargs)

        self._val_color = value_color or C['text_bright']

        # Icon row
        if icon:
            icon_lbl = MDLabel(
                text=icon,
                font_style='Body2',
                theme_text_color='Custom',
                text_color=value_color or C['cyan'],
                halign='center',
                size_hint_y=None,
                height=dp(18),
            )
            self.add_widget(icon_lbl)

        self._val = MDLabel(
            text=str(value),
            font_style='H5',
            theme_text_color='Custom',
            text_color=self._val_color,
            halign='center',
            bold=True,
            size_hint_y=None,
            height=dp(36),
        )
        self._lbl = MDLabel(
            text=label,
            font_style='Overline',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            halign='center',
            size_hint_y=None,
            height=dp(14),
        )
        self.add_widget(self._val)
        self.add_widget(self._lbl)

    def set_value(self, v: str):
        self._val.text = str(v)

    def set_color(self, color):
        self._val.text_color = color


# =============================================================================
# StatusPill — inline coloured status badge
# =============================================================================
class StatusPill(MDCard):
    def __init__(self, text: str, color=None, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(90), dp(24)))
        kwargs.setdefault('radius', [dp(12)])
        kwargs.setdefault('elevation', 0)
        c = color or C['cyan']
        bg = (c[0], c[1], c[2], 0.15)
        kwargs.setdefault('md_bg_color', bg)
        super().__init__(**kwargs)
        self._color = c
        self._lbl = MDLabel(
            text=text,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=c,
            halign='center',
            valign='center',
            bold=True,
        )
        self.add_widget(self._lbl)

    def update(self, text: str, color=None):
        c = color or self._color
        self._color = c
        self._lbl.text = text
        self._lbl.text_color = c
        self.md_bg_color = (c[0], c[1], c[2], 0.15)


# =============================================================================
# KegIDRow — individual scanned keg row with delete
# =============================================================================
class KegIDRow(MDBoxLayout):
    def __init__(self, index: int, keg_id: str,
                 is_new: bool = False, on_delete=None, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(36),
            spacing=dp(6),
            padding=[dp(8), dp(2), dp(4), dp(2)],
            **kwargs
        )
        self._keg_id    = keg_id
        self._on_delete = on_delete

        # Row background
        with self.canvas.before:
            Color(*(C['bg_elevated'] if not is_new else (0.05, 0.22, 0.20, 1)))
            self._bg_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(6)]
            )
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Index badge
        idx_card = MDCard(
            size_hint=(None, None),
            size=(dp(28), dp(22)),
            radius=[dp(4)],
            elevation=0,
            md_bg_color=C['bg_void'],
            pos_hint={'center_y': 0.5},
        )
        idx_lbl = MDLabel(
            text=f"{index:02d}",
            font_style='Caption',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            halign='center',
            valign='center',
        )
        idx_card.add_widget(idx_lbl)
        self.add_widget(idx_card)

        # Keg ID – monospace look
        id_lbl = MDLabel(
            text=str(keg_id),
            font_style='Body2',
            theme_text_color='Custom',
            text_color=C['cyan'] if not is_new else C['success'],
            halign='left',
            valign='center',
        )
        self.add_widget(id_lbl)

        # NEW badge
        if is_new:
            new_pill = StatusPill('NEW', C['success'])
            new_pill.size = (dp(58), dp(20))
            new_pill.pos_hint = {'center_y': 0.5}
            self.add_widget(new_pill)

        # Delete button
        del_btn = MDIconButton(
            icon='trash-can-outline',
            theme_text_color='Custom',
            text_color=C['danger'],
            icon_size=dp(18),
            size_hint=(None, None),
            size=(dp(34), dp(34)),
            pos_hint={'center_y': 0.5},
        )
        del_btn.bind(on_release=self._handle_delete)
        self.add_widget(del_btn)

    def _update_bg(self, *a):
        self._bg_rect.pos  = self.pos
        self._bg_rect.size = self.size

    def _handle_delete(self, instance):
        if self._on_delete:
            self._on_delete(self._keg_id)


# =============================================================================
# Divider
# =============================================================================
class HDivider(Widget):
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', dp(1))
        super().__init__(**kwargs)
        with self.canvas:
            Color(*C['border'])
            self._line = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._line, 'pos', self.pos))
        self.bind(size=lambda *a: setattr(self._line, 'size', self.size))


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
        # Root canvas background
        with self.canvas.before:
            Color(*C['bg_void'])
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda *a: setattr(self._bg, 'pos', self.pos),
            size=lambda *a: setattr(self._bg, 'size', self.size),
        )

        root = MDBoxLayout(
            orientation='horizontal',
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(12),
            md_bg_color=(0, 0, 0, 0),
        )
        root.add_widget(self._build_left_panel())
        root.add_widget(self._build_right_panel())
        self.add_widget(root)

    # ── LEFT PANEL ────────────────────────────────────────────────────────────

    def _build_left_panel(self):
        panel = MDBoxLayout(
            orientation='vertical',
            size_hint_x=0.65,
            spacing=dp(10),
        )

        panel.add_widget(self._build_top_bar())
        panel.add_widget(self._build_camera_card())
        panel.add_widget(self._build_stat_bar())
        panel.add_widget(self._build_notify_bar())

        return panel

    def _build_top_bar(self):
        bar = MDBoxLayout(
            size_hint_y=None,
            height=dp(50),
            spacing=dp(10),
            padding=[dp(4), 0, 0, 0],
        )

        # Logo / Title block
        logo_block = MDBoxLayout(orientation='vertical', spacing=dp(1))

        title_row = MDBoxLayout(orientation='horizontal', spacing=dp(8))

        # Camera icon
        cam_icon = MDIconButton(
            icon='cctv',
            theme_text_color='Custom',
            text_color=C['cyan'],
            icon_size=dp(28),
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
        )
        title_row.add_widget(cam_icon)

        title_lbl = MDLabel(
            text='PALLETIZER',
            font_style='H5',
            theme_text_color='Custom',
            text_color=C['text_bright'],
            bold=True,
            halign='left',
            valign='center',
        )
        title_row.add_widget(title_lbl)

        subtitle_lbl = MDLabel(
            text=f"TOP CAMERA  |  {SYSTEM_CONFIG.get('forklift_id', 'TOP-CAM-001')}",
            font_style='Caption',
            theme_text_color='Custom',
            text_color=C['cyan_dim'],
            halign='left',
            valign='center',
            size_hint_y=None,
            height=dp(16),
        )

        logo_block.add_widget(title_row)
        logo_block.add_widget(subtitle_lbl)
        bar.add_widget(logo_block)

        # Spacer
        bar.add_widget(Widget())

        # WebSocket status pill
        self._ws_pill = StatusPill('CONNECTED', C['cyan'])
        self._ws_pill.pos_hint = {'center_y': 0.5}
        bar.add_widget(self._ws_pill)

        # Time display
        self._time_lbl = MDLabel(
            text=datetime.now().strftime('%H:%M'),
            font_style='Body1',
            theme_text_color='Custom',
            text_color=C['text_secondary'],
            size_hint_x=None,
            width=dp(52),
            halign='center',
            valign='center',
            bold=True,
        )
        Clock.schedule_interval(self._tick_clock, 30)
        bar.add_widget(self._time_lbl)

        # Exit button
        exit_btn = MDIconButton(
            icon='power',
            theme_text_color='Custom',
            text_color=C['danger'],
            icon_size=dp(26),
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            pos_hint={'center_y': 0.5},
        )
        exit_btn.bind(on_release=self._on_exit)
        bar.add_widget(exit_btn)

        return bar

    def _tick_clock(self, dt):
        self._time_lbl.text = datetime.now().strftime('%H:%M')

    def _build_camera_card(self):
        card = MDCard(
            elevation=6,
            radius=[dp(12)],
            padding=dp(3),
            md_bg_color=C['bg_surface'],
        )
        # Inner border effect using a nested card
        inner = MDCard(
            elevation=0,
            radius=[dp(10)],
            padding=0,
            md_bg_color=C['bg_void'],
        )
        self._cam_img = Image(fit_mode='contain')
        inner.add_widget(self._cam_img)
        card.add_widget(inner)
        return card

    def _build_stat_bar(self):
        bar = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(76),
            spacing=dp(8),
        )
        self._stat_kegs   = StatCard('KEGS SCANNED', '0',         C['amber'],   )
        self._stat_cola   = StatCard('COLA PACKS',   '0',         C['cola'],    )
        self._stat_water  = StatCard('WATER PACKS',  '0',         C['water'],   )
        self._stat_status = StatCard('SESSION',      'ASSEMBLING',C['cyan'])
        for card in (self._stat_kegs, self._stat_cola, self._stat_water, self._stat_status):
            bar.add_widget(card)
        return bar

    def _build_notify_bar(self):
        bar = GlowCard(
            accent_color=C['cyan'],
            md_bg_color=C['bg_surface'],
            size_hint_y=None,
            height=dp(34),
            padding=[dp(14), dp(4), dp(14), dp(4)],
            radius=[dp(8)],
        )
        self._notify_lbl = MDLabel(
            text='System Ready',
            font_style='Body2',
            theme_text_color='Custom',
            text_color=C['cyan'],
            halign='left',
            valign='center',
            bold=True,
        )
        bar.add_widget(self._notify_lbl)
        return bar

    # ── RIGHT PANEL ───────────────────────────────────────────────────────────

    def _build_right_panel(self):
        panel = MDCard(
            orientation='vertical',
            size_hint_x=0.35,
            padding=[dp(14), dp(14), dp(14), dp(14)],
            spacing=dp(10),
            radius=[dp(14)],
            elevation=4,
            md_bg_color=C['bg_deep'],
        )

        # ── Keg count hero ────────────────────────────────────────────────────
        hero = GlowCard(
            accent_color=C['amber'],
            md_bg_color=C['bg_surface'],
            orientation='vertical',
            size_hint_y=None,
            height=dp(90),
            padding=[dp(10), dp(8)],
            radius=[dp(10)],
        )
        self._keg_count_lbl = MDLabel(
            text='0',
            font_style='H2',
            theme_text_color='Custom',
            text_color=C['amber'],
            halign='center',
            bold=True,
        )
        self._count_sub = MDLabel(
            text='KEGS ON PALLET',
            font_style='Overline',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            halign='center',
            size_hint_y=None,
            height=dp(20),
        )
        hero.add_widget(self._keg_count_lbl)
        hero.add_widget(self._count_sub)
        panel.add_widget(hero)

        # ── Product counts row ────────────────────────────────────────────────
        prod_row = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(64),
            spacing=dp(8),
        )
        self._cola_card  = StatCard('COLA PACKS',  '0', C['cola'],  )
        self._water_card = StatCard('WATER PACKS', '0', C['water'], )
        prod_row.add_widget(self._cola_card)
        prod_row.add_widget(self._water_card)
        panel.add_widget(prod_row)

        panel.add_widget(HDivider())

        # ── Customer selector ─────────────────────────────────────────────────
        panel.add_widget(_section_label('CUSTOMER'))

        cust_row = MDBoxLayout(
            size_hint_y=None, height=dp(46), spacing=dp(8)
        )
        self._cust_btn = MDRaisedButton(
            text=_DEFAULT_CUSTOMER,
            pos_hint={'center_y': 0.5},
            size_hint_x=1,
            font_size='12sp',
            md_bg_color=C['bg_elevated'],
            text_color=C['text_secondary'],
            elevation=0,
        )
        self._cust_btn.bind(on_release=self._open_customer_menu)

        self._refresh_btn = MDIconButton(
            icon='refresh',
            theme_text_color='Custom',
            text_color=C['cyan'],
            icon_size=dp(22),
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            pos_hint={'center_y': 0.5},
        )
        self._refresh_btn.bind(on_release=lambda _: self._on_refresh_click())
        cust_row.add_widget(self._cust_btn)
        cust_row.add_widget(self._refresh_btn)
        panel.add_widget(cust_row)

        # ── Location ──────────────────────────────────────────────────────────
        panel.add_widget(_section_label('DISPATCH LOCATION'))

        self._loc_card = GlowCard(
            accent_color=C['text_muted'],
            orientation='horizontal',
            size_hint_y=None,
            height=dp(40),
            radius=[dp(8)],
            padding=[dp(12), dp(4)],
            elevation=0,
            md_bg_color=C['bg_surface'],
        )
        self._loc_status_icon = MDIconButton(
            icon='map-marker-outline',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            icon_size=dp(18),
            size_hint=(None, None),
            size=(dp(30), dp(30)),
            pos_hint={'center_y': 0.5},
            disabled=True,
        )
        self._loc_lbl = MDLabel(
            text='Awaiting location from cloud…',
            font_style='Body2',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            halign='left',
            valign='center',
        )
        self._loc_card.add_widget(self._loc_status_icon)
        self._loc_card.add_widget(self._loc_lbl)
        panel.add_widget(self._loc_card)

        # ── Scanned IDs list ──────────────────────────────────────────────────
        list_hdr = MDBoxLayout(
            size_hint_y=None, height=dp(24), spacing=dp(6)
        )
        list_hdr.add_widget(_section_label('SCANNED KEG IDs'))
        self._scan_badge = StatusPill('0 KEGS', C['amber'])
        self._scan_badge.size = (dp(72), dp(22))
        self._scan_badge.pos_hint = {'center_y': 0.5}
        list_hdr.add_widget(self._scan_badge)
        panel.add_widget(list_hdr)

        scroll_bg = MDCard(
            md_bg_color=C['bg_void'],
            radius=[dp(10)],
            padding=[dp(6), dp(4)],
            elevation=0,
        )
        self._id_scroll = ScrollView(bar_width=dp(3))
        self._id_list_box = MDBoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=dp(4),
        )
        self._id_list_box.bind(minimum_height=self._id_list_box.setter('height'))

        self._empty_lbl = MDLabel(
            text=_WAITING_TEXT,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=C['text_muted'],
            halign='center',
            size_hint_y=None,
            height=dp(50),
        )
        self._id_list_box.add_widget(self._empty_lbl)
        self._id_scroll.add_widget(self._id_list_box)
        scroll_bg.add_widget(self._id_scroll)
        panel.add_widget(scroll_bg)

        # ── Action buttons ────────────────────────────────────────────────────
        panel.add_widget(HDivider())

        btn_row = MDBoxLayout(
            size_hint_y=None, height=dp(54), spacing=dp(10)
        )

        self._reset_btn = MDRaisedButton(
            text='RESET',
            disabled=True,
            font_size='13sp',
            md_bg_color=C['bg_elevated'],
            text_color=C['amber_dim'],
            elevation=0,
            size_hint_x=None,
            width=dp(100),
            size_hint_y=None,
            height=dp(48),
            pos_hint={'center_y': 0.5},
        )
        self._reset_btn.bind(on_release=self._on_reset)

        self._submit_btn = MDRaisedButton(
            text=_SUBMIT_TEXT,
            md_bg_color=C['text_muted'],
            disabled=True,
            font_size='14sp',
            size_hint_x=1,
            size_hint_y=None,
            height=dp(48),
            pos_hint={'center_y': 0.5},
            elevation=0,
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
        self._scan_badge.update(f"{keg_count} KEGS", C['amber'])
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

        # Reset button
        self._reset_btn.disabled = not has_kegs
        self._reset_btn.md_bg_color = (
            C['bg_elevated'] if not has_kegs else C['bg_surface']
        )
        self._reset_btn.text_color = (
            C['text_muted'] if not has_kegs else C['amber']
        )

        # Submit gate
        is_dispatch = "dispatch" in str(self.confirmed_location or '').lower()
        all_ready = (
            (has_kegs and has_location and has_customer) if is_dispatch
            else (has_kegs and has_location)
        )

        self._submit_btn.disabled = not all_ready
        if all_ready:
            self._submit_btn.md_bg_color = C['success']
            self._submit_btn.text_color  = (0.02, 0.06, 0.04, 1)
        else:
            self._submit_btn.md_bg_color = C['bg_elevated']
            self._submit_btn.text_color  = C['text_muted']

        # Customer button colour feedback
        if has_customer:
            self._cust_btn.md_bg_color = (0.05, 0.22, 0.20, 1)
            self._cust_btn.text_color  = C['cyan']
        else:
            self._cust_btn.md_bg_color = C['bg_elevated']
            self._cust_btn.text_color  = C['text_secondary']

    # =========================================================================
    # DELETE KEG
    # =========================================================================

    def _on_delete_keg(self, keg_id: str):
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='Remove Keg?',
            text=(
                f"Remove [b]{keg_id}[/b] from this session?\n\n"
                "This keg will not be included in the submission."
            ),
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    theme_text_color='Custom',
                    text_color=C['text_secondary'],
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='REMOVE',
                    md_bg_color=C['danger'],
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
            self._notify(f"Removed: {keg_id}", color=C['warning'])
        else:
            self._notify(f"Could not remove {keg_id}", color=C['danger'])

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
    def _draw_corner_brackets(frame, x1, y1, x2, y2, color, length=16, thick=3):
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
                lambda _: self._notify('Network error — customer list not updated',
                                       color=C['danger']), 0
            )

    def _apply_customers(self, customers: list[dict]):
        if not customers:
            self._notify('No customers returned from API', color=C['warning'])
            return
        self.customer_map = {c['name']: c['id'] for c in customers}
        if self._cust_btn.text not in self.customer_map:
            self._cust_btn.text = _DEFAULT_CUSTOMER
        self._notify(f"{len(customers)} customers loaded",
                     color=C['success'], duration=3)

    def _open_customer_menu(self, instance):
        if not self.customer_map:
            self._notify('No customers loaded — tap Refresh', color=C['warning'])
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
        self._notify(f"Customer selected: {name}", color=C['cyan'], duration=3)
        self._update_button_states(len(self.controller.scanned_kegs))

    def _on_refresh_click(self):
        self._notify('Refreshing customer list…', color=C['warning'])
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

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            size_hint_y=None,
            height=dp(80),
        )
        msg_lbl = MDLabel(
            text=(
                f"Forklift has arrived at:\n\n"
                f"[b][color=#00E5FF]{location_name}[/color][/b]\n\n"
                "Confirm to enable submission."
            ),
            markup=True,
            font_style='Body1',
            theme_text_color='Custom',
            text_color=C['text_primary'],
            halign='center',
        )
        content.add_widget(msg_lbl)

        self._dialog = MDDialog(
            title='Location Arrived',
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(
                    text='DISMISS',
                    theme_text_color='Custom',
                    text_color=C['text_muted'],
                    on_release=lambda _: self._on_location_cancel(),
                ),
                MDRaisedButton(
                    text='CONFIRM',
                    md_bg_color=C['cyan'],
                    text_color=(0.02, 0.06, 0.07, 1),
                    on_release=lambda _: self._on_location_confirm(),
                ),
            ],
        )
        self._dialog.open()

    def _on_location_confirm(self):
        self._dismiss_dialog()
        self.confirmed_location = self.pending_location
        loc = self.confirmed_location or ''

        self.controller.freeze_product_counts()
        self._mark_product_counts_frozen()

        self._loc_card._accent = C['success']
        self._loc_card._redraw()
        self._loc_card.md_bg_color = (0.04, 0.18, 0.12, 1)
        self._loc_status_icon.icon = 'map-marker-check-outline'
        self._loc_status_icon.text_color = C['success']
        
        self._loc_lbl.text = loc
        self._loc_lbl.text_color = C['success']

        self._stat_status.set_value('READY')
        self._stat_status.set_color(C['success'])
        self._notify(
            f"Location confirmed: {loc}  —  product counts locked",
            color=C['success'],
        )
        self._update_button_states(len(self.controller.scanned_kegs))
        if not self._submit_btn.disabled:
            self._notify('Ready to submit — press SUBMIT TO CLOUD', color=C['amber'])
        else:
            is_dispatch = "dispatch" in loc.lower()
            if is_dispatch and self._cust_btn.text == _DEFAULT_CUSTOMER:
                self._notify('Select a customer to enable submission', color=C['warning'])

    def _mark_product_counts_frozen(self) -> None:
        for card in (self._stat_cola, self._cola_card):
            card._lbl.text = 'COLA — LOCKED'
        for card in (self._stat_water, self._water_card):
            card._lbl.text = 'WATER — LOCKED'

    def _mark_product_counts_active(self) -> None:
        for card in (self._stat_cola, self._cola_card):
            card._lbl.text = 'COLA PACKS'
        for card in (self._stat_water, self._water_card):
            card._lbl.text = 'WATER PACKS'

    def _on_location_cancel(self):
        self._dismiss_dialog()
        self._notify('Location cancelled', color=C['danger'])

    # =========================================================================
    # RESET
    # =========================================================================

    def _on_reset(self, instance):
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='Reset Session?',
            text=(
                f"This will clear all {len(self.controller.scanned_kegs)} scanned kegs "
                "and start a new pallet.\n\nThis action cannot be undone."
            ),
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    theme_text_color='Custom',
                    text_color=C['text_secondary'],
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='RESET',
                    md_bg_color=C['danger'],
                    on_release=lambda _: self._confirm_reset(),
                ),
            ],
        )
        self._dialog.open()

    def _confirm_reset(self):
        self._dismiss_dialog()
        self.confirmed_location = None
        self.pending_location   = None

        # Reset location card
        self._loc_card.md_bg_color = C['bg_surface']
        self._loc_card._accent = C['text_muted']
        self._loc_card._redraw()
        self._loc_status_icon.icon = 'map-marker-outline'
        self._loc_status_icon.text_color = C['text_muted']

        self._loc_lbl.text = 'Awaiting location from cloud…'
        self._loc_lbl.text_color = C['text_muted']

        self._stat_status.set_value('ASSEMBLING')
        self._stat_status.set_color(C['cyan'])
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
        self._notify('Session reset — new pallet started', color=C['cyan'])
        Clock.schedule_once(lambda _: setattr(self, '_ignore_cam', False), 2.0)

    # =========================================================================
    # SUBMIT
    # =========================================================================

    def _on_submit(self, instance):
        self._submit_btn.disabled = True
        self._submit_btn.text     = _SENDING_TEXT
        self._submit_btn.md_bg_color = C['warning']
        self._stat_status.set_value('SENDING')
        self._stat_status.set_color(C['warning'])
        self._notify('Dispatching batch to cloud…', color=C['amber'])
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
            self._stat_status.set_color(C['success'])
            self._notify('Batch dispatched successfully!', color=C['success'])

            try:
                response_str = result.get('data')
                if response_str:
                    resp = json.loads(response_str)
                    pallet_id = (resp.get('paletteId')
                                 or resp.get('palletId')
                                 or resp.get('id'))
                    if pallet_id and self.printer:
                        self._notify(f"Printing Pallet {pallet_id}…", color=C['cyan'])

                        def _do_print_bg():
                            ok, msg = self.printer.print_pallet_qr(pallet_id)
                            Clock.schedule_once(lambda _: self._notify(
                                f"Pallet {pallet_id} printed successfully" if ok
                                else f"Printer error: {msg}",
                                color=C['success'] if ok else C['danger']
                            ), 0)

                        threading.Thread(
                            target=_do_print_bg, name='PrinterThread', daemon=True
                        ).start()
            except Exception as e:
                logger.warning(f"Failed to trigger printer logic: {e}")

            self._confirm_reset()
        else:
            self._submit_failed(result)

    def _submit_failed(self, result: dict):
        self._submit_btn.text     = _SUBMIT_TEXT
        self._submit_btn.disabled = False
        self._stat_status.set_value('ERROR')
        self._stat_status.set_color(C['danger'])
        self._notify('Submission failed — see details', color=C['danger'])
        err = result.get('error', 'Unknown network error')
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='Submission Failed',
            text=f"Could not dispatch batch to cloud.\n\nReason: {err}",
            buttons=[
                MDRaisedButton(
                    text='CLOSE',
                    md_bg_color=C['danger'],
                    on_release=lambda _: self._dismiss_dialog(),
                ),
            ],
        )
        self._dialog.open()
        # Re-enable submit after failure
        self._update_button_states(len(self.controller.scanned_kegs))

    # =========================================================================
    # EXIT
    # =========================================================================

    def _on_exit(self, instance):
        self._dismiss_dialog()
        self._dialog = MDDialog(
            title='Exit Application?',
            text='Shut down the Top Camera System?\n\nSession data is safe in the local database.',
            buttons=[
                MDFlatButton(
                    text='CANCEL',
                    theme_text_color='Custom',
                    text_color=C['text_secondary'],
                    on_release=lambda _: self._dismiss_dialog(),
                ),
                MDRaisedButton(
                    text='SHUT DOWN',
                    md_bg_color=C['danger'],
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
            self._notify_lbl.text_color = color or C['cyan']
            if self._notify_event:
                self._notify_event.cancel()
            d = duration if duration is not None else UI_CONFIG.get('notification_duration', 4)
            if d > 0:
                self._notify_event = Clock.schedule_once(self._clear_notify, d)
        Clock.schedule_once(_do, 0)

    def _clear_notify(self, dt):
        self._notify_lbl.text       = 'System Ready'
        self._notify_lbl.text_color = C['cyan']

    # =========================================================================
    # WEBSOCKET STATUS
    # =========================================================================

    def set_ws_status(self, status: str):
        def _do(dt):
            if status == 'connected':
                self._ws_pill.update('CONNECTED', C['success'])
            elif status == 'connecting':
                self._ws_pill.update('CONNECTING', C['warning'])
            else:
                self._ws_pill.update('OFFLINE', C['danger'])
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