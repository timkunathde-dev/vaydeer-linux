"""Gemeinsame Teile fuer Vaydeer-Dienst und -Oberflaeche."""
import glob
import json
import os

VID, PID = 0x0483, 0x5752
NUM_KEYS = 9
NUM_LAYERS = 6   # Ebenen beim ersten Start
MAX_LAYERS = 50

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "vaydeer-linux"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
OVERLAY_PATH = os.path.join(CONFIG_DIR, "overlay.json")
AUTOSTART_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "autostart", "vaydeer-overlay.desktop")

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
STATE_PATH = os.path.join(RUNTIME_DIR, f"vaydeer-linux-state-{os.getuid()}.json")
OVERLAY_LOCK = os.path.join(RUNTIME_DIR, f"vaydeer-overlay-{os.getuid()}.lock")

OVERLAY_DEFAULTS = {"mode": "always", "compact": False, "opacity": 0.9, "x": None, "y": None}

# Medientasten: (evdev-Name, Anzeigename, Symbol)
MEDIA_KEYS = [
    ("KEY_PLAYPAUSE", "Play / Pause", "media-playback-start-symbolic"),
    ("KEY_NEXTSONG", "Nächster Titel", "media-skip-forward-symbolic"),
    ("KEY_PREVIOUSSONG", "Vorheriger Titel", "media-skip-backward-symbolic"),
    ("KEY_STOPCD", "Stopp", "media-playback-stop-symbolic"),
    ("KEY_VOLUMEUP", "Lauter", "audio-volume-high-symbolic"),
    ("KEY_VOLUMEDOWN", "Leiser", "audio-volume-low-symbolic"),
    ("KEY_MUTE", "Ton aus", "audio-volume-muted-symbolic"),
    ("KEY_MICMUTE", "Mikrofon aus", "microphone-sensitivity-muted-symbolic"),
]
MEDIA_BY_KEY = {k: (label, icon) for k, label, icon in MEDIA_KEYS}

# Aktionstypen: (Typ, Titel, Untertitel, Symbol)
ACTION_TYPES = [
    ("combo", "Tastenkombination", "z. B. Strg+C, Super+E", "input-keyboard-symbolic"),
    ("text", "Text eingeben", "Tippt einen festen Text", "insert-text-symbolic"),
    ("app", "Programm starten", "Aus deinen installierten Apps", "application-x-executable-symbolic"),
    ("command", "Befehl ausführen", "Beliebiger Shell-Befehl", "utilities-terminal-symbolic"),
    ("media", "Medien & Lautstärke", "Play, Skip, Lauter, Stumm ...", "media-playback-start-symbolic"),
    ("url", "Webseite öffnen", "Im Standardbrowser", "web-browser-symbolic"),
    ("layer", "Ebene wechseln", "Zwischen Belegungen umschalten", "view-paged-symbolic"),
]
ACTION_INFO = {t: (title, sub, icon) for t, title, sub, icon in ACTION_TYPES}


def new_layer(index):
    return {"name": f"Ebene {index + 1}", "keys": [None] * NUM_KEYS}


def default_config():
    return {"layers": [new_layer(i) for i in range(NUM_LAYERS)]}


def normalize(cfg):
    layers = []
    try:
        for i, layer in enumerate(cfg.get("layers", [])[:MAX_LAYERS]):
            out = new_layer(i)
            if isinstance(layer.get("name"), str) and layer["name"].strip():
                out["name"] = layer["name"]
            keys = layer.get("keys", [])
            for k in range(min(NUM_KEYS, len(keys))):
                if isinstance(keys[k], dict) and keys[k].get("type") in ACTION_INFO:
                    out["keys"][k] = keys[k]
            layers.append(out)
    except (AttributeError, TypeError):
        pass
    return {"layers": layers} if layers else default_config()


