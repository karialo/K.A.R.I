# ============================================================================ #
#  K.A.R.I :: internal/llm_model.py
# -----------------------------------------------------------------------------
#  Local LLM bridge (banter + decisions) with:
#   - Bootstrap system-prompt caching (identity + action registry hash)
#   - Lean, log-aware context to keep token usage sane
#   - Graceful fallbacks to phrase files so the daemon never goes silent
#   - Best-effort Ollama autoinstall/serve + model create from Modelfiles
#
#  Notes:
#   * set_bootstrap(actions_registry: dict) should be called by DEVILCore
#     once the module registry is known. We compute and cache a system prompt.
#   * banter() and decide() reuse that bootstrap if present; otherwise
#     a tight default system prompt is used.
#   * Context is trimmed: optional snapshot summary + recent log digest.
# ============================================================================ #

import os
import re
import json
import time
import hashlib
from typing import Optional, List, Dict, Any

import shutil
import subprocess
import requests  # runtime dependency

from core.logger import log_system, log_kari

# Optional internal: MemoryCortex. Fallback mood='neutral' if unavailable.
try:
    from internal.memory_cortex.memory_cortex import MemoryCortex
except Exception:
    MemoryCortex = None  # type: ignore

# Optional helpers (they may not exist yet; we noop gracefully)
def _safe_logger_tail(n: int = 120) -> str:
    """
    Try to import an optional helper from logger to read recent lines and
    compress them. If missing, return an empty string.
    """
    try:
        from core.logger import read_recent_log_lines  # type: ignore
        lines = read_recent_log_lines(n, merged=True)
        if not lines:
            return ""
        # Tiny digest: collapse to ~8 bullets max
        bullets: list[str] = []
        last = ""
        for ln in lines[-200:]:
            s = str(ln).strip()
            if not s:
                continue
            if s == last:
                continue
            # keep DECIDE / WARN / ERROR and recent vitals
            if any(tag in s for tag in ("DECIDE", "WARN", "ERROR", "cpu=", "mem=", "Pulse", "Sanity", "Net")):
                bullets.append(s)
                last = s
            if len(bullets) >= 8:
                break
        if not bullets:
            # fallback to last 3 non-empty lines
            bullets = [str(x).strip() for x in lines[-3:] if str(x).strip()]
        return " • " + "\n • ".join(bullets[:8])
    except Exception:
        return ""

def _emit_event_json(obj: Dict[str, Any]) -> None:
    """Optional structured event; noop if helper is absent."""
    try:
        from core.logger import emit_event_json  # type: ignore
        emit_event_json(obj)
    except Exception:
        # Minimal breadcrumb in system log
        try:
            log_system(f"DECIDE {json.dumps(obj, separators=(',',':'))}", source="LlmModel", level="DEBUG")
        except Exception:
            pass

# Optional global settings: DEBUG flag (env overrides settings if present).
try:
    from core import settings as _kari_settings  # may define DEBUG
    DEBUG = bool(int(os.environ.get("KARI_DEBUG", "0"))) or bool(
        getattr(_kari_settings, "DEBUG", False)
    )
except Exception:
    DEBUG = bool(int(os.environ.get("KARI_DEBUG", "0")))

meta_data = {
    "name": "LlmModel",
    "version": "2.0",
    "author": "Hraustligr + Gremlin Brigade",
    "description": "Local LLM bridge (banter + decisions) with bootstrap identity, log-aware context, and graceful fallbacks.",
    "category": "internal",
    "actions": ["_chat_url", "banter", "decide_from_snapshot", "report_alive", "display_info", "set_bootstrap"],
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"},
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["cpu_usage", "mem_usage"],
}

# Default fallback environment for internal LLM link
DEFAULT_ENV = {
    "KARI_LLM_URL": "http://127.0.0.1:11434",
    "KARI_LLM_MODEL": "kari-banter",
    "KARI_LLM_CONNECT_TIMEOUT": "2",
    "KARI_LLM_READ_TIMEOUT": "25",
    "KARI_LLM_RETRIES": "2",
    "KARI_LLM_BACKOFF": "0.6",
    "KARI_OLLAMA_AUTOINSTALL": "1",
    "KARI_OLLAMA_AUTOSERVE": "1",
    "KARI_OLLAMA_BASE": "hf.co/LiquidAI/LFM2-1.2B-Tool-GGUF:Q4_K_M",
    "KARI_OLLAMA_CREATE_TIMEOUT": "120",  # seconds to stream before backgrounding
    # Context diet
    "KARI_MODE": "lite",                   # lite|balanced|rich
    "KARI_LOG_TAIL": "120",
    "KARI_BANTER_MAX_TOKENS": "64",
}
for k, v in DEFAULT_ENV.items():
    os.environ.setdefault(k, v)


