# retina_array.py
# Retina Array — K.A.R.I.'s visual cortex (Display HAT Mini handler)
# Handles framebuffer + button polling directly. No pygame event injection.

import os
from PIL import Image, ImageDraw, ImageFont
from displayhatmini import DisplayHATMini

meta_data = {
    "name": "Retina Array",
    "version": "1.9",
    "description": "Handles visual output and button polling on Display HAT Mini (no GPIO interrupts)",
    "category": "internal"
}

class RetinaArray:
    def __init__(self):
        self.name = meta_data["name"]

        # === Display config ===
        self.WIDTH = 320
        self.HEIGHT = 240
        self.LINE_HEIGHT = 12
        self.MAX_LINES = self.HEIGHT // self.LINE_HEIGHT
        self.FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

        # === State ===
        self.lines = []

        # === Init display ===
        self.framebuffer = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        self.draw = ImageDraw.Draw(self.framebuffer)
        self.displayhat = DisplayHATMini(self.framebuffer)
        self.displayhat.set_backlight(1.0)

        # === Load font (fallback if needed) ===
        try:
            self.font = ImageFont.truetype(self.FONT_PATH, 12)
        except IOError:
            self.font = ImageFont.load_default()

    def init(self):
        """Clear and show startup line."""
        self.clear()
        self.write_line("Retina Array online.")

    def clear(self):
        """Clear screen and internal buffer."""
        self.lines = []
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")
        self.displayhat.display()

    def write_line(self, text: str):
        """Write a single scrolling log line to the screen."""
        self.lines.append(text)
        if len(self.lines) > self.MAX_LINES:
            self.lines.pop(0)

        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")
        for i, line in enumerate(self.lines):
            self.draw.text((5, i * self.LINE_HEIGHT), line, font=self.font, fill=(0, 255, 0))
        self.displayhat.display()

    def splash(self, title="K.A.R.I.", subtitle="SYNAPSYS Boot Sequence"):
        """Display a centered splash screen with title + subtitle."""
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")

        try:
            title_font = ImageFont.truetype(self.FONT_PATH, 28)
            sub_font = ImageFont.truetype(self.FONT_PATH, 16)
        except IOError:
            title_font = sub_font = ImageFont.load_default()

        tw = title_font.getlength(title)
        sw = sub_font.getlength(subtitle)

        self.draw.text(((self.WIDTH - tw) // 2, 60), title, font=title_font, fill=(0, 255, 255))
        self.draw.text(((self.WIDTH - sw) // 2, 120), subtitle, font=sub_font, fill=(100, 255, 100))
        self.displayhat.display()

    def draw_lines(self, lines):
        """Draw a full list of lines (replaces screen)."""
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")
        for i, line in enumerate(lines[:self.MAX_LINES]):
            self.draw.text((5, i * self.LINE_HEIGHT), line, font=self.font, fill=(0, 255, 0))
        self.displayhat.display()

    def poll_events(self):
        """Poll physical button states (true polling) — returns dict of button:bool."""
        try:
            return {
                "a": self.displayhat.read_button(self.displayhat.BUTTON_A),
                "b": self.displayhat.read_button(self.displayhat.BUTTON_B),
                "x": self.displayhat.read_button(self.displayhat.BUTTON_X),
                "y": self.displayhat.read_button(self.displayhat.BUTTON_Y),
            }
        except Exception as e:
            print(f"[BUTTON POLL ERROR] {e}")
            return { "a": False, "b": False, "x": False, "y": False }

    def debug_button_map(self):
        """Dump attributes for developer diagnostics."""
        print("[DEBUG] Dumping displayhat button attributes:")
        for name in dir(self.displayhat):
            if "button" in name:
                attr = getattr(self.displayhat, name)
                print(f"  - {name}: {type(attr)}")
