import os
import random
from functools import lru_cache

# Default root where internal modules keep their phrases (fallback pathing).
PHRASE_ROOT = "internal"

def _norm(s: str) -> str:
    return (s or "").strip().lower()

@lru_cache(maxsize=512)
def _read_lines(path: str):
    """Read non-empty, non-comment lines from a file. Cached for speed."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except Exception:
        return None

def _choose_from_tagged(lines, mood: str):
    """Pick a line from [mood]-tagged lines, else [neutral], else any."""
    mood = _norm(mood)
    if not lines:
        return None
    mood_tag = f"[{mood}]"
    neutral_tag = "[neutral]"
    mood_lines = [ln for ln in lines if ln.lower().startswith(mood_tag)]
    if not mood_lines:
        mood_lines = [ln for ln in lines if ln.lower().startswith(neutral_tag)]
    pool = mood_lines or lines
    chosen = random.choice(pool)
    # Strip the leading bracketed tag if present
    if "]" in chosen and chosen.startswith("["):
        return chosen.split("]", 1)[-1].strip()
    return chosen

def get_phrase(module_name: str, event: str, mood: str = "neutral", module_path: str | None = None) -> str:
    """
    Retrieve a phrase for a given module and event, filtered by mood.

    Supports two layouts:
    1) Per-mood files: <base>/<event>/<mood>.txt
    2) Single file with [mood] tags: <base>/<event>.txt

    Args:
        module_name: The module folder name (e.g., "net_synapse", "mood_engine").
        event: The phrase group (e.g., "boot", "banter", "react" or custom).
        mood: Current mood (e.g., "excited", "angry", "neutral").
        module_path: Optional override for the base phrases directory.
                     If provided, this should be the folder that CONTAINS the event subfolders/files.
                     Example: ".../internal/voicebox/phrases"
    Returns:
        A single phrase string, or "..." if none found.
    """
    mood = _norm(mood)
    event = _norm(event)

    # Resolve base directory to search
    if module_path:
        base = module_path
    else:
        # Default to internal/<module_name>/phrases
        base = os.path.join(PHRASE_ROOT, module_name, "phrases")

    # Strategy A: per-mood file: <base>/<event>/<mood>.txt
    mood_file = os.path.join(base, event, f"{mood}.txt")
    lines = _read_lines(mood_file)
    if lines:
        return random.choice(lines)

    # Strategy B: single file with [mood] tags: <base>/<event>.txt
    tagged_file = os.path.join(base, f"{event}.txt")
    lines = _read_lines(tagged_file)
    if lines:
        chosen = _choose_from_tagged(lines, mood)
        if chosen:
            return chosen

    # Last resort… silence is golden.
    return "..."
