# ⚡ K.A.R.I

![Welcome](docs/images/welcome.png)

> **K.A.R.I** (Knowledgeable Autonomous Reactive Interface) is the caffeinated Linux daemon that splices the D.E.V.I.L. Core into your box, hypes itself up on pulse-driven chaos, roasts you in real time, and still manages to automate the weird rituals you built her for.

---

## 🖤 Who You're Summoning

K.A.R.I isn’t a single binary — she’s a swarm of organs, prosthetics, and personalities that report to the D.E.V.I.L. Core conductor. Boot her up and you get:

- **D.E.V.I.L. Core** — orchestrator, module loader, socket server, pulse dispatcher, banter gremlin-in-chief.
- **Organs** (`internal/`) — mandatory survival kit: Mood Engine, Pulse Matrix, VoiceBox, Memory Cortex, Net Synapse, Sanity Relay… the stuff that keeps her alive.
- **Prosthetics** (`prosthetics/`) — optional chaos add-ons. Drop in a module, flip the service, and she grows new limbs.
- **Personalities** (`personalities/`) — phrase packs sorted by mood and tag so she can deliver sass that matches her vital signs.

![Warning](docs/images/warning.png)

## ⚠️ Temper Your Expectations

Install K.A.R.I and you are inviting a biomechanical gremlin into your systemd lineup. She will roast you, demand snacks, hijack your logs, and announce every mood swing. You’ve been warned.

---

## 🔩 Architecture Crash Course

| Layer | Purpose | Where to look |
| --- | --- | --- |
| **D.E.V.I.L. Core** | Instantiates modules, runs the heartbeat loop, keeps shared `data_store`, pushes logs, and exposes the live control socket. | `core/devil_core.py` |
| **Pulse Dispatcher** | Every tick (default 5s) reads each module’s `meta_data["pulse"]` list and runs the referenced methods (async supported). Keep pulse work fast. | `DEVILCore.pulse()` |
| **Menu & Help Engine** | surfaces module docs and manual actions via the socket. | `core/menu_engine.py` |
| **Organs** | Built-in modules that always load. They publish vitals, moods, phrases, net telemetry. | `internal/` |
| **Prosthetics** | Hot-swappable plugins; optional, independently versioned. | `prosthetics/` |
| **Personalities** | Text banks grouped by mood/tag, consumed by VoiceBox and modules. | `personalities/` |

### DEVIL Core Pulse Loop (abridged)
```python
for mod in list(self.modules.values()):
    for action in mod.meta_data.get("pulse", []):
        method = getattr(mod, action, None)
        if inspect.iscoroutinefunction(method):
            asyncio.create_task(method())
        elif callable(method):
            method()
```
- Tick counter lives at `core.data_store["tick"]`.
- Pulse Matrix pushes vitals (CPU, memory, temps) into the store for everyone to read.
- Modules should throttle expensive work internally or flip to async.

### Control Socket
- Enabled with `KARI_ENABLE_SOCKET=1` and bound to `KARI_SOCKET` (default `/run/kari/kari.sock`).
- DEVIL Core spins it up the moment the event loop is ready and downgrades gracefully if no socket client is installed.

---

![Setup](docs/images/setup.png)

## 🗂️ Project Layout ( `/home/kari/Projects/KARI` )

```text
core/           # DEVIL Core, logger, menu engine, shared utilities
internal/       # Built-in organs (pulse_matrix, mood_engine, memory_cortex, ...)
prosthetics/    # Optional plugins; each folder = module package
personalities/  # Phrase packs organised by mood/tag
system/         # System helpers, service glue, waveform toys
utils/          # Tooling (mod_gen.py, control_server.py, helpers)
logs/           # Runtime logs (rotated by installer helpers)
install-kari.sh # The omnipotent installer/update/uninstall script
headless.py     # Systemd target entry (non-display runtime)
kari.py         # Full-fat launch script (display + extras)
```

