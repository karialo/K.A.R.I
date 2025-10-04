# === K.A.R.I. Memory Cortex 🧠 v1.6.3 ===
# Persistent memory engine for logs, mood, diary, events, and dynamic phrase interpolation.
# - No banner spam: logs only the phrase text (no "React Phrase [mood]" headers)
# - Compatible with VoiceBox v2.4-split (react phrase/action split)
# - Safe neutral filter + *resilient* placeholder parser with sane defaults

import sqlite3
import random
import os
import re
import asyncio
from datetime import datetime
from typing import Any, Dict

from core.logger import log_system, log_kari_async

# ----------------------------------------------------------------------------------
# Metadata Declaration
# ----------------------------------------------------------------------------------
meta_data = {
    "name": "Memory Cortex",
    "version": "1.6.3",  # safer placeholder parsing + defaults; minor cleanups
    "author": "Hraustligr",
    "description": "Persistent memory engine for logs, mood, diary, events, and dynamic phrase interpolation.",
    "category": "internal",
    "actions": [
        'remember', 'recall', 'forget', 'forget_all_memory',
        'log_event', 'get_logs', 'clear_logs',
        'write_diary', 'get_diary', 'delete_diary_entry',
        'log_event_type', 'get_events', 'delete_event',
        'get_current_mood', 'set_current_mood',
        'format_phrase', 'speak', 'react', 'get_phrase',
        'parse_placeholders', 'close'
    ],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"}
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": []
}

