#!/usr/bin/env python3
"""Vaydeer fuer Linux - Hintergrunddienst.

Liest die Rohdaten des Vaydeer 9-key Smart Keypad (0483:5752) und fuehrt die in
~/.config/vaydeer-linux/config.json hinterlegten Aktionen aus.
Unbelegte Tasten senden F13..F21.

Test im Terminal:  python3 vaydeerd.py --debug
"""
import os
import select
import shutil
import subprocess
import sys
import threading
import time

from evdev import UInput, ecodes as e

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vaydeer_common as vc  # noqa: E402

DEBUG = "--debug" in sys.argv
FALLBACK = [e.KEY_F13 + i for i in range(vc.NUM_KEYS)]  # F13..F21

# ---- Deutsches Tastaturlayout (QWERTZ) fuer "Text eingeben" ---------------
SHIFT, ALTGR = e.KEY_LEFTSHIFT, e.KEY_RIGHTALT
LAYOUT = {" ": (e.KEY_SPACE, ()), "\n": (e.KEY_ENTER, ()), "\t": (e.KEY_TAB, ())}
for ch in "abcdefghijklmnopqrstuvwxyz":
    code = getattr(e, "KEY_" + {"y": "Z", "z": "Y"}.get(ch, ch.upper()))
    LAYOUT[ch] = (code, ())
    LAYOUT[ch.upper()] = (code, (SHIFT,))
for i, ch in enumerate("1234567890"):
    LAYOUT[ch] = (getattr(e, f"KEY_{ch}"), ())
for ch, base in zip('!"§$%&/()=', "1234567890"):
    LAYOUT[ch] = (getattr(e, f"KEY_{base}"), (SHIFT,))
LAYOUT.update({
    "ß": (e.KEY_MINUS, ()), "?": (e.KEY_MINUS, (SHIFT,)), "\\": (e.KEY_MINUS, (ALTGR,)),
    "ü": (e.KEY_LEFTBRACE, ()), "Ü": (e.KEY_LEFTBRACE, (SHIFT,)),
    "+": (e.KEY_RIGHTBRACE, ()), "*": (e.KEY_RIGHTBRACE, (SHIFT,)), "~": (e.KEY_RIGHTBRACE, (ALTGR,)),
    "ö": (e.KEY_SEMICOLON, ()), "Ö": (e.KEY_SEMICOLON, (SHIFT,)),
    "ä": (e.KEY_APOSTROPHE, ()), "Ä": (e.KEY_APOSTROPHE, (SHIFT,)),
    "#": (e.KEY_BACKSLASH, ()), "'": (e.KEY_BACKSLASH, (SHIFT,)),
    "<": (e.KEY_102ND, ()), ">": (e.KEY_102ND, (SHIFT,)), "|": (e.KEY_102ND, (ALTGR,)),
    ",": (e.KEY_COMMA, ()), ";": (e.KEY_COMMA, (SHIFT,)),
    ".": (e.KEY_DOT, ()), ":": (e.KEY_DOT, (SHIFT,)),
    "-": (e.KEY_SLASH, ()), "_": (e.KEY_SLASH, (SHIFT,)),
    "°": (e.KEY_GRAVE, (SHIFT,)),
    "@": (e.KEY_Q, (ALTGR,)), "€": (e.KEY_E, (ALTGR,)),
    "{": (e.KEY_7, (ALTGR,)), "[": (e.KEY_8, (ALTGR,)),
    "]": (e.KEY_9, (ALTGR,)), "}": (e.KEY_0, (ALTGR,)),
    "²": (e.KEY_2, (ALTGR,)), "³": (e.KEY_3, (ALTGR,)), "µ": (e.KEY_M, (ALTGR,)),
})
# Tottasten: Taste druecken, danach Leertaste
DEAD = {"^": (e.KEY_GRAVE, ()), "´": (e.KEY_EQUAL, ()), "`": (e.KEY_EQUAL, (SHIFT,))}


def log(*args):
    if DEBUG:
        print(*args, flush=True)