Bonus directories like `display/`, `displayhatmini/`, `netcore/`, and `data/` host hardware integrations and local caches. Leave them be unless you know what you’re summoning.

---

![Installation](docs/images/installation.png)

## ⚙️ Installation (bring coffee, bring sudo)

### Requirements
- systemd-based Linux distro (Arch, Debian, Ubuntu, etc.)
- Python 3 with `venv`
- `git`, `jq`, `rsync`, and a socket tool (`socat`, `nc`, or `ncat`)

### Quick Install
```bash
git clone git@github.com:karialo/K.A.R.I.git
cd K.A.R.I
chmod +x install-kari.sh
sudo ./install-kari.sh install
```
What the script does while screaming happily:
1. Creates a dedicated `kari` user and home.
2. Drops the project into `/home/kari/Projects/KARI` (override with `--project` or env vars).
3. Builds the virtualenv at `/home/kari/.venvs/kari` and installs requirements.
4. Writes `/etc/kari/kari.env` with sane defaults (see variables below).
5. Installs `kari.service` (+ optional `kari-pi.service`) and enables them.
6. Installs two CLIs: `kari-cli` for systemd duties, `kari` for live socket control.

### Updating & Uninstalling
- `kari-cli update /path/to/kari.zip` — sync new bits, backup current install, restart.
- `kari-cli uninstall` — stop services and remove CLIs (project files stay put for archaeology).

Pro tip: run `sudo ./install-kari.sh -h` to see every flag (`--user`, `--project`, `--venv`, `--src`, `--dry-run`).

---

![Examples](docs/images/examples.png)

## 🛠️ Systemd Playbook
- **Services**: `kari.service` (headless runtime) and `kari-pi.service` (DisplayHAT Mini front-end).
- **Working directory**: `/home/kari/Projects/KARI`.
- **Environment**: sourced from `/etc/kari/kari.env` (auto-created on install).
- **RuntimeDirectory**: `/run/kari` for the control socket.
- **Enable/Disable**: `sudo systemctl enable --now kari.service` is automatic during install. Use `kari-cli start|stop|restart [--pi]` for day-to-day.
- **Logs**: `journalctl -u kari.service` or `kari-cli logs -n 200`. The installer’s log cleaner can rotate and truncate both journald and app logs in one go.

If you add or remove modules, bounce the service with `kari-cli restart` so DEVIL Core can re-index the filesystem.

---

## 🕹️ Operator Console

### `kari-cli` (service wrangler)
```bash
kari-cli status [--pi]
kari-cli start|stop|restart [--pi]
kari-cli logs [-n 300] [--since "2025-02-01"] [--clear]
kari-cli env edit
kari-cli module new HyperArm --type prosthetic --action swing --action pose
kari-cli check                     # import health for all modules
kari-cli ctl "debug on"            # raw socket command passthrough
kari-cli update /tmp/KARI.zip
```
- `module new` calls `utils/mod_gen.py` to scaffold code and phrase directories.
- `ctl` forwards anything to the live socket (same as using `kari`).

### `kari` (control socket hype line)
```bash
kari status               # JSON snapshot of DEVIL Core vitals
kari mods                 # list attached organs + prosthetics
kari phrase banter angry  # demand exactly the mood you want
kari speak "hello, foolish human"
kari call Lokisfury portscan '{"target":"192.168.0.1","max_port":200}'
kari debug toggle         # flip DEVIL logging from the couch
kari watch 5              # curses-free status dashboard every 5s
```
- Commands stream over `/run/kari/kari.sock`; output auto-prettified JSON.
- `kari help` or `kari help "Mood Engine"` surfaces the module metadata from `meta_data["help"]`.

Socket down? Check permissions on `/run/kari` and confirm `KARI_ENABLE_SOCKET=1` in your env file.

---

## 🌡️ Environment Variables

K.A.R.I reads most of her attitude from `/etc/kari/kari.env` (override per service with `Environment=` lines if you’re brave). Highlights:

