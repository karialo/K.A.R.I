#!/usr/bin/env bash
set -euo pipefail

# ===== Subcommand (default: install) =====
CMD="${1:-install}"; shift || true

# ===== Defaults (override via env or flags) =====
KARI_USER="${KARI_USER:-kari}"
KARI_HOME="${KARI_HOME:-/home/${KARI_USER}}"
KARI_PROJECT_DIR="${KARI_PROJECT_DIR:-${KARI_HOME}/Projects/KARI}"
KARI_VENV_DIR="${KARI_VENV_DIR:-${KARI_HOME}/.venvs/kari}"
KARI_ETC_DIR="${KARI_ETC_DIR:-/etc/kari}"
KARI_ENV_FILE="${KARI_ENV_FILE:-${KARI_ETC_DIR}/kari.env}"
KARI_SERVICE="${KARI_SERVICE:-/etc/systemd/system/kari.service}"
KARI_PI_SERVICE="${KARI_PI_SERVICE:-/etc/systemd/system/kari-pi.service}"
KARI_CLI_PATH="${KARI_CLI_PATH:-/usr/local/bin/kari-cli}"
KARI_SOCKET_CLI="${KARI_SOCKET_CLI:-/usr/local/bin/kari}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DRY_RUN=0
SRC_PATH="${SRC_PATH:-}"     # optional install/update source: zip/tar/folder
KARI_GIT_URL="${KARI_GIT_URL:-}"  # optional git URL to clone if nothing else provided

usage(){ cat <<EOF
K.A.R.I. installer

Usage:
  sudo ./install-kari.sh install  [--user USER] [--project PATH] [--venv PATH] [--src ZIP|DIR] [--dry-run]
  sudo ./install-kari.sh update   --src ZIP|TAR|DIR [--user USER] [--project PATH] [--venv PATH]
  sudo ./install-kari.sh uninstall
  sudo ./install-kari.sh -h|--help

Environment overrides: KARI_USER KARI_PROJECT_DIR KARI_VENV_DIR KARI_ETC_DIR KARI_ENV_FILE KARI_GIT_URL ...
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      KARI_USER="${2:-kari}"
      KARI_HOME="/home/${KARI_USER}"
      shift 2;;
    --project)
      KARI_PROJECT_DIR="${2:-/home/${KARI_USER}/Projects/KARI}"
      shift 2;;
    --venv)
      KARI_VENV_DIR="${2:-/home/${KARI_USER}/.venvs/kari}"
      shift 2;;
    --dry-run)
      DRY_RUN=1; shift;;
    --src)
      SRC_PATH="${2:-.}"  # 👈 default to current dir if omitted
      shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown arg: $1"; usage; exit 1;;
  esac
done


run(){ [[ "$DRY_RUN" -eq 1 ]] && echo "DRY: $*" || eval "$@"; }
info(){ echo ">>> $*"; }
err(){ echo "ERROR: $*" >&2; exit 1; }
trap 'echo "ERROR: line $LINENO failed"; exit 1' ERR
have(){ command -v "$1" >/dev/null 2>&1; }

# ===== Distro detection & helpers =====
IS_PACMAN=0; IS_APT=0
if command -v pacman >/dev/null 2>&1; then IS_PACMAN=1; fi
if command -v apt-get >/dev/null 2>&1; then IS_APT=1; fi

apt_install(){ run "apt-get update -y" || true; run "apt-get install -y $*"; }
pac_install(){ run "pacman -S --needed --noconfirm $*"; }

install_dep(){
  local apt_pkg="$1"; local pac_pkg="${2:-$1}"
  if [[ $IS_PACMAN -eq 1 ]]; then
    pac_install "$pac_pkg" || true
  elif [[ $IS_APT -eq 1 ]]; then
    apt_install "$apt_pkg" || true
  fi
}

