#!/usr/bin/env python3
"""Vaydeer fuer Linux - Oberflaeche zum Belegen der 9 Tasten per Drag & Drop."""
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vaydeer_common as vc  # noqa: E402

APP_ID = "io.github.vaydeer_linux"
HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY_SCRIPT = os.path.join(HERE, "vaydeer-overlay.py")
OVERLAY_LAUNCHER = "/usr/local/bin/vaydeer-overlay"

# evdev-Codes der Modifikatortasten
MOD_NAMES = {29: "Strg", 97: "Strg", 42: "Shift", 54: "Shift",
             56: "Alt", 100: "AltGr", 125: "Super", 126: "Super"}
KEY_NAMES = {
    "Return": "Enter", "KP_Enter": "Enter", "space": "Leertaste", "Escape": "Esc",
    "Delete": "Entf", "BackSpace": "Rücktaste", "Tab": "Tab", "ISO_Left_Tab": "Tab",
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→", "Page_Up": "Bild↑",
    "Page_Down": "Bild↓", "Home": "Pos1", "End": "Ende", "Insert": "Einfg",
    "Print": "Druck", "Pause": "Pause", "Menu": "Menü",
}

CSS = b"""
.sidebar { padding: 18px; }
.heading { font-weight: bold; font-size: 1.15em; }
.dim { opacity: 0.65; }
.small { font-size: 0.85em; }
.palette-item {
  padding: 10px 12px; border-radius: 10px;
  background: alpha(currentColor, 0.05);
  border: 1px solid alpha(currentColor, 0.08);
}
.palette-item:hover { background: alpha(currentColor, 0.10); }
.palette-title { font-weight: bold; }
.key {
  padding: 10px 12px; border-radius: 16px;
  background: alpha(currentColor, 0.04);
  border: 2px dashed alpha(currentColor, 0.18);
  transition: background 120ms, border-color 120ms;
}
.key:hover { background: alpha(currentColor, 0.08); }
.key.assigned {
  border-style: solid;
  border-color: alpha(@theme_selected_bg_color, 0.55);
  background: alpha(@theme_selected_bg_color, 0.12);
}
.key.drop-hover {
  border-style: solid; border-color: @theme_selected_bg_color;
  background: alpha(@theme_selected_bg_color, 0.22);
}
.key.pressed {
  background: @theme_selected_bg_color; color: @theme_selected_fg_color;
  border-color: @theme_selected_bg_color;
}
.keynum { font-size: 0.8em; opacity: 0.6; font-weight: bold; }
.keylabel { font-weight: bold; }
.capture { font-size: 1.2em; min-height: 52px; }
.capture.recording { color: @theme_selected_bg_color; }
.error { color: #c01c28; }
.status-ok { color: #26a269; }
.status-warn { color: #c64600; }
.live-layer { box-shadow: inset 0 -3px @theme_selected_bg_color; font-weight: bold; }
.legend { font-size: 0.8em; opacity: 0.6; }
"""


def string_provider(text):
    val = GObject.Value()
    val.init(GObject.TYPE_STRING)
    val.set_string(text)
    return Gdk.ContentProvider.new_for_value(val)


def action_icon(action, size=40):
    """Gtk.Image passend zur Aktion."""
    img = Gtk.Image(pixel_size=size)
    t = action.get("type")
    if t == "app" and action.get("icon"):
        try:
            img.set_from_gicon(Gio.Icon.new_for_string(action["icon"]))
            return img
        except GLib.Error:
            pass
    if t == "media":
        img.set_from_icon_name(vc.MEDIA_BY_KEY.get(action.get("key"), ("", "media-playback-start-symbolic"))[1])
    else:
        img.set_from_icon_name(vc.ACTION_INFO[t][2])
    return img


def selectable_list(rows, selected=None):
    """ListBox aus (icon, text)-Zeilen; liefert die ListBox."""
    lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
    for i, (icon, text) in enumerate(rows):
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        if isinstance(icon, Gio.Icon):
            box.append(Gtk.Image(gicon=icon, pixel_size=24))
        elif icon:
            box.append(Gtk.Image(icon_name=icon, pixel_size=24))
        box.append(Gtk.Label(label=text, xalign=0))
        lb.append(box)
        if i == selected:
            lb.select_row(lb.get_row_at_index(i))
    return lb