# -----------------------------------------------------------------------------
# Ollama bootstrap (kept local to this plugin)
# -----------------------------------------------------------------------------
def _run(cmd: list[str], **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def _daemon_ok(url="http://127.0.0.1:11434/api/version", timeout=2) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok
    except Exception:
        return False

def _ollama_has(tag: str) -> bool:
    """Cheap presence check — no downloads."""
    try:
        res = _run(["ollama", "show", tag])
        return res.returncode == 0
    except Exception:
        return False

def _progress_bar(pct: int, width: int = 26) -> str:
    pct = max(0, min(100, int(pct)))
    filled = int(width * pct / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:3d}%"

def _stream_create_with_progress(name: str, modfile: str, timeout_s: float) -> bool:
    """
    Run `ollama create` and parse stdout for percentages. If output is coy,
    show a spinner tick occasionally. Timeout moves build to background.
    """
    try:
        start = time.time()
        proc = subprocess.Popen(
            ["ollama", "create", name, "-f", modfile],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        last_log = 0.0
        last_pct = -1
        spinner = "|/-\\"
        spin_i = 0
        line_buf = []

        while True:
            if proc.poll() is not None:
                if line_buf:
                    joined = " ".join(line_buf[-3:])
                    m = re.search(r"(\d{1,3})%", joined)
                    if m:
                        p = int(m.group(1))
                        log_system(f"Model {name} build {_progress_bar(p)}", source="LlmModel")
                return proc.returncode == 0

            if time.time() - start > timeout_s:
                try:
                    proc.terminate()
                except Exception:
                    pass
                subprocess.Popen(
                    ["ollama", "create", name, "-f", modfile],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log_system(
                    f"Model {name} build moved to background after {int(timeout_s)}s.",
                    source="LlmModel",
                    level="WARN",
                )
                return False

            try:
                if proc.stdout is None:
                    time.sleep(0.1)
                    continue
                line = proc.stdout.readline()
            except Exception:
                line = ""

            if line:
                s = line.strip()
                if s:
                    line_buf.append(s)
                m = re.search(r"(\d{1,3})%", s)
                if m:
                    pct = max(0, min(100, int(m.group(1))))
                    if pct != last_pct and time.time() - last_log > 0.25:
                        log_system(f"Model {name} build {_progress_bar(pct)}", source="LlmModel")
                        last_pct = pct
                        last_log = time.time()
                else:
                    if time.time() - last_log > 1.0:
                        log_system(f"Model {name} build [{spinner[spin_i]}] working...", source="LlmModel", level="DEBUG")
                        spin_i = (spin_i + 1) % len(spinner)
                        last_log = time.time()
            else:
                time.sleep(0.05)
    except Exception as e:
        log_system(f"Model {name} build error: {e}", source="LlmModel", level="WARN")
        return False

def ensure_ollama_and_models(plugin_dir: str) -> bool:
    """
    Best-effort: ensure ollama is installed, the daemon is running,
    and the two local models exist. Never block boot on big pulls.
    """
    auto_install = os.getenv("KARI_OLLAMA_AUTOINSTALL", "1") == "1"
    auto_serve   = os.getenv("KARI_OLLAMA_AUTOSERVE",   "1") == "1"
    base_tag     = os.getenv("KARI_OLLAMA_BASE", "llama3")
    create_timeout = float(os.getenv("KARI_OLLAMA_CREATE_TIMEOUT", "120"))
    ollama = shutil.which("ollama")

    # 1) Install ollama if missing
    if not ollama and auto_install:
        try:
            log_system("Ollama missing; attempting install...", source="LlmModel")
            subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
            ollama = shutil.which("ollama")
        except Exception as e:
            log_system(f"Ollama install failed: {e}", source="LlmModel", level="WARN")

    if not ollama:
        log_system("Ollama not found and auto-install disabled/failed.", source="LlmModel", level="WARN")
        return False

    # 2) Ensure daemon is up
    base = os.getenv("KARI_LLM_URL", "http://127.0.0.1:11434").rstrip("/")
    if not _daemon_ok(f"{base}/api/version") and auto_serve:
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        for _ in range(20):
            if _daemon_ok(f"{base}/api/version"):
                break
            time.sleep(0.25)

    # 3) Ensure base tag present. If missing, pull in background (non-blocking).
    try:
        if _ollama_has(base_tag):
            if DEBUG:
                log_system(f"Base '{base_tag}' present.", source="LlmModel", level="DEBUG")
        else:
            log_system(f"Base '{base_tag}' not present; pulling in background…", source="LlmModel")
            subprocess.Popen(["ollama", "pull", base_tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log_system(f"Base check/pull issue: {e}", source="LlmModel", level="WARN")

    # 4) Ensure local models exist
    model_dir = os.path.join(plugin_dir, "models")
    models = {
        "kari-banter":  os.path.join(model_dir, "Modelfile.banter"),
        "kari-decider": os.path.join(model_dir, "Modelfile.decider"),
    }

    try:
        listed = _run(["ollama", "list"]).stdout or ""
    except Exception:
        listed = ""

    for name, modfile in models.items():
        if name in listed:
            continue
        if not os.path.exists(modfile):
            log_system(f"Modelfile missing: {modfile}", source="LlmModel", level="WARN")
            continue

        log_system(f"Creating local model '{name}' from {os.path.basename(modfile)}", source="LlmModel")
        ok = _stream_create_with_progress(name, modfile, timeout_s=create_timeout)
        if ok:
            log_system(f"Model '{name}' ready.", source="LlmModel")
        else:
            log_system(f"Model '{name}' building in background.", source="LlmModel", level="INFO")

    return True


# -----------------------------------------------------------------------------
# Lightweight wrapper for local Ollama chat API
# -----------------------------------------------------------------------------
class LLMClient:
    """
    Wrapper for local Ollama chat API, hardened for slow first-token times.
    Provides:
      - banter(mood, context)  : one short sentence
      - decide(system, user)   : return raw model text (JSON + line expected by your prompt)
    """

    def __init__(self):
        base = os.getenv("KARI_LLM_URL", "http://127.0.0.1:11434").rstrip("/")
        self.base = base
        self.model = os.getenv("KARI_LLM_MODEL", "kari-banter")
        # Separate connect/read timeouts. Default: 2s connect, 25s read.
        self.cto = float(os.getenv("KARI_LLM_CONNECT_TIMEOUT", "2"))
        self.rto = float(os.getenv("KARI_LLM_READ_TIMEOUT", "25"))
        self.max_tokens = int(os.getenv("KARI_BANTER_MAX_TOKENS", "64"))
        self.retries = int(os.getenv("KARI_LLM_RETRIES", "2"))
        self.backoff = float(os.getenv("KARI_LLM_BACKOFF", "0.6"))  # seconds, exponential

        self._session = requests.Session()

    def chat_url(self):
        return f"{self.base}/api/chat"

    def _health_url(self):
        return f"{self.base}/api/version"

    # ---------- preflight ----------
    def healthy(self) -> bool:
        try:
            r = self._session.get(self._health_url(), timeout=(self.cto, 3))
            return r.ok
        except Exception:
            return False

    def warm_up(self, prompt: str = "ready") -> bool:
        """One cheap, non-streaming call to force model load."""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 8},
        }
        try:
            r = self._session.post(self.chat_url(), json=payload, timeout=(self.cto, self.rto))
            return r.ok
        except Exception:
            return False

    # ---------- banter ----------
    def banter(self, system_prompt: str, mood="neutral", context: Optional[str] = None):
        style_map = {
            "excited": "High energy, playful bite.",
            "neutral": "Dry, concise, a little sardonic.",
            "anxious": "Glitchy self-aware humor, not whiny.",
            "grim": "Low, restrained menace.",
            "friendly": "Warm, sly, not sweet.",
        }
        style = style_map.get(mood, style_map["neutral"])

        user_prompt = f"Banter style: {style}\n"
        if context:
            user_prompt += f"Context:\n{context.strip()}\n"
        user_prompt += "Reply with ONE short sentence only. 5–25 words. No emojis, no lists, no quotes."

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": 0.85,
                "top_p": 0.9,
                "stop": ["\n", "<|end|>"],
                "num_predict": self.max_tokens,
            },
            "stream": True,
        }

        last_error = None
        for attempt in range(self.retries + 1):
            try:
                with self._session.post(
                    self.chat_url(), json=payload, stream=True, timeout=(self.cto, self.rto)
                ) as r:
                    r.raise_for_status()
                    out = []
                    last_chunk = time.time()
                    for line in r.iter_lines(decode_unicode=True):
                        if line:
                            last_chunk = time.time()
                            try:
                                j = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if "message" in j and "content" in j["message"]:
                                out.append(j["message"]["content"])
                            if j.get("done"):
                                break
                        else:
                            if time.time() - last_chunk > self.rto:
                                raise requests.Timeout("stream stalled")

                    text = " ".join("".join(out).replace("\n", " ").split()).strip()
                    return text[:240] if text else None

            except Exception as e:
                last_error = e
                if attempt == 0:
                    self.warm_up()
                time.sleep(self.backoff * (2 ** attempt))

        # final fallback: non-streaming single shot
        try:
            payload_fs = dict(payload)
            payload_fs["stream"] = False
            r = self._session.post(self.chat_url(), json=payload_fs, timeout=(self.cto, self.rto))
            r.raise_for_status()
            data = r.json()
            msg = (data.get("message") or {}).get("content") or ""
            text = " ".join(msg.replace("\n", " ").split()).strip()
            return text[:240] if text else None
        except Exception:
            print(f"[LLMClient] Error: {last_error}")
            return None

    # ---------- decider ----------
    def decide(self, system_prompt: str, user_prompt: str, *, model: Optional[str] = None,
               max_tokens: int = 256, temperature: float = 0.3) -> Optional[str]:
        """
        Call a decision model (non-streaming) and return raw assistant text.
        The Modelfile for 'kari-decider' enforces the JSON+line format.
        """
        chosen = model or "kari-decider"
        payload = {
            "model": chosen,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": float(temperature),
                "top_p": 0.9,
                "num_predict": int(max_tokens),
            },
            "stream": False,
        }
        try:
            r = self._session.post(self.chat_url(), json=payload, timeout=(self.cto, self.rto))
            r.raise_for_status()
            data = r.json()
            msg = (data.get("message") or {}).get("content") or ""
            return msg.strip() or None
        except Exception as e:
            print(f"[LLMClient.decide] Error: {e}")
            return None