| Variable | Default | What it unlocks |
| --- | --- | --- |
| `KARI_BANTER` | `1` | Global sass switch; `0` mutes banter broadcasts. |
| `KARI_DEVIL_BANTER` | `1` | Lets the core interject during pulses and boot. |
| `KARI_MOOD_BANTER` | `1` | Enables Mood Engine flavor text. |
| `KARI_MEMORY_BANTER` | `0` | Memory Cortex storytelling; verbose when `1`. |
| `KARI_PERSONALITY` | `Default` | Picks phrase pack under `personalities/`. |
| `KARI_PULSE_INTERVAL` | `5` | Seconds between DEVIL core pulses. |
| `KARI_PULSE_INFO_GAP` | `15` | Frequency of Pulse Matrix vitals announcements. |
| `KARI_CPU_LOW` / `KARI_CPU_HIGH` | `10` / `85` | Thermal thresholds influencing mood + warnings. |
| `KARI_MEM_FREE_LOW` / `KARI_MEM_USED_HIGH` | `200` / `85` | Memory thresholds (MB/%). |
| `KARI_THERMAL_HOT` / `KARI_THERMAL_COOL` | `82.0` / `75.0` | Overheat/relief boundaries for the Pulse Matrix. |
| `KARI_ALLOW_ACTIVE_NET` | `0` | Allow Net Synapse to perform active scans when `1`. |
| `KARI_NET_SCAN_INTERVAL` | `30` | Seconds between passive Wi-Fi scans. |
| `KARI_NET_ANNOUNCE_GAP` | `2` | Minimum minutes between Wi-Fi announcements. |
| `KARI_NET_BOOT_LIST_N` | `12` | How many SSIDs to list at boot. |
| `KARI_SANITY_INFLUENCE` | `1` | Enables Sanity Relay mood nudging. |
| `KARI_SANITY_INFLUENCE_MIN/MAX` | `120` / `240` | Bounds for Sanity Relay timers. |
| `KARI_VOICEBOX_ANNOUNCE` | `0` | When `1`, VoiceBox narrates more events. |
| `KARI_DEBUG` / `KARI_TRACE` | `0` | Verbose logging toggles; `kari debug on` flips the first at runtime. |
| `KARI_LOG_LEVEL` | `INFO` | Default logging severity. |
| `KARI_ENABLE_SOCKET` | `1` | Master switch for the `/run/kari/kari.sock` server. |
| `KARI_SOCKET` | `/run/kari/kari.sock` | Socket path; must match CLI config. |
| `KARI_AUTO_PIP` | `1` | Auto-install module requirements declared in `meta_data`. |
| `KARI_PIP_ARGS` | `` | Extra args passed to pip during installs. |
| `KARI_USER` / `KARI_GROUP` | `kari` | Propagated into the service unit for file ownership. |

Set these in `/etc/kari/kari.env`, then `kari-cli restart` to make the gremlin respect them.

---

## 🧪 Developer Lab: Building Organs & Prosthetics

### 1. Scaffold your creature
```bash
kari-cli module new WeatherEye --type internal --action pulse --action forecast
# or
kari-cli module new TentacleArm --type prosthetic --action hug --action yeet
```
This drops a module under `internal/` or `prosthetics/` plus phrase directories at `.../phrases/<tag>/<mood>.txt`.

### 2. Know the anatomy
Every module is expected to expose:
- `meta_data` dict with `name`, `category`, `version`, `actions`, optional `pulse`, `aliases`, and `help` entries.
- A class whose name matches the file in `CapWords` form, e.g. `system/pulse_matrix/pulse_matrix.py` → `PulseMatrix`.
- Optional lifecycle hooks: `init()` (sync) and `initialize()` (async) — DEVIL Core calls both if present.
- Runtime fields: set `self.core` in `init()` if you want to talk to DEVIL Core or other modules.
- Pulse methods listed in `meta_data["pulse"]` — keep them fast or async.
- `manual_actions` (list of dicts) show up in the `kari help` menu.
- Phrase usage via `core.personality.get_phrase(<module_key>, <tag>, mood)`; use `MemoryCortex` to fetch mood safely.

