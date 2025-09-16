# utils/control_server.py
import json, os, socket, threading, traceback
from socketserver import ThreadingMixIn, UnixStreamServer, StreamRequestHandler

DEFAULT_SOCKET = "/run/kari/kari.sock"

class _Handler(StreamRequestHandler):
    # self.server.core provided by ControlServer
    def handle(self):
        core = self.server.core
        while True:
            line = self.rfile.readline()
            if not line:
                return
            try:
                req = json.loads(line.decode("utf-8").strip() or "{}")
            except Exception as e:
                self._send({"ok": False, "error": f"invalid json: {e}"})
                continue

            try:
                op = req.get("op")
                if op == "ping":
                    self._send({"ok": True, "pong": True})
                elif op == "say":
                    # route to your VoiceBox
                    text = req.get("text","")
                    vb = core.get_module("internal.voicebox") or core.get_module("VoiceBox")
                    if not vb: raise RuntimeError("voicebox not found")
                    vb.say(text)
                    self._send({"ok": True})
                elif op == "mood":
                    val = req.get("value")
                    me = core.get_module("internal.mood_engine") or core.get_module("Mood Engine") or core.get_module("MoodEngine")
                    if not me: raise RuntimeError("mood engine not found")
                    me.set_mood(val)
                    self._send({"ok": True})
                elif op == "trigger":
                    # trigger a phrase by name (e.g., boot/react/wake_up/banter)
                    phrase = req.get("phrase")
                    core.trigger_phrase(phrase)   # adapt to your phrase bus
                    self._send({"ok": True})
                elif op == "list_modules":
                    self._send({"ok": True, "modules": core.list_modules()})
                elif op == "defcon":
                    level = int(req.get("level"))
                    me = core.get_module("MoodEngine") or core.get_module("internal.mood_engine")
                    if not me: raise RuntimeError("mood engine not found")
                    me.set_defcon(level)  # adapt if your API differs
                    self._send({"ok": True})
                elif op == "action":
                    # run any module action: {"op":"action","module":"internal.mood_engine","method":"report","args":[], "kwargs":{}}
                    modname = req["module"]; method = req["method"]
                    args = req.get("args", []); kwargs = req.get("kwargs", {})
                    mod = core.get_module(modname) or core.get_module(modname.split(".")[-1])
                    if not mod: raise RuntimeError(f"module not found: {modname}")
                    fn = getattr(mod, method)
                    res = fn(*args, **kwargs)
                    self._send({"ok": True, "result": res})
                else:
                    self._send({"ok": False, "error": f"unknown op: {op}"})
            except Exception as e:
                traceback.print_exc()
                self._send({"ok": False, "error": str(e)})

    def _send(self, obj):
        self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))

class _ThreadedUnixServer(ThreadingMixIn, UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

class ControlServer:
    def __init__(self, core, path: str | None = None):
        self.core = core
        self.path = path or os.environ.get("KARI_SOCKET", DEFAULT_SOCKET)
        self._srv = None
        self._thr = None

    def start(self, mode=0o660, uid=None, gid=None):
        # ensure old socket removed
        try: os.unlink(self.path)
        except FileNotFoundError: pass

        basedir = os.path.dirname(self.path)
        os.makedirs(basedir, exist_ok=True)
        self._srv = _ThreadedUnixServer(self.path, _Handler)
        self._srv.core = self.core

        # set permissions
        os.chmod(self.path, mode)
        if uid is not None or gid is not None:
            try: os.chown(self.path, uid if uid is not None else -1, gid if gid is not None else -1)
            except PermissionError: pass

        self._thr = threading.Thread(target=self._srv.serve_forever, name="kari-control", daemon=True)
        self._thr.start()
        return self

    def stop(self):
        try: self._srv.shutdown(); self._srv.server_close()
        finally:
            try: os.unlink(self.path)
            except FileNotFoundError: pass
