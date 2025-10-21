# devil_core.py
# === D.E.V.I.L. Core v2.5 ===
# Primary nervous system for K.A.R.I.
# Handles loading, booting, logging, wake-up, real-time orchestration,
# and a lightweight Unix socket for live control.

# =========================
# Imports
# =========================
import asyncio
import time
import os
import sys
import importlib.util
import inspect
from datetime import datetime
import random
import json
import pathlib
import shlex
import subprocess
from pathlib import Path

# (best-effort; only used to chown the socket)
try:
    import pwd
    import grp
except Exception:  # pragma: no cover
    pwd = grp = None

# =========================
# K.A.R.I. Core Systems
# =========================
from core.logger import log_system, log_divider, detach_retina
import core.logger as logger
from core.menu_engine import MenuEngine
from core.logger import mark_main_loop_started

DEVIL = None


class DEVILCore:
    # ============================================================
    # Init / Identity
    # ============================================================
    def __init__(self, preloaded_modules=None, debug=False, trace=None):
        # --- instance identity ---
        global DEVIL
        DEVIL = self
        self.name = "D.E.V.I.L Core"

        # Two modes:
        # - default/quiet: no debug logs
        # - debug/chatty: all [DEBUG] logs visible
        env_debug = os.getenv("KARI_DEBUG", "0") == "1"
        self.debug = bool(debug or env_debug)

        # Optional ultra-verbose breadcrumbs (modules may honor .trace)
        if trace is None:
            self.trace = (os.getenv("KARI_TRACE", "0") == "1")
        else:
            self.trace = bool(trace)

        # module state
        self.modules = preloaded_modules or {}
        self.boot_time = time.time()
        self.logs = []
        self.status = "Initializing"
        self.tick_count = 0
        self.attached_internal = []
        self.attached_prosthetic = []
        self.ready_modules = {}
        self.menu = MenuEngine()
        self.ghost_modules = set()
        self.voice = None

        self.data_store = {
            "vitals": {},
            "networks": [],
            "last_seen_wifi": None,
            "boot_time": None,
            "tick": 0,  # ← expose pulse count to phrases
            # optional: "disk_usage": "XGB used / YGB"
        }

        # Core-level banter loop — ON by default. Set KARI_DEVIL_BANTER=0 to disable.
        self._devil_banter_enabled = os.getenv("KARI_DEVIL_BANTER", "0") == "1"

        # Brain-cycle (JSON decision) scheduler
        self._brain_enabled  = os.getenv("KARI_BRAIN_ENABLED", "1") == "1"
        self._brain_interval = float(os.getenv("KARI_BRAIN_INTERVAL", "30"))
        self._brain_jitter   = float(os.getenv("KARI_BRAIN_JITTER", "0.15"))  # ±15%
        self._brain_timeout  = float(os.getenv("KARI_BRAIN_TIMEOUT", "6"))
        self._brain_tokens   = int(os.getenv("KARI_DECIDE_MAX_TOKENS", "256"))

        # Prebound memory (if passed in)
        self.memory = self.modules.get("memory_cortex")
        if self.memory:
            if self.debug:
                log_system(
                    "[DEBUG] Memory Cortex module found and preparing to bind",
                    source=self.name,
                    level="DEBUG",
                )

            # BIND CORE so MemoryCortex.speak() can route via VoiceBox (no fallback headers)
            self.memory.core = self

            # Do NOT wipe mood; preserve across boots.
            self.memory.name = "Memory Cortex"
            self.modules["Memory Cortex"] = self.modules.pop("memory_cortex")
            self.attached_internal.append("Memory Cortex")
            self.ghost_modules.add("memory_cortex")

            self.memory.log_event(
                self.name, "INFO", "Memory Cortex acknowledged and bound inside DEVILCore."
            )

            boot_time = datetime.utcnow().isoformat()
            self.memory.remember("last_boot_time", boot_time)
            self.data_store["boot_time"] = boot_time
            self.ready_modules["Memory Cortex"] = getattr(self.memory, "ready", False)

            # Bind logger mood (best-effort)
            try:
                logger.mood = self.memory.get_current_mood()
                if self.debug:
                    log_system(f"Logger mood set to: {logger.mood}", source=self.name, level="DEBUG")
            except Exception as e:
                log_system(f"Failed to bind mood to logger: {e}", source=self.name, level="WARN")
        else:
            log_system("[WARN] No Memory Cortex found in modules at init!", source=self.name, level="WARN")

        # === Live control socket wiring ===
        self._socket_enabled = os.getenv("KARI_ENABLE_SOCKET", "1") == "1"
        self._socket_path = os.getenv("KARI_SOCKET", "/run/kari/kari.sock")
        self._socket_task = None
        self._start_socket_later = False  # set if no running loop at __init__

        if self._socket_enabled:
            try:
                # Try to start immediately if we're already inside a running loop.
                loop = asyncio.get_running_loop()
                self._socket_task = loop.create_task(self._start_control_socket())
                log_system(f"Live control socket booting at {self._socket_path}", source=self.name)
            except RuntimeError:
                # No loop yet (e.g., constructed before asyncio.run). Defer to run_forever().
                self._start_socket_later = True
                log_system(f"Live control socket scheduled at {self._socket_path}", source=self.name)
            except Exception as e:
                log_system(f"Control socket failed to schedule: {e}", source=self.name, level="WARN")

    # ============================================================
    # Runtime verbosity toggles
    # ============================================================
    def set_debug(self, on: bool):
        """Flip DEVILCore + module debug at runtime."""
        self.debug = bool(on)
        log_system(f"Debug mode {'ENABLED' if self.debug else 'DISABLED'}", source=self.name)
        for mod in self.modules.values():
            try:
                if hasattr(mod, "debug"):
                    mod.debug = bool(on) or bool(getattr(mod, "debug", False))
                    if not on:
                        mod.debug = False
            except Exception:
                pass

    def enable_debug(self):
        self.set_debug(True)

    def disable_debug(self):
        self.set_debug(False)

    def set_trace(self, on: bool):
        """Flip DEVILCore + module trace (for modules that honor .trace)."""
        self.trace = bool(on)
        log_system(f"Trace {'ENABLED' if self.trace else 'DISABLED'}", source=self.name)
        for mod in self.modules.values():
            try:
                if hasattr(mod, "trace"):
                    mod.trace = bool(on)
            except Exception:
                pass

    def enable_trace(self):
        self.set_trace(True)

    def disable_trace(self):
        self.set_trace(False)

    # ============================================================
    # Help / Introspection
    # ============================================================
    def _general_help_text(self) -> str:
        return (
            "K.A.R.I control via UNIX socket\n\n"
            "Core commands:\n"
            "  status                 Show status & module list\n"
            "  debug [on|off|toggle]  Toggle debug logging\n"
            "  trace [on|off|toggle]  Toggle trace breadcrumbs\n"
            "  snapshot               Speak one-line brain snapshot\n"
            "  speak <text...>        Log a line in K.A.R.I voice\n"
            "  phrase <type> [mood]   boot|banter|react [mood]\n"
            "  mods                   List loaded modules\n"
            "  call <Mod> <meth> [json|raw]\n"
            "                         Invoke a module method. Third arg is either\n"
            "                         a JSON object of kwargs or a raw string that\n"
            "                         the module can parse.\n"
            "  help                   This help\n"
            "  help <Mod>             Show a module's actions & notes\n"
            "  help <Mod> <method>    Show method usage & signature\n"
        )

    def _module_help_text(self, mod) -> str:
        md = getattr(mod, "meta_data", {}) or {}
        name = md.get("name") or getattr(mod, "name", mod.__class__.__name__)
        desc = md.get("description", "")
        actions = md.get("actions", [])
        aliases = md.get("aliases", {})
        notes = md.get("help", None)  # optional rich text provided by module

        out = [f"{name}", "-" * len(name)]
        if desc:
            out.append(desc)
            out.append("")
        if actions:
            out.append("Actions:")
            for a in actions:
                alias_to = None
                if isinstance(aliases, dict):
                    alias_to = aliases.get(a)
                if alias_to and alias_to != a:
                    out.append(f"  • {a}  →  {alias_to}")
                else:
                    out.append(f"  • {a}")
            out.append("")
        if aliases and isinstance(aliases, dict):
            # also show reverse aliases for discoverability
            rev = {v: [] for v in aliases.values()}
            for k, v in aliases.items():
                rev.setdefault(v, []).append(k)
            lines = []
            for target, aka in rev.items():
                if aka:
                    lines.append(f"  {target}: {', '.join(sorted(set(aka)))}")
            if lines:
                out.append("Aliases:")
                out.extend(lines)
                out.append("")
        if notes:
            out.append("Notes:")
            out.append(notes.strip())
        return "\n".join(out).rstrip()

    def _method_help_text(self, mod, method_name: str) -> str:
        # try exact/normalized/alias lookup like call-path does
        norm = method_name.replace("-", "_")
        func = getattr(mod, norm, None)
        if not callable(func):
            for attr in dir(mod):
                if attr.lower() == norm.lower() and callable(getattr(mod, attr)):
                    func = getattr(mod, attr)
                    break
        if not callable(func):
            aliases = getattr(mod, "meta_data", {}).get("aliases", {})
            alias_target = aliases.get(method_name) or aliases.get(norm)
            if alias_target and hasattr(mod, alias_target):
                cand = getattr(mod, alias_target)
                if callable(cand):
                    func = cand
        if not callable(func):
            return f"Method not found: {method_name}"

        # Signature & docstring
        try:
            sig = str(inspect.signature(func))
        except Exception:
            sig = "(...)"
        doc = inspect.getdoc(func) or "No docstring available."
        lines = [f"{mod.meta_data.get('name', mod.__class__.__name__)}.{method_name}{sig}", "-" * 40, doc]

        # If module provides structured help for method:
        md_help = getattr(mod, "meta_data", {}).get("help", {})
        if isinstance(md_help, dict):
            extra = md_help.get(method_name) or md_help.get(norm)
            if extra:
                lines.append("")
                lines.append(extra.strip())

        # Friendly examples if we can infer them
        lines.append("")
        lines.append("Examples:")
        lines.append(f"  kari call {mod.meta_data.get('name', 'Module')} {method_name} '{{}}'")
        lines.append(f"  kari call {mod.meta_data.get('name', 'Module')} {method_name} 'raw args here'")
        return "\n".join(lines).rstrip()

    # ============================================================
    # Convenience hooks for control server
    # ============================================================
    def get_module(self, name: str):
        """Find a module by the human name (e.g., 'VoiceBox')."""
        m = self.modules.get(name)
        if m:
            return m
        # soft fallback: title-cased
        return self.modules.get(name.title())

    def list_modules(self):
        return {
            "internal": list(self.attached_internal),
            "prosthetic": list(self.attached_prosthetic),
        }

    async def trigger_phrase(self, phrase: str, mood: str | None = None):
        """Route a phrase via VoiceBox if ready."""
        if not (self.voice and getattr(self.voice, "ready", False)):
            raise RuntimeError("VoiceBox not ready")
        if self.memory and not mood:
            mood = self.memory.get_current_mood()
        await self.voice.say(
            phrase_type=phrase,
            mood=mood,
            context={**self.data_store, **self.data_store.get("vitals", {})},
        )

    # ============================================================
    # Chatty brain snapshot helpers
    # ============================================================
    def brain_snapshot_text(self):
        v = self.data_store.get("vitals", {}) or {}
        ssid = self.data_store.get("last_seen_wifi") or "—"
        try:
            temp = v.get("temperature")
            temp_str = f"{temp}°C" if temp is not None else "n/a"
        except Exception:
            temp_str = "n/a"
        return (
            f"Vitals: CPU {int(v.get('cpu_usage', 0))}% · MEM {int(v.get('mem_usage', 0))}% · TEMP {temp_str}. "
            f"Link: {ssid}. "
            f"Modules online: {len(self.attached_internal)} internal / {len(self.attached_prosthetic)} prosthetic. "
            f"Uptime: {int(time.time() - self.boot_time)}s. "
            f"Tick: {self.data_store.get('tick', 0)}."
        )

    async def speak_brain_snapshot(self):
        """Have K.A.R.I. say a one-line snapshot into chat (not just logs)."""
        if not (self.voice and getattr(self.voice, 'ready', False)):
            log_system("VoiceBox not ready for brain snapshot.", source=self.name, level="WARN")
            return
        from core.logger import log_kari
        log_kari(self.brain_snapshot_text(), module_name="K.A.R.I")

    # ============================================================
    # Auto-Pip: Per-module requirements installer (env-togglable)
    # ============================================================
    @staticmethod
    def _which_python() -> str:
        # Prefer explicit override, else use this running interpreter (the venv python via systemd)
        return os.environ.get("KARI_PYTHON", sys.executable)

    @staticmethod
    def _pip_install_requirements(req_file: Path, *, log) -> bool:
        """
        Install requirements.txt into the service's venv using the current python.
        Returns True on success, False on failure.
        """
        pip_args = os.getenv("KARI_PIP_ARGS", "").strip()
        cmd = [DEVILCore._which_python(), "-m", "pip", "install"]
        if pip_args:
            cmd += pip_args.split()
        cmd += ["-r", str(req_file)]
        try:
            log(f"[AutoPip] Installing {req_file} ...", level="INFO")
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode == 0:
                log("[AutoPip] Installation OK.", level="INFO")
                return True
            log(f"[AutoPip] Failed to install {req_file}:\n{p.stdout}\n{p.stderr}", level="WARN")
            return False
        except Exception as e:
            log(f"[AutoPip] Exception while installing {req_file}: {e}", level="WARN")
            return False

    def _import_module_from_path(self, module_name: str, module_path: str):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # may raise
        return mod

    def _try_import_with_requirements(self, module_name: str, module_path: str, module_folder: str):
        """
        Attempt to import a module. On ModuleNotFoundError, if the folder has a requirements.txt
        and KARI_AUTO_PIP=1 (default), try installing then retry import once.
        """
        auto_pip = os.getenv("KARI_AUTO_PIP", "1") == "1"

        def _log(msg, level="INFO"):
            log_system(msg, source=self.name, level=level)

        try:
            return self._import_module_from_path(module_name, module_path)
        except ModuleNotFoundError as e:
            _log(f"[Loader] Missing dependency for '{module_name}': {e}", level="WARN")
            req = Path(module_folder) / "requirements.txt"
            if auto_pip and req.exists():
                ok = self._pip_install_requirements(req, log=_log)
                if ok:
                    try:
                        return self._import_module_from_path(module_name, module_path)
                    except Exception as e2:
                        _log(f"[Loader] Import still failing after installing requirements: {e2}", level="WARN")
                        return None
            return None
        except Exception as e:
            _log(f"[Loader] Error importing '{module_name}': {e}", level="WARN")
            return None

    # ============================================================
    # Module attach / scan
    # ============================================================
    async def attach(self, module, source_category="internal"):
        organ_name = getattr(module, "name", module.__class__.__name__)
        version = getattr(module, "meta_data", {}).get("version", "?.?")
        log_divider()
        log_system(f"{source_category.title()} module detected: {organ_name} v{version}", source=self.name)
        print("")
        await asyncio.sleep(random.uniform(0.5, 1.5))

        if self.debug:
            log_system(
                f"[DEBUG] Attaching module '{organ_name}' from category '{source_category}'",
                source=self.name,
                level="DEBUG",
            )
            print("")

        log_system(f"Initializing {organ_name}...", source=self.name)
        print("")
        await asyncio.sleep(random.uniform(0.3, 1.0))

        self.modules[organ_name] = module

        # Bind core + propagate debug/trace (module keeps its own True if already set)
        setattr(module, "core", self)
        try:
            current_debug = bool(getattr(module, "debug"))
        except Exception:
            current_debug = False
        setattr(module, "debug", current_debug or self.debug)

        if hasattr(module, "trace"):
            try:
                module.trace = bool(getattr(module, "trace")) or bool(self.trace)
            except Exception:
                module.trace = bool(self.trace)

        log_system("Engaging neural handshake...", source=self.name)
        print("")
        await asyncio.sleep(random.uniform(0.3, 1.0))

        # Synchronous init hook
        if hasattr(module, "init"):
            if organ_name.lower() == "heartbeat" and hasattr(module, "get_vitals"):
                self.data_store["vitals"] = module.get_vitals()
            module.init()

        # Async initialize hook
        if hasattr(module, "initialize") and inspect.iscoroutinefunction(module.initialize):
            await module.initialize()

        if organ_name.lower() == "voicebox":
            self.voice = module
            self.voice.ready = getattr(self.voice, "ready", False)

        await asyncio.sleep(random.uniform(0.3, 1.0))

        actions = getattr(module, "meta_data", {}).get("actions", [])

        log_system("Routing quantum interlink node...", source=self.name)
        print("")
        await asyncio.sleep(random.uniform(0.3, 1.0))

        if actions:
            log_system("Available actions:", source=organ_name)
            for act in actions:
                log_system(f" • {act}", source=organ_name)

        if source_category == "internal":
            self.attached_internal.append(organ_name)
        else:
            self.attached_prosthetic.append(organ_name)

        is_ready = getattr(module, "ready", False)
        print("")
        if is_ready:
            log_system(f"{organ_name} reports READY status", source=self.name)
        else:
            log_system(f"{organ_name} did NOT report ready status ❌", source=self.name)
            if self.memory:
                self.memory.log_event(
                    organ_name, "ERROR", "Module attached but did not confirm ready status."
                )
        self.ready_modules[organ_name] = is_ready

        # Boot phrase
        if self.memory and self.voice and getattr(self.voice, "ready", False):
            log_divider()
            try:
                mood = self.memory.get_current_mood()
                module_root = getattr(module, "__path_hint__", os.path.dirname(__file__))
                phrases_dir = os.path.join(module_root, "phrases")
                if not os.path.isdir(phrases_dir):
                    phrases_dir = None

                if self.debug:
                    log_system(f"Trying to speak boot phrase for {organ_name}", source="K.A.R.I.", level="DEBUG")
                    log_system(f" → Mood: {mood}", source="K.A.R.I.", level="DEBUG")
                    log_system(f" → Phrases dir: {phrases_dir or '(none)'}", source="K.A.R.I.", level="DEBUG")

                await self.voice.say(
                    phrase_type="boot",
                    mood=mood,
                    module_path=phrases_dir,  # VoiceBox will fall back to persona/core if None
                    context={**self.data_store, **self.data_store.get("vitals", {})},
                )
            except Exception as e:
                log_system(
                    f"K.A.R.I. failed to speak boot line for {organ_name}: {e}",
                    source=self.name,
                    level="WARN",
                )

        if organ_name.lower() == "heartbeat" and hasattr(module, "get_vitals"):
            self.data_store["vitals"] = module.get_vitals()

    async def scan_and_attach(self, path, category="internal"):
        log_divider()
        log_system(f"Scanning '{path}/' for {category} modules...", source=self.name)
        await asyncio.sleep(0.2)

        attached_before = len(self.attached_internal) + len(self.attached_prosthetic)

        for entry in os.scandir(path):
            if not entry.is_dir():
                continue
            if os.path.basename(entry.path).startswith("_"):
                continue
            folder = entry.path
            for file in os.listdir(folder):
                if not file.endswith(".py") or file.startswith("__"):
                    continue
                module_path = os.path.join(folder, file)
                module_name = os.path.splitext(file)[0]
                class_name = "".join(part.capitalize() for part in module_name.split("_"))

                if module_name in self.ghost_modules:
                    continue

                try:
                    # Try import; if deps missing and requirements.txt exists, auto-pip then retry.
                    mod = self._try_import_with_requirements(module_name, module_path, folder)
                    if not mod:
                        raise RuntimeError("import failed")

                    if hasattr(mod, "meta_data") and hasattr(mod, class_name):
                        instance = getattr(mod, class_name)()
                        setattr(instance, "meta_data", mod.meta_data)
                        setattr(instance, "__path_hint__", os.path.dirname(module_path))
                        await self.attach(instance, source_category=category)
                        if self.memory:
                            self.memory.log_event(
                                instance.name, "INFO", f"{module_name} attached from {folder}"
                            )
                    else:
                        log_system(
                            f"Skipping '{module_name}': missing 'meta_data' or class '{class_name}'.",
                            source=self.name,
                            level="WARN",
                        )
                        if self.memory:
                            self.memory.log_event(
                                self.name, "WARNING", f"Skipped '{module_name}': missing class or meta."
                            )
                except Exception as e:
                    log_system(f"Error loading '{module_name}': {str(e)}", source=self.name, level="WARN")
                    if self.memory:
                        self.memory.log_event(
                            self.name, "ERROR", f"Failed to attach {module_name}: {str(e)}"
                        )
                    log_divider()

        attached_after = len(self.attached_internal) + len(self.attached_prosthetic)
        count = attached_after - attached_before
        log_system(
            f"Scan complete. {count} {category} module{'s' if count != 1 else ''} attached.",
            source=self.name,
        )
        if self.memory:
            self.memory.log_event(
                self.name, "INFO", f"Completed scan of '{path}', {count} modules attached."
            )

    # ============================================================
    # Summary / UI
    # ============================================================
    async def show_summary(self):
        log_divider()
        if self.attached_internal:
            log_system("Internal modules loaded:", source=self.name)
            print("")
            for name in self.attached_internal:
                version = self.modules[name].meta_data.get("version", "?.?")
                log_system(f"  • {name} v{version}", source=self.name)
            print("")
            log_divider()
        if self.attached_prosthetic:
            log_system("Prosthetic modules loaded:", source=self.name)
            print("")
            for name in self.attached_prosthetic:
                version = self.modules[name].meta_data.get("version", "?.?")
                log_system(f"  • {name} v{version}", source=self.name)
            print("")
            log_divider()
        total = len(self.attached_internal) + len(self.attached_prosthetic)
        ready = sum(self.ready_modules.get(name, False) for name in self.ready_modules)
        percent = (ready / total) * 100 if total > 0 else 0
        if ready == total:
            log_system("All core systems verified ONLINE.", source=self.name)
        else:
            log_system(
                f"⚠️ System integrity check: {ready}/{total} modules responsive ({percent:.1f}%)",
                source=self.name,
            )
        log_divider()
        log_system("Preparing interface...", source=self.name)
        log_divider()
        await asyncio.sleep(3)
        detach_retina()

        # >>> Switch logger to runtime (stop boxing K.A.R.I. lines when policy=boot)
        mark_main_loop_started()

    # ============================================================
    # Runtime helpers (brain-cycle + housekeeping)
    # ============================================================
    def _jittered(self, base: float, j: float) -> float:
        j = max(0.0, min(j, 0.5))
        span = base * j
        return base + random.uniform(-span, span)

    def _collect_actions(self) -> list[str]:
        # Base, safe enums; add module-advertised actions opportunistically
        core_actions = [
            "scan_network", "crack_password", "complain", "insult_user",
            "check_thermals", "reload_modules",
            "scan_and_attach", "list_modules", "get_module", "trigger_phrase",
            "speak_brain_snapshot", "show_summary", "pulse",
            "enable_debug", "disable_debug", "cooldown", "self_log"
        ]
        seen = {a for a in core_actions}
        for mod in self.modules.values():
            try:
                for a in getattr(mod, "meta_data", {}).get("actions", []):
                    if isinstance(a, str) and a and a not in seen and len(seen) < 32:
                        seen.add(a)
            except Exception:
                pass
        return list(seen)

    def _build_status_packet(self) -> str:
        v = self.data_store.get("vitals", {}) or {}
        cpu = f"{int(v.get('cpu_usage', 0))}%"
        mem = v.get('mem_usage')
        if isinstance(mem, (int, float)):
            mem = f"{int(mem)}%"
        else:
            mem = str(mem or "n/a")
        disk = self.data_store.get("disk_usage", "n/a")

        mood_txt = "neutral"
        if self.memory:
            try:
                m = self.memory.get_current_mood()
                mood_txt = m if m else "neutral"
            except Exception:
                pass

        notes = []
        if self.memory and hasattr(self.memory, "recent_notes"):
            try:
                notes = list(self.memory.recent_notes(limit=6))
            except Exception:
                notes = []

        lines = [
            "SYSTEM STATUS PACKET // DEVIL CORE SNAPSHOT",
            "",
            f"CPU Load: {cpu}",
            f"RAM Usage: {mem}",
            f"Storage Usage: {disk}",
            f"Mood: {mood_txt}",
            "",
            "Notes:",
            "{",
        ]
        if notes:
            for n in notes:
                lines.append(f'  "{str(n)}",')
        else:
            lines.append('  "No notable events logged.",')
        lines.append("}")
        lines.append("")
        actions = self._collect_actions()
        lines.append("available actions:")
        lines.append("{")
        for a in actions:
            lines.append(f'  "{a}",')
        lines.append("}")
        lines.append("")
        lines.append('Respond EXACTLY with:')
        lines.append('{')
        lines.append('  "summary": "<short technical summary>",')
        lines.append('  "focus": "<which subsystem to handle next>",')
        lines.append('  "action": "<one enum action>"')
        lines.append('  "quote": "<one mood-correct comment,relating to the action, in the first person. (you are K.A.R.I)>"')
        lines.append('}')
        lines.append("")
        lines.append("BEGIN CYCLE >>")
        return "\n".join(lines)

    def _update_disk_usage(self):
        # Optional: capture disk usage for the packet
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free  = st.f_bfree  * st.f_frsize
            used  = total - free
            self.data_store["disk_usage"] = f"{used//(1024**3)}GB used / {total//(1024**3)}GB"
        except Exception:
            pass

    # ============================================================
    # Runtime loop
    # ============================================================
    def pulse(self):
        self.tick_count += 1
        self.data_store["tick"] = self.tick_count  # <- keep {tick} current
        if self.tick_count % 20 == 0:
            self._update_disk_usage()
        if self.tick_count % 100 == 0:
            log_system("System pulse verified.", source=self.name, level="DEBUG")

        for mod in list(self.modules.values()):
            try:
                if hasattr(mod, "meta_data"):
                    for action in mod.meta_data.get("pulse", []):
                        method = getattr(mod, action, None)
                        if callable(method):
                            if inspect.iscoroutinefunction(method):
                                asyncio.create_task(method())
                            else:
                                method()
            except Exception as e:
                log_system(
                    f"Pulse dispatch error in {getattr(mod, 'name', mod)}: {e}",
                    source=self.name,
                    level="WARN",
                )

    async def background_kari_banter(self):
        if not self._devil_banter_enabled:
            return
        await asyncio.sleep(random.randint(30, 120))  # Initial wait
        while True:
            try:
                if self.voice and getattr(self.voice, "ready", False) and self.memory:
                    mood = self.memory.get_current_mood()
                    await self.voice.say(
                        phrase_type="banter",
                        mood=mood,
                        context={**self.data_store, **self.data_store.get("vitals", {})},
                    )
            except Exception as e:
                log_system(
                    f"K.A.R.I. background banter error: {e}", source="K.A.R.I", level="DEBUG"
                )
            await asyncio.sleep(random.randint(30, 120))

    async def background_brain_cycle(self):
        if not self._brain_enabled:
            return

        def _llm_mod():
            return self.get_module("LlmModel") or self.get_module("llmmodel")

        # stagger the first call
        await asyncio.sleep(self._jittered(self._brain_interval, self._brain_jitter))
        while True:
            try:
                mod = _llm_mod()
                if mod and getattr(mod, "ready", False):
                    packet = self._build_status_packet()
                    actions = self._collect_actions()
                    result = mod.decide_from_snapshot(
                        packet,
                        actions,
                        max_tokens=self._brain_tokens,
                        timeout=self._brain_timeout,
                    )

                    # Log compact JSON and speak quote if possible
                    try:
                        from core.logger import log_kari
                        log_system(f"[DECIDE] {json.dumps(result, ensure_ascii=False)}", source="K.A.R.I")
                        if result.get("quote") and self.voice and getattr(self.voice, "ready", False):
                            log_kari(result["quote"], module_name="K.A.R.I")
                    except Exception:
                        pass

                    # Act on a tiny safe subset
                    act = str(result.get("action") or "").strip()
                    if act == "speak_brain_snapshot":
                        await self.speak_brain_snapshot()
                    elif act == "show_summary":
                        await self.show_summary()
                    elif act == "enable_debug":
                        self.enable_debug()
                    elif act == "disable_debug":
                        self.disable_debug()
                    elif act == "cooldown":
                        pass  # intentionally idle
                    # Wire more actions explicitly when ready.
            except Exception as e:
                log_system(f"Brain cycle error: {e}", source=self.name, level="WARN")

            await asyncio.sleep(self._jittered(self._brain_interval, self._brain_jitter))

    async def run_forever(self):
        # Ensure the control socket is up once the loop is alive.
        if self._socket_enabled and (self._start_socket_later or self._socket_task is None):
            self._socket_task = asyncio.create_task(self._start_control_socket())
            self._start_socket_later = False

        # Safety net: ensure dividers are disabled for runtime if policy=boot
        mark_main_loop_started()

        asyncio.create_task(self.background_kari_banter())
        asyncio.create_task(self.background_brain_cycle())  # ← JSON decision loop
        try:
            while True:
                self.pulse()
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            log_system("DEVILCore main loop cancelled.", source=self.name)
        except KeyboardInterrupt:
            log_system("KeyboardInterrupt: DEVILCore shutting down...", source=self.name)

    # ============================================================
    # Control socket (private)
    # ============================================================
    async def _start_control_socket(self):
        """Bring up an asyncio UNIX socket server for live control."""
        path = pathlib.Path(self._socket_path)

        # ensure parent dir
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # fallback to /tmp if /run/kari/ not writable
            path = pathlib.Path("/tmp/kari.sock")

        # cleanup stale
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

        server = await asyncio.start_unix_server(self._handle_client, path=str(path))

        # permissions / ownership
        try:
            os.chmod(path, 0o660)
        except Exception:
            try:
                os.chmod(path, 0o660)
            except Exception:
                pass
        try:
            user = os.getenv("KARI_USER")
            group = os.getenv("KARI_GROUP") or user
            if user and pwd and grp:
                uid = pwd.getpwnam(user).pw_uid
                gid = grp.getgrnam(group).gr_gid if group else -1
                os.chown(path, uid, gid)
        except Exception:
            # not fatal; leave defaults
            pass

        self._socket_path = str(path)
        log_system(f"Control socket listening on {self._socket_path}", source=self.name)

        # keep serving forever
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Very small text protocol: each line is one command; reply is one JSON line."""
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                return
            line = data.decode("utf-8", "ignore").strip()
            if not line:
                writer.write(b'{"ok":false,"error":"empty command"}\n')
                await writer.drain()
                writer.close()
                return
            cmd, *rest = shlex.split(line)
            result = await self._dispatch_command(cmd.lower(), rest)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        try:
            writer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _dispatch_command(self, cmd: str, args: list[str]):
        # helpers to keep replies consistent
        def ok(**payload):
            out = {"ok": True}
            out.update(payload)
            return out

        def fail(msg):
            return {"ok": False, "error": msg}

        if cmd in ("ping", "hi"):
            return ok(pong=True)

        if cmd == "status":
            return ok(
                status=self.status,
                tick=self.data_store.get("tick", 0),
                uptime=int(time.time() - self.boot_time),
                modules=self.list_modules(),
                debug=self.debug,
                trace=self.trace,
            )

        if cmd == "debug":
            if not args:
                return ok(debug=self.debug)
            sw = args[0].lower()
            if sw in ("on", "1", "true"):
                self.enable_debug()
            elif sw in ("off", "0", "false"):
                self.disable_debug()
            elif sw in ("toggle", "t"):
                self.set_debug(not self.debug)
            return ok(debug=self.debug)

        if cmd == "trace":
            if not args:
                return ok(trace=self.trace)
            sw = args[0].lower()
            if sw in ("on", "1", "true"):
                self.enable_trace()
            elif sw in ("off", "0", "false"):
                self.disable_trace()
            elif sw in ("toggle", "t"):
                self.set_trace(not self.trace)
            return ok(trace=self.trace)

        if cmd == "snapshot":
            await self.speak_brain_snapshot()
            return ok(spoken=True, text=self.brain_snapshot_text())

        if cmd == "speak":
            if not self.voice or not getattr(self.voice, "ready", False):
                return fail("VoiceBox not ready")
            text = " ".join(args)
            from core.logger import log_kari
            log_kari(text, module_name="K.A.R.I")
            return ok(spoken=True)

        if cmd == "phrase":
            # phrase boot|banter|react [mood]
            if not args:
                return fail("Usage: phrase <type> [mood]")
            ptype = args[0]
            mood = args[1] if len(args) > 1 else None
            await self.trigger_phrase(ptype, mood=mood)
            return ok(phrase=ptype, mood=mood or (self.memory.get_current_mood() if self.memory else None))

        if cmd in ("mods", "modules"):
            return ok(**self.list_modules())

        # ---------------- HELP ----------------
        if cmd == "help":
            # usage:
            #   help                     -> core help
            #   help <Module>            -> module overview + actions
            #   help <Module> <action>   -> action-specific help if available
            if not args:
                lines = [
                    "K.A.R.I. Help",
                    "",
                    "Core commands:",
                    "  status                – system status snapshot",
                    "  mods|modules          – list loaded modules",
                    "  speak <text...>       – print a line as K.A.R.I.",
                    "  phrase <type> [mood]  – boot|banter|react",
                    "  debug on|off|toggle   – toggle debug logs",
                    "  trace on|off|toggle   – toggle trace",
                    "  call <Mod> <meth> [json|raw] – invoke module method",
                    "  help <Mod> [action]   – module/action help",
                    "",
                    "Examples:",
                    "  help Lokisfury",
                    "  help Lokisfury portscan",
                    "  call Lokisfury portscan '{\"target\":\"127.0.0.1\",\"max_port\":200}'",
                ]
                return ok(text="\n".join(lines))

            mod_name = args[0]
            mod = self.get_module(mod_name)
            if not mod:
                return fail(f"Module not found: {mod_name}")

            meta = getattr(mod, "meta_data", {}) or {}
            help_obj = meta.get("help")
            actions = list(meta.get("actions", []) or [])
            aliases = meta.get("aliases", {}) or {}

            # ----- Module-level help (no action specified) -----
            if len(args) == 1:
                header = f"{getattr(mod, 'name', mod_name)} — {meta.get('description', '')}".rstrip()
                body = ""
                if isinstance(help_obj, str):
                    body = help_obj.strip()
                elif isinstance(help_obj, dict):
                    body = (help_obj.get("_module") or help_obj.get("module") or "").strip()

                lines = [header]
                if body:
                    lines += ["", body]

                if actions:
                    lines += ["", "Actions:"]
                    # show unique, de-aliased action names prettily
                    shown = set()
                    for a in actions:
                        if a in shown:
                            continue
                        shown.add(a)
                        lines.append(f"  • {a}")
                return ok(text="\n".join(lines))

            # ----- Action-level help -----
            action = args[1]
            norm = action.replace("-", "_")

            # Resolve via aliases if needed
            alias_target = aliases.get(action) or aliases.get(norm)
            if alias_target:
                norm = alias_target.replace("-", "_")

            text = None
            if isinstance(help_obj, dict):
                # try exact, then normalized, then alias target
                text = (
                    help_obj.get(action)
                    or help_obj.get(norm)
                    or (help_obj.get(alias_target) if alias_target else None)
                )

            if not text:
                # default fallback if module didn’t provide action help
                text = (
                    f"Usage:\n"
                    f"  kari call {getattr(mod, 'name', mod_name)} {action} '{{}}'\n"
                    f"(No action-specific help was provided by the module.)"
                )

            return ok(text=str(text))

        # ---------------- CALL ----------------
        if cmd == "call":
            # call <ModuleName> <method> [json_args or raw...]
            if len(args) < 2:
                return fail("Usage: call <ModuleName> <method> [json_args|raw_args]")

            mod_name_raw, method_raw = args[0], args[1]

            # --- module lookup (exact -> TitleCase) ---
            mod = self.get_module(mod_name_raw)
            if not mod:
                return fail(f"Module not found: {mod_name_raw}")

            # --- parse kwargs OR fall back to raw string ---
            kwargs = {}
            if len(args) >= 3:
                third = args[2]
                try:
                    parsed = json.loads(third)
                    if isinstance(parsed, dict):
                        kwargs = parsed
                    else:
                        return fail("json_args must be an object")
                except Exception:
                    # fallback: pass the rest as a raw string and token list
                    raw_tail = " ".join(args[2:])
                    kwargs = {"raw": raw_tail, "args": args[2:]}

            # --- method normalization & aliasing ---
            method_norm = method_raw.replace("-", "_")

            func = getattr(mod, method_norm, None)
            if not callable(func):
                # case-insensitive sweep
                for attr in dir(mod):
                    if attr.lower() == method_norm.lower():
                        cand = getattr(mod, attr)
                        if callable(cand):
                            func = cand
                            break

            if not callable(func):
                # alias map from module meta_data
                aliases = getattr(mod, "meta_data", {}).get("aliases", {})
                alias_target = aliases.get(method_raw) or aliases.get(method_norm)
                if alias_target and hasattr(mod, alias_target):
                    cand = getattr(mod, alias_target)
                    if callable(cand):
                        func = cand

            if not callable(func):
                return fail(f"Method not found: {method_raw}")

            # --- invoke (await if coroutine) ---
            if inspect.iscoroutinefunction(func):
                out = await func(**kwargs)
            else:
                out = func(**kwargs)

            # ensure JSON-able
            try:
                json.dumps(out)
            except Exception:
                out = str(out)

            return ok(result=out)

        return fail(f"Unknown command: {cmd}")
