# splash.py
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.spinner import MDSpinner
from kivy.metrics import dp
from kivy.clock import Clock
import threading

class SplashScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'splash'
        self._build_ui()
        
    def _build_ui(self):
        # Main Layout
        layout = MDBoxLayout(orientation='vertical', padding=dp(40), spacing=dp(20))
        layout.pos_hint = {'center_x': 0.5, 'center_y': 0.5}
        layout.size_hint = (0.6, 0.6)
        
        # Title
        title = MDLabel(
            text="Custom Palletization",
            halign="center",
            font_style="H2",
            theme_text_color="Primary",
            bold=True
        )
        subtitle = MDLabel(
            text="Top Camera System",
            halign="center",
            font_style="H5",
            theme_text_color="Secondary"
        )
        
        layout.add_widget(title)
        layout.add_widget(subtitle)
        
        # Spacer
        layout.add_widget(MDLabel(size_hint_y=0.2)) # Spacer
        
        # Spinner
        self.spinner = MDSpinner(
            size_hint=(None, None),
            size=(dp(60), dp(60)),
            pos_hint={'center_x': 0.5},
            active=True,
            palette=[
                [0.2, 0.6, 1, 1],
                [0.2, 0.5, 0.9, 1],
            ]
        )
        layout.add_widget(self.spinner)
        
        # Status Label
        self.status_label = MDLabel(
            text="Initializing System...",
            halign="center",
            font_style="Subtitle1",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(40)
        )
        layout.add_widget(self.status_label)
        
        self.add_widget(layout)
        
    def update_status(self, text):
        """Update status text safely from any thread"""
        def _update(dt):
            self.status_label.text = text
        Clock.schedule_once(_update, 0)