ensure_deps(){
  # Python & tooling
  if ! have "${PYTHON_BIN}"; then
    if [[ $IS_PACMAN -eq 1 ]]; then install_dep python python; else install_dep python3 python3; fi
  fi
  have pip3 || install_dep python3-pip python-pip

  # venv: included with Arch 'python', needs apt pkg on Debian/Ubuntu
  if ! "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import sys, importlib.util
sys.exit(0 if importlib.util.find_spec("venv") else 1)
PY
  then
    [[ $IS_APT -eq 1 ]] && install_dep python3-venv python || true
  fi

  # Utilities used by installer/runtime
  have rsync || install_dep rsync rsync
  have unzip || install_dep unzip unzip
  have jq    || install_dep jq jq   # nice-to-have for pretty JSON

  # Socket client (prefer socat, else netcat flavor, else ncat)
  if ! have socat && ! have nc && ! have ncat; then
    install_dep socat socat
    if ! have socat; then
      if [[ $IS_APT -eq 1 ]]; then
        install_dep netcat-openbsd netcat-openbsd || install_dep ncat nmap
      else
        install_dep openbsd-netcat openbsd-netcat || install_dep nmap nmap
      fi
    fi
  fi

  # Optional net tooling (best-effort)
  have iw || install_dep iw iw
  have ip || install_dep iproute2 iproute2
  have nmap || install_dep nmap nmap
  have netstat || install_dep net-tools net-tools
}

# ===== Common helpers =====
ensure_user_and_group(){
  if ! id -u "$KARI_USER" >/dev/null 2>&1; then
    if command -v useradd >/dev/null 2>&1; then
      run "useradd -m -U -s /bin/bash ${KARI_USER}" || run "useradd -m -s /bin/bash ${KARI_USER}"
    fi
  fi
  if ! getent group "$KARI_USER" >/dev/null 2>&1; then
    run "groupadd -f ${KARI_USER}" || true
  fi
  KARI_GROUP="$(id -gn "${KARI_USER}" 2>/dev/null || echo "${KARI_USER}")"
}

extract_src_to_tmp(){
  local src="$1"; local tmpdir; tmpdir="$(mktemp -d)"
  case "$src" in
    *.zip) run "unzip -qq '$src' -d '$tmpdir'";;
    *.tar.gz|*.tgz) run "tar -xzf '$src' -C '$tmpdir'";;
    *.tar) run "tar -xf '$src' -C '$tmpdir'";;
    *) [[ -d "$src" ]] || err "Unknown src type or missing path: $src"; tmpdir="$src";;
  esac
  # If there is a single top-level dir that isn't the project root, descend into it
  if [[ -d "$tmpdir" ]] && [[ $(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | wc -l) -eq 1 ]] && [[ ! -f "$tmpdir/headless.py" ]]; then
    tmpdir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d)"
  fi
  echo "$tmpdir"
}

populate_project_dir(){
  # 1) If --src provided, extract/sync from it
  if [[ -n "${SRC_PATH}" ]]; then
    info "Populating project from --src: ${SRC_PATH}"
    local tmpdir; tmpdir="$(extract_src_to_tmp "$SRC_PATH")"
    run "mkdir -p '$(dirname "$KARI_PROJECT_DIR")'"
    run "rsync -a --delete --exclude '.venv' --exclude 'logs' --exclude '.git' '$tmpdir/' '${KARI_PROJECT_DIR}/'"
    return 0
  fi

  # 2) If running from a project tree, copy current directory
  if [[ -f "headless.py" || -d ".git" ]]; then
    info "Populating project from current directory → ${KARI_PROJECT_DIR}"
    run "mkdir -p '$(dirname "$KARI_PROJECT_DIR")'"
    run "rsync -a --delete --exclude '.venv' --exclude 'logs' --exclude '.git' ./ '${KARI_PROJECT_DIR}/'"
    return 0
  fi

  # 3) If git URL provided, clone it
  if [[ -n "${KARI_GIT_URL}" && $(command -v git || true) ]]; then
    info "Cloning project from \$KARI_GIT_URL → ${KARI_PROJECT_DIR}"
    run "mkdir -p '$(dirname "$KARI_PROJECT_DIR")'"
    run "git clone --depth 1 '${KARI_GIT_URL}' '${KARI_PROJECT_DIR}'"
    return 0
  fi

  # 4) Otherwise, we can't populate
  err "Project dir not found and no source provided. Re-run with --src /path/to/Kari.zip (or set KARI_GIT_URL), or run installer from inside the repo."
}

ensure_project_dir(){
  if [[ ! -d "$KARI_PROJECT_DIR" ]]; then
    populate_project_dir
  fi
  run "chown -R ${KARI_USER}:${KARI_GROUP} ${KARI_PROJECT_DIR}"
}