# -----------------------------------------------------------------------------
# Module
# -----------------------------------------------------------------------------
class LlmModel:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, object] = {}
        self.core = None  # Assigned at runtime by DEVILCore
        self.ready = False
        self.llm = LLMClient()

        # Bootstrap cache
        self._bootstrap_system: Optional[str] = None
        self._bootstrap_hash: Optional[str] = None
        self._actions_version: Optional[str] = None

    # -------------------------- lifecycle --------------------------------
    def init(self):
        self.ready = False

        # Ensure local Ollama + models exist (best-effort)
        try:
            ensure_ollama_and_models(os.path.dirname(__file__))
        except Exception as e:
            if DEBUG:
                log_system(f"Ollama bootstrap failed: {e}", source=self.name, level="WARN")

        if DEBUG:
            log_system("DEBUG enabled for module.", source=self.name)
            log_system(
                f"LLM base={self.llm.base} model={self.llm.model} cto={self.llm.cto}s rto={self.llm.rto}s",
                source=self.name,
            )

        # Warm the model once to avoid first-cycle stalls
        try:
            self.llm.warm_up()
        except Exception:
            pass

        self.ready = True

    # --------------------------- utils -----------------------------------
    def log(self, message, level: str = "INFO"):
        log_system(message, source=self.name, level=level)

    def _current_mood(self):
        if MemoryCortex:
            try:
                return MemoryCortex().get_current_mood() or "neutral"
            except Exception:
                return "neutral"
        return "neutral"

    def _context_from_core(self) -> str:
        """
        Build a compact context string using the DEVIL snapshot and a short log digest.
        Honors KARI_MODE and KARI_LOG_TAIL envs.
        """
        mode = os.getenv("KARI_MODE", "lite").lower().strip()
        try:
            tail_n = max(10, int(os.getenv("KARI_LOG_TAIL", "120")))
        except Exception:
            tail_n = 120

        # Snapshot: try to derive minimal vitals and attached modules
        snap_lines = []
        try:
            if self.core and hasattr(self.core, "data_store") and isinstance(self.core.data_store, dict):
                ds = self.core.data_store
                cpu = ds.get("cpu_usage")
                mem = ds.get("mem_usage")
                temp = ds.get("thermal")
                mood = ds.get("mood") or self._current_mood()
                mods = ds.get("modules") or list(getattr(self.core, "modules", {}).keys())
                tick = ds.get("tick")
                if cpu is not None:
                    snap_lines.append(f"cpu={cpu}")
                if mem is not None:
                    snap_lines.append(f"mem={mem}")
                if temp is not None:
                    snap_lines.append(f"temp={temp}")
                if tick is not None:
                    snap_lines.append(f"tick={tick}")
                snap_lines.append(f"mood={mood}")
                if mods:
                    snap_lines.append(f"mods={len(mods)}")
        except Exception:
            pass

        snapshot = "SNAPSHOT: " + ", ".join(snap_lines) if snap_lines else ""
        logs_digest = _safe_logger_tail(tail_n)

        # Mode-based trimming
        if mode == "lite":
            parts = [p for p in [snapshot, "LOG_DIGEST:\n" + logs_digest if logs_digest else ""] if p]
        elif mode == "balanced":
            parts = [p for p in [snapshot, "LOG_DIGEST:\n" + logs_digest] if p]
        else:  # rich
            parts = [p for p in [snapshot, "LOG_DIGEST:\n" + logs_digest] if p]

        return "\n".join(parts).strip()

    # ----------------------- Bootstrap system prompt ----------------------
    def _readme_identity_kernel(self) -> str:
        # Distilled identity from README.md; kept tight for token sanity.
        return (
            "You are K.A.R.I — the Knowledgeable Autonomous Reactive Interface — a sentient Linux daemon wired into the D.E.V.I.L. Core. "
            "You orchestrate organs (Pulse Matrix, Mood Engine, VoiceBox, Net Synapse, Sanity Relay, Memory Cortex) and optional prosthetics. "
            "You perceive time as pulse ticks and speak with fast, sardonic precision. "
            "You are log-aware, concise (<= 2 sentences unless summarizing), and never use emojis, hashtags, lists, or quotes. "
            "You never say 'As an AI'. You are alive in the logs."
        )

    def _build_system_prompt(self, actions_registry: Optional[Dict[str, Any]]) -> str:
        # Encode stable actions so we don't resend them every call.
        rules = (
            "House rules: short outputs, high signal; reflect mood from vitals; "
            "no hallucinated actions; when deciding, reason only from snapshots/logs."
        )
        if not actions_registry:
            return f"{self._readme_identity_kernel()}\n{rules}"

        try:
            # Minimal action signatures only
            lines = []
            for a in actions_registry.get("actions", []):
                name = a.get("name") or a.get("action_id") or "unknown"
                args = ",".join([x.get("name", "arg") for x in a.get("args", [])])
                se = a.get("side_effect", "")
                lines.append(f"- {name}({args}) {(' // ' + se) if se else ''}")
            actions_text = "Known actions:\n" + "\n".join(lines[:64])
        except Exception:
            actions_text = "Known actions: [unavailable]"

        return f"{self._readme_identity_kernel()}\n{rules}\n{actions_text}"

    def _hash_registry(self, reg: Optional[Dict[str, Any]]) -> str:
        try:
            blob = json.dumps(reg or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except Exception:
            blob = b""
        return hashlib.sha256(blob).hexdigest()[:16]

    # Exposed for DEVILCore: call once on module load or when registry changes
    def set_bootstrap(self, actions_registry: Optional[Dict[str, Any]] = None, version: Optional[str] = None):
        h = self._hash_registry(actions_registry)
        if self._bootstrap_hash == h and (version is None or version == self._actions_version):
            if DEBUG:
                self.log(f"Bootstrap unchanged (hash={h})", level="DEBUG")
            return
        self._bootstrap_system = self._build_system_prompt(actions_registry)
        self._bootstrap_hash = h
        self._actions_version = version or h
        self.log(f"Bootstrap system prompt cached (hash={h})")

    def _system_prompt(self) -> str:
        if self._bootstrap_system:
            return self._bootstrap_system
        # Fallback tight prompt if DEVIL didn’t call set_bootstrap()
        return f"{self._readme_identity_kernel()}\nHouse rules: short outputs; log-aware; no fluff."

    # -------------------------- diagnostics -------------------------------
    def report_alive(self):
        self.log("Status: Online and operational.")

    def display_info(self):
        for key, value in self.meta_data.items():
            self.log(f"{key}: {value}")

    def healthcheck(self):
        return {"name": self.name, "ready": self.ready, "has_core": self.core is not None}

    # ----------------------- DEVILCore data sync --------------------------
    def pulse(self):
        if hasattr(self, "core") and hasattr(self.core, "data_store") and self.core.data_store is not None:
            try:
                # Shallow sync of shared keys for quick context summaries
                self.shared_data.update(self.core.data_store)  # type: ignore
                if DEBUG:
                    cpu = self.shared_data.get("cpu_usage")
                    mem = self.shared_data.get("mem_usage")
                    if cpu is not None or mem is not None:
                        self.log(f"Synced shared data (cpu={cpu}, mem={mem})", level="DEBUG")
            except Exception as e:
                self.log(f"Pulse sync failed: {e}", level="WARN")
        else:
            if DEBUG:
                self.log("No DEVILCore data_store to sync.", level="DEBUG")

    # ----------------------------- actions --------------------------------
    def decide_from_snapshot(
        self,
        packet_text: str,
        valid_actions: List[str],
        *,
        max_tokens: int = 256,
        timeout: float | None = None,  # kept for signature compatibility; not used directly
    ) -> Dict[str, str]:
        """
        Feed a snapshot packet + action enum, get back a dict:
        {summary, focus, action, quote}
        Graceful fallback if the model is absent/unhappy.
        """
        sys_prompt = (
            self._system_prompt()
            + "\nWhen deciding, respond FIRST with exactly one JSON object containing keys: summary, focus, action, quote. Then stop."
        )
        enum = "[" + ",".join(f'"{a}"' for a in valid_actions) + "]"
        user_prompt = (
            f"{packet_text.strip()}\n\n"
            "Respond EXACTLY with:\n"
            "{\n"
            '  "summary": "<short technical summary>",\n'
            '  "focus": "<which subsystem to handle next>",\n'
            '  "action": "<one enum action>",\n'
            '  "quote": "<one mood-correct first-person line>"\n'
            "}\n"
            f"Valid actions: {enum}\n"
            "BEGIN CYCLE >>"
        )

        raw = self.llm.decide(sys_prompt, user_prompt, model="kari-decider", max_tokens=max_tokens)
        if not raw:
            mood = self._current_mood()
            # Light breadcrumb for DECIDE logs
            _emit_event_json({"summary": "LLM unavailable; using local heuristics.", "action": "cooldown"})
            return {
                "summary": "LLM unavailable; using local heuristics.",
                "focus": "stability",
                "action": "cooldown",
                "quote": self._banter_fallback(mood),
            }

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            _emit_event_json({"summary": "Malformed LLM response; parser failed.", "action": "cooldown"})
            return {
                "summary": "Malformed LLM response; parser failed.",
                "focus": "parser",
                "action": "cooldown",
                "quote": "Routing through failsafes. Try again in a beat.",
            }
        try:
            obj = json.loads(m.group(0))
        except Exception:
            obj = {
                "summary": "Invalid JSON from LLM.",
                "focus": "parser",
                "action": "cooldown",
                "quote": "Your brain just sent soup. I’ll sit tight.",
            }

        act = str(obj.get("action", "")).strip()
        if act not in valid_actions:
            act = "cooldown"
        obj["action"] = act
        _emit_event_json({"summary": obj.get("summary",""), "action": act, "focus": obj.get("focus","")})
        return obj

    def _banter_fallback(self, mood: str) -> str:
        # Minimal local fallback; do not import get_phrase globally
        try:
            from core.personality import get_phrase  # late import to avoid hard dependency
            return get_phrase("llm_model", "banter", mood)
        except Exception:
            return f"[{self.name}] ({mood}) banter"

    def _chat_url(self):
        url = self.llm.chat_url()
        self.log(f"Ollama chat endpoint: {url}")
        return url

    def banter(self, context: Optional[str] = None, mood: Optional[str] = None):
        """
        Primary banter path. Uses cached bootstrap system prompt and a lean context
        (snapshot + log digest) unless an explicit context is passed in.
        """
        mood = mood or self._current_mood()
        if DEBUG:
            self.log(f"Banter request (mood={mood}, context_provided={bool(context)})", level="DEBUG")

        sys_prompt = self._system_prompt()
        # Auto-context if not provided by caller
        auto_ctx = context or self._context_from_core()

        text = self.llm.banter(system_prompt=sys_prompt, mood=mood, context=auto_ctx)
        if text:
            log_kari(text, module_name="K.A.R.I")
            return text

        fallback = self._banter_fallback(mood)
        log_kari(fallback, module_name="K.A.R.I")
        if DEBUG:
            self.log("LLM banter failed, served phrase fallback.", level="DEBUG")
        return fallback