def resolve_layer_target(target, current, count):
    """Ziel einer Ebenen-Aktion -> Index der neuen Ebene."""
    if target == "next":
        return (current + 1) % count
    if target == "prev":
        return (current - 1) % count
    try:
        return int(target) % count
    except (TypeError, ValueError):
        return current


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return default_config()


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def config_mtime():
    try:
        return os.stat(CONFIG_PATH).st_mtime_ns
    except OSError:
        return 0


def find_hidraw():
    """Alle hidraw-Knoten des Vaydeer-Pads."""
    found = []
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(path, "device", "uevent")) as f:
                for line in f:
                    if line.startswith("HID_ID="):
                        _, vid, pid = line.strip().split("=", 1)[1].split(":")
                        if int(vid, 16) == VID and int(pid, 16) == PID:
                            found.append("/dev/" + os.path.basename(path))
        except (OSError, ValueError):
            continue
    return found


def parse_report(data):
    """Rohreport -> (taste 0..8, gedrueckt) oder None.

    Format: fb 03 ?? KK SS CC  (KK Taste, SS 00=gedrueckt 02=los, CC XOR-Pruefsumme)
    """
    if len(data) < 6 or data[0] != 0xFB or data[1] != 0x03:
        return None
    if data[0] ^ data[1] ^ data[2] ^ data[3] ^ data[4] != data[5]:
        return None
    key = data[3]
    if key >= NUM_KEYS:
        return None
    return key, data[4] == 0x00


def describe(action):
    """Kurzer Anzeigetext fuer eine Aktion."""
    if not action:
        return ""
    t = action.get("type")
    if t == "combo":
        return action.get("label", "Kombination")
    if t == "text":
        txt = action.get("text", "").replace("\n", " ")
        return (txt[:22] + "...") if len(txt) > 25 else txt
    if t == "app":
        return action.get("name", "Programm")
    if t == "command":
        cmd = action.get("command", "")
        return (cmd[:22] + "...") if len(cmd) > 25 else cmd
    if t == "media":
        return MEDIA_BY_KEY.get(action.get("key"), ("Medien", ""))[0]
    if t == "url":
        url = action.get("url", "")
        for p in ("https://", "http://", "www."):
            if url.startswith(p):
                url = url[len(p):]
        return (url[:22] + "...") if len(url) > 25 else url
    if t == "layer":
        target = action.get("target", "next")
        if target == "next":
            return "Nächste Ebene"
        if target == "prev":
            return "Vorherige Ebene"
        return f"Zu Ebene {int(target) + 1}"
    return t


# ---- Status zwischen Dienst, App und Overlay ------------------------------
def file_mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def write_state(layer):
    """Vom Dienst: aktuell aktive Ebene melden."""
    try:
        _atomic_json(STATE_PATH, {"layer": layer, "pid": os.getpid()})
    except OSError:
        pass


def read_state():
    """Aktive Ebene des Dienstes oder None."""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid and not os.path.exists(f"/proc/{pid}"):
            return None
        return int(data["layer"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load_overlay():
    out = dict(OVERLAY_DEFAULTS)
    try:
        with open(OVERLAY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("mode") in ("always", "auto"):
            out["mode"] = data["mode"]
        out["compact"] = bool(data.get("compact", False))
        out["opacity"] = min(1.0, max(0.3, float(data.get("opacity", 0.9))))
        for k in ("x", "y"):
            out[k] = int(data[k]) if data.get(k) is not None else None
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return out


def save_overlay(settings):
    try:
        _atomic_json(OVERLAY_PATH, settings)
    except OSError:
        pass


def update_overlay(**changes):
    """Einzelne Overlay-Einstellungen aendern, Rest (z. B. Position) behalten."""
    s = load_overlay()
    s.update(changes)
    save_overlay(s)


def overlay_pid():
    """PID des laufenden Overlays oder None."""
    try:
        with open(OVERLAY_LOCK) as f:
            pid = int(f.read().strip() or 0)
        if pid and os.path.exists(f"/proc/{pid}"):
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"vaydeer-overlay" in f.read():
                    return pid
    except (OSError, ValueError):
        pass
    return None
