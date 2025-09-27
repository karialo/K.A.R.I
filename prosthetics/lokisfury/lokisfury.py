# prosthetics/lokisfury/lokisfury.py
# Clean, core-compatible Lokisfury prosthetic for K.A.R.I.
# - preserves meta_data used by DEVILCore for discovery
# - lifecycle hooks (init, start/stop not required by generator but kept)
# - action methods accept optional (ctx, raw_args) for flexible invocation
#
# Design choices:
# - Action handlers return plain text (string) when called with args.
# - If called without args (old-style call), they log the intent and return None.
# - Uses LokisFury internals (network/hashes) when available; falls back to stdlib.
# - Minimal, robust argument parsing with shlex.
# - No TUI / spinner usage inside module (headless-friendly).

import os
import shlex
import socket
import platform
import getpass
import requests
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.logger import log_system, log_kari
from core.personality import get_phrase

# Optional MemoryCortex; gracefully degrade if absent
try:
    from internal.memory_cortex.memory_cortex import MemoryCortex
except Exception:
    MemoryCortex = None  # type: ignore

# Try to reuse your LokisFury package internals if present
try:
    from LokisFury import network as lf_net
    from LokisFury import hashes as lf_hashes
except Exception:
    lf_net = None
    lf_hashes = None

# Debug flag: environment override or core settings
try:
    from core import settings as _kari_settings  # may define DEBUG
    DEBUG = bool(int(os.environ.get("KARI_DEBUG", "0"))) or bool(getattr(_kari_settings, "DEBUG", False))
except Exception:
    DEBUG = bool(int(os.environ.get("KARI_DEBUG", "0")))

