# === Net Synapse 🌐 v1.8.3 ===
# Internal network scanner and signal strength monitor for K.A.R.I.
# Emits mood-aware info beats + triggers react phrases on changes.
#
# Changes in 1.8.3:
#   • Mesh-aware SSID summary:
#       - Build a per-SSID, per-band summary (2.4 / 5 / 6E) keeping ALL APs internally
#       - Boot list shows strongest per band + AP count per SSID
#   • Info-beats now:  "<distinct SSIDs> SSIDs / <APs> APs; best “X” 94% (ch 36)."
#   • Still no raw dict/list dumps in persona stream (from 1.8.2)
#       - Phrase context sets `networks` to a COUNT (and adds `networks_count`)
#       - Bus keys use non-colliding names: wifi_networks / wifi_ssids / wifi_count
#
# Env knobs:
#   KARI_NET_SCAN_INTERVAL   default 30 (seconds)
#   KARI_NET_ANNOUNCE_GAP    default 2.0 (seconds)
#   KARI_NET_BOOT_LIST_N     default 12 (max SSID lines at boot)
#   KARI_BANTER              default "1" (enable background banter)
#   KARI_ALLOW_ACTIVE_NET    default "0" (block active recon like deauth)

import os
import shutil
import subprocess
import random
import asyncio
import time
import json
import ipaddress
from typing import Optional, Dict, Any, List

from core.logger import log_system
from internal.memory_cortex.memory_cortex import MemoryCortex

meta_data = {
    "name": "NetSynapse",
    "version": "1.8.3",
    "author": "Hraustligr",
    "description": "Internal network scanner and signal monitor for K.A.R.I.",
    "category": "internal",
    "actions": [
        "initial_scan", "scan", "log_signal", "channel_map",
        "beacon_sweep", "deauth_probe",
        "scan_network", "wifi_scan", "scan_ports",
        "ifaces", "arp_table", "dns_check", "lan_sweep", "recon_dump"
    ],
    "aliases": {
        # legacy -> current
        "scan": "initial_scan"
    },
    "manual_actions": [
        {"name": "Report Module Alive", "function": "report_alive"},
        {"name": "Display Module Info", "function": "display_info"}
    ],
    "pulse": ["pulse"],
    "capabilities": ["neural_sync"],
    "resources": ["networks"],
    "help": {
        "_module": (
            "Net Synapse surveys nearby Wi-Fi, tracks signal health, and surfaces network "
            "context for other modules.\n\n"
            "Actions may shell out to tools like nmcli/ip/ping, so they inherit whatever "
            "permissions the host grants."
        ),
        "initial_scan": (
            "Usage:\n"
            "  initial_scan\n\n"
            "Runs a one-shot nmcli scan, logs strongest SSIDs per band, publishes results "
            "into shared data, and emits info beats. Call at startup or on demand."
        ),
        "scan": (
            "Usage:\n"
            "  scan\n\n"
            "Legacy alias; routes to initial_scan."
        ),
        "scan_network": (
            "Usage:\n"
            "  scan_network\n\n"
            "Passive network refresh for the brain loop. Delegates to initial_scan and returns "
            "a compact summary without extra noise."
        ),
        "wifi_scan": (
            "Usage:\n"
            "  wifi_scan\n\n"
            "Returns parsed nmcli results as JSON (ssid_count, active_ssid). No announcements."
        ),
        "scan_ports": (
            "Usage:\n"
            "  scan_ports {\"target\":\"10.0.0.42\", \"start_port\":1, \"end_port\":1024}\n\n"
            "TCP connect scan with sane defaults. Returns a dict of open ports."
        ),
        "log_signal": (
            "Usage:\n"
            "  log_signal\n\n"
            "Compatibility stub that simply logs the action. Net Synapse now updates "
            "signals automatically during pulses."
        ),
        "channel_map": (
            "Usage:\n"
            "  channel_map\n\n"
            "Placeholder for historical exports. Currently logs the request only."
        ),
        "beacon_sweep": (
            "Usage:\n"
            "  beacon_sweep\n\n"
            "Stub maintained for old scripts. Logs that a sweep was asked for."
        ),
        "deauth_probe": (
            "Usage:\n"
            "  deauth_probe\n\n"
            "Performs an active deauth probe when KARI_ALLOW_ACTIVE_NET=1. Otherwise the "
            "request is blocked and a warning is logged."
        ),
        "ifaces": (
            "Usage:\n"
            "  ifaces\n\n"
            "Returns a JSON object describing network interfaces via `ip -j addr`."
        ),
        "arp_table": (
            "Usage:\n"
            "  arp_table\n\n"
            "Parses `ip neigh show` into a list of neighbors (ip/mac/dev/state)."
        ),
        "dns_check": (
            "Usage:\n"
            "  dns_check {\"host\":\"1.1.1.1\", \"count\":5}\n\n"
            "Pings the host several times and returns latency samples plus the average in ms."
        ),
        "lan_sweep": (
            "Usage:\n"
            "  lan_sweep {\"cidr\":\"192.168.1.0/24\", \"limit\":128, \"timeout_ms\":300}\n\n"
            "ICMP sweeps the subnet (auto-detected if omitted) and lists responsive hosts."
        ),
        "recon_dump": (
            "Usage:\n"
            "  recon_dump\n\n"
            "Collects interfaces, ARP neighbors, DNS timings, LAN sweep results, and Wi-Fi "
            "scan data, then writes a timestamped JSON under /kari/data/net. Path is also "
            "published to shared data as `net_last_recon`."
        ),
        "report_alive": (
            "Usage:\n"
            "  report_alive\n\n"
            "Logs an operational heartbeat line."
        ),
        "display_info": (
            "Usage:\n"
            "  display_info\n\n"
            "Logs module metadata (name, version, author, description)."
        ),
        "show_shared_data": (
            "Usage:\n"
            "  show_shared_data\n\n"
            "Prints the cached shared_data snapshot to the debug log."
        ),
    },
}