create_venv(){
  info "Creating venv at ${KARI_VENV_DIR} (user=${KARI_USER}, group=${KARI_GROUP})"
  run "install -d -o ${KARI_USER} -g ${KARI_GROUP} '$(dirname "$KARI_VENV_DIR")'"
  [[ -d "$KARI_VENV_DIR" ]] || run "sudo -u ${KARI_USER} ${PYTHON_BIN} -m venv ${KARI_VENV_DIR}"
  if [[ -f "${KARI_PROJECT_DIR}/requirements.txt" ]]; then
    run "sudo -u ${KARI_USER} ${KARI_VENV_DIR}/bin/pip install -U pip wheel"
    run "sudo -u ${KARI_USER} ${KARI_VENV_DIR}/bin/pip install -r ${KARI_PROJECT_DIR}/requirements.txt"
  fi
}

write_env_if_missing(){
  run "install -d -m 0755 ${KARI_ETC_DIR}"
  [[ -f "$KARI_ENV_FILE" ]] && return 0
  info "Writing ${KARI_ENV_FILE}"
  cat <<'ENV' | run "tee ${KARI_ENV_FILE} >/dev/null"
# ==== K.A.R.I. Environment ====
# Chatter & mood gates
KARI_BANTER=1
KARI_DEVIL_BANTER=1
KARI_MOOD_BANTER=1
KARI_MEMORY_BANTER=0
KARI_LOG_LEVEL=INFO

# Pulse timing (seconds)
KARI_PULSE_INTERVAL=5
KARI_PULSE_INFO_GAP=15

# Vitals thresholds
KARI_CPU_LOW=10
KARI_CPU_HIGH=85
KARI_MEM_FREE_LOW=200
KARI_MEM_USED_HIGH=85

# Networking safety
KARI_ALLOW_ACTIVE_NET=0

# Live control socket
KARI_ENABLE_SOCKET=1
KARI_SOCKET=/run/kari/kari.sock
ENV
}

write_units(){
  info "Writing systemd units"

  # Headless unit
  cat > /tmp/kari.service <<UNITFILE
[Unit]
Description=K.A.R.I. (DEVIL Core - headless)
After=network.target

[Service]
Type=simple
User=${KARI_USER}
Group=${KARI_GROUP}
WorkingDirectory=${KARI_PROJECT_DIR}
EnvironmentFile=-${KARI_ENV_FILE}
# Writable runtime dir for the control socket
RuntimeDirectory=kari
RuntimeDirectoryMode=0750
Environment=KARI_USER=${KARI_USER}
Environment=KARI_GROUP=${KARI_GROUP}
ExecStart=${KARI_VENV_DIR}/bin/python ${KARI_PROJECT_DIR}/headless.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
UNITFILE
  run "tee ${KARI_SERVICE} >/dev/null < /tmp/kari.service"
  run "rm -f /tmp/kari.service"

  # Pi Display unit
  cat > /tmp/kari-pi.service <<PIUNITFILE
[Unit]
Description=K.A.R.I. (Pi DisplayHAT Mini)
After=network.target

[Service]
Type=simple
User=${KARI_USER}
Group=${KARI_GROUP}
WorkingDirectory=${KARI_PROJECT_DIR}
EnvironmentFile=-${KARI_ENV_FILE}
RuntimeDirectory=kari
RuntimeDirectoryMode=0750
Environment=KARI_USER=${KARI_USER}
Environment=KARI_GROUP=${KARI_GROUP}
ExecStart=${KARI_VENV_DIR}/bin/python ${KARI_PROJECT_DIR}/kari.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
PIUNITFILE
  run "tee ${KARI_PI_SERVICE} >/dev/null < /tmp/kari-pi.service"
  run "rm -f /tmp/kari-pi.service"
}