# --- tiny neutral guard (mirrors VoiceBox’s vibe) -------------------------------
_NEUTRAL_BLOCK = [
    r"\bfeel something\b", r"\bempty\b", r"\bvoid\b", r"\bdespair\b",
    r"\bpretend to crash\b", r"\bstuck with you\b", r"\bcry(?:ing)?\b",
    r"\bkill (?:switch|me|it)\b"
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

# --- phrase safety defaults -----------------------------------------------------
# These are used whenever a placeholder is missing or resolves to None/"" *and*
# the phrase did not provide an explicit {key|default}.
_SAFE_DEFAULTS: Dict[str, Any] = {
    "networks": 0,
    "networks_count": 0,
    "total_ssids": 0,
    "wifi_count": 0,
    "active_ssid": "—",
    "ssid": "—",
    "best_ssid": "—",
    "best_signal": "n/a",
    "signal": "n/a",
    "best_chan": "?",
    "chan": "?",
    "cpu_usage": "n/a",
    "mem_usage": "n/a",
    "cpu": "n/a",
    "mem": "n/a",
    "temperature": "n/a",
    "temp": "n/a",
    "tick": 0,
    "boot_time": "—",
    "wifi_seen": [],
    "wifi_seen_str": "",
}

def _coerce_for_phrase(v: Any) -> Any:
    if v is None:
        return "—"
    if isinstance(v, float):
        # trim float noise for casual lines
        return f"{v:.1f}"
    return v


class MemoryCortex:
    def __init__(self, db_path="kari_memory.db"):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, Any] = {}
        self.core = None
        self.db_path = db_path
        self.ready = False

        # verbosity toggles (quiet by default)
        self.debug = os.getenv("KARI_DEBUG", "0") == "1"
        self.trace = os.getenv("KARI_TRACE", "0") == "1"
        # optional internal banter (off by default to avoid duplicate chatter)
        self._banter_enabled = os.getenv("KARI_MEMORY_BANTER", "0") == "1"

        # phrase roots
        here = os.path.dirname(__file__)
        self._module_phrases = os.path.join(here, "phrases")
        self._persona_phrases = os.path.normpath(os.path.join(here, "..", "..", "personalities", "Default", "phrases"))
        self._core_phrases   = os.path.normpath(os.path.join(here, "..", "..", "phrases"))

        # connect storage
        self._connect()
        self._create_tables()
        if not os.access(self.db_path, os.W_OK):
            self.log("Cannot write to DB file: " + self.db_path, level="ERROR")
            raise PermissionError(f"Cannot write to {self.db_path}")
        self.log("Using DB path: " + self.db_path)
        self.log("Memory Cortex initialized and ready.")
        self.ready = True

    # ---------- lifecycle ----------
    def _dbg(self, msg):
        if self.debug:
            log_system(f"[DEBUG] {msg}", source=self.name, level="DEBUG")

    def _trc(self, msg):
        if self.trace:
            log_system(f"[TRACE] {msg}", source=self.name, level="DEBUG")

    async def initialize(self):
        # only run MC’s own banter if explicitly enabled
        if self._banter_enabled:
            asyncio.create_task(self._background_banter())

    async def _background_banter(self):
        await asyncio.sleep(random.uniform(5, 10))
        while True:
            delay = random.uniform(120, 180)
            await asyncio.sleep(delay)
            try:
                mood = self.get_current_mood()
                await self.speak(tag="banter", mood=mood, module_path=self._module_phrases)
            except Exception as e:
                self.log_event("Memory Cortex", "ERROR", f"Banter failed: {e}")

    # ---------- storage ----------
    def _connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def _create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, timestamp TEXT, source TEXT, level TEXT, message TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS diary (id INTEGER PRIMARY KEY, timestamp TEXT, mood TEXT, entry TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, value TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, timestamp TEXT, event_type TEXT, data TEXT)''')
        self.conn.commit()

    def _now(self):
        return datetime.utcnow().isoformat()

    # ---------- logging ----------
    def log(self, message, level="INFO"):
        self.log_event("Memory Cortex", level, message)

    def log_event(self, source, level, message):
        try:
            self.cursor.execute(
                '''INSERT INTO logs (timestamp, source, level, message) VALUES (?, ?, ?, ?)''',
                (self._now(), source, level.upper(), message)
            )
            self.conn.commit()
        except Exception as e:
            # only console-print on failure to persist
            print(f"[Memory Cortex] Logging failed: {e}")

    def get_logs(self, log_type=None, limit=100):
        query = (
            '''SELECT * FROM logs WHERE level = ? ORDER BY id DESC LIMIT ?'''
            if log_type else
            '''SELECT * FROM logs ORDER BY id DESC LIMIT ?'''
        )
        self.cursor.execute(query, (log_type.upper(), limit) if log_type else (limit,))
        return self.cursor.fetchall()

    def clear_logs(self):
        self.cursor.execute('DELETE FROM logs')
        self.conn.commit()

    # ---------- key-value memory ----------
    def remember(self, key, value):
        self.cursor.execute(
            '''INSERT INTO memory (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
            (key, value)
        )
        self.conn.commit()

    def recall(self, key):
        self.cursor.execute('SELECT value FROM memory WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def forget(self, key):
        self.cursor.execute('DELETE FROM memory WHERE key = ?', (key,))
        self.conn.commit()

    def forget_all_memory(self):
        self.cursor.execute('DELETE FROM memory')
        self.conn.commit()

    # ---------- mood ----------
    def get_current_mood(self):
        mood = self.recall("current_mood")
        if mood is None:
            mood = "neutral"
            self.remember("current_mood", mood)
            self._trc("No stored mood; defaulting to 'neutral'.")
        return mood

    async def set_current_mood(self, mood):
        self.remember("current_mood", mood)
        # If DEVILCore attached a voice, let her react softly
        try:
            if self.core and getattr(self.core, "voice", None):
                await self.core.voice.say(
                    phrase_type="react",
                    mood=mood,
                    module_path=self._module_phrases,
                    context={"mood": mood, "module_name": "Memory Cortex"}
                )
        except Exception:
            pass

    # ---------- diary ----------
    def write_diary(self, mood, entry):
        self.cursor.execute(
            '''INSERT INTO diary (timestamp, mood, entry) VALUES (?, ?, ?)''',
            (self._now(), mood, entry)
        )
        self.conn.commit()

    def get_diary(self, limit=50):
        self.cursor.execute('''SELECT * FROM diary ORDER BY id DESC LIMIT ?''', (limit,))
        return self.cursor.fetchall()

    def delete_diary_entry(self, entry_id):
        self.cursor.execute('DELETE FROM diary WHERE id = ?', (entry_id,))
        self.conn.commit()

    # ---------- events API ----------
    def log_event_type(self, event_type: str, data: str):
        """Store a typed event (free-form data string or JSON-serialized payload)."""
        try:
            self.cursor.execute(
                '''INSERT INTO events (timestamp, event_type, data) VALUES (?, ?, ?)''',
                (self._now(), event_type, data)
            )
            self.conn.commit()
        except Exception as e:
            self.log(f"Event log failed: {e}", level="WARN")

    def get_events(self, limit: int = 100, event_type: str | None = None):
        if event_type:
            self.cursor.execute(
                '''SELECT * FROM events WHERE event_type = ? ORDER BY id DESC LIMIT ?''',
                (event_type, limit)
            )
        else:
            self.cursor.execute(
                '''SELECT * FROM events ORDER BY id DESC LIMIT ?''',
                (limit,)
            )
        return self.cursor.fetchall()

    def delete_event(self, event_id: int):
        self.cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
        self.conn.commit()

    # ---------- phrase plumbing ----------
    def format_phrase(self, phrase, **kwargs):
        try:
            return phrase.format(**kwargs)
        except KeyError as e:
            self.log(f"Missing placeholder: {e}", level="WARN")
            return phrase

    def _collect_context(self, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Merge provided context + DEVILCore data_store (flattened) + shared_data.
        Adds friendly aliases (cpu, mem, temp, ssid, tick) and seeds SAFE_DEFAULTS.
        """
        # start with safe defaults
        data: Dict[str, Any] = dict(_SAFE_DEFAULTS)

        # bring in bus data
        try:
            if self.core:
                store = getattr(self.core, "data_store", {}) or {}
                data.update(store or {})
                vitals = store.get("vitals", {}) or {}
                data.update(vitals)

                # helpful aliases
                data.setdefault("tick", getattr(self.core, "tick_count", 0))
                data.setdefault("boot_time", store.get("boot_time", "—"))

                if "cpu_usage" in data and "cpu" not in data:
                    try: data["cpu"] = int(float(data["cpu_usage"]))
                    except Exception: data["cpu"] = data["cpu_usage"]
                if "mem_usage" in data and "mem" not in data:
                    try: data["mem"] = int(float(data["mem_usage"]))
                    except Exception: data["mem"] = data["mem_usage"]
                if "temperature" in data and "temp" not in data:
                    data["temp"] = data["temperature"]
                if "last_seen_wifi" in data and "ssid" not in data:
                    data["ssid"] = data["last_seen_wifi"] or "—"
        except Exception:
            pass

        # include any shared_data we’ve cached
        try:
            data.update(self.shared_data.get("vitals", {}))
            data.update(self.shared_data)
        except Exception:
            pass

        # finally, the caller context (wins)
        if context:
            for k, v in context.items():
                data[k] = _coerce_for_phrase(v)

        # convenience pretty strings
        if isinstance(data.get("wifi_seen"), (list, tuple)) and not data.get("wifi_seen_str"):
            try:
                data["wifi_seen_str"] = ", ".join(map(str, data["wifi_seen"]))
            except Exception:
                data["wifi_seen_str"] = str(data["wifi_seen"])

        return data

    # --- smart placeholder parsing ------------------------------------------
    # Supports:
    #   {key}                      → lookup; if missing/None -> SAFE_DEFAULTS or "—"
    #   {key|default}             → default if missing/None/""
    #   dotted keys (e.g., {vitals.cpu} or {wifi.0.ssid})
    # Lists auto-render via ", " join if no explicit default provided.
    _PH_RX = re.compile(r"\{([^{}]+)\}")

    @staticmethod
    def _dig(data: Dict[str, Any], path: str) -> Any:
        """Best-effort dotted path resolver: 'a.b.0.c'."""
        cur: Any = data
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, (list, tuple)):
                try:
                    idx = int(part)
                    cur = cur[idx]
                except Exception:
                    return None
            else:
                return None
        return cur

    def _render_value(self, val: Any) -> str:
        if val is None or val == "":
            return "—"
        if isinstance(val, (list, tuple, set)):
            try:
                return ", ".join(map(str, val))
            except Exception:
                return str(val)
        if isinstance(val, float):
            return f"{val:.1f}"
        return str(val)

    def parse_placeholders(self, phrase: str, context: Dict[str, Any] | None = None) -> str:
        """
        Replace {key} or {key|default} using merged context (includes DEVILCore bus).
        - If key missing/None/"", use explicit default if provided.
        - Otherwise fall back to _SAFE_DEFAULTS.get(key, "—").
        """
        data = self._collect_context(context)

        def repl(match: re.Match) -> str:
            body = match.group(1).strip()
            if "|" in body:
                key, default = (body.split("|", 1) + [""])[:2]
                key = key.strip()
                default = default.strip()
            else:
                key, default = body, ""

            val = self._dig(data, key) if "." in key else data.get(key, None)

            if val is None or val == "":
                if default != "":
                    return default
                # fallback to safe defaults, then em dash
                return self._render_value(_SAFE_DEFAULTS.get(key, "—"))

            return self._render_value(val)

        try:
            return self._PH_RX.sub(repl, phrase)
        except Exception as e:
            self.log(f"Placeholder parse error: {e}", level="WARN")
            return phrase

    def _resolve_phrase_file(self, tag, mood="neutral", module_path=None):
        """
        Resolution order (first hit wins, no merging):
          1) module_path/<tag>/mood.txt  or  module_path/<tag>/<mood>.txt
          2) personalities/Default/phrases/<tag>/<mood>.txt
          3) phrases/<tag>/<mood>.txt   (core defaults)
        """
        # 1) module-local
        mod_root = module_path or self._module_phrases
        if mod_root:
            path = os.path.join(mod_root, tag, "mood.txt")
            if os.path.exists(path):
                return path
            path = os.path.join(mod_root, tag, f"{mood}.txt")
            if os.path.exists(path):
                return path

        # 2) personality override
        persona = os.path.join(self._persona_phrases, tag, f"{mood}.txt")
        if os.path.exists(persona):
            return persona

        # 3) core pack
        return os.path.join(self._core_phrases, tag, f"{mood}.txt")

    def _get_random_phrase(self, tag, mood="neutral", module_path=None):
        path = self._resolve_phrase_file(tag, mood, module_path)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            if not lines:
                return None
            # light neutral safety if VoiceBox isn’t in play for this line
            if mood == "neutral":
                lines = [ln for ln in lines if _is_neutral_safe(ln)]
                if not lines:
                    return None
            return random.choice(lines)
        except Exception as e:
            self.log(f"Phrase load failed: {e}", level="ERROR")
            return None

    async def speak(self, tag="boot", mood=None, module_path=None, return_only=False, **kwargs):
        mood = mood or self.get_current_mood()
        phrase = self._get_random_phrase(tag, mood, module_path)
        if phrase:
            # merge kwargs with bus so the voice path also has full context
            context = self._collect_context(kwargs)
            formatted = self.parse_placeholders(phrase, context)
            self.log_event("K.A.R.I.", "SPEAK", formatted)
            if return_only:
                return formatted
            # Ask VoiceBox to actually say it if available, else log JUST THE PHRASE.
            try:
                if self.core and getattr(self.core, "voice", None) and self.core.voice.ready:
                    await self.core.voice.say(
                        phrase_type=tag,
                        mood=mood,
                        module_path=module_path or self._module_phrases,
                        context=context
                    )
                else:
                    # No banners; speak only the line to persona stream.
                    await log_kari_async(formatted, module_name="K.A.R.I")
            except Exception:
                await log_kari_async(formatted, module_name="K.A.R.I")
        else:
            self.log_event("K.A.R.I.", "SPEAK", f"(No phrase for {tag}/{mood})")
            if not return_only:
                await log_kari_async("...", module_name="K.A.R.I")

    async def react(self, module_name, fail=False):
        # For module-specific reactions, read phrases/react/<module>.txt style if you have them;
        # otherwise, just fall back to generic react/mood.txt via speak()
        await self.speak(tag="react", module_path=self._module_phrases)

    def get_phrase(self, tag, mood=None, module_path=None):
        mood = mood or self.get_current_mood()
        path = self._resolve_phrase_file(tag, mood, module_path)
        try:
            if not os.path.exists(path):
                return "[no phrase file]"
            with open(path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                if mood == "neutral":
                    lines = [ln for ln in lines if _is_neutral_safe(ln)]
                return random.choice(lines) if lines else "[no valid lines found]"
        except Exception as e:
            return f"[load error: {e}]"

    # ---------- misc ----------
    def report_alive(self):
        self.log("Status: Online and operational.")

    def display_info(self):
        for k, v in self.meta_data.items():
            self.log(f"{k}: {v}")

    def pulse(self):
        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            self.shared_data.update(self.core.data_store)

    def push_shared_data(self):
        pass

    def close(self):
        """Close the SQLite connection cleanly."""
        try:
            self.conn.close()
        except Exception:
            pass

    def collect_info(self):
        return {
            "Module Info": {
                "name": self.meta_data.get("name"),
                "version": self.meta_data.get("version"),
                "author": self.meta_data.get("author"),
                "description": self.meta_data.get("description")
            }
        }