# --------------------------------------------------------------------------
class Editor(Gtk.Window):
    """Dialog zum Einstellen einer Aktion."""

    def __init__(self, parent, atype, action, on_save):
        title = vc.ACTION_INFO[atype][0]
        super().__init__(transient_for=parent, modal=True, title=title,
                         default_width=480, resizable=True)
        self.parent_win = parent
        self.atype = atype
        self.action = dict(action or {})
        self.on_save = on_save

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.set_child(outer)
        self.get_value = getattr(self, "build_" + atype)(outer)

        self.err = Gtk.Label(xalign=0, css_classes=["error"], wrap=True)
        outer.append(self.err)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Abbrechen")
        cancel.connect("clicked", lambda *_: self.close())
        ok = Gtk.Button(label="Übernehmen", css_classes=["suggested-action"])
        ok.connect("clicked", self.on_ok)
        buttons.append(cancel)
        buttons.append(ok)
        outer.append(buttons)

    def on_ok(self, *_):
        value = self.get_value()
        if isinstance(value, str):
            self.err.set_text(value)
            return
        value["type"] = self.atype
        self.on_save(value)
        self.close()

    @staticmethod
    def hint(text):
        return Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["dim", "small"])

    # ---- Tastenkombination -------------------------------------------------
    def build_combo(self, box):
        box.append(self.hint("Klicke auf das Feld und drücke dann die gewünschte "
                             "Kombination auf deiner normalen Tastatur."))
        self.cap_keys = list(self.action.get("keys", []))
        self.cap_label = self.action.get("label", "")
        self.capturing = False
        self.held_mods = []
        self.capture = Gtk.Button(label=self.cap_label or "Hier klicken, dann Tasten drücken",
                                  css_classes=["capture"])
        self.capture.connect("clicked", self.start_capture)
        box.append(self.capture)
        box.append(self.hint("Die Kombination bleibt gedrückt, solange du die Pad-Taste hältst."))

        ctrl = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        ctrl.connect("key-pressed", self.on_cap_press)
        ctrl.connect("key-released", self.on_cap_release)
        self.add_controller(ctrl)

        def get():
            if not self.cap_keys:
                return "Bitte zuerst eine Kombination aufnehmen."
            return {"keys": self.cap_keys, "label": self.cap_label}
        return get

    def start_capture(self, *_):
        self.capturing = True
        self.held_mods = []
        self.capture.set_label("Tasten jetzt drücken …")
        self.capture.add_css_class("recording")

    def mods_label(self, mods):
        names = []
        for m in mods:
            n = MOD_NAMES[m]
            if n not in names:
                names.append(n)
        return names

    @staticmethod
    def key_name(keycode, keyval):
        base = keyval
        display = Gdk.Display.get_default()
        try:
            ok, _keys, keyvals = display.map_keycode(keycode)
            if ok and keyvals:
                base = keyvals[0]
        except (TypeError, ValueError):
            pass
        name = Gdk.keyval_name(base) or "?"
        if name in KEY_NAMES:
            return KEY_NAMES[name]
        uni = Gdk.keyval_to_unicode(base)
        if uni and chr(uni).isprintable() and not chr(uni).isspace():
            return chr(uni).upper()
        return name

    def finish_capture(self, codes, label):
        self.capturing = False
        self.cap_keys = codes
        self.cap_label = label
        self.capture.set_label(label)
        self.capture.remove_css_class("recording")
        self.err.set_text("")

    def on_cap_press(self, ctrl, keyval, keycode, state):
        if not self.capturing:
            return False
        code = keycode - 8
        if code in MOD_NAMES:
            if code not in self.held_mods:
                self.held_mods.append(code)
            self.capture.set_label("+".join(self.mods_label(self.held_mods)) + " + …")
            return True
        label = "+".join(self.mods_label(self.held_mods) + [self.key_name(keycode, keyval)])
        self.finish_capture(self.held_mods + [code], label)
        return True

    def on_cap_release(self, ctrl, keyval, keycode, state):
        if self.capturing and (keycode - 8) in self.held_mods:
            # nur Modifikatoren gedrueckt (z. B. Super allein)
            self.finish_capture(list(self.held_mods), "+".join(self.mods_label(self.held_mods)))

    # ---- Text --------------------------------------------------------------
    def build_text(self, box):
        sw = Gtk.ScrolledWindow(min_content_height=140, has_frame=True)
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.get_buffer().set_text(self.action.get("text", ""))
        sw.set_child(tv)
        box.append(sw)
        box.append(self.hint("Wird mit deutschem Tastaturlayout getippt. "
                             "Ein Zeilenumbruch drückt Enter."))
        GLib.idle_add(tv.grab_focus)

        def get():
            buf = tv.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            return {"text": text} if text else "Bitte einen Text eingeben."
        return get

    # ---- Programm ----------------------------------------------------------
    def build_app(self, box):
        self.set_default_size(480, 560)
        search = Gtk.SearchEntry(placeholder_text="Programm suchen …")
        box.append(search)
        apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        apps.sort(key=lambda a: a.get_display_name().casefold())
        selected = next((i for i, a in enumerate(apps) if a.get_id() == self.action.get("id")), None)
        lb = selectable_list([(a.get_icon(), a.get_display_name()) for a in apps], selected)
        lb.set_filter_func(lambda row: search.get_text().casefold()
                           in apps[row.get_index()].get_display_name().casefold())
        search.connect("search-changed", lambda *_: lb.invalidate_filter())
        sw = Gtk.ScrolledWindow(vexpand=True, min_content_height=320, has_frame=True)
        sw.set_child(lb)
        box.append(sw)
        GLib.idle_add(search.grab_focus)

        def get():
            row = lb.get_selected_row()
            if row is None:
                return "Bitte ein Programm auswählen."
            a = apps[row.get_index()]
            icon = a.get_icon()
            return {"id": a.get_id(), "name": a.get_display_name(),
                    "desktop": getattr(a, "get_filename", lambda: "")() or "",
                    "icon": icon.to_string() if icon else ""}
        return get

    # ---- Befehl ------------------------------------------------------------
    def build_command(self, box):
        entry = Gtk.Entry(text=self.action.get("command", ""),
                          placeholder_text="z. B. nautilus ~/Downloads")
        box.append(entry)
        row = Gtk.Box(spacing=8)
        row.append(self.hint("Wird als dein Benutzer in einer Shell ausgeführt."))
        test = Gtk.Button(label="Jetzt testen", halign=Gtk.Align.END, hexpand=True)
        test.connect("clicked", lambda *_: entry.get_text().strip() and subprocess.Popen(
            entry.get_text(), shell=True, start_new_session=True))
        row.append(test)
        box.append(row)

        def get():
            cmd = entry.get_text().strip()
            return {"command": cmd} if cmd else "Bitte einen Befehl eingeben."
        return get

    # ---- Medien ------------------------------------------------------------
    def build_media(self, box):
        keys = [k for k, _, _ in vc.MEDIA_KEYS]
        selected = keys.index(self.action["key"]) if self.action.get("key") in keys else 0
        lb = selectable_list([(icon, label) for _, label, icon in vc.MEDIA_KEYS], selected)
        box.append(lb)

        def get():
            row = lb.get_selected_row()
            return {"key": keys[row.get_index()]} if row else "Bitte eine Funktion wählen."
        return get

    # ---- URL ---------------------------------------------------------------
    def build_url(self, box):
        entry = Gtk.Entry(text=self.action.get("url", ""), placeholder_text="https://…")
        box.append(entry)

        def get():
            url = entry.get_text().strip()
            return {"url": url} if url else "Bitte eine Adresse eingeben."
        return get

    # ---- Ebene -------------------------------------------------------------
    def build_layer(self, box):
        layers = self.parent_win.cfg["layers"]
        self.set_default_size(480, 520)
        rows = [("go-next-symbolic", "Nächste Ebene (der Reihe nach)"),
                ("go-previous-symbolic", "Vorherige Ebene")]
        rows += [(None, f"Ebene {i + 1}: {l['name']}") for i, l in enumerate(layers)]
        target = self.action.get("target", "next")
        if target == "next":
            selected = 0
        elif target == "prev":
            selected = 1
        else:
            selected = min(int(target), len(layers) - 1) + 2
        lb = selectable_list(rows, selected)
        sw = Gtk.ScrolledWindow(vexpand=True, min_content_height=260, has_frame=True,
                                hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(lb)
        box.append(sw)
        box.append(self.hint("Tipp: Lege auf jeder Ebene dieselbe Taste auf "
                             "„Nächste Ebene“, dann kannst du immer weiterschalten."))

        def get():
            row = lb.get_selected_row()
            if row is None:
                return "Bitte eine Ebene wählen."
            i = row.get_index()
            return {"target": "next" if i == 0 else "prev" if i == 1 else i - 2}
        return get


# --------------------------------------------------------------------------
class KeyTile(Gtk.Box):
    """Eine der 9 Tasten im Raster."""

    def __init__(self, win, index):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["key"])
        self.win = win
        self.index = index
        self.set_size_request(200, 150)

        top = Gtk.Box()
        top.append(Gtk.Label(label=f"TASTE {index + 1}", xalign=0, hexpand=True, css_classes=["keynum"]))
        self.clear_btn = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"],
                                    tooltip_text="Belegung entfernen", valign=Gtk.Align.START)
        self.clear_btn.connect("clicked", lambda *_: self.win.set_key(self.index, None))
        top.append(self.clear_btn)
        self.append(top)

        self.icon_slot = Gtk.Box(halign=Gtk.Align.CENTER, vexpand=True, valign=Gtk.Align.CENTER)
        self.append(self.icon_slot)
        self.type_label = Gtk.Label(css_classes=["dim", "small"])
        self.append(self.type_label)
        self.main_label = Gtk.Label(css_classes=["keylabel"], ellipsize=3, max_width_chars=20)
        self.append(self.main_label)

        # Ablegen
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("drop", lambda _t, value, _x, _y: self.win.on_drop(self.index, value))
        self.add_controller(drop)
        motion = Gtk.DropControllerMotion()
        motion.connect("enter", lambda *_: self.add_css_class("drop-hover"))
        motion.connect("leave", lambda *_: self.remove_css_class("drop-hover"))
        self.add_controller(motion)

        # Ziehen (Taste auf Taste = tauschen)
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", self.on_prepare)
        drag.connect("drag-begin", lambda src, _d: src.set_icon(Gtk.WidgetPaintable.new(self), 100, 75))
        self.add_controller(drag)

        # Klick = bearbeiten
        click = Gtk.GestureClick()
        click.connect("released", self.on_click)
        self.add_controller(click)
        self.set_cursor_from_name("pointer")

    def on_prepare(self, _src, _x, _y):
        if not self.win.current_keys()[self.index]:
            return None
        return string_provider(f"key:{self.index}")

    def on_click(self, gesture, _n, x, y):
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and picked is not self:
            if picked is self.clear_btn:
                return
            picked = picked.get_parent()
        action = self.win.current_keys()[self.index]
        if action:
            self.win.open_editor(self.index, action["type"], action)
        else:
            self.win.choose_type(self.index)

    def refresh(self, action):
        child = self.icon_slot.get_first_child()
        if child:
            self.icon_slot.remove(child)
        if action:
            self.add_css_class("assigned")
            self.icon_slot.append(action_icon(action))
            self.type_label.set_text(vc.ACTION_INFO[action["type"]][0])
            self.main_label.set_text(vc.describe(action))
            self.clear_btn.set_visible(True)
        else:
            self.remove_css_class("assigned")
            img = Gtk.Image(icon_name="list-add-symbolic", pixel_size=32, css_classes=["dim"])
            self.icon_slot.append(img)
            self.type_label.set_text(f"unbelegt · sendet F{13 + self.index}")
            self.main_label.set_text("Aktion hierher ziehen")
            self.clear_btn.set_visible(False)

    def set_pressed(self, pressed):
        (self.add_css_class if pressed else self.remove_css_class)("pressed")


