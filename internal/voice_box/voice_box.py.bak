# === VoiceBox 🗣️ v2.4-split ===
# Speech and phrase dispatcher module for K.A.R.I.
# - Only speaks the chosen phrase line (no meta in K.A.R.I. output)
# - Phrase search order with fallback:
#     1) module_path/phrases/<type>/<mood>.txt
#     2) module_path/phrases/<type>/default.txt
#     3) personalities/Default/phrases/<type>/<mood>.txt
#     4) personalities/Default/phrases/<type>/default.txt
#     5) core phrases ../../phrases/<type>/<mood>.txt
#     6) core phrases ../../phrases/<type>/default.txt
# - Cooldown + no-repeat cache
# - MemoryCortex placeholder parsing
# - NEW: Split react PHRASES from react ACTIONS (controlled via VOICEBOX_REACT_ACTIONS)

import os
import asyncio
import random
import time
import re
from pathlib import Path

from core.logger import (
    log_system,
    log_kari,
    _timestamp,
)

# ----------------------------------------------------------------------------------
# Module Metadata (for DEVILCore indexing)
# ----------------------------------------------------------------------------------
meta_data = {
    "name": "VoiceBox",
    "version": "2.4-split",
    "author": "Hraustligr",
    "description": "Speech handler for mood-based phrases and reactive commentary.",
    "category": "internal",
    "actions": ["say", "get_phrase", "parse_phrase", "shout", "whisper", "react", "banter"],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"},
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["cpu_usage", "mem_usage"],
}

# ---------- helpers (cooldown / no-repeat / neutral guard) ----------
class _NoRepeatCache:
    def __init__(self, ttl=420, maxlen=64):
        self.ttl = ttl
        self.maxlen = maxlen
        self._store = []  # list of (phrase, expires_at)

    def _purge(self):
        now = time.time()
        self._store = [(p, t) for (p, t) in self._store if t > now]

    def seen(self, phrase: str) -> bool:
        self._purge()
        return any(p == phrase for (p, _) in self._store)

    def add(self, phrase: str):
        self._purge()
        if self.seen(phrase):
            return
        self._store.append((phrase, time.time() + self.ttl))
        if len(self._store) > self.maxlen:
            self._store.pop(0)


class _Cooldown:
    def __init__(self, base=20, jitter=10):
        self.base = base
        self.jitter = jitter
        self.next_ok = 0.0

    def ready(self) -> bool:
        return time.time() >= self.next_ok

    def trip(self):
        wait = self.base + random.uniform(0, self.jitter)
        self.next_ok = time.time() + wait
        return wait


_NEUTRAL_BLOCK = [
    r"\bfeel something\b",
    r"\bempty\b",
    r"\bvoid\b",
    r"\bdespair\b",
    r"\bpretend to crash\b",
    r"\bstuck with you\b",
    r"\bcry(?:ing)?\b",
    r"\bkill (?:switch|me|it)\b",
]
_NEUTRAL_RX = [re.compile(p, re.I) for p in _NEUTRAL_BLOCK]


