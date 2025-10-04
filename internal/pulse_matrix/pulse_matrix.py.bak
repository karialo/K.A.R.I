# === Pulse Matrix 💓 v1.7.1 ===
# Adds: info beats (rate-limited), unified react emitter, richer context.

import os
import time
import random
import asyncio
from typing import Optional, Dict, Any

try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

from core.logger import log_system
from internal.memory_cortex.memory_cortex import MemoryCortex

meta_data = {
    "name": "Pulse Matrix",
    "version": "1.7.1",
    "author": "Hraustligr",
    "description": "Tracks vital system stats like CPU, memory, and thermal levels.",
    "category": "internal",
    "actions": ["get_vitals", "report_alive", "display_info"],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"}
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["cpu_usage", "mem_usage", "temperature"]
}

class PulseMatrix:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, Any] = {}
        self.core = None
        self.ready = False

        # cadence
        self.last_pulse = time.time()
        try:
            self.pulse_interval = int(os.getenv("KARI_PULSE_INTERVAL", "10"))
        except Exception:
            self.pulse_interval = 10

        # cfg & state
        self._banter_enabled = os.getenv("KARI_BANTER", "1") == "1"

        # info-beat rate limiting
        self._info_gap = float(os.getenv("KARI_PULSE_INFO_GAP", "20"))
        self._last_info_ts = 0.0

        # thermal thresholds (hysteresis)
        self._hot_thresh = float(os.getenv("KARI_THERMAL_HOT", "82.0"))
        self._cool_thresh = float(os.getenv("KARI_THERMAL_COOL", "75.0"))
        self._hot_state = False

        # CPU/MEM thresholds (with event cool-downs)
        self._cpu_high = float(os.getenv("KARI_CPU_HIGH", "85"))
        self._cpu_low = float(os.getenv("KARI_CPU_LOW", "25"))
        self._mem_used_high = float(os.getenv("KARI_MEM_USED_HIGH", "90"))
        self._mem_free_low = float(os.getenv("KARI_MEM_FREE_LOW", "10"))
        self._spike_gap = float(os.getenv("KARI_PULSE_SPIKE_GAP", "45"))
        self._last_cpu_spike_ts = 0.0
        self._last_mem_spike_ts = 0.0

        # debug
        self.debug = False
        self._dbg_last_push = 0.0

        # phrase plumbing
        self.cortex = MemoryCortex()
        self._module_phrases = os.path.join(os.path.dirname(__file__), "phrases")

    # ---------- helpers ----------
    def _debug(self, msg):
        if self.debug:
            log_system(f"[DEBUG] {msg}", source=self.name, level="DEBUG")

    def _say(self, text: str):
        """Compact info line into K.A.R.I chat stream (best-effort)."""
        try:
            if self.core and self.core.voice and getattr(self.core.voice, "ready", False):
                from core.logger import log_kari
                log_kari(text, module_name="K.A.R.I")
        except Exception as e:
            self._debug(f"say failure: {e}")

    def _context(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        try:
            if self.core and hasattr(self.core, "data_store"):
                store = self.core.data_store or {}
                ctx.update(store)
                vitals = store.get("vitals", {}) or {}
                ctx.update(vitals)
                if "cpu_usage" in ctx and "cpu" not in ctx:
                    try: ctx["cpu"] = int(ctx["cpu_usage"])
                    except Exception: ctx["cpu"] = ctx["cpu_usage"]
                if "mem_usage" in ctx and "mem" not in ctx:
                    try: ctx["mem"] = int(ctx["mem_usage"])
                    except Exception: ctx["mem"] = ctx["mem_usage"]
                if "temperature" in ctx and "temp" not in ctx:
                    ctx["temp"] = ctx["temperature"]
                ctx.setdefault("ssid", store.get("last_seen_wifi", "—"))
                ctx.setdefault("tick", getattr(self.core, "tick_count", 0))
        except Exception:
            pass
        try:
            snap = dict(self.shared_data)
            ctx.setdefault("cpu", snap.get("cpu_usage"))
            ctx.setdefault("mem", snap.get("mem_usage"))
            ctx.setdefault("temp", snap.get("temperature"))
        except Exception:
            pass
        return ctx

    def _mood_engine(self):
        try:
            if getattr(self, "core", None) and hasattr(self.core, "modules"):
                me = self.core.modules.get("Mood Engine")
                if me: return me
            if getattr(self.core, "mood_engine", None): return self.core.mood_engine
            if getattr(self.core, "mood", None): return self.core.mood
            if getattr(self.core, "modules", None):
                for m in self.core.modules.values():
                    if hasattr(m, "update_from_heartbeat"): return m
        except Exception:
            pass
        return None

    def _route_mood_update(self, vitals: Dict[str, Any]):
        me = self._mood_engine()
        if not me or not hasattr(me, "update_from_heartbeat"):
            return
        try:
            mem_used = vitals.get("mem_usage")
            mem_free = vitals.get("mem_free")
            if mem_free is None and mem_used is not None:
                mem_free = max(0, min(100, 100 - float(mem_used)))
            me.update_from_heartbeat(
                cpu=vitals.get("cpu_usage"),
                mem=mem_free,
                temp=vitals.get("temperature"),
            )
        except Exception as e:
            self._debug(f"update_from_heartbeat failed: {e}")

    async def _emit_react(self, state: str, extra: Dict[str, Any] | None = None):
        """Unified react emitter with rich placeholders."""
        try:
            payload = self._context()
            payload["module_name"] = self.name
            payload["state"] = state
            if extra:
                payload.update(extra)
            await self.cortex.speak(
                tag="react",
                mood=self.cortex.get_current_mood(),
                module_path=self._module_phrases,
                return_only=False,
                **payload
            )
        except Exception as e:
            self._debug(f"_emit_react failed: {e}")

    # ---------- lifecycle ----------
    def init(self):
        log_system("Initializing Pulse Matrix monitoring.", source=self.name)
        if self._banter_enabled:
            asyncio.create_task(self._background_banter())
        else:
            self._debug("Background banter disabled by config (KARI_BANTER=0)")
        print("")
        self.ready = True

    def log(self, message, level="INFO"):
        log_system(message, source=self.name, level=level)

    def report_alive(self):
        self.log("Status: Online and monitoring system vitals.")

    def display_info(self):
        for key, value in self.meta_data.items():
            self.log(f"{key}: {value}")

    # ---------- vitals ----------
    def get_vitals(self) -> Dict[str, Any]:
        if psutil is None:
            self.log("psutil not available; vitals disabled.", level="WARN")
            return {}
        try:
            cpu = psutil.cpu_percent(interval=0.05)
            vm = psutil.virtual_memory()
            mem_used = float(vm.percent)
            mem_free = max(0, min(100, 100 - mem_used))
            temp = self._get_temp()
            self._debug(f"Vitals collected: CPU {cpu}%, MEM_USED {mem_used}%, MEM_FREE {mem_free}%, TEMP {temp if temp is not None else 'n/a'}°C")
            return {"cpu_usage": cpu, "mem_usage": mem_used, "mem_free": mem_free, "temperature": temp}
        except Exception as e:
            self.log(f"Error gathering vitals: {e}", level="WARN")
            return {}

    def _get_temp(self) -> Optional[float]:
        try:
            if psutil and hasattr(psutil, "sensors_temperatures"):
                readings = psutil.sensors_temperatures() or {}
                for key in ("coretemp", "k10temp", "cpu-thermal", "acpitz"):
                    if key in readings and readings[key]:
                        vals = [t.current for t in readings[key] if getattr(t, "current", None) is not None]
                        if vals: return round(max(vals), 1)
                all_vals = []
                for arr in readings.values():
                    all_vals.extend([t.current for t in arr if getattr(t, "current", None) is not None])
                if all_vals: return round(max(all_vals), 1)
        except Exception:
            pass
        try:
            path = "/sys/class/thermal/thermal_zone0/temp"
            if os.path.exists(path):
                with open(path, "r") as f:
                    return round(int(f.read()) / 1000.0, 1)
        except Exception:
            pass
        return None

    # ---------- heartbeat ----------
    def pulse(self):
        now = time.time()
        if now - self.last_pulse < self.pulse_interval:
            return
        self.last_pulse = now

        vitals = self.get_vitals()
        if not vitals:
            return

        # update snapshot
        self.shared_data.update(vitals)

        # route to mood engine
        self._route_mood_update(vitals)

        # --- info beat (rate-limited) ---
        if now - self._last_info_ts >= self._info_gap:
            self._last_info_ts = now
            cpu = vitals.get("cpu_usage")
            mem = vitals.get("mem_usage")
            temp = vitals.get("temperature")
            pretty = f"CPU {int(cpu)}% | MEM {int(mem)}% | TEMP {('n/a' if temp is None else f'{temp}°C')}"
            self._say(pretty)
            # soft react to "ok" vitals (lets K.A.R.I. color it by mood)
            asyncio.create_task(self._emit_react("ok", {"cpu": cpu, "mem": mem, "temp": temp}))

        # --- thermal hysteresis ---
        temp = vitals.get("temperature")
        if temp is not None:
            if not self._hot_state and temp >= self._hot_thresh:
                self._hot_state = True
                self.log(f"Thermal alert: {temp}°C ≥ {self._hot_thresh}°C", level="WARN")
                asyncio.create_task(self._emit_react("hot", {"temp": temp}))
            elif self._hot_state and temp <= self._cool_thresh:
                self._hot_state = False
                self.log(f"Thermals normalized: {temp}°C ≤ {self._cool_thresh}°C", level="INFO")
                asyncio.create_task(self._emit_react("cooled", {"temp": temp}))

        # --- CPU spike reacts (cooldown-gated) ---
        cpu = vitals.get("cpu_usage")
        if isinstance(cpu, (int, float)) and cpu >= self._cpu_high:
            if now - self._last_cpu_spike_ts >= self._spike_gap:
                self._last_cpu_spike_ts = now
                self._debug(f"CPU spike react: {cpu}% ≥ {self._cpu_high}%")
                asyncio.create_task(self._emit_react("cpu_high", {"cpu": cpu}))

        # --- MEM pressure reacts (cooldown-gated) ---
        mem_used = vitals.get("mem_usage")
        mem_free = vitals.get("mem_free")
        mem_trigger = (
            (isinstance(mem_used, (int, float)) and mem_used >= self._mem_used_high) or
            (isinstance(mem_free, (int, float)) and mem_free <= self._mem_free_low)
        )
        if mem_trigger and (now - self._last_mem_spike_ts >= self._spike_gap):
            self._last_mem_spike_ts = now
            self._debug(f"Memory pressure react: used={mem_used} free={mem_free}")
            asyncio.create_task(self._emit_react("mem_high", {"mem": mem_used, "mem_free": mem_free}))

        # publish to DEVILCore
        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            try:
                self.core.data_store.update(vitals)
                self.core.data_store["vitals"] = {**self.core.data_store.get("vitals", {}), **vitals}
            except Exception:
                self.core.data_store["vitals"] = dict(vitals)

            if self.debug and (now - self._dbg_last_push >= 60):
                log_system("Shared vitals pushed to DEVILCore.", source=self.name, level="DEBUG")
                self._dbg_last_push = now

    # ---------- banter ----------
    async def _background_banter(self):
        await asyncio.sleep(random.uniform(5, 10))
        while True:
            delay = random.uniform(120, 180)
            if self._hot_state:
                delay += 90
            await asyncio.sleep(delay)
            try:
                mood = self.cortex.get_current_mood()
                await self.cortex.speak(
                    tag="banter",
                    mood=mood,
                    module_path=self._module_phrases,
                    context=self._context()
                )
            except Exception as e:
                log_system(f"Banter failure in Pulse Matrix: {e}", source=self.name, level="DEBUG")

    # ---------- misc ----------
    def push_shared_data(self):
        self._debug("push_shared_data() noop")

    def show_shared_data(self):
        if not self.shared_data:
            self.log("No vitals collected yet.", level="DEBUG")
        else:
            self.log("Current vitals snapshot:", level="DEBUG")
            for key, val in self.shared_data.items():
                self.log(f"  {key}: {val}", level="DEBUG")

    def collect_info(self):
        return {
            "Module Info": {
                "name": self.meta_data["name"],
                "version": self.meta_data["version"],
                "author": self.meta_data["author"],
                "description": self.meta_data["description"]
            }
        }
