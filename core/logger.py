# === K.A.R.I. LOGGER MODULE ===
# Handles formatted logging to system, raw, and K.A.R.I. persona outputs.
# Adds:
#   • Log level gate via KARI_LOG_LEVEL (DEBUG|INFO|WARN|ERROR)
#   • Divider policy with boot/runtime switch:
#       - KARI_DIVIDERS = boot (default) | always | never
#       - mark_main_loop_started() disables dividers after boot (policy=boot)

import os
import time
from datetime import datetime
import asyncio

# === Global Runtime Hooks ===
retina = None
mood = "neutral"

# === Log level control ===
LOG_LEVEL = os.getenv("KARI_LOG_LEVEL", "INFO").upper()  # DEBUG | INFO | WARN | ERROR
_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

def _allow(level: str) -> bool:
    level = (level or "INFO").upper()
    return _LEVEL_ORDER.get(level, 20) >= _LEVEL_ORDER.get(LOG_LEVEL, 20)

def set_log_level(level: str):
    """Programmatic override of log level at runtime."""
    global LOG_LEVEL
    LOG_LEVEL = (level or "INFO").upper()

def get_log_level() -> str:
    return LOG_LEVEL

# === Divider policy ===
# boot: dividers only during boot phase; runtime banter is unboxed
# always: always print dividers around K.A.R.I. lines
# never: never print dividers
DIVIDER_POLICY = os.getenv("KARI_DIVIDERS", "boot").strip().lower()  # boot|always|never
_BOOT_PHASE = True  # switched off by mark_main_loop_started()

def mark_main_loop_started():
    """Call this when DEVIL Core hands off to the main loop."""
    global _BOOT_PHASE
    _BOOT_PHASE = False

def set_divider_mode(mode: str):
    """Force divider policy at runtime."""
    global DIVIDER_POLICY
    m = (mode or "").strip().lower()
    if m in ("boot", "always", "never"):
        DIVIDER_POLICY = m

def get_divider_mode() -> str:
    return DIVIDER_POLICY

def _should_dividers() -> bool:
    if DIVIDER_POLICY == "always":
        return True
    if DIVIDER_POLICY == "never":
        return False
    # boot mode
    return _BOOT_PHASE

# === Log Paths ===
LOG_DIR = "logs"
RAW_LOG = os.path.join(LOG_DIR, "raw.log")
SYSTEM_LOG = os.path.join(LOG_DIR, "system.log")
KARI_LOG = os.path.join(LOG_DIR, "kari.log")

# Ensure log folder exists
os.makedirs(LOG_DIR, exist_ok=True)

# === Log File Handles ===
_raw_log = open(RAW_LOG, "a", buffering=1)
_system_log = open(SYSTEM_LOG, "a", buffering=1)
_kari_log = open(KARI_LOG, "a", buffering=1)

# === Known Modules for Log Padding ===
KNOWN_MODULES = [
    "Memory Cortex", "Net Synapse", "D.E.V.I.L Core",
    "MenuEngine", "heartbeat", "System", "CORE", "K.A.R.I",
    "VoiceBox", "Pulse Matrix", "Sanity Relay", "Decision Engine",
]
MAX_SOURCE_WIDTH = max(len(name) for name in KNOWN_MODULES)

def _timestamp():
    return time.strftime("%H:%M:%S")

def _padded_source(source):
    return f"[{source}]".ljust(MAX_SOURCE_WIDTH + 2)

def _write_line(file, line):
    try:
        file.write(line + "\n")
        file.flush()
    except Exception:
        pass

def format_kari_output(*thoughts):
    timestamp = _timestamp()
    name = "[K.A.R.I]"
    text = " ".join(str(t) for t in thoughts)
    return f"{timestamp} | {name.ljust(MAX_SOURCE_WIDTH + 2)} | {text}"

def _emit_stdout_with_optional_divider(line: str):
    """Print one K.A.R.I. line, wrapped in dividers only if policy allows."""
    if _should_dividers():
        divider = "-" * 100
        print(divider)
        print(line)
        print(divider)
    else:
        print(line)

def log_kari(*thoughts, event_type="banter", module_path=None, module_name=None, level: str = "INFO"):
    """Synchronous K.A.R.I. line(s). Respects KARI_LOG_LEVEL and divider policy."""
    if not _allow(level):
        return
    timestamp = _timestamp()

    for thought in thoughts:
        line = format_kari_output(thought)
        _emit_stdout_with_optional_divider(line)
        _write_line(_kari_log, line)
        _write_line(_raw_log, f"{timestamp} | [K.A.R.I] | {thought}")

        if retina:
            try:
                retina.write_line(f"[K.A.R.I] {thought}")
            except Exception:
                pass

async def log_kari_async(*thoughts, event_type="banter", module_name=None, level: str = "INFO"):
    """Asynchronous K.A.R.I. line produced through VoiceBox (if ready). Respects level + divider policy."""
    if not _allow(level):
        return

    timestamp = _timestamp()

    # Try to have VoiceBox craft the phrase; fall back to raw text
    try:
        import core.devil_core as core_devil
        voice = core_devil.DEVIL.modules.get("VoiceBox")
        memory = core_devil.DEVIL.memory

        if not voice or not getattr(voice, "ready", False):
            raise RuntimeError("voicebox not ready")

        curr_mood = memory.get_current_mood()
        phrase = await voice.say(
            phrase_type=event_type,
            mood=curr_mood,
            context={"module_name": module_name, "log_voicebox": True},
            return_only=True
        )
    except Exception as e:
        phrase = f"[error: {e}]"

    line = format_kari_output(phrase)
    _emit_stdout_with_optional_divider(line)
    _write_line(_kari_log, line)
    _write_line(_raw_log, f"{timestamp} | [K.A.R.I] | {phrase}")

    # log any extra provided thoughts as additional lines (no extra boxes in runtime)
    for thought in thoughts:
        if thought != phrase:
            extra = format_kari_output(thought)
            _emit_stdout_with_optional_divider(extra)
            _write_line(_kari_log, extra)
            _write_line(_raw_log, f"{timestamp} | [K.A.R.I] | {thought}")

    if retina:
        try:
            retina.write_line(f"[K.A.R.I] {phrase}")
        except Exception:
            pass

def log_system(message, source="CORE", level: str = "INFO"):
    """System log line (also mirrored to raw). Respects KARI_LOG_LEVEL. No dividers ever."""
    if not _allow(level):
        return None
    padded = _padded_source(source)
    line = f"{_timestamp()} | {padded} | {message}"
    print(line)
    _write_line(_system_log, line)
    _write_line(_raw_log, line)
    if retina:
        try:
            retina.write_line(line)
        except Exception:
            pass
    return line

def log_raw(message, source="CORE", level: str = "INFO"):
    """Raw log line only (printed + raw file). Respects KARI_LOG_LEVEL."""
    if not _allow(level):
        return None
    padded = _padded_source(source)
    line = f"{_timestamp()} | {padded} | {message}"
    print(line)
    _write_line(_raw_log, line)
    if retina:
        try:
            retina.write_line(line)
        except Exception:
            pass
    return line

def log_divider(level: str = "INFO"):
    """Pretty divider (used during boot banners). Respects KARI_LOG_LEVEL."""
    if not _allow(level):
        return
    divider = "-" * 100
    print(divider)
    _write_line(_system_log, f"\n{divider}")
    _write_line(_raw_log, f"\n{divider}")

def detach_retina():
    global retina
    retina = None