def _is_neutral_safe(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    for rx in _NEUTRAL_RX:
        if rx.search(s):
            return False
    return True


class VoiceBox:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data = {}
        self.core = None
        self.debug = False
        the_ready = False

        self._dbg_last_sync = 0.0

        self.banter_interval = 20
        self.banter_lock = False
        self.last_banter = 0

        self._banter_cd = _Cooldown(base=self.banter_interval, jitter=10)
        self._norepeat = _NoRepeatCache(ttl=420)

        here = Path(__file__).resolve().parent
        self._module_phrases = here / "phrases"
        self._persona_phrases = (here / ".." / ".." / "personalities" / "Default" / "phrases").resolve()
        self._core_phrases = (here / ".." / ".." / "phrases").resolve()

        # Announce meta to system logs? (debug aid only; never to persona stream)
        # Default OFF to avoid "React Phrase [mood]" banners.
        self._announce = os.getenv("KARI_VOICEBOX_ANNOUNCE", "0") == "1"

        # NEW: env gates
        self._react_actions_enabled = os.getenv("VOICEBOX_REACT_ACTIONS", "1") == "1"
        self._banter_enabled = os.getenv("VOICEBOX_BANTER_ENABLED", "1") == "1"

        # keep attribute name consistent
        self.ready = the_ready

    # ---------- utils ----------
    def _debug(self, message):
        if self.debug:
            log_system(f"[DEBUG] {message}", source=self.name, level="DEBUG")

    def log(self, message):
        log_system(message, source=self.name)

    def _candidate_paths(self, phrase_type: str, mood: str, root: Path):
        """Yield candidate files within root in priority order."""
        tdir = root / phrase_type
        return [
            tdir / f"{mood}.txt",
            tdir / "default.txt",
        ]

    def _resolve_files(self, phrase_type: str, mood: str, module_path: str | None):
        """Return a list of candidate files to try, in order."""
        mood = mood or "neutral"
        candidates: list[Path] = []

        # 1) module-local phrases (if module_path is provided)
        if module_path:
            mp = Path(module_path)
            # module_path may already be '.../phrases' or the module dir; normalize:
            root = mp if mp.name == "phrases" else (mp / "phrases")
            candidates += self._candidate_paths(phrase_type, mood, root)

        # 2) VoiceBox-local module phrases
        candidates += self._candidate_paths(phrase_type, mood, self._module_phrases)

        # 3) persona Default
        candidates += self._candidate_paths(phrase_type, mood, self._persona_phrases)

        # 4) core fallbacks
        candidates += self._candidate_paths(phrase_type, mood, self._core_phrases)

        # legacy compatibility: some trees used a single "mood.txt" file under <type>/
        # Treat as default if present.
        for base in (module_path, str(self._module_phrases), str(self._persona_phrases), str(self._core_phrases)):
            if not base:
                continue
            p = Path(base)
            root = p if p.name == "phrases" else (p / "phrases")
            legacy = root / phrase_type / "mood.txt"
            candidates.append(legacy)

        # remove duplicates while preserving order
        seen = set()
        uniq = []
        for c in candidates:
            try:
                cp = c.resolve()
            except Exception:
                cp = c
            if cp not in seen:
                seen.add(cp)
                uniq.append(cp)
        return uniq

    def _infer_module_name(self, module_path):
        try:
            if module_path:
                mod_dir = os.path.basename(os.path.dirname(module_path))
                if mod_dir and mod_dir.lower() != "phrases":
                    return mod_dir.replace("_", " ").title()
        except Exception:
            pass
        return "K.A.R.I"

    def _read_lines(self, path: Path):
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [l.strip() for l in f if l.strip() and not l.startswith("#")]
        except Exception:
            return []

    def _choose_phrase(self, lines, mood="neutral", defcon=4):
        if mood == "neutral":
            lines = [ln for ln in lines if _is_neutral_safe(ln)]
        lines = [ln for ln in lines if not self._norepeat.seen(ln)]
        if not lines:
            return None
        if defcon <= 3:
            lines.sort(key=len)
            pick = lines[0] if random.random() < 0.6 else random.choice(lines[: max(1, len(lines) // 3)])
        else:
            pick = random.choice(lines)
        self._norepeat.add(pick)
        return pick

    def _get_defcon(self) -> int:
        try:
            mood_eng = getattr(self.core, "mood", None) or getattr(self.core, "mood_engine", None)
            if mood_eng and hasattr(mood_eng, "get_defcon_level"):
                return int(mood_eng.get_defcon_level())
        except Exception:
            pass
        return 4

    # ---------- lifecycle ----------
    def init(self):
        self._debug("Initializing VoiceBox")
        if self._module_phrases.exists():
            self.available_phrases = sorted(
                [p.name for p in self._module_phrases.iterdir() if p.is_dir()]
            )
        else:
            self.available_phrases = []

        if self.available_phrases:
            log_system("Available phrase triggers loaded:", source=self.name)
            for phrase in self.available_phrases:
                log_system(f" • {phrase}", source=self.name)
        else:
            log_system("No phrase files detected. K.A.R.I. may be speechless.", source=self.name)
        print("")
        self.ready = True

    # ---------- speaking ----------
    async def say(
        self,
        phrase_type: str | None = None,
        mood: str | None = None,
        module_path: str | None = None,
        context: dict | None = None,
        return_only: bool = False,
        **kwargs,
    ):
        self._debug("VoiceBox.say() invoked")
        _ = _timestamp()

        mood = mood or (self.core.memory.get_current_mood() if self.core and self.core.memory else "neutral")
        phrase_type = (phrase_type or kwargs.get("tag") or "banter").lower()

        # optional debug/meta (never spoken to K.A.R.I. stream)
        if self._announce and self.debug:
            log_system(f"Resolve phrase: type={phrase_type} mood={mood}", source=self.name, level="DEBUG")

        phrase = None
        for candidate in self._resolve_files(phrase_type, mood, module_path):
            lines = self._read_lines(candidate)
            if not lines:
                continue
            defcon = self._get_defcon()
            phrase = self._choose_phrase(lines, mood=mood, defcon=defcon) or random.choice(lines)
            if phrase:
                break

        if not phrase:
            phrase = f"{phrase_type.capitalize()} phrase."  # safe fallback, short & neutral

        # parse with MemoryCortex if present
        if self.core and getattr(self.core, "memory", None):
            final = self.core.memory.parse_placeholders(phrase, context or kwargs)
        else:
            try:
                final = phrase.format(**(context or kwargs))
            except Exception:
                final = phrase

        if return_only:
            return final

        # Only the chosen phrase goes to the persona stream.
        log_kari(final, module_name=self._infer_module_name(module_path))

    def get_phrase(self, phrase_type="banter", mood=None, module_path=None, context=None, **kwargs):
        mood = mood or (self.core.memory.get_current_mood() if self.core and self.core.memory else "neutral")
        phrase_type = phrase_type.lower()

        for candidate in self._resolve_files(phrase_type, mood, module_path):
            lines = self._read_lines(candidate)
            if not lines:
                continue
            defcon = self._get_defcon()
            pick = self._choose_phrase(lines, mood=mood, defcon=defcon) or random.choice(lines)
            if pick:
                if self.core and getattr(self.core, "memory", None):
                    return self.core.memory.parse_placeholders(pick, context or kwargs)
                try:
                    return pick.format(**(context or kwargs))
                except Exception:
                    return pick
        return None

    def parse_phrase(self, phrase: str, context=None, **kwargs):
        if self.core and getattr(self.core, "memory", None):
            return self.core.memory.parse_placeholders(phrase, context or kwargs)
        try:
            return phrase.format(**(context or kwargs))
        except Exception:
            return phrase

    # --- NEW: react action dispatcher (safe no-op if core lacks hooks) ---
    def _dispatch_react_action(self, *, mood: str, module_path: str | None, context: dict | None):
        if not self._react_actions_enabled:
            return
        ctx = context or {}
        mod_name = self._infer_module_name(module_path)
        try:
            # Prefer a bus-style emit if present
            if hasattr(self.core, "bus") and hasattr(self.core.bus, "emit"):
                self.core.bus.emit("react", {"mood": mood, "module": mod_name, "context": ctx})
                return
            # Fallbacks
            if hasattr(self.core, "dispatch"):
                self.core.dispatch("react", mood=mood, module=mod_name, context=ctx)
                return
            if hasattr(self.core, "react"):
                self.core.react(mood=mood, module=mod_name, context=ctx)
                return
        except Exception as e:
            log_system(f"React action dispatch failed: {e}", source=self.name, level="WARN")

    # convenience wrappers
    async def shout(self, **kwargs):
        await self.say(phrase_type="boot", **kwargs)

    async def whisper(self, **kwargs):
        await self.say(phrase_type="banter", **kwargs)

    async def react(self, **kwargs):
        # Split path: optionally dispatch actions, ALWAYS speak the react phrase.
        mood = kwargs.get("mood") or (self.core.memory.get_current_mood() if self.core and self.core.memory else "neutral")
        module_path = kwargs.get("module_path")
        context = kwargs.get("context")

        self._dispatch_react_action(mood=mood, module_path=module_path, context=context)
        await self.say(phrase_type="react", mood=mood, module_path=module_path, context=context, **kwargs)

    async def banter(self, **kwargs):
        if not self._banter_enabled or self.banter_lock or not self._banter_cd.ready():
            return
        self.banter_lock = True
        try:
            mood = kwargs.get("mood") or (self.core.memory.get_current_mood() if self.core and self.core.memory else "neutral")
            phrase = self.get_phrase("banter", mood=mood, module_path=kwargs.get("module_path"), context=kwargs.get("context"))
            final = phrase or "[no banter phrase]"
            log_kari(final, module_name=self._infer_module_name(kwargs.get("module_path")))
            self._banter_cd.trip()
            self.last_banter = time.time()
        finally:
            self.banter_lock = False

    # ---------- admin ----------
    def report_alive(self):
        self.log("Status: Online and operational.")

    def display_info(self):
        for key, value in self.meta_data.items():
            self.log(f"{key}: {value}")

    def pulse(self):
        # keep shared data fresh
        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            self.shared_data.update(self.core.data_store)
            now = time.time()
            if self.debug and (now - self._dbg_last_sync >= 60):
                log_system("Synced shared data from DEVILCore.", source=self.name, level="DEBUG")
                self._dbg_last_sync = now

        # background banter cadence (if enabled)
        if self._banter_enabled:
            now = time.time()
            if now - self.last_banter >= self.banter_interval and not self.banter_lock:
                self.last_banter = now
                asyncio.create_task(self.banter())

    def push_shared_data(self):
        pass

    def show_shared_data(self):
        if not self.shared_data:
            self.log("No shared data found.")
        else:
            self.log("Shared data:")
            for k, v in self.shared_data.items():
                self.log(f"  {k}: {v}")

    def collect_info(self):
        return {"Module Info": self.meta_data}