install_cli(){
  info "Installing kari-cli → ${KARI_CLI_PATH}"
  run "install -d -m 0755 /usr/local/bin"
  cat <<'CLISRC' | run "tee ${KARI_CLI_PATH} >/dev/null"
#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-kari}"
PI_SERVICE="${PI_SERVICE:-kari-pi}"
ETC_ENV="${ETC_ENV:-/etc/kari/kari.env}"
PROJECT="${PROJECT:-/home/kari/Projects/KARI}"
VENV="${VENV:-/home/kari/.venvs/kari}"
SOCK="${KARI_SOCKET:-/run/kari/kari.sock}"
PY="${PY:-$VENV/bin/python}"
SUDO=""; [[ "${EUID:-$(id -u)}" -ne 0 ]] && SUDO="sudo"

usage(){ cat <<'EOF'
kari-cli — control K.A.R.I.

Usage:
  kari-cli status [--pi]
  kari-cli start|stop|restart [--pi]
  kari-cli logs [-n LINES] [--pi] [--since "YYYY-MM-DD HH:MM"] [--clear|--truncate]
  kari-cli env edit
  kari-cli module new Name --type internal|prosthetic [--action foo ...]
  kari-cli check
  kari-cli version
  kari-cli update /path/to/Kari.zip|/path/to/folder
  kari-cli ctl <command line...>
  kari-cli uninstall
  kari-cli -h|--help
EOF
}

system(){ local svc="$SERVICE"; [[ "${1:-}" == "--pi" ]] && svc="$PI_SERVICE" && shift; $SUDO systemctl "$@" "$svc"; }

ctl(){
  [[ $# -gt 0 ]] || { echo "usage: kari-cli ctl <command...>"; exit 2; }
  local cmd="$*"
  if command -v socat >/dev/null 2>&1; then
    printf '%s\n' "$cmd" | socat - UNIX-CONNECT:"${SOCK}"
  elif command -v nc >/dev/null 2>&1; then
    printf '%s\n' "$cmd" | nc -U "${SOCK}"
  elif command -v ncat >/dev/null 2>&1; then
    printf '%s\n' "$cmd" | ncat -U "${SOCK}"
  else
    echo "No socat/nc found; install one to use ctl."
    exit 3
  fi
}

case "${1:-}" in
  -h|--help|"") usage ;;

  status) shift; system status "$@" ;;

  start|stop|restart)
    cmd="$1"; shift; system "$cmd" "$@" ;;

  logs)
    shift
    LINES=200
    SVC="$SERVICE"
    APP_LOG_DIR="${PROJECT}/logs"
    CLEAR=0
    TRUNCATE_ONLY=0
    SINCE_ARGS=()

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --pi) SVC="$PI_SERVICE"; shift;;
        -n) LINES="$2"; shift 2;;
        --since) SINCE_ARGS=(--since "$2"); shift 2;;
        --clear) CLEAR=1; shift;;
        --truncate) TRUNCATE_ONLY=1; shift;;
        *) break;;
      esac
    done

    if [[ $CLEAR -eq 1 || $TRUNCATE_ONLY -eq 1 ]]; then
      echo "[i] Stopping ${SVC}…"
      $SUDO systemctl stop "$SVC" || true

      if [[ $TRUNCATE_ONLY -eq 0 ]]; then
        echo "[i] Rotating & vacuuming journald (system-wide)…"
        $SUDO journalctl --rotate || true
        $SUDO journalctl --vacuum-time=1s || true
      fi

      if [[ -d "$APP_LOG_DIR" ]]; then
        echo "[i] Truncating app logs under $APP_LOG_DIR…"
        $SUDO find "$APP_LOG_DIR" -type f -name "*.log*" -exec truncate -s 0 {} \; || true
      fi

      echo "[i] Starting ${SVC}…"
      $SUDO systemctl start "$SVC"
      echo "[✓] Logs cleared."
      exit 0
    fi

    journalctl -u "$SVC" -f -n "$LINES" "${SINCE_ARGS[@]}" ;;

  env)
    [[ "${2:-}" != "edit" ]] && usage && exit 1
    ${EDITOR:-nano} "$ETC_ENV"
    echo "[i] Restart to apply: sudo systemctl restart $SERVICE" ;;

  module)
    shift; [[ "${1:-}" == "new" ]] || { usage; exit 1; }; shift
    NAME=""; TYPE=""; ACTIONS=()
    while [[ $# -gt 0 ]]; do
      case "$1" in --type) TYPE="$2"; shift 2;;
                      --action) ACTIONS+=("$2"); shift 2;;
                      *) NAME="$1"; shift;;
      esac
    done
    [[ -z "$NAME" || -z "$TYPE" ]] && { echo "Need name and --type internal|prosthetic"; exit 1; }
    MODGEN="$PROJECT/utils/mod_gen.py"; [[ -f "$MODGEN" ]] || { echo "mod_gen.py not found at $MODGEN"; exit 1; }
    "$PY" "$MODGEN" "$NAME" "$TYPE" "${ACTIONS[@]:-}"
    echo "[✓] Module scaffolded. Restarting…"
    $SUDO systemctl restart "$SERVICE" ;;

  check)
    "$PY" - <<'PYCHK'
