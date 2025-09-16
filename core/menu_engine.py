# menu_engine.py
# K.A.R.I. Async DisplayHATMini-driven menu interface using polling-style button handling

import asyncio
from core.logger import log_system

retina = None  # Will be injected from kari.py

def set_retina(device):
    global retina
    retina = device

class MenuEngine:
    def __init__(self):
        self.name = "MenuEngine"
        self.options = [
            "Status Report",
            "Diagnostics",
            "Memory Logs",
            "Network Tools",
            "Reboot System",
            "Shutdown"
        ]
        self.selected = 0
        self.running = True
        self.last_press = {}  # debounce tracking

    async def run(self):
        log_system("Main Menu Interface Online.", source=self.name)
        try:
            while self.running:
                await self.draw()
                await self.poll_buttons()
                await asyncio.sleep(0.1)
        except Exception as e:
            log_system(f"Menu crashed: {e}", source=self.name)
            if retina:
                retina.draw_lines(["[ERROR]", str(e)])

    async def draw(self):
        """Draws the menu to the screen."""
        if not retina:
            return

        lines = ["= K.A.R.I MAIN MENU ="]

        for idx, option in enumerate(self.options):
            prefix = "➤" if idx == self.selected else "  "
            lines.append(f"{prefix} {option}")

        lines.append("=" * 24)
        retina.draw_lines(lines)

    async def poll_buttons(self):
        """Polls button states and reacts."""
        if not retina:
            return

        buttons = retina.poll_events()

        for key, pressed in buttons.items():
            # Simple debounce: only react on "new" presses
            if pressed and not self.last_press.get(key, False):
                await self.handle_press(key)
            self.last_press[key] = pressed

    async def handle_press(self, key):
        """Logic for handling specific button presses."""
        if key == "a":
            self.selected = (self.selected - 1) % len(self.options)
            print("[MENU] UP")
        elif key == "b":
            self.selected = (self.selected + 1) % len(self.options)
            print("[MENU] DOWN")
        elif key == "y":
            print("[MENU] CONFIRM")
            await self.select_option()
        elif key == "x":
            print("[MENU] EXIT")
            self.running = False
            log_system("Exiting menu...", source=self.name)
            retina.clear()
            retina.write_line("Exiting menu...")

    async def select_option(self):
        """Handles what happens when an option is selected."""
        selected_option = self.options[self.selected]
        log_system(f"Selected: {selected_option}", source=self.name)

        if not retina:
            return

        response = {
            "Status Report": "All systems green. Mood stable. Memory intact.",
            "Diagnostics": "Self-check complete. No anomalies detected.",
            "Memory Logs": "Logs stored. Cortex operational.",
            "Network Tools": "Pinging localhost... pong!",
            "Reboot System": "System reboot requested... (not implemented)",
            "Shutdown": "System shutdown requested... (not implemented)"
        }.get(selected_option, "Command not recognized.")

        retina.clear()
        retina.draw_lines([
            f">>> {selected_option}",
            response
        ])
        await asyncio.sleep(2)