class Daemon:
    def __init__(self, ui):
        self.ui = ui
        self.lock = threading.Lock()
        self.cfg = vc.load_config()
        self.mtime = vc.config_mtime()
        self.layer = 0
        self.held = {}  # Taste -> Liste gedrueckter Keycodes (Kombi halten)
        vc.write_state(self.layer)

    # ---- uinput-Helfer ---------------------------------------------------
    def _emit(self, code, value):
        self.ui.write(e.EV_KEY, code, value)
        self.ui.syn()

    def tap(self, code, mods=()):
        with self.lock:
            for m in mods:
                self._emit(m, 1)
            self._emit(code, 1)
            self._emit(code, 0)
            for m in reversed(mods):
                self._emit(m, 0)
        time.sleep(0.004)

    def type_text(self, text):
        for ch in text:
            if ch in LAYOUT:
                self.tap(*LAYOUT[ch])
            elif ch in DEAD:
                self.tap(*DEAD[ch])
                self.tap(e.KEY_SPACE)
            else:
                log(f"Zeichen nicht tippbar: {ch!r}")

    # ---- Konfiguration ---------------------------------------------------
    def reload_if_changed(self):
        m = vc.config_mtime()
        if m != self.mtime:
            self.mtime = m
            self.cfg = vc.load_config()
            if self.layer >= len(self.cfg["layers"]):
                self.layer = 0
                vc.write_state(self.layer)
            log("Konfiguration neu geladen.")

    def action_for(self, key):
        return self.cfg["layers"][self.layer]["keys"][key]

    # ---- Ereignisse ------------------------------------------------------
    def on_key(self, key, pressed):
        if pressed:
            self.reload_if_changed()
            action = self.action_for(key)
            log(f"Taste {key + 1} gedrueckt (Ebene {self.layer + 1}): {action}")
            self.press(key, action)
        else:
            self.release(key)

    def press(self, key, action):
        if not action:
            self.held[key] = [FALLBACK[key]]
            with self.lock:
                self._emit(FALLBACK[key], 1)
            return
        t = action["type"]
        if t == "combo":
            codes = [c for c in action.get("keys", []) if isinstance(c, int) and 0 < c < 0x2FF]
            self.held[key] = codes
            with self.lock:
                for c in codes:
                    self._emit(c, 1)
        elif t == "media":
            code = getattr(e, action.get("key", ""), None)
            if code:
                self.tap(code)
        elif t == "text":
            threading.Thread(target=self.type_text, args=(action.get("text", ""),), daemon=True).start()
        elif t == "app":
            self.launch_app(action)
        elif t == "command":
            self.spawn(action.get("command", ""), shell=True)
        elif t == "url":
            url = action.get("url", "").strip()
            if url and "://" not in url:
                url = "https://" + url
            if url:
                self.spawn(["xdg-open", url])
        elif t == "layer":
            self.layer = vc.resolve_layer_target(action.get("target", "next"), self.layer,
                                                 len(self.cfg["layers"]))
            vc.write_state(self.layer)
            name = self.cfg["layers"][self.layer]["name"]
            log(f"Ebene gewechselt: {self.layer + 1} {name}")
            if shutil.which("notify-send"):
                self.spawn(["notify-send", "-a", "Vaydeer", "-i", "input-keyboard",
                            "-h", "string:x-canonical-private-synchronous:vaydeer",
                            "-t", "1500", f"Ebene {self.layer + 1}", name])

    def release(self, key):
        codes = self.held.pop(key, [])
        with self.lock:
            for c in reversed(codes):
                self._emit(c, 0)

    def launch_app(self, action):
        path = action.get("desktop", "")
        if path and os.path.exists(path) and shutil.which("gio"):
            self.spawn(["gio", "launch", path])
        elif action.get("id") and shutil.which("gtk-launch"):
            self.spawn(["gtk-launch", action["id"]])
        else:
            log("Programm nicht gefunden:", action)

    @staticmethod
    def spawn(cmd, shell=False):
        if not cmd:
            return
        try:
            subprocess.Popen(cmd, shell=shell, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as err:
            log("Start fehlgeschlagen:", err)

    def release_all(self):
        for key in list(self.held):
            self.release(key)


def run():
    capabilities = {e.EV_KEY: sorted(set(range(1, 249)) | set(FALLBACK))}
    ui = UInput(capabilities, name="Vaydeer Macro Keys")
    d = Daemon(ui)
    log("Virtuelles Geraet 'Vaydeer Macro Keys' angelegt.")
    warned = False
    while True:
        fds = {}
        devices = vc.find_hidraw()
        for dev in devices:
            try:
                fds[os.open(dev, os.O_RDONLY | os.O_NONBLOCK)] = dev
            except PermissionError:
                if not warned:
                    print(f"Keine Berechtigung fuer {dev} - udev-Regel aktiv? Ggf. neu anmelden.",
                          file=sys.stderr, flush=True)
                    warned = True
            except OSError:
                pass
        if not fds:
            time.sleep(2)
            continue
        warned = False
        log("Lese von:", ", ".join(fds.values()))
        try:
            while True:
                ready, _, _ = select.select(list(fds), [], [])
                for fd in ready:
                    parsed = vc.parse_report(os.read(fd, 64))
                    if parsed:
                        d.on_key(*parsed)
        except OSError:
            log("Pad getrennt, suche neu ...")
            d.release_all()
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
        time.sleep(1)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