import importlib, pkgutil, sys, pathlib
root = pathlib.Path("/home/kari/Projects/KARI")
sys.path.insert(0, str(root))
ok=True
for pkg in ("internal","prosthetics"):
    p=root/pkg
    if not p.exists(): continue
    for m in pkgutil.iter_modules([str(p)]):
        name=f"{pkg}.{m.name}"
        try: importlib.import_module(name); print(f"[OK] {name}")
        except Exception as e: ok=False; print(f"[ERR] {name}: {e}")
sys.exit(0 if ok else 1)
PYCHK
    ;;

  version)
    [[ -f "$PROJECT/VERSION" ]] && cat "$PROJECT/VERSION" || echo "VERSION file missing" ;;

  update)
    shift; SRC="${1:-}"
    [[ -z "$SRC" ]] && { echo "Provide path to zip/tar/folder"; exit 1; }
    $SUDO ./install-kari.sh update --src "$SRC" ;;

  ctl)
    shift; ctl "$@" ;;

  uninstall)
    $SUDO ./install-kari.sh uninstall ;;

  *)
    usage; exit 1;;
esac
CLISRC
  run "chmod +x ${KARI_CLI_PATH}"
}

install_kari_client(){
  info "Installing kari → ${KARI_SOCKET_CLI}"
  run "install -d -m 0755 /usr/local/bin"

  # Prefer repo script if present (keeps things versioned in git)
  if [[ -f "${KARI_PROJECT_DIR}/scripts/kari" ]]; then
    run "install -m 0755 '${KARI_PROJECT_DIR}/scripts/kari' '${KARI_SOCKET_CLI}'"
    return
  fi

  # Fallback: embed client
  cat <<'KARISRC' | run "tee ${KARI_SOCKET_CLI} >/dev/null"
#!/usr/bin/env bash
set -euo pipefail
SOCK="${KARI_SOCKET:-/run/kari/kari.sock}"

have(){ command -v "$1" >/dev/null 2>&1; }
send(){
  local line="$*"
  if have socat; then
    printf '%s\n' "$line" | socat - UNIX-CONNECT:"$SOCK"
  elif have nc; then
    printf '%s\n' "$line" | nc -U "$SOCK"
  elif have ncat; then
    printf '%s\n' "$line" | ncat -U "$SOCK"
  else
    echo '{"ok":false,"error":"no socat/nc/ncat found"}'
    exit 3
  fi
}
render(){  # pretty print: text -> as-is, string result -> as-is, else pretty JSON
  python - "$@" <<'PY'
import sys, json
data = sys.stdin.read()
try:
    resp = json.loads(data)
except Exception:
    print(data, end=""); sys.exit(0)
# if server sent a friendly text field, show it raw (keeps \n)
if isinstance(resp, dict) and resp.get("ok") and isinstance(resp.get("text"), str):
    print(resp["text"]); sys.exit(0)
# common pattern: result is a string
if isinstance(resp, dict) and isinstance(resp.get("result"), str):
    print(resp["result"]); sys.exit(0)
print(json.dumps(resp, ensure_ascii=False, indent=2))
PY
}
usage(){ cat <<'EOF'
kari — live control of K.A.R.I. via UNIX socket

Usage:
  kari <raw command line>       # e.g. kari status
  kari speak <text...>
  kari phrase <type> [mood]     # boot|banter|react [mood]
  kari debug on|off|toggle
  kari trace on|off|toggle
  kari mods
  kari call <Module> <method> [json]   # kwargs as JSON object or raw string
  kari watch [sec]              # watch status every N seconds (default 2)

Tips:
  kari help                     # global help from DEVILCore
  kari help <Module>            # module help (pretty-rendered)
EOF
}
case "${1:-}" in
  ""|-h|--help) usage ;;
  speak)  shift; send "speak $*" | render ;;
  phrase) shift; [[ $# -lt 1 ]] && { echo "usage: kari phrase <type> [mood]"; exit 2; }
          [[ $# -eq 1 ]] && send "phrase $1" | render || send "phrase $1 $2" | render ;;
  debug)  shift; [[ $# -gt 0 ]] && send "debug $1" | render || send "debug" | render ;;
  trace)  shift; [[ $# -gt 0 ]] && send "trace $1" | render || send "trace" | render ;;
  mods)   send "mods" | render ;;
  call)   shift; [[ $# -lt 2 ]] && { echo "usage: kari call <Module> <method> [json]"; exit 2; }
          mod="$1"; meth="$2"; json="${3:-{}}"
          send "call ${mod@Q} ${meth@Q} ${json@Q}" | render ;;
  watch)  shift; int="${1:-2}"; while true; do clear; echo "K.A.R.I. status — $(date)"; send status | render | sed 's/^/  /'; sleep "$int"; done;;
  *)      send "$*" | render ;;
esac
KARISRC
  run "chmod +x ${KARI_SOCKET_CLI}"
}

# ===== Subcommands =====
do_install(){
  echo ">>> K.A.R.I. installer"
  echo "    user:      $KARI_USER"
  echo "    project:   $KARI_PROJECT_DIR"
  echo "    venv:      $KARI_VENV_DIR"
  echo "    etc:       $KARI_ETC_DIR"
  echo "    env file:  $KARI_ENV_FILE"
  echo "    service:   $KARI_SERVICE"
  echo

  ensure_deps
  ensure_user_and_group
  ensure_project_dir
  create_venv
  write_env_if_missing
  write_units
  install_cli
  install_kari_client
  run "systemctl daemon-reload"
  run "systemctl enable --now kari.service"
  info "Done. Try:"
  echo "  kari-cli status"
  echo "  kari-cli logs"
  echo "  kari status | jq ."
  echo "  kari phrase banter"
}

do_uninstall(){
  info "Uninstalling services & CLI"
  run "systemctl disable --now kari.service || true"
  run "systemctl disable --now kari-pi.service || true"
  run "rm -f ${KARI_SERVICE} ${KARI_PI_SERVICE} || true"
  run "systemctl daemon-reload"
  run "rm -f ${KARI_CLI_PATH} || true"
  run "rm -f ${KARI_SOCKET_CLI} || true"
  info "Left intact (safe): ${KARI_PROJECT_DIR}, ${KARI_VENV_DIR}, ${KARI_ETC_DIR}"
}

do_update(){
  [[ -n "$SRC_PATH" ]] || err "update requires --src ZIP|TAR|DIR"
  [[ -d "$KARI_PROJECT_DIR" ]] || err "Project dir missing: $KARI_PROJECT_DIR"

  ensure_deps
  ensure_user_and_group
  ensure_project_dir

  info "Update from: $SRC_PATH"
  tmpdir="$(extract_src_to_tmp "$SRC_PATH")"
  backup="/tmp/kari-backup-$(date +%s).tar.gz"

  info "Stopping service…"
  run "systemctl stop kari.service || true"

  info "Backup current project → $backup"
  run "tar -czf '$backup' -C '$(dirname "$KARI_PROJECT_DIR")' '$(basename "$KARI_PROJECT_DIR")'"

  info "Sync new files (preserve .venv, logs, .git)"
  run "rsync -a --delete --exclude '.venv' --exclude 'logs' --exclude '.git' '$tmpdir/' '${KARI_PROJECT_DIR}/'"

  run "chown -R ${KARI_USER}:${KARI_GROUP} ${KARI_PROJECT_DIR}"

  if [[ -f "${KARI_PROJECT_DIR}/requirements.txt" ]]; then
    info "Updating Python deps…"
    run "sudo -u ${KARI_USER} ${KARI_VENV_DIR}/bin/pip install -r ${KARI_PROJECT_DIR}/requirements.txt"
  fi

  if [[ -x "${KARI_PROJECT_DIR}/scripts/migrate.sh" ]]; then
    info "Running migration hook…"
    run "sudo -u ${KARI_USER} ${KARI_PROJECT_DIR}/scripts/migrate.sh"
  fi

  info "Reloading units & restarting…"
  run "systemctl daemon-reload"
  if ! run "systemctl start kari.service"; then
    err "Start failed — restoring backup: $backup"
    run "systemctl stop kari.service || true"
    run "rm -rf '${KARI_PROJECT_DIR}'"
    run "mkdir -p '$(dirname "$KARI_PROJECT_DIR")'"
    run "tar -xzf '$backup' -C '$(dirname "$KARI_PROJECT_DIR")'"
    run "systemctl start kari.service"
  fi

  info "Update complete. (Backup kept at $backup)"
}

case "$CMD" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
  update)    do_update ;;
  -h|--help) usage ;;
  *) usage; exit 1;;
esac