meta_data = {
    "name": "Lokisfury",
    "version": "1.0",
    "author": "Change me",
    "description": "Network and hash utilities (portscan, public-ip, hasher, hashcrack, localinfo)",
    "category": "prosthetic",
    "actions": ['portscan', 'public-ip', 'hasher', 'hashcrack', 'localinfo'],
    "manual_actions": [
        { "name": "Report Module Alive", "function": "report_alive" },
        { "name": "Display Module Info", "function": "display_info" }
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["cpu_usage", "mem_usage"]
}


class Lokisfury:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data = {}
        self.core = None  # assigned by DEVILCore at runtime
        self.ready = False
        self.available_phrases = []

    # -------------------------- lifecycle --------------------------------
    def init(self):
        """Called by the core when loading the module (generator expects this)."""
        self.ready = False
        self.available_phrases = self._load_available_phrases()
        if self.available_phrases:
            log_system("Available phrase triggers loaded:", source=self.name)
            for phrase in sorted(self.available_phrases):
                log_system(f" • {phrase}", source=self.name)
        else:
            log_system("No phrase files detected. K.A.R.I. may be speechless.", source=self.name)
        if DEBUG:
            log_system("DEBUG enabled for module.", source=self.name)
        self.ready = True

    # --------------------------- utils -----------------------------------
    def log(self, message: str):
        """Convenience wrapper to the core logger(s)."""
        try:
            log_system(message, source=self.name)
        except Exception:
            # best-effort fallback
            try:
                log_kari(message)
            except Exception:
                print(f"[{self.name}] {message}")

    def _current_mood(self) -> str:
        if MemoryCortex:
            try:
                return MemoryCortex().get_current_mood() or "neutral"
            except Exception:
                return "neutral"
        return "neutral"

    def _safe_phrase(self, module_key: str, tag: str, mood: str):
        try:
            return get_phrase(module_key, tag, mood)
        except Exception as e:
            if DEBUG:
                self.log(f"get_phrase() failed for tag '{tag}' mood '{mood}': {e}")
            return f"[{self.name}] ({mood}) {tag}"

    def react(self, phrase_file: str, override_mood: str | None = None) -> str:
        mood = override_mood or self._current_mood()
        return self._safe_phrase("lokisfury", phrase_file, mood)

    def _load_available_phrases(self):
        phrases_path = os.path.join(os.path.dirname(__file__), "phrases")
        if not os.path.exists(phrases_path):
            return []
        subdirs = [f for f in os.listdir(phrases_path) if os.path.isdir(os.path.join(phrases_path, f))]
        return subdirs

    # -------------------------- diagnostics -------------------------------
    def report_alive(self):
        self.log("Status: Online and operational.")
        return "OK"

    def display_info(self):
        for key, value in self.meta_data.items():
            self.log(f"{key}: {value}")
        return self.collect_info()

    def healthcheck(self):
        return {
            "name": self.name,
            "ready": self.ready,
            "has_core": self.core is not None
        }

    # ----------------------- DEVILCore data sync --------------------------
    def pulse(self):
        """Called periodically by core to sync shared data into module."""
        if hasattr(self, "core") and hasattr(self.core, "data_store") and self.core.data_store is not None:
            try:
                self.shared_data.update(self.core.data_store)  # shallow sync
                if DEBUG:
                    cpu = self.shared_data.get("cpu_usage")
                    mem = self.shared_data.get("mem_usage")
                    if cpu is not None or mem is not None:
                        self.log(f"Synced shared data (cpu={cpu}, mem={mem})")
                    else:
                        self.log("Synced shared data.")
            except Exception as e:
                self.log(f"Pulse sync failed: {e}")
        else:
            if DEBUG:
                self.log("No DEVILCore data_store to sync.")

    def push_shared_data(self):
        """Optional; publish data back into core.data_store if needed."""
        if hasattr(self, "core") and hasattr(self.core, "data_store") and self.core.data_store is not None:
            # Example: self.core.data_store["last_"+self.name] = "timestamp"
            pass

    def show_shared_data(self):
        if not self.shared_data:
            self.log("No shared data found.")
        else:
            self.log("Shared data:")
            for k, v in self.shared_data.items():
                self.log(f"  {k}: {v}")

    def collect_info(self):
        return {
            "Module Info": {
                "name": self.meta_data["name"],
                "version": self.meta_data["version"],
                "author": self.meta_data["author"],
                "description": self.meta_data["description"]
            },
            "State": {
                "ready": self.ready
            },
            "Actions": self.meta_data.get("actions", [])
        }

    # -------------------------- helpers ----------------------------------
    @staticmethod
    def _auto_algo_from_hash(h: str) -> str | None:
        s = h.strip().lower()
        if all(c in "0123456789abcdef" for c in s):
            L = len(s)
            if L == 32: return "md5"
            if L == 40: return "sha1"
            if L == 64: return "sha256"
            if L == 128: return "sha512"
        return None

    @staticmethod
    def _hash_of(text: str, algo: str) -> str:
        fmap = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
            "sha512": hashlib.sha512,
        }
        if algo not in fmap:
            raise ValueError(f"Unsupported algo: {algo}")
        h = fmap[algo]()
        h.update(text.encode("utf-8", errors="ignore"))
        return h.hexdigest()

    # -------------------------- actions ---------------------------------
    # Note: core may call these as no-arg methods (module.portscan()),
    # or as module.portscan(ctx, raw_args). We support both signatures.

    def public_ip(self, ctx=None, raw_args: str | None = None) -> str | None:
        """Return public IP string when invoked with args (headless)."""
        # If called with no args, just log and return
        if ctx is None and raw_args is None:
            self.log("public-ip requested (no-context).")
            return None
        try:
            ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
            return f"Public IP: {ip}"
        except Exception as e:
            return f"Public IP: Error: {e}"

    def localinfo(self, ctx=None, raw_args: str | None = None) -> str | None:
        if ctx is None and raw_args is None:
            self.log("localinfo requested (no-context).")
            return None
        data = {
            "hostname": socket.gethostname(),
            "username": getpass.getuser(),
            "os": platform.system(),
            "platform": platform.platform()
        }
        longest = max(len(k) for k in data)
        lines = [f"{k.ljust(longest)} : {v}" for k, v in data.items()]
        return "\n".join(lines)

    def portscan(self, ctx=None, raw_args: str | None = None) -> str | None:
        """
        portscan usage (headless): portscan <host> [--max-port N] [--concurrency N] [--timeout S]
        If called without args, logs intent and returns None.
        """
        if ctx is None and raw_args is None:
            self.log("portscan requested (no-context).")
            return None

        args = shlex.split(raw_args or "")
        if not args:
            return "Usage:\n  portscan <host> [--max-port N] [--concurrency N] [--timeout S]"

        # defaults
        host = None
        max_port = 1024
        concurrency = 100
        timeout = 0.3

        i = 0
        while i < len(args):
            a = args[i]
            if a in ("--max-port", "-m") and i + 1 < len(args):
                i += 1; max_port = int(args[i])
            elif a.startswith("--max-port="):
                max_port = int(a.split("=", 1)[1])
            elif a in ("--concurrency", "-c") and i + 1 < len(args):
                i += 1; concurrency = int(args[i])
            elif a.startswith("--concurrency="):
                concurrency = int(a.split("=", 1)[1])
            elif a == "--timeout" and i + 1 < len(args):
                i += 1; timeout = float(args[i])
            elif a.startswith("--timeout="):
                timeout = float(a.split("=", 1)[1])
            elif a.startswith("-"):
                return f"Unknown option: {a}"
            else:
                host = a
            i += 1

        if not host:
            return "Error: host required.\nUsage:\n  portscan <host> [--max-port N] [--concurrency N] [--timeout S]"

        def scan_port(p: int) -> bool:
            if lf_net and hasattr(lf_net, "_scan_port"):
                return lf_net._scan_port(host, p, timeout=timeout)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    return s.connect_ex((host, p)) == 0
            except Exception:
                return False

        open_ports = []
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {ex.submit(scan_port, p): p for p in range(1, max_port)}
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    if fut.result():
                        open_ports.append(p)
                except Exception:
                    pass

        open_ports.sort()
        if open_ports:
            return f"Open ports: {', '.join(map(str, open_ports))}"
        return "No open ports found."

    def hasher(self, ctx=None, raw_args: str | None = None) -> str | None:
        """
        hasher <text> [--algo md5|sha1|sha256|sha512|all]
        """
        if ctx is None and raw_args is None:
            self.log("hasher requested (no-context).")
            return None

        args = shlex.split(raw_args or "")
        if not args:
            return "Usage:\n  hasher <text> [--algo md5|sha1|sha256|sha512|all]"

        text = None
        algo = "all"
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--algo" and i + 1 < len(args):
                i += 1; algo = args[i].lower()
            elif a.startswith("--algo="):
                algo = a.split("=", 1)[1].lower()
            elif a.startswith("-"):
                return f"Unknown option: {a}"
            else:
                text = a if text is None else f"{text} {a}"
            i += 1

        if text is None:
            return "Error: text required.\nUsage:\n  hasher <text> [--algo md5|sha1|sha256|sha512|all]"

        algos = ["md5", "sha1", "sha256", "sha512"] if algo == "all" else [algo]
        lines = []
        for a in algos:
            try:
                digest = self._hash_of(text, a)
                lines.append(f"{a}: {digest}")
            except Exception as e:
                lines.append(f"{a}: Error: {e}")
        return "\n".join(lines)

    def hashcrack(self, ctx=None, raw_args: str | None = None) -> str | None:
        """
        hashcrack <algo|auto> <hash> [--wordlist FILE]
        """
        if ctx is None and raw_args is None:
            self.log("hashcrack requested (no-context).")
            return None

        args = shlex.split(raw_args or "")
        if len(args) < 2:
            return "Usage:\n  hashcrack <algo|auto> <hash> [--wordlist FILE]"

        algo = args[0].lower()
        target = args[1]
        wordlist = None

        for i, a in enumerate(args[2:], start=2):
            if a in ("-w", "--wordlist") and i + 1 < len(args):
                wordlist = args[i + 1]
            elif a.startswith("--wordlist="):
                wordlist = a.split("=", 1)[1]

        if algo == "auto":
            det = self._auto_algo_from_hash(target)
            if not det:
                return "Could not auto-detect algorithm from hash."
            algo = det

        if not wordlist:
            wordlist = os.environ.get("DEFAULT_WORDLIST") or os.path.expanduser("~/.wordlists/rockyou.txt")

        try:
            with open(wordlist, "r", errors="ignore") as fh:
                for line in fh:
                    word = line.strip()
                    if not word:
                        continue
                    if lf_hashes and hasattr(lf_hashes, "_hash_of"):
                        ok = lf_hashes._hash_of(word, algo) == target
                    else:
                        ok = self._hash_of(word, algo) == target
                    if ok:
                        return f"[+] Found: {word}"
            return "[-] Not found in provided wordlist."
        except FileNotFoundError:
            return f"Wordlist not found: {wordlist}"
