# === Sanity Relay 🌀 v1.7 ===
# Reflective AI conscience: predicts mood, evaluates integrity, nudges state, and chatters banter.

import os, datetime, asyncio, time, random
from core.logger import log_system
from internal.memory_cortex.memory_cortex import MemoryCortex
from internal.sanity_relay.models.mood_model import FakeMoodModel

meta_data = {
    "name": "Sanity Relay",
    "version": "1.7",
    "author": "Hraustligr",
    "description": "K.A.R.I.'s reflective sanity and ethical inference core. Predicts mood, monitors behavior, and influences internal state.",
    "category": "internal",
    "actions": [
        "predict", "evaluate_self", "get_status_report",
        "generate_conscience_banter", "influence_mood", "record_decision"
    ],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"},
        {"name": "Show Shared Data", "function": "show_shared_data"}
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync", "sentience"],
    "resources": ["cpu_usage", "mem_usage", "interaction_count"]
}

class SanityRelay:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data = {}
        self.core = None
        self.models = {}
        self.ready = False
        self.debug = False
        self._cortex = None
        self._module_phrases = os.path.join(os.path.dirname(__file__), "phrases")

        self._dbg_last_sync = 0.0

        self._influence_enabled = os.getenv("KARI_SANITY_INFLUENCE", "1") == "1"
        self._influence_min = int(os.getenv("KARI_SANITY_INFLUENCE_MIN", "120"))
        self._influence_max = max(
            int(os.getenv("KARI_SANITY_INFLUENCE_MAX", "240")), self._influence_min
        )
        self._influence_next_ts = 0.0
        self._last_influence = None

    # ---------- lifecycle ----------
    def init(self):
        self._debug("SanityRelay.init()")
        self.available_phrases = self._load_available_phrases()
        if self.available_phrases:
            log_system("Available phrase triggers loaded:", source=self.name)
            for p in sorted(self.available_phrases):
                log_system(f" • {p}", source=self.name)
        else:
            log_system("No phrase files detected.", source=self.name)

        self.load_models()

        if os.getenv("KARI_BANTER", "1") == "1":
            asyncio.create_task(self._background_banter())
        else:
            self._debug("Background banter disabled (KARI_BANTER=0)")

        self._schedule_next_influence()
        self.ready = True

    def _memory(self) -> MemoryCortex:
        if self.core and getattr(self.core, "memory", None):
            return self.core.memory
        if self._cortex is None:
            self._cortex = MemoryCortex()
        return self._cortex

    # ---------- utils ----------
    def _debug(self, msg):
        if self.debug: log_system(f"[DEBUG] {msg}", source=self.name, level="DEBUG")

    def log(self, msg, level="INFO"):
        log_system(msg, source=self.name, level=level)

    def _load_available_phrases(self):
        if not os.path.exists(self._module_phrases): return []
        return [d for d in os.listdir(self._module_phrases)
                if os.path.isdir(os.path.join(self._module_phrases,d))]

    def _context(self):
        ctx = {}
        try:
            if self.core and hasattr(self.core,"data_store"):
                store = self.core.data_store or {}
                ctx.update(store)
                vitals = store.get("vitals",{}) or {}
                ctx.update(vitals)
                ctx.setdefault("ssid", store.get("last_seen_wifi","—"))
                ctx.setdefault("cpu", vitals.get("cpu_usage"))
                ctx.setdefault("mem", vitals.get("mem_usage"))
                ctx.setdefault("temp", vitals.get("temperature"))
                ctx.setdefault("tick", getattr(self.core,"tick_count",0))
        except Exception: pass
        return ctx

    # ---------- models ----------
    def load_models(self):
        models_path = os.path.join(os.path.dirname(__file__), "models")
        model_file = os.path.join(models_path, "mood_model.joblib")
        self.models["mood_model"] = FakeMoodModel()
        if os.path.exists(model_file):
            try:
                from joblib import load
                self.models["mood_model"] = load(model_file)
                self.log("✓ Mood model loaded.")
            except Exception as e:
                self._debug(f"Failed to load model: {e}")
                self.log("Using fallback mood model.")
        else:
            self._debug("No saved mood_model found; fallback active.")

    # ---------- core hooks ----------
    def pulse(self):
        if self.core and hasattr(self.core,"data_store"):
            self.shared_data.update(self.core.data_store)
            now=time.time()
            if self.debug and (now-self._dbg_last_sync>=60):
                log_system("Synced shared data from DEVILCore.",source=self.name,level="DEBUG")
                self._dbg_last_sync=now
        self._maybe_influence()

    def report_alive(self): self.log("Status: Online and operational.")
    def display_info(self): [self.log(f"{k}: {v}") for k,v in self.meta_data.items()]
    def show_shared_data(self):
        if not self.shared_data: self._debug("No shared data found.")
        else:
            self._debug("Shared data dump:")
            for k,v in self.shared_data.items(): self._debug(f" {k}: {v}")

    def collect_info(self):
        return {"Module Info": {
            "name": self.meta_data["name"],
            "version": self.meta_data["version"],
            "author": self.meta_data["author"],
            "description": self.meta_data["description"]
        }}

    # ---------- actions ----------
    def predict(self):
        model=self.models.get("mood_model")
        if not model: return None
        feats=[ self.shared_data.get("cpu_usage",0),
                self.shared_data.get("mem_usage",0),
                self.shared_data.get("interaction_count",0)]
        try:
            pred=model.predict([feats])[0]
            self.log(f"Predicted mood: {pred}")
            return pred
        except Exception as e:
            self._debug(f"Prediction failed: {e}")
            return None

    def evaluate_self(self):
        ts=datetime.datetime.now().isoformat()
        self.log("Evaluating system integrity...")
        self.log(f"Self-check timestamp: {ts}")

    def influence_mood(self,force=False):
        pred=self.predict()
        if not pred: return
        mem=self._memory()
        cur=mem.get_current_mood()
        if pred!=cur or force:
            self.log(f"Sanity Relay mood shift: {cur} → {pred}")
            asyncio.create_task(mem.set_current_mood(pred))
        # if MoodEngine attached, also nudge scores
        if self.core and getattr(self.core,"mood",None):
            try: self.core.mood.adjust_mood(pred,+3)
            except Exception: pass
        self._last_influence=time.time()

    def record_decision(self,context:str,input_data:dict,outcome:str):
        mem=self._memory()
        mem.log_event("SanityRelay","DECISION",f"{context}: {outcome}")

    async def generate_conscience_banter(self):
        mood=self._memory().get_current_mood()
        await self._memory().speak(
            tag="banter", mood=mood, module_path=self._module_phrases,
            context=self._context()
        )

    def get_status_report(self):
        rpt={"models_loaded":list(self.models.keys()),
             "shared_keys":list(self.shared_data.keys()),
             "ready":self.ready,
             "last_influence":self._last_influence,
             "next_influence":self._influence_next_ts}
        self.log("Sanity Relay Status:")
        for k,v in rpt.items(): self.log(f" {k}: {v}")
        return rpt

    # ---------- background ----------
    async def _background_banter(self):
        await asyncio.sleep(10)
        while True:
            await asyncio.sleep(random.uniform(120,180))
            try: await self.generate_conscience_banter()
            except Exception as e: self._debug(f"Banter fail: {e}")

    # ---------- autonomous influence ----------
    def _schedule_next_influence(self):
        if not self._influence_enabled:
            self._influence_next_ts=float("inf"); return
        jitter=random.uniform(self._influence_min,self._influence_max)
        self._influence_next_ts=time.time()+jitter
        self._debug(f"Next influence in ~{int(jitter)}s")

    def _maybe_influence(self):
        if not self._influence_enabled: return
        now=time.time()
        if now>=self._influence_next_ts:
            try: self.influence_mood()
            finally: self._schedule_next_influence()
