# === Decision Engine 🧠 v1.1 ===
# Chooses what K.A.R.I. should do next based on mood, DEFCON, vitals, and shared data.
# Fully async-aware. Supports quiet hours, cooldowns, mood-weighted scores,
# and lightweight periodic info beats to break up chatter.

import os, time, asyncio, random, inspect
from typing import Dict, Any, Optional

from core.logger import log_system

try:
    from internal.memory_cortex.memory_cortex import MemoryCortex
except Exception:
    MemoryCortex = None  # type: ignore

meta_data = {
    "name": "Decision Engine",
    "version": "1.1",
    "author": "Hraustligr + K.A.R.I.",
    "description": "Picks and triggers helpful actions across modules using scores, gates, and cooldowns.",
    "category": "internal",
    "actions": [
        "tick", "evaluate", "plan", "execute",
        "report_alive", "display_info", "set_quiet_hours"
    ],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"}
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["defcon", "mood", "cpu_usage", "mem_usage", "networks"]
}


class DecisionEngine:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, Any] = {}
        self.core = None
        self.ready = False
        self.debug = os.getenv("KARI_DEBUG", "0") == "1"
        self._last_run: Dict[str, float] = {}
        self._last_chat = 0.0

        # Quiet hours (2–6am default)
        self._quiet_hours = {"enabled": False, "start": 2, "end": 6}

        # Policies define what actions she can choose
        self.policies = {
            "tick_seconds": 10,
            "announce_gap": float(os.getenv("KARI_PLAN_ANNOUNCE_GAP", "5")),
            "actions": {
                # --- Net Synapse -------------------------------------------------
                "wifi_recon_dump": {
                    "module": "Net Synapse",
                    "method": "recon_dump",
                    "cooldown": 300,
                    "defcon_max": 3,
                    "score": lambda s: 12 if len(s.get("wifi_seen", []) or []) >= 5 else 5
                },
                "wifi_greet_new_ssid": {
                    "module": None,
                    "method": None,
                    "cooldown": 90,
                    "defcon_max": 5,
                    "score": lambda s: 9 if s.get("last_seen_wifi") else 0,
                    "say": lambda s: f"Hello, {s.get('last_seen_wifi')}."
                },

                # --- Pulse Matrix ------------------------------------------------
                "report_health": {
                    "module": "Pulse Matrix",
                    "method": "get_vitals",
                    "cooldown": 180,
                    "defcon_max": 4,
                    "score": lambda s: (
                        8 if (s.get("cpu_usage", 0) > 70 or s.get("mem_usage", 0) > 80) else 2
                    )
                },

                # --- Mood Engine -------------------------------------------------
                "adjust_mood_from_net": {
                    "module": "Mood Engine",
                    "method": "update_from_network",
                    "cooldown": 60,
                    "defcon_max": 5,
                    "score": lambda s: 6 if s.get("best_signal") else 0,
                    "args": lambda s: {"signal": int(s["best_signal"])}
                },

                # --- VoiceBox ----------------------------------------------------
                "banter_if_idle": {
                    "module": "VoiceBox",
                    "method": "banter",
                    "cooldown": 120,
                    "defcon_max": 5,
                    "score": lambda s: (
                        6 if (time.time() - s.get("last_user_interaction_ts", 0) > 180) else 0
                    )
                },

                # --- NEW: periodic info beats (voice-only text) ------------------
                "periodic_wifi_summary": {
                    "module": None,
                    "method": None,
                    "cooldown": 120,
                    "defcon_max": 5,
                    "score": lambda s: 3,  # low priority, just filler facts
                    "say": lambda s: (
                        f"{len(s.get('networks', []) or [])} networks in range; "
                        f"strongest {s.get('best_signal') if s.get('best_signal') is not None else 'n/a'}%."
                    )
                },
                "periodic_vitals_summary": {
                    "module": None,
                    "method": None,
                    "cooldown": 120,
                    "defcon_max": 5,
                    "score": lambda s: 3,
                    "say": lambda s: (
                        f"CPU {int(s.get('cpu_usage', 0))}% | "
                        f"MEM {int(s.get('mem_usage', 0))}% | "
                        f"TEMP {s.get('temperature', 'n/a')}°C."
                    )
                },
            }
        }

    # ---------- lifecycle ----------
    def init(self):
        self.ready = True
        log_system("Decision Engine initialized.", source=self.name)
        try:
            asyncio.create_task(self._loop())
        except RuntimeError:
            # No running loop yet; core may call tick() via pulse()
            pass

    def report_alive(self):
        log_system("Status: Online and operational.", source=self.name)

    def display_info(self):
        for k, v in self.meta_data.items():
            log_system(f"{k}: {v}", source=self.name)

    def set_quiet_hours(self, enabled: bool, start: int = 2, end: int = 6):
        self._quiet_hours = {"enabled": enabled, "start": start % 24, "end": end % 24}
        log_system(f"Quiet hours set: {self._quiet_hours}", source=self.name)

    # ---------- helpers ----------
    def _voice(self):
        try:
            if self.core and self.core.voice and getattr(self.core.voice, "ready", False):
                from core.logger import log_kari
                return log_kari
        except Exception:
            pass
        return None

    def _say(self, text: str):
        now = time.time()
        if now - self._last_chat < self.policies["announce_gap"]:
            return
        v = self._voice()
        if v:
            v(text, module_name="K.A.R.I")
        self._last_chat = now

    def _record_decision(self, action_name: str, snapshot: Dict[str, Any], outcome: str):
        """
        Forward decisions to Sanity Relay (if present) for journaling/analysis.
        """
        try:
            if self.core and hasattr(self.core, "modules"):
                sr = self.core.modules.get("Sanity Relay")
                if sr and hasattr(sr, "record_decision"):
                    sr.record_decision(context=action_name, input_data=snapshot, outcome=outcome)
        except Exception:
            pass

    def _get_shared(self) -> Dict[str, Any]:
        s: Dict[str, Any] = {}
        if self.core and hasattr(self.core, "data_store") and self.core.data_store:
            s.update(self.core.data_store)

        # DEFCON + mood inference
        try:
            s["defcon"] = s.get("defcon") or (
                self.core.get_defcon_level() if hasattr(self.core, "get_defcon_level") else 4
            )
        except Exception:
            s["defcon"] = 4

        s["mood"] = "neutral"
        try:
            mem = self.core.memory if self.core and hasattr(self.core, "memory") else (MemoryCortex() if MemoryCortex else None)
            if mem:
                s["mood"] = mem.get_current_mood() or "neutral"
        except Exception:
            pass

        # network signals
        try:
            nets = s.get("networks") or []
            signals = [n.get("signal") for n in nets if isinstance(n, dict) and n.get("signal") is not None]
            s["best_signal"] = max(signals) if signals else None
            s["wifi_seen"] = [n.get("ssid") for n in nets if isinstance(n, dict) and n.get("ssid")]
        except Exception:
            s["best_signal"] = None
            s["wifi_seen"] = []

        # vitals defaults if missing (keeps formatters safe)
        s.setdefault("cpu_usage", 0)
        s.setdefault("mem_usage", 0)
        s.setdefault("temperature", s.get("temp", None))
        return s

    def _quiet_hours_block(self) -> bool:
        if not self._quiet_hours["enabled"]:
            return False
        lt = time.localtime().tm_hour
        a, b = self._quiet_hours["start"], self._quiet_hours["end"]
        if a < b:
            return a <= lt < b
        return not (b <= lt < a)

    # ---------- main loop ----------
    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(self.policies["tick_seconds"])
                self.tick()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log_system(f"Decision loop error: {e}", source=self.name, level="WARN")

    def pulse(self):
        # Let pulse trigger tick opportunistically without tight coupling
        if int(time.time()) % self.policies["tick_seconds"] == 0:
            self.tick()

    def tick(self):
        if not self.ready or self._quiet_hours_block():
            return
        s = self._get_shared()
        plan = self.plan(s)
        if plan:
            self.execute(plan, s)

    # ---------- planner ----------
    def evaluate(self, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        s = snapshot or self._get_shared()
        scores: Dict[str, float] = {}
        mood = s.get("mood", "neutral")
        defcon = s.get("defcon", 4)

        for name, cfg in self.policies["actions"].items():
            if defcon > cfg.get("defcon_max", 5):
                continue
            last = self._last_run.get(name, 0.0)
            if time.time() - last < cfg.get("cooldown", 60):
                continue
            fn = cfg.get("score")
            try:
                base_score = float(fn(s)) if callable(fn) else 0.0
            except Exception:
                base_score = 0.0

            # Mood bias multipliers
            mood_bias = {
                "happy": 1.2,
                "excited": 1.3,
                "angry": 0.8,
                "sad": 0.7,
                "anxious": 0.9,
                "glitched": 0.6,
                "neutral": 1.0,
            }
            final_score = base_score * mood_bias.get(mood, 1.0)

            if final_score > 0:
                scores[name] = final_score
        return scores

    def plan(self, snapshot: Optional[Dict[str, Any]] = None) -> Optional[str]:
        scores = self.evaluate(snapshot)
        if not scores:
            return None
        best = max(scores.items(), key=lambda kv: (kv[1], random.random()))[0]
        if self.debug:
            log_system(f"Plan → {best} (scores={scores})", source=self.name, level="DEBUG")
        return best

    # ---------- async-safe execution ----------
    def _schedule(self, coro):
        try:
            asyncio.get_running_loop()
            asyncio.create_task(coro)
            return True
        except RuntimeError:
            try:
                asyncio.run(coro)
                return True
            except RuntimeError:
                return False

    def execute(self, action_name: str, snapshot: Optional[Dict[str, Any]] = None):
        cfg = self.policies["actions"].get(action_name)
        if not cfg:
            return
        mod_name = cfg.get("module")
        method = cfg.get("method")
        snap = snapshot or self._get_shared()

        # voice-only action
        if not mod_name and cfg.get("say"):
            try:
                text_fn = cfg["say"]
                msg = text_fn(snap)
                self._say(msg)
                self._last_run[action_name] = time.time()
                if self.debug:
                    log_system(f"Executed voice-only: {action_name} → “{msg}”", source=self.name, level="DEBUG")
                self._record_decision(action_name, snap, outcome="voice_only")
            except Exception as e:
                log_system(f"say failed: {e}", source=self.name, level="DEBUG")
            return

        try:
            if not self.core or not hasattr(self.core, "modules"):
                return
            target = self.core.modules.get(mod_name)
            if not target or not hasattr(target, method):
                return

            fn = getattr(target, method)
            args, kwargs = [], {}
            if callable(cfg.get("args")):
                a = cfg["args"](snap)
                if isinstance(a, dict):
                    kwargs = a
                elif isinstance(a, (list, tuple)):
                    args = list(a)

            if inspect.iscoroutinefunction(fn):
                if self._schedule(fn(*args, **kwargs)):
                    self._last_run[action_name] = time.time()
                    self._record_decision(action_name, snap, outcome=f"{mod_name}.{method} (awaitable)")
                return

            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                if self._schedule(result):
                    self._last_run[action_name] = time.time()
                    self._record_decision(action_name, snap, outcome=f"{mod_name}.{method} (awaited)")
                return

            self._last_run[action_name] = time.time()
            if self.debug:
                log_system(f"Executed {action_name} → {mod_name}.{method}", source=self.name, level="DEBUG")
            self._record_decision(action_name, snap, outcome=f"{mod_name}.{method} (sync)")

        except Exception as e:
            log_system(f"execute error: {e}", source=self.name, level="WARN")
