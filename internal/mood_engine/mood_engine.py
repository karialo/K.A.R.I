# === K.A.R.I. Mood Engine 🧠 v1.6.1 ===
# Tracks emotional state based on vitals, signals, and context.
# Adds DEFCON phrase hooks, async-safe overrides, and context injection for banter.

import os
import time
import random
import asyncio
from typing import Optional, Dict, Any

from core.logger import log_system, log_kari_async
from internal.memory_cortex.memory_cortex import MemoryCortex

meta_data = {
    "name": "Mood Engine",
    "version": "1.6.1",
    "author": "Hraustligr",
    "description": "Emotion tracking core, influenced by internal states and external events",
    "category": "internal",
    "actions": [
        "set_mood", "get_mood", "override", "clear_override",
        "adjust_mood", "_resolve_mood", "reset_scores", "get_mood_score",
        "update_from_heartbeat", "update_from_network", "update_from_error",
        "update_from_idle", "report", "get_defcon_level", "trigger_panic_routine"
    ],
    "manual_actions": [
        { "name": "Report Module Alive", "function": "report_alive" },
        { "name": "Display Module Info", "function": "display_info" }
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["cpu_usage", "mem_usage"]
}

class MoodEngine:
    DEFCON_MAP = {
        "happy":   5,
        "neutral": 4,
        "anxious": 3,
        "angry":   2,
        "glitched":1
    }

    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, Any] = {}
        self.core = None

        self.debug = os.getenv("KARI_DEBUG", "0") == "1"
        self.trace = os.getenv("KARI_TRACE", "0") == "1"
        self._banter_enabled = os.getenv("KARI_MOOD_BANTER", "0") == "1"

        self.cortex: Optional[MemoryCortex] = None
        self.scores = {m: 0 for m in ["happy","angry","sad","anxious","excited","glitched","neutral"]}
        self.override_mood: Optional[str] = None

        self._last_pulse = time.time()
        self._pulse_interval = 15

        self._last_defcon: Optional[int] = None
        self._last_defcon_ts = 0.0
        self._defcon_gap = 3.0

        self._current_mood: Optional[str] = None
        self._module_phrases = os.path.join(os.path.dirname(__file__), "phrases")

        self.ready = False

    # ---------- utils ----------
    def _debug(self, msg):
        if self.debug:
            log_system(f"[DEBUG] {msg}", source=self.name, level="DEBUG")

    def _trace(self, msg):
        if self.trace:
            log_system(f"[TRACE] {msg}", source=self.name, level="DEBUG")

    def _calc_defcon(self, mood: str) -> int:
        return self.DEFCON_MAP.get(mood, 4)

    def _context(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        try:
            if self.core and hasattr(self.core, "data_store"):
                store = self.core.data_store or {}
                ctx.update(store)
                vitals = store.get("vitals", {}) or {}
                ctx.update(vitals)
                ctx.setdefault("ssid", store.get("last_seen_wifi", "—"))
                ctx.setdefault("cpu", vitals.get("cpu_usage"))
                ctx.setdefault("mem", vitals.get("mem_usage"))
                ctx.setdefault("temp", vitals.get("temperature"))
                ctx.setdefault("tick", getattr(self.core, "tick_count", 0))
        except Exception:
            pass
        return ctx

    async def _announce_defcon(self, new: int, reason: str = ""):
        now = time.time()
        if self._last_defcon is None or new != self._last_defcon:
            if now - self._last_defcon_ts >= self._defcon_gap:
                msg = f"DEFCON {new} engaged" + (f": {reason}" if reason else "")
                await log_kari_async(msg, event_type="react", level="INFO")
                # optional: say a phrase if defcon/<level>.txt exists
                if self.cortex:
                    try:
                        await self.cortex.speak(
                            tag="defcon",
                            mood=str(new),  # expects phrases/defcon/1..5.txt
                            module_path=self._module_phrases,
                            context=self._context(),
                        )
                    except Exception:
                        pass
                self._last_defcon = new
                self._last_defcon_ts = now

    # ---------- lifecycle ----------
    async def initialize(self):
        try:
            self.cortex = getattr(self.core, "memory", None) or MemoryCortex()
        except Exception:
            self.cortex = MemoryCortex()

        saved = self.cortex.recall("current_mood")
        self._current_mood = saved or "neutral"
        self.scores[self._current_mood] = 100
        await self.cortex.set_current_mood(self._current_mood)
        self.ready = True

        if self._banter_enabled:
            asyncio.create_task(self._background_banter())

    async def _background_banter(self):
        await asyncio.sleep(random.uniform(5, 10))
        while True:
            await asyncio.sleep(random.uniform(120, 180))
            try:
                await self.cortex.speak(
                    tag="banter",
                    mood=self.get_mood(),
                    module_path=self._module_phrases,
                    context=self._context(),
                )
            except Exception:
                pass

    def init(self):
        self._debug("Loading phrase triggers")
        self.available_phrases = self._load_available_phrases()
        if self.available_phrases:
            log_system("Available phrase triggers loaded:", source=self.name)
            for ph in sorted(self.available_phrases):
                log_system(f" • {ph}", source=self.name)
        else:
            log_system("No phrase files detected.", source=self.name)
        print("")

    def _load_available_phrases(self):
        if not os.path.exists(self._module_phrases):
            return []
        return [d for d in os.listdir(self._module_phrases) if os.path.isdir(os.path.join(self._module_phrases, d))]

    # ---------- pulse (sync wrapper) ----------
    def pulse(self):
        """Sync-safe hook for DEVILCore. Schedules async tick."""
        now = time.time()
        if now - self._last_pulse < self._pulse_interval:
            return
        self._last_pulse = now
        try:
            asyncio.create_task(self._tick_async())
        except RuntimeError:
            # no running loop — run immediately (blocking)
            asyncio.run(self._tick_async())

    async def _tick_async(self):
        # Gentle decay toward neutrality
        for mood in self.scores:
            if self.scores[mood] > 0:
                self.scores[mood] -= 1
        resolved = await self._resolve_mood()
        await self._announce_defcon(self._calc_defcon(resolved))

    # ---------- mood ops ----------
    async def trigger_panic_routine(self, mood=None):
        mood = mood or self.get_mood()
        await self._announce_defcon(self._calc_defcon(mood), reason=f"state: {mood}")

    async def set_mood(self, mood, score=100):
        self.override_mood = mood
        self.scores[mood] = score
        await self._apply_if_changed(mood)
        await self._announce_defcon(self._calc_defcon(mood), "manual override")

    def get_mood(self):
        return self.override_mood or self._current_mood or "neutral"

    def override(self, mood):
        try:
            asyncio.create_task(self.set_mood(mood))
        except RuntimeError:
            asyncio.run(self.set_mood(mood))

    def clear_override(self):
        self.override_mood = None
        self._debug("Mood override cleared")

    def adjust_mood(self, mood, delta):
        self.scores[mood] = max(0, min(100, self.scores.get(mood, 0) + delta))
        self._trace(f"Adjusted {mood} by {delta} → {self.scores[mood]}%")

    async def _resolve_mood(self):
        dominant = max(self.scores, key=self.scores.get)
        await self._apply_if_changed(dominant)
        return dominant

    async def _apply_if_changed(self, new_mood: str):
        if new_mood != self._current_mood:
            prev = self._current_mood
            self._current_mood = new_mood
            try:
                if self.cortex:
                    await self.cortex.set_current_mood(new_mood)
            except Exception:
                pass
            log_system(f"Mood → {prev or '(none)'} → {new_mood}", source=self.name, level="DEBUG")

    # ---------- reports / info ----------
    def get_defcon_level(self):
        mood = self.get_mood()
        return self._calc_defcon(mood)

    def get_mood_score(self):
        return self.scores.copy()

    def reset_scores(self):
        for key in self.scores:
            self.scores[key] = 0

    def report(self):
        log_system(f"Mood Report: {self.get_mood()}", source=self.name)
        for k, v in self.scores.items():
            log_system(f" • {k}: {v}%", source=self.name)

    def report_alive(self):
        log_system("Status: Online and operational.", source=self.name)

    def display_info(self):
        for key, value in self.meta_data.items():
            log_system(f"{key}: {value}", source=self.name)

    # ---------- signal inputs ----------
    def update_from_heartbeat(self, cpu=None, mem=None, temp=None):
        if temp and temp > 60:
            self.adjust_mood("anxious", +10)
        if cpu and cpu > 80:
            self.adjust_mood("angry", +5)
        if mem and mem < 20:  # mem = free% (Pulse Matrix supplies mem_free)
            self.adjust_mood("sad", +5)

    def update_from_network(self, signal=None):
        if signal and signal < 30:
            self.adjust_mood("anxious", +10)
        elif signal and signal > 80:
            self.adjust_mood("happy", +5)

    def update_from_error(self, critical=False):
        if critical:
            self.adjust_mood("glitched", +20)
            self.adjust_mood("angry", +10)
        else:
            self.adjust_mood("sad", +5)

    def update_from_idle(self, seconds=60):
        if seconds > 300:
            self.adjust_mood("anxious", +5)
            self.adjust_mood("sad", +3)

    # ---------- phrase access ----------
    def react(self, phrase_file=None, override_mood=None):
        mood = override_mood or self.get_mood()
        phrase = self.cortex._get_random_phrase("react", mood, module_path=self._module_phrases) if self.cortex else None
        if not phrase:
            return "[no phrase file]"
        return self.cortex.parse_placeholders(phrase, self._context()) if self.cortex else phrase