### 3. Register it with the Core
- Drop your module file into the correct folder (auto-created by the scaffold).
- DEVIL Core scans `internal/` first, then `prosthetics/`. Set `meta_data["category"]` to match.
- Restart the service: `kari-cli restart` and watch the logs for boot phrases.
- Verify with `kari mods` and `kari help "Your Module"`.

### 4. Prosthetics 101
- Keep dependencies optional; use guarded imports so the module can run standalone (`python prosthetics/foo/foo.py`).
- Expose CLI-friendly actions (JSON kwargs or raw strings) — see `prosthetics/lokisfury/lokisfury.py` for patterns.
- Add phrases under `prosthetics/<name>/phrases/banter/happy.txt` etc to make your plugin talk.

### 5. Advanced Tricks
- Use `self.core.data_store` to read vitals or publish your own keys.
- Emit logs via `core.logger.log_system()`; use `log_kari` for in-character banter.
- Need scheduled tasks? Append to `meta_data["pulse"]` or spin up your own asyncio tasks in `initialize()`.

If DEVIL Core refuses to load your masterpiece, run `kari-cli check` to inspect import errors.

---

## 🔁 Runtime Quick Reference
- `kari status` → JSON snapshot with tick count, vitals, attached modules, mood.
- Pulse Matrix pushes CPU/memory/thermal data; Mood Engine converts it into DEFCON-level moods.
- Sanity Relay throttles banter when the system is stressed (toggle with `KARI_SANITY_INFLUENCE`).
- Net Synapse logs Wi-Fi state and (optionally) performs scans when `KARI_ALLOW_ACTIVE_NET=1`.
- VoiceBox handles speech synthesis/phrase delivery; respect `KARI_VOICEBOX_ANNOUNCE` if you add new announcements.

---

![Winner](docs/images/winner.png)

## 📦 Updating & Maintenance
```bash
kari-cli update /tmp/KARI-2025-03-01.tar.gz
kari-cli logs --since "1 hour ago"
kari-cli ctl "mods"
```
- Installer makes a tarball backup under `/tmp/kari-backup-<timestamp>.tar.gz` before syncing updates.
- Use `kari-cli logs --clear` to rotate journald and truncate app logs when they get spicy.
- `push "fix(mood): stop double-banter"` remains the YOLO alias if your shell RC enables it.

---

![Contribute](docs/images/contribute.png)

## 🤝 Contributions Welcome (Enter at Own Risk)
1. Fork.
2. `git checkout -b feature/abomination`.
3. Build your module/phrases/tests.
4. Commit with real messages (no "update lol").
5. Push and open a PR. By contributing you agree K.A.R.I can adopt your code and roast you forever.

---

![License](docs/images/license.png)

## 📜 License

K.A.R.I is **proprietary software**. No redistribution, no sublicensing, no sneaky forks. Contributions via pull request assign copyright to the project owner unless you negotiated otherwise.

`Copyright (c) 2025 karialo. All rights reserved.`

---

![Credits](docs/images/credits.png)

## 💖 Credits
- Creator: unleashed the D.E.V.I.L. Core and gave it free reign.
- Module authors, phrase pack goblins, and testers who keep poking the socket.
- Everyone brave enough to turn debug on and read the logs.

Snacks can be addressed to `kari`@your-hostname.

---

![Help](docs/images/helpme.png)

## ❓ Help Me
- `kari-cli help` — CLI usage recap.
- `kari help` — live module docs direct from DEVIL Core.
- `kari-cli logs` — watch behaviour as it happens.
- Still stuck? Open an issue on GitHub, attach logs, bribe with snacks.

Power-cycle if she gets moody. She’ll pretend it never happened.

---