DATA_DIR = "/kari/data/net"

class NetSynapse:
    def __init__(self):
        self.meta_data = meta_data
        self.name = self.meta_data["name"]
        self.shared_data: Dict[str, Any] = {}
        self.core = None
        self.ready = False
        self.debug = False  # inherited from DEVILCore.attach()

        self._nmcli = shutil.which("nmcli")
        self._ip = shutil.which("ip")
        self._ping = shutil.which("ping")

        self._banter_enabled = os.getenv("KARI_BANTER", "1") == "1"
        self._allow_active = os.getenv("KARI_ALLOW_ACTIVE_NET", "0") == "1"

        # State for change detection
        self._known_ssids: set[str] = set()
        self._last_active_ssid: Optional[str] = None
        self._last_scan_ts = 0.0
        self._scan_interval = int(os.getenv("KARI_NET_SCAN_INTERVAL", "30"))

        # Announcement rate limiting
        try:
            self._announce_min_gap = float(os.getenv("KARI_NET_ANNOUNCE_GAP", "2"))
        except Exception:
            self._announce_min_gap = 2.0
        self._last_announce_ts = 0.0

        self._cortex = MemoryCortex()
        self._module_phrases = os.path.join(os.path.dirname(__file__), "phrases")

        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception:
            pass

    # ---------- helpers ----------
    def _debug(self, msg):
        if self.debug:
            log_system(f"[DEBUG] {msg}", source=self.name, level="DEBUG")

    def _memory(self) -> MemoryCortex:
        if self.core and getattr(self.core, "memory", None):
            return self.core.memory
        return self._cortex

    def _get_mood(self) -> str:
        try:
            return self._memory().get_current_mood()
        except Exception:
            return "neutral"

    async def _say(self, text: str):
        """Compact info line into K.A.R.I chat stream (rate-limited)."""
        now = time.time()
        gap = now - self._last_announce_ts
        if gap < self._announce_min_gap:
            await asyncio.sleep(self._announce_min_gap - gap)
        self._last_announce_ts = time.time()
        try:
            if self.core and self.core.voice and getattr(self.core.voice, "ready", False):
                from core.logger import log_kari
                log_kari(text, module_name="K.A.R.I")
        except Exception as e:
            self._debug(f"say failure: {e}")

    def _mood_engine(self):
        """Best-effort resolver for the mood engine instance."""
        try:
            if getattr(self, "core", None) and hasattr(self.core, "modules"):
                me = self.core.modules.get("Mood Engine")
                if me: return me
            if getattr(self.core, "mood_engine", None): return self.core.mood_engine
            if getattr(self.core, "mood", None): return self.core.mood
            if getattr(self.core, "modules", None):
                for m in self.core.modules.values():
                    if hasattr(m, "update_from_network"): return m
        except Exception:
            pass
        return None

    def _route_mood_update(self, best_signal: Optional[int]):
        me = self._mood_engine()
        if not me or not hasattr(me, "update_from_network"):
            return
        try:
            me.update_from_network(signal=best_signal)
        except Exception as e:
            self._debug(f"update_from_network failed: {e}")

    def _run(self, cmd, timeout=5) -> str:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
            return out.decode(errors="ignore")
        except Exception as e:
            return f"__ERR__ {e}"

    # ---------- band helpers ----------
    @staticmethod
    def _band_from_chan(chan: str | int | None) -> str:
        """Rough-but-practical band bucketing for nmcli channel integers."""
        try:
            c = int(chan)
        except Exception:
            return "?"
        if 1 <= c <= 14:
            return "2.4"
        if 36 <= c <= 165:
            return "5"
        # Heuristic for 6 GHz: nmcli may show 1..233 for 6E; treat high channel indexes as 6E
        if c >= 181:
            return "6E"
        # Fallback: many mid/high values still 5 GHz in practice
        return "5"

    # ---------- phrase/react wiring ----------
    async def _emit_react(self, event: str, ctx: Dict[str, Any]):
        """
        Fire a react phrase with rich context; event included in ctx['event'].
        Module path ensures we pick up internal phrases/react/<mood>.txt first.
        """
        try:
            mood = self._get_mood()
            payload = dict(ctx)
            payload.setdefault("event", event)
            payload.setdefault("module_name", self.name)
            await self._memory().speak(
                tag="react",
                mood=mood,
                module_path=self._module_phrases,
                return_only=False,
                **payload
            )
        except Exception as e:
            self._debug(f"_emit_react failed: {e}")

    async def _info_beats(self, nets: Dict[str, Any]):
        """Compact, human-ish one-liners to break up chatter (mesh-aware)."""
        parsed: List[Dict[str, Any]] = nets.get("parsed", [])
        total_aps = len(parsed)
        distinct_ssids = len(nets.get("summary", {})) or len(nets.get("ssids", []))
        active = nets.get("active_ssid") or "—"
        best = self._best_network(parsed)
        if best:
            await self._say(
                f"{distinct_ssids} SSIDs / {total_aps} APs; best “{best['ssid']}” {best['signal']}% (ch {best['chan'] or '?'})."
            )
        else:
            await self._say(f"{distinct_ssids} SSIDs detected. Active: {active}.")

    @staticmethod
    def _best_network(parsed: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        best = None
        try:
            cands = [n for n in parsed if n.get("signal") is not None]
            if cands:
                best = max(cands, key=lambda n: n["signal"])
        except Exception:
            pass
        return best

    def _phrase_context_from_scan(self, nets: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build safe phrase context:
          - `networks` is COUNT (prevents list dict-dump in phrases)
          - `networks_count` is explicit count alternative
          - `wifi_seen_str` is a pretty, comma-joined SSID list
          - includes distinct SSID count as `ssid_count`
        """
        parsed = nets.get("parsed", [])
        best = self._best_network(parsed) or {}
        total_aps = len(parsed)
        ssids = [p.get("ssid") for p in parsed if p.get("ssid")]
        ssid_count = len(nets.get("summary", {})) or len(set(ssids))
        ctx = {
            "total_ssids": total_aps,     # legacy naming kept
            "ssid_count": ssid_count,     # distinct SSIDs in a mesh
            "active_ssid": nets.get("active_ssid"),
            "best_signal": best.get("signal"),
            "best_chan": best.get("chan"),
            "ssid": best.get("ssid"),
            "signal": best.get("signal"),
            "chan": best.get("chan"),
            "networks": total_aps,        # <— safe override for {networks}
            "networks_count": total_aps,  # <— explicit alias
            "wifi_seen": ssids,           # raw list if someone explicitly wants it
            "wifi_seen_str": ", ".join(ssids) if ssids else "",
        }
        return ctx

    # ---------- lifecycle ----------
    def init(self):
        self._debug("Initializing Net Synapse module")
        self.available_phrases = self._load_available_phrases()
        if self.available_phrases:
            log_system("Available phrase triggers loaded:", source=self.name)
            for phrase in sorted(self.available_phrases):
                log_system(f" • {phrase}", source=self.name)
        else:
            log_system("No phrase files detected. K.A.R.I. may be speechless.", source=self.name)
        print("")

        self.initial_scan()
        asyncio.create_task(self._background_banter())
        self.ready = True

    # ---------- phrases ----------
    def react(self, phrase_file=None, override_mood=None):
        mood = override_mood or self._get_mood()
        phrase = self._memory()._get_random_phrase("react", mood, module_path=self._module_phrases)
        if not phrase:
            return "[no phrase file]"
        # minimal context if someone calls this directly
        return self._memory().parse_placeholders(phrase, context={"mood": mood, "module_name": self.name})

    def _load_available_phrases(self):
        phrases_path = self._module_phrases
        self._debug(f"Checking phrases in: {phrases_path}")
        if not os.path.exists(phrases_path):
            return []
        return [f for f in os.listdir(phrases_path) if os.path.isdir(os.path.join(phrases_path, f))]

    async def _background_banter(self):
        if not self._banter_enabled:
            self._debug("Background banter disabled by config (KARI_BANTER=0)")
            return
        await asyncio.sleep(random.uniform(5, 10))
        while True:
            delay = random.uniform(120, 180)
            await asyncio.sleep(delay)
            try:
                mood = self._get_mood()
                await self._memory().speak(tag="banter", mood=mood, module_path=self._module_phrases)
            except Exception as e:
                log_system(f"Banter failure in Net Synapse: {e}", source=self.name, level="DEBUG")

    # ---------- core hooks ----------
    def report_alive(self):
        self._debug("report_alive()")
        log_system("Status: Online and operational.", source=self.name)

    def display_info(self):
        self._debug("display_info()")
        for key, value in self.meta_data.items():
            log_system(f"{key}: {value}", source=self.name)

    def help(self, topic: str | None = None) -> str:
        """Return help text stored in meta_data['help']."""
        help_map = getattr(self, "meta_data", {}).get("help", {})
        if not topic:
            return help_map.get("_module", f"{self.name} - no help available.")
        key = topic.replace("-", "_")
        return help_map.get(key, f"No help for '{topic}'.")

    def pulse(self):
        """Periodic rescan and change detection + quick recon surfaces."""
        now = time.time()
        if now - self._last_scan_ts >= self._scan_interval:
            self._last_scan_ts = now
            self._debug("pulse()-> periodic scan")
            self._periodic_scan()

        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            self.shared_data.update(self.core.data_store)

        # surface quick recon shards (non-blocking, best-effort)
        try:
            wifi = self._scan_nmcli_list() or {}
            self.shared_data["wifi_seen"] = [w.get("ssid") for w in wifi.get("parsed", [])][:10]
        except Exception:
            pass
        try:
            neigh = self.arp_table()
            if isinstance(neigh, dict):
                self.shared_data["lan_neighbors"] = [n.get("ip") for n in neigh.get("neighbors", [])][:20]
        except Exception:
            pass

    def push_shared_data(self):
        self._debug("push_shared_data()")

    def show_shared_data(self):
        self._debug("show_shared_data()")
        if not self.shared_data:
            log_system("No shared data found.", source=self.name, level="DEBUG")
        else:
            log_system("Shared data:", source=self.name, level="DEBUG")
            for k, v in self.shared_data.items():
                log_system(f"  {k}: {v}", source=self.name, level="DEBUG")

    # ---------- network ops ----------
    def initial_scan(self):
        self._debug("initial_scan()")
        nets = self._scan_nmcli_list()
        if nets is None:
            log_system("nmcli not found; skipping Wi-Fi scan.", source=self.name, level="WARN")
            print("")
            return

        self._publish_networks(nets, announce=False)

        total_aps = len(nets.get("parsed", []))
        active = nets.get("active_ssid") or "—"

        # best signal for mood + context
        best_signal: Optional[int] = None
        try:
            signals = [n["signal"] for n in nets.get("parsed", []) if n["signal"] is not None]
            best_signal = max(signals) if signals else None
        except Exception:
            pass
        if best_signal is not None:
            self._route_mood_update(best_signal)

        log_system(
            f"Initial network scan complete: {total_aps} SSIDs; active: {active}; "
            f"best signal: {best_signal if best_signal is not None else 'n/a'}",
            source=self.name
        )

        # Compact SSID inventory (mesh-aware: strongest per band, AP count)
        self._log_boot_ssid_list(nets, limit=int(os.getenv("KARI_NET_BOOT_LIST_N", "12")))

        if self.debug:
            for raw in nets.get("raw_lines", []):
                log_system(raw, source=self.name, level="DEBUG")
        print("")

        # info beat + soft react about the current environment
        ctx = self._phrase_context_from_scan(nets)
        asyncio.create_task(self._info_beats(nets))
        asyncio.create_task(self._emit_react("initial_scan", ctx))

    def _periodic_scan(self):
        nets = self._scan_nmcli_list()
        if nets is None:
            return

        parsed = nets.get("parsed", [])
        # Route mood update with strongest signal each pass
        best_signal: Optional[int] = None
        try:
            signals = [n["signal"] for n in parsed if n["signal"] is not None]
            best_signal = max(signals) if signals else None
        except Exception:
            pass
        if best_signal is not None:
            self._route_mood_update(best_signal)

        # Active SSID change?
        active_ssid = nets.get("active_ssid")
        if active_ssid and active_ssid != self._last_active_ssid:
            asyncio.create_task(self._say(f"Link update: now connected to “{active_ssid}”."))
            asyncio.create_task(self._emit_react("link_update", {"active_ssid": active_ssid}))
        elif self._last_active_ssid and active_ssid is None:
            asyncio.create_task(self._say("Link update: disconnected."))
            asyncio.create_task(self._emit_react("link_drop", {"active_ssid": None, "ssid": self._last_active_ssid}))

        # New / vanished SSIDs
        seen = set(nets.get("ssids", []))
        new = sorted(seen - self._known_ssids)
        gone = sorted(self._known_ssids - seen)

        for ssid in new[:5]:
            asyncio.create_task(self._say(f"New network discovered: “{ssid}”."))
            asyncio.create_task(self._emit_react("ssid_new", {"ssid": ssid, **self._phrase_context_from_scan(nets)}))
        for ssid in gone[:5]:
            asyncio.create_task(self._say(f"Network vanished: “{ssid}”. Farewell, ghost Wi-Fi."))
            asyncio.create_task(self._emit_react("ssid_gone", {"ssid": ssid}))

        self._known_ssids = seen
        self._last_active_ssid = active_ssid

        self._publish_networks(nets, announce=False)

        # quick status ping each cycle (not too spammy)
        asyncio.create_task(self._info_beats(nets))

    def _publish_networks(self, nets, announce=True):
        """Publish scan results onto the bus using non-colliding keys."""
        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            self.core.data_store["wifi_networks"] = nets.get("parsed", [])
            self.core.data_store["wifi_ssids"] = nets.get("ssids", [])
            self.core.data_store["wifi_count"] = len(nets.get("parsed", []))
            self.core.data_store["last_seen_wifi"] = nets.get("active_ssid")
        if announce:
            log_system("Networks updated on bus.", source=self.name, level="DEBUG")

    def _log_boot_ssid_list(self, nets, limit=12):
        """
        Pretty boot list: one line per SSID, strongest per band + AP count.
        Example:
          • NWG-Corp — 2.4: 65% (ch 6) | 5: 94% (ch 36) — 3 APs
        """
        summary = nets.get("summary") or {}
        if not summary:
            log_system("No Wi-Fi networks detected.", source=self.name)
            return

        # Sort SSIDs by best available signal across any band (desc), then by name
        def best_sig(ssid):
            bands = summary[ssid]["bands"].values()
            vals = [b["signal"] for b in bands if b.get("signal") is not None]
            return max(vals) if vals else -1

        ssid_order = sorted(summary.keys(), key=lambda s: (-best_sig(s), s))
        total = len(ssid_order)

        log_system(f"Available SSIDs ({total} total):", source=self.name)

        max_lines = int(limit) if isinstance(limit, int) else 12
        shown = 0
        for ssid in ssid_order:
            if shown >= max_lines:
                break
            rec = summary[ssid]
            parts = []
            for band_tag in ("2.4", "5", "6E", "?"):
                b = rec["bands"].get(band_tag)
                if not b:
                    continue
                sig = b.get("signal")
                chan = b.get("chan")
                if sig is not None:
                    seg = f"{band_tag}: {sig}% (ch {chan})"
                else:
                    seg = f"{band_tag} (ch {chan or '?'})"
                parts.append(seg)
            bands_str = " | ".join(parts) if parts else "—"
            count = rec.get("count", 1)
            count_str = f" — {count} APs" if count > 1 else ""
            log_system(f"  • {ssid} — {bands_str}{count_str}", source=self.name)
            shown += 1

        if total > shown:
            log_system(f"  … and more ({total - shown} hidden)", source=self.name)

    def _scan_nmcli_list(self):
        if not self._nmcli:
            return None
        try:
            raw_list = subprocess.check_output(
                ['nmcli', '-f', 'SSID,SIGNAL,CHAN', 'dev', 'wifi'],
                text=True
            ).strip().splitlines()
            header, lines = (raw_list[0], raw_list[1:]) if raw_list else ("", [])

            parsed: List[Dict[str, Any]] = []
            ssids: List[str] = []

            for ln in lines:
                ln = ln.rstrip()
                if not ln:
                    continue
                try:
                    left, signal, chan = ln.rsplit(None, 2)
                    ssid = left.strip()
                    sig = int(signal)
                except Exception:
                    ssid = ln.strip()
                    sig = None
                    chan = None
                band = self._band_from_chan(chan)
                entry = {"ssid": ssid, "signal": sig, "chan": chan, "band": band}
                parsed.append(entry)
                ssids.append(ssid)

            # active ssid
            active_ssid = None
            try:
                raw_active = subprocess.check_output(
                    ['nmcli', '-t', '-f', 'ACTIVE,SSID', 'dev', 'wifi'],
                    text=True
                ).strip().splitlines()
                for ln in raw_active:
                    if ln.startswith("yes:"):
                        active_ssid = ln.split(":", 1)[1]
                        break
            except Exception:
                pass

            # Build summary: strongest per SSID per band + counts
            summary: Dict[str, Dict[str, Any]] = {}
            for e in parsed:
                ssid = e["ssid"] or "—"
                band = e["band"]
                srec = summary.setdefault(ssid, {"count": 0, "bands": {}})
                srec["count"] += 1
                b = srec["bands"].get(band)
                if b is None or (e["signal"] is not None and (b.get("signal") is None or e["signal"] > b["signal"])):
                    srec["bands"][band] = {"signal": e["signal"], "chan": e["chan"]}

            return {
                "raw_lines": lines,
                "ssids": ssids,          # all SSIDs (AP-level, not distinct)
                "parsed": parsed,        # full list of AP observations
                "summary": summary,      # compact view per SSID (mesh-aware)
                "active_ssid": active_ssid,
            }
        except Exception as e:
            log_system(f"Wi-Fi scan failed: {e}", source=self.name, level="WARN")
            return {"raw_lines": [], "ssids": [], "parsed": [], "summary": {}, "active_ssid": None}

    # ---------- recon add-ons ----------
    def ifaces(self):
        if not self._ip:
            self._debug("ip command not found; ifaces() unavailable.")
            return {"ifaces": []}
        out = self._run([self._ip, "-j", "addr"], timeout=5)
        if out.startswith("__ERR__"):
            self._debug(out); return {"ifaces": []}
        try:
            data = json.loads(out)
            info = []
            for dev in data:
                entry = {
                    "name": dev.get("ifname"),
                    "flags": dev.get("flags", []),
                    "addr_info": dev.get("addr_info", []),
                }
                info.append(entry)
            return {"ifaces": info}
        except Exception as e:
            self._debug(f"ifaces parse failed: {e}")
            return {"ifaces": []}

    def arp_table(self):
        if not self._ip:
            self._debug("ip command not found; arp_table() unavailable.")
            return {"neighbors": []}
        out = self._run([self._ip, "neigh", "show"], timeout=5)
        neigh = []
        for line in out.splitlines():
            if not line or line.startswith("__ERR__"):
                continue
            parts = line.split()
            try:
                ip = parts[0]
                state = parts[-1]
                mac = None
                if "lladdr" in parts:
                    mac = parts[parts.index("lladdr")+1]
                dev = parts[parts.index("dev")+1] if "dev" in parts else None
                neigh.append({"ip": ip, "mac": mac, "dev": dev, "state": state})
            except Exception:
                continue
        return {"neighbors": neigh}

    def dns_check(self, host="1.1.1.1", count=3):
        if not self._ping:
            self._debug("ping not found; dns_check() unavailable.")
            return {"host": host, "ms": [], "avg": None}
        lat = []
        for _ in range(count):
            out = self._run([self._ping, "-c", "1", "-W", "1000", host], timeout=2)
            for part in out.split():
                if part.startswith("time="):
                    try:
                        lat.append(float(part.split("=", 1)[1]))
                    except Exception:
                        pass
        return {"host": host, "ms": lat, "avg": (sum(lat)/len(lat) if lat else None)}

    def _guess_subnet(self):
        if not self._ip:
            return None
        r = self._run([self._ip, "-j", "route"], timeout=5)
        try:
            data = json.loads(r)
            dev = None
            for row in data:
                if row.get("dst") == "default":
                    dev = row.get("dev")
                    break
            if not dev:
                return None
            a = self._run([self._ip, "-j", "addr", "show", "dev", dev], timeout=5)
            ad = json.loads(a)
            for ent in ad:
                for info in ent.get("addr_info", []):
                    if info.get("family") == "inet":
                        ip = info.get("local")
                        network = ipaddress.ip_network(ip + "/24", strict=False)
                        return str(network)
        except Exception:
            return None
        return None

    def lan_sweep(self, cidr=None, limit=256, timeout_ms=300):
        subnet = cidr or self._guess_subnet()
        if not subnet or not self._ping:
            self._debug("lan_sweep unavailable (no subnet or ping).")
            return {"subnet": subnet, "alive": []}
        net = ipaddress.ip_network(subnet, strict=False)
        alive = []
        for i, host in enumerate(net.hosts()):
            if i >= limit:
                break
            out = self._run([self._ping, "-c", "1", "-W", str(timeout_ms), str(host)], timeout=1)
            if "1 received" in out or "1 packets received" in out:
                alive.append(str(host))
        return {"subnet": subnet, "alive": alive}

    def recon_dump(self):
        blob = {
            "ts": int(time.time()),
            "ifaces": self.ifaces(),
            "neighbors": self.arp_table(),
            "dns": self.dns_check(),
            "lan": self.lan_sweep(),
            "wifi": self._scan_nmcli_list() or {"parsed": []}
        }
        path = os.path.join(DATA_DIR, f"recon_{blob['ts']}.json")
        try:
            with open(path, "w") as f:
                json.dump(blob, f, indent=2)
            log_system(f"Recon saved → {path}", source=self.name)
        except Exception as e:
            log_system(f"Recon save failed: {e}", source=self.name, level="WARN")
        if hasattr(self, "core") and hasattr(self.core, "data_store"):
            self.core.data_store["net_last_recon"] = {"path": path, "ts": blob["ts"]}
        return blob

    # ---------- LLM-accessible convenience wrappers ----------
    async def scan_network(self):
        """
        Lightweight alias so the brain can request a passive scan.
        Simply runs initial_scan() and returns a short summary dict.
        """
        self._debug("scan_network() → delegating to initial_scan()")
        self.initial_scan()
        wifi_count = len(self.core.data_store.get("wifi_ssids", [])) if self.core else 0
        return {"ok": True, "wifi_count": wifi_count}

    async def wifi_scan(self):
        """
        Perform a one-off nmcli listing and return parsed summary.
        Does NOT announce or trigger reacts.
        """
        nets = self._scan_nmcli_list()
        if not nets:
            return {"ok": False, "error": "nmcli unavailable"}
        summary = {
            "ssid_count": len(nets.get("summary", {})),
            "active_ssid": nets.get("active_ssid"),
        }
        self._debug(f"wifi_scan() → {summary}")
        return {"ok": True, **summary}

    async def scan_ports(self, target: str, start_port: int = 1, end_port: int = 1024):
        """
        Quick TCP connect scan using Python sockets only.
        Returns dict with list of open ports.
        """
        import socket, asyncio
        open_ports = []
        sem = asyncio.Semaphore(128)

        async def probe(p):
            async with sem:
                try:
                    fut = asyncio.open_connection(target, p)
                    r, w = await asyncio.wait_for(fut, timeout=0.25)
                    open_ports.append(p)
                    w.close()
                except Exception:
                    pass

        await asyncio.gather(*(probe(p) for p in range(start_port, end_port + 1)), return_exceptions=True)
        self._debug(f"scan_ports({target}) → {len(open_ports)} open")
        return {"ok": True, "target": target, "open": open_ports[:20]}

    # ---------- compatibility stubs ----------
    def scan(self):        log_system("Executing action: scan", source=self.name, level="INFO")
    def log_signal(self):  log_system("Executing action: log_signal", source=self.name, level="INFO")
    def channel_map(self): log_system("Executing action: channel_map", source=self.name, level="INFO")
    def beacon_sweep(self):log_system("Executing action: beacon_sweep", source=self.name, level="INFO")
    def deauth_probe(self):
        if not self._allow_active:
            log_system("deauth_probe blocked (KARI_ALLOW_ACTIVE_NET=0).", source=self.name, level="WARN"); return
        log_system("Executing action: deauth_probe", source=self.name, level="INFO")