# --------------------------------------------------------------------------
class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Vaydeer für Linux",
                         default_width=1040, default_height=680)
        self.cfg = vc.load_config()
        self.layer = 0
        self.updating = False
        self.save_source = 0
        self.hid = {}  # fd -> GLib-Quelle

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        header.pack_start(self.build_overlay_button())
        self.service_btn = Gtk.Button(label="Dienst starten", visible=False)
        self.service_btn.connect("clicked", self.start_service)
        header.pack_end(self.service_btn)
        self.status = Gtk.Label()
        header.pack_end(self.status)

        root = Gtk.Box()
        self.set_child(root)

        # Seitenleiste mit Aktionen
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["sidebar"])
        side.set_size_request(280, -1)
        side.append(Gtk.Label(label="Aktionen", xalign=0, css_classes=["heading"]))
        side.append(Gtk.Label(label="Ziehe eine Aktion auf eine Taste.", xalign=0,
                              wrap=True, css_classes=["dim", "small"]))
        for t, title, sub, icon in vc.ACTION_TYPES:
            side.append(self.palette_item(t, title, sub, icon))
        root.append(side)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Hauptbereich
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, hexpand=True,
                       margin_top=20, margin_bottom=20, margin_start=24, margin_end=24)
        root.append(main)

        bar = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        bar.append(Gtk.Label(label="Ebene", css_classes=["dim"]))
        self.layer_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_width=True, max_content_width=420)
        self.layer_box = Gtk.Box(css_classes=["linked"])
        self.layer_scroll.set_child(self.layer_box)
        bar.append(self.layer_scroll)
        self.layer_buttons = []

        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Neue leere Ebene")
        add_btn.connect("clicked", lambda *_: self.add_layer(copy=False))
        bar.append(add_btn)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.name_entry = Gtk.Entry(width_chars=16, placeholder_text="Name der Ebene")
        self.name_entry.connect("changed", self.on_name_changed)
        bar.append(self.name_entry)
        dup_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Ebene duplizieren")
        dup_btn.connect("clicked", lambda *_: self.add_layer(copy=True))
        bar.append(dup_btn)
        self.del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Ebene löschen")
        self.del_btn.connect("clicked", self.ask_delete_layer)
        bar.append(self.del_btn)
        main.append(bar)

        grid = Gtk.Grid(row_spacing=14, column_spacing=14, halign=Gtk.Align.CENTER,
                        valign=Gtk.Align.CENTER, vexpand=True)
        self.tiles = []
        for i in range(vc.NUM_KEYS):
            tile = KeyTile(self, i)
            grid.attach(tile, i % 3, i // 3, 1, 1)
            self.tiles.append(tile)
        main.append(grid)

        main.append(Gtk.Label(
            label="Klick auf eine Taste: bearbeiten  ·  Taste auf Taste ziehen: tauschen  ·  "
                  "Drückst du eine Pad-Taste, leuchtet sie hier auf.",
            wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim", "small"]))

        self.rebuild_layer_buttons()
        self.update_status()
        GLib.timeout_add_seconds(3, self.update_status)
        self.live_layer = None
        GLib.timeout_add(500, self.update_live_layer)
        self.connect("close-request", self.on_close)

    # ---- Aufbau ------------------------------------------------------------
    def palette_item(self, atype, title, sub, icon):
        box = Gtk.Box(spacing=12, css_classes=["palette-item"])
        box.append(Gtk.Image(icon_name=icon, pixel_size=28))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.append(Gtk.Label(label=title, xalign=0, css_classes=["palette-title"]))
        texts.append(Gtk.Label(label=sub, xalign=0, css_classes=["dim", "small"]))
        box.append(texts)
        box.set_cursor_from_name("grab")
        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.connect("prepare", lambda *_: string_provider(f"palette:{atype}"))
        drag.connect("drag-begin", lambda src, _d: src.set_icon(Gtk.WidgetPaintable.new(box), 20, 20))
        box.add_controller(drag)
        return box

    # ---- Daten -------------------------------------------------------------
    def current_keys(self):
        return self.cfg["layers"][self.layer]["keys"]

    def save(self):
        vc.save_config(self.cfg)

    def refresh(self):
        self.updating = True
        self.name_entry.set_text(self.cfg["layers"][self.layer]["name"])
        self.updating = False
        for i, b in enumerate(self.layer_buttons):
            b.set_tooltip_text(self.cfg["layers"][i]["name"])
        self.del_btn.set_sensitive(len(self.cfg["layers"]) > 1)
        for tile, action in zip(self.tiles, self.current_keys()):
            tile.refresh(action)

    def set_key(self, index, action):
        self.current_keys()[index] = action
        self.save()
        self.tiles[index].refresh(action)

    # ---- Ebenen verwalten --------------------------------------------------
    def rebuild_layer_buttons(self):
        """Ebenen-Knoepfe neu aufbauen und aktuelle Ebene auswaehlen."""
        self.layer = min(self.layer, len(self.cfg["layers"]) - 1)
        self.updating = True
        while child := self.layer_box.get_first_child():
            self.layer_box.remove(child)
        self.layer_buttons = []
        first = None
        for i in range(len(self.cfg["layers"])):
            b = Gtk.ToggleButton(label=str(i + 1))
            if first:
                b.set_group(first)
            else:
                first = b
            b.connect("toggled", self.on_layer_toggled, i)
            self.layer_box.append(b)
            self.layer_buttons.append(b)
        self.layer_buttons[self.layer].set_active(True)
        self.updating = False
        self.refresh()
        self.live_layer = -1
        if hasattr(self, "tiles"):
            self.update_live_layer()
        GLib.idle_add(self.scroll_to_layer)

    def scroll_to_layer(self):
        btn = self.layer_buttons[self.layer]
        adj = self.layer_scroll.get_hadjustment()
        ok, rect = btn.compute_bounds(self.layer_box)
        if ok:
            x = rect.get_x()
            w = rect.get_width()
            if x < adj.get_value():
                adj.set_value(x)
            elif x + w > adj.get_value() + adj.get_page_size():
                adj.set_value(x + w - adj.get_page_size())
        return False

    def on_layer_toggled(self, button, index):
        if button.get_active() and not self.updating:
            self.layer = index
            self.refresh()

    def add_layer(self, copy):
        layers = self.cfg["layers"]
        if len(layers) >= vc.MAX_LAYERS:
            return
        if copy:
            src = layers[self.layer]
            layer = {"name": f"{src['name']} (Kopie)",
                     "keys": [dict(a) if a else None for a in src["keys"]]}
        else:
            layer = vc.new_layer(len(layers))
        insert_at = self.layer + 1 if copy else len(layers)
        layers.insert(insert_at, layer)
        # Spruenge auf Ebenen hinter der Einfuegestelle mitverschieben
        for lyr in layers:
            for a in lyr["keys"]:
                if a and a["type"] == "layer" and isinstance(a.get("target"), int) \
                        and a["target"] >= insert_at:
                    a["target"] += 1
        self.layer = insert_at
        self.save()
        self.rebuild_layer_buttons()
        if not copy:
            GLib.idle_add(self.name_entry.grab_focus)

    def ask_delete_layer(self, *_):
        if len(self.cfg["layers"]) <= 1:
            return
        layer = self.cfg["layers"][self.layer]
        used = sum(1 for a in layer["keys"] if a)
        jumps = sum(1 for i, lyr in enumerate(self.cfg["layers"]) if i != self.layer
                    for a in lyr["keys"]
                    if a and a["type"] == "layer" and a.get("target") == self.layer)
        detail = f"Auf dieser Ebene sind {used} Tasten belegt." if used else "Die Ebene ist leer."
        if jumps:
            detail += f" {jumps} Taste(n) auf anderen Ebenen springen hierher und werden geleert."
        dialog = Gtk.AlertDialog(message=f"„{layer['name']}“ löschen?", detail=detail,
                                 buttons=["Abbrechen", "Löschen"], cancel_button=0, default_button=0)

        def done(dlg, result):
            try:
                if dlg.choose_finish(result) == 1:
                    self.delete_layer(self.layer)
            except GLib.Error:
                pass
        dialog.choose(self, None, done)

    def delete_layer(self, index):
        layers = self.cfg["layers"]
        del layers[index]
        for lyr in layers:
            for k, a in enumerate(lyr["keys"]):
                if a and a["type"] == "layer" and isinstance(a.get("target"), int):
                    if a["target"] == index:
                        lyr["keys"][k] = None
                    elif a["target"] > index:
                        a["target"] -= 1
        self.layer = max(0, index - 1)
        self.save()
        self.rebuild_layer_buttons()

    def on_name_changed(self, entry):
        if self.updating:
            return
        self.cfg["layers"][self.layer]["name"] = entry.get_text().strip() or f"Ebene {self.layer + 1}"
        self.layer_buttons[self.layer].set_tooltip_text(self.cfg["layers"][self.layer]["name"])
        if self.save_source:
            GLib.source_remove(self.save_source)
        self.save_source = GLib.timeout_add(400, self._delayed_save)

    def _delayed_save(self):
        self.save_source = 0
        self.save()
        return False

    # ---- Drag & Drop / Bearbeiten -----------------------------------------
    def on_drop(self, index, value):
        if value.startswith("palette:"):
            atype = value.split(":", 1)[1]
            if atype in vc.ACTION_INFO:
                existing = self.current_keys()[index]
                keep = existing if existing and existing["type"] == atype else None
                GLib.idle_add(self.open_editor, index, atype, keep)
                return True
        elif value.startswith("key:"):
            src = int(value.split(":", 1)[1])
            if src != index:
                keys = self.current_keys()
                keys[src], keys[index] = keys[index], keys[src]
                self.save()
                self.tiles[src].refresh(keys[src])
                self.tiles[index].refresh(keys[index])
            return True
        return False

    def open_editor(self, index, atype, action):
        Editor(self, atype, action, lambda new: self.set_key(index, new)).present()
        return False

    def choose_type(self, index):
        """Klick auf leere Taste: Aktionstyp auswaehlen (Alternative zu Drag & Drop)."""
        win = Gtk.Window(transient_for=self, modal=True, title=f"Taste {index + 1} belegen",
                         default_width=360, resizable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=14,
                      margin_bottom=14, margin_start=14, margin_end=14)
        for t, title, sub, icon in vc.ACTION_TYPES:
            btn = Gtk.Button(css_classes=["flat"])
            row = Gtk.Box(spacing=12)
            row.append(Gtk.Image(icon_name=icon, pixel_size=24))
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.append(Gtk.Label(label=title, xalign=0, css_classes=["palette-title"]))
            texts.append(Gtk.Label(label=sub, xalign=0, css_classes=["dim", "small"]))
            row.append(texts)
            btn.set_child(row)
            btn.connect("clicked", lambda _b, t=t: (win.close(), self.open_editor(index, t, None)))
            box.append(btn)
        win.set_child(box)
        win.present()

    # ---- Pad live anzeigen & Status ---------------------------------------
    def open_pad(self):
        if self.hid:
            return "ok"
        devices = vc.find_hidraw()
        if not devices:
            return "missing"
        denied = False
        for dev in devices:
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError:
                denied = True
                continue
            except OSError:
                continue
            cond = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR
            self.hid[fd] = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, cond, self.on_hid)
        if self.hid:
            return "ok"
        return "denied" if denied else "missing"

    def close_pad(self):
        for fd, src in self.hid.items():
            GLib.source_remove(src)
            try:
                os.close(fd)
            except OSError:
                pass
        self.hid = {}
        for t in self.tiles:
            t.set_pressed(False)

    def on_hid(self, fd, cond, *_):
        if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
            GLib.idle_add(self.close_pad)
            return False
        try:
            data = os.read(fd, 64)
        except BlockingIOError:
            return True
        except OSError:
            GLib.idle_add(self.close_pad)
            return False
        parsed = vc.parse_report(data)
        if parsed:
            self.tiles[parsed[0]].set_pressed(parsed[1])
        return True

    def update_status(self):
        state = self.open_pad()
        try:
            active = subprocess.run(["systemctl", "--user", "is-active", "vaydeerd.service"],
                                    capture_output=True, text=True, timeout=2).stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            active = False
        if state == "ok":
            text, ok = "● Pad verbunden", True
        elif state == "denied":
            text, ok = "● Keine Berechtigung – bitte ab- und wieder anmelden", False
        else:
            text, ok = "● Pad nicht angeschlossen", False
        if not active:
            text += "  ·  Dienst läuft nicht"
            ok = False
        self.status.set_text(text)
        self.status.set_css_classes(["status-ok" if ok else "status-warn"])
        self.service_btn.set_visible(not active)
        return True

    def start_service(self, *_):
        subprocess.run(["systemctl", "--user", "restart", "vaydeerd.service"])
        GLib.timeout_add(800, lambda: self.update_status() and False)

    # ---- Overlay -----------------------------------------------------------
    def build_overlay_button(self):
        btn = Gtk.MenuButton(icon_name="view-reveal-symbolic", tooltip_text="Overlay")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12,
                      margin_bottom=12, margin_start=12, margin_end=12)
        pop.set_child(box)
        btn.set_popover(pop)

        row = Gtk.Box(spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        texts.append(Gtk.Label(label="Overlay anzeigen", xalign=0, css_classes=["palette-title"]))
        texts.append(Gtk.Label(label="Startet automatisch mit der Anmeldung", xalign=0,
                               css_classes=["dim", "small"]))
        row.append(texts)
        self.ov_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        row.append(self.ov_switch)
        box.append(row)
        box.append(Gtk.Separator())

        def radio_pair(title, labels, active_first, on_first, on_second):
            box.append(Gtk.Label(label=title, xalign=0, css_classes=["dim", "small"]))
            a = Gtk.CheckButton(label=labels[0], active=active_first)
            b = Gtk.CheckButton(label=labels[1], active=not active_first, group=a)
            a.connect("toggled", lambda w: w.get_active() and on_first())
            b.connect("toggled", lambda w: w.get_active() and on_second())
            box.append(a)
            box.append(b)

        s = vc.load_overlay()
        radio_pair("Anzeige", ("Immer sichtbar", "Nur bei Tastendruck einblenden"),
                   s["mode"] == "always",
                   lambda: vc.update_overlay(mode="always"), lambda: vc.update_overlay(mode="auto"))
        radio_pair("Größe", ("Normal (mit allen 9 Tasten)", "Kompakt (nur Ebene & letzte Taste)"),
                   not s["compact"],
                   lambda: vc.update_overlay(compact=False), lambda: vc.update_overlay(compact=True))

        box.append(Gtk.Label(label="Deckkraft", xalign=0, css_classes=["dim", "small"]))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 5)
        scale.set_value(round(s["opacity"] * 100))
        scale.set_size_request(240, -1)
        scale.connect("value-changed", lambda sc: vc.update_overlay(opacity=sc.get_value() / 100))
        box.append(scale)

        reset = Gtk.Button(label="Position zurücksetzen")
        reset.connect("clicked", lambda *_: vc.update_overlay(x=None, y=None))
        box.append(reset)
        box.append(Gtk.Label(label="Overlay mit der Maus verschieben,\nRechtsklick darauf für das Menü.",
                             xalign=0, css_classes=["dim", "small"]))

        self.ov_switch.set_active(os.path.exists(vc.AUTOSTART_PATH) or vc.overlay_pid() is not None)
        self.ov_switch.connect("notify::active", self.on_overlay_switch)
        pop.connect("show", lambda *_: self.sync_overlay_switch())
        return btn

    def sync_overlay_switch(self):
        running = vc.overlay_pid() is not None
        if running != self.ov_switch.get_active():
            self.ov_switch.handler_block_by_func(self.on_overlay_switch)
            self.ov_switch.set_active(running or os.path.exists(vc.AUTOSTART_PATH))
            self.ov_switch.handler_unblock_by_func(self.on_overlay_switch)

    def overlay_command(self):
        if os.path.exists(OVERLAY_LAUNCHER):
            return [OVERLAY_LAUNCHER]
        return [sys.executable, OVERLAY_SCRIPT]

    def on_overlay_switch(self, switch, _pspec):
        if switch.get_active():
            os.makedirs(os.path.dirname(vc.AUTOSTART_PATH), exist_ok=True)
            with open(vc.AUTOSTART_PATH, "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=Vaydeer Overlay\n"
                        "Comment=Zeigt Ebene und Tastendrücke des Vaydeer-Pads\n"
                        f"Exec={' '.join(self.overlay_command())}\nIcon=input-keyboard\n"
                        "NoDisplay=true\nX-GNOME-Autostart-enabled=true\n")
            if vc.overlay_pid() is None:
                subprocess.Popen(self.overlay_command(), start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.remove(vc.AUTOSTART_PATH)
            except OSError:
                pass
            pid = vc.overlay_pid()
            if pid:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass

    def update_live_layer(self):
        live = vc.read_state()
        if live != self.live_layer:
            self.live_layer = live
            for i, b in enumerate(self.layer_buttons):
                name = self.cfg["layers"][i]["name"]
                if i == live:
                    b.add_css_class("live-layer")
                    b.set_tooltip_text(f"{name} · gerade auf dem Pad aktiv")
                else:
                    b.remove_css_class("live-layer")
                    b.set_tooltip_text(name)
        return True

    def on_close(self, *_):
        if self.save_source:
            GLib.source_remove(self.save_source)
            self.save()
        self.close_pad()
        return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(CSS.decode())
        else:
            provider.load_from_data(CSS.decode(), -1)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.get_active_window() or MainWindow(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
