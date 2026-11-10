#!/usr/bin/env python3
"""Vaydeer fuer Linux - schwebendes Overlay.

Zeigt die aktive Ebene und die Tastendruecke, transparent und immer im Vordergrund.
Laeuft ueber X11/XWayland, weil Wayland Programmen "immer im Vordergrund" und
eigene Positionen nicht erlaubt.

Bedienung: mit der linken Maustaste verschieben, Rechtsklick fuer das Menue.
"""
import fcntl
import os
import signal
import sys

os.environ["GDK_BACKEND"] = "x11"  # muss vor dem GTK-Import stehen

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vaydeer_common as vc  # noqa: E402

SHOW_MS = 2500  # Modus "Nur bei Tastendruck": so lange sichtbar
FADE_STEP_MS = 25

CSS = b"""
window, window.background { background-color: transparent; }
.panel {
  background-color: rgba(22, 22, 26, 0.88);
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  padding: 10px 12px 10px 12px;
  color: #f2f2f2;
}
.layer-num { font-size: 9px; font-weight: bold; color: rgba(255, 255, 255, 0.5); }
.layer-name { font-size: 13px; font-weight: bold; }
.layer-flash { color: #62a0ea; }
.cell {
  background-color: rgba(255, 255, 255, 0.07);
  border-radius: 8px;
  padding: 4px 3px;
}
.cell.empty { background-color: rgba(255, 255, 255, 0.025); }
.cell.empty .cell-label { color: rgba(255, 255, 255, 0.35); }
.cell.pressed { background-color: #3584e4; }
.cell.pressed .cell-label, .cell.pressed .cell-num { color: #ffffff; }
.cell-num { font-size: 8px; font-weight: bold; color: rgba(255, 255, 255, 0.4); }
.cell-label { font-size: 9px; }
.last { font-size: 11px; color: rgba(255, 255, 255, 0.85); }
.last-dim { color: rgba(255, 255, 255, 0.4); }
"""


def acquire_lock():
    """Nur ein Overlay gleichzeitig."""
    fd = os.open(vc.OVERLAY_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def action_image(action, size):
    t = action.get("type") if action else None
    img = Gtk.Image()
    if t == "app" and action.get("icon"):
        try:
            img.set_from_gicon(Gio.Icon.new_for_string(action["icon"]), Gtk.IconSize.BUTTON)
            img.set_pixel_size(size)
            return img
        except GLib.Error:
            pass
    if t == "media":
        name = vc.MEDIA_BY_KEY.get(action.get("key"), ("", "media-playback-start-symbolic"))[1]
    elif t:
        name = vc.ACTION_INFO[t][2]
    else:
        name = "list-add-symbolic"
    img.set_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return img


class Cell(Gtk.Box):
    def __init__(self, index):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.get_style_context().add_class("cell")
        self.set_size_request(76, 50)
        self.index = index
        num = Gtk.Label(label=str(index + 1), xalign=0)
        num.get_style_context().add_class("cell-num")
        self.pack_start(num, False, False, 0)
        self.icon_slot = Gtk.Box(halign=Gtk.Align.CENTER)
        self.pack_start(self.icon_slot, True, True, 0)
        self.label = Gtk.Label(ellipsize=3, max_width_chars=10)
        self.label.get_style_context().add_class("cell-label")
        self.pack_start(self.label, False, False, 0)

    def set_action(self, action):
        for c in self.icon_slot.get_children():
            self.icon_slot.remove(c)
        self.icon_slot.pack_start(action_image(action, 16), False, False, 0)
        ctx = self.get_style_context()
        if action:
            ctx.remove_class("empty")
            self.label.set_text(vc.describe(action))
        else:
            ctx.add_class("empty")
            self.label.set_text(f"F{13 + self.index}")
        self.icon_slot.show_all()

    def set_pressed(self, pressed):
        ctx = self.get_style_context()
        (ctx.add_class if pressed else ctx.remove_class)("pressed")


class Overlay(Gtk.Window):
    def __init__(self):
        super().__init__(title="Vaydeer Overlay")
        self.settings = vc.load_overlay()
        self.cfg = vc.load_config()
        self.layer = vc.read_state() or 0
        self.mtimes = {p: vc.file_mtime(p) for p in (vc.CONFIG_PATH, vc.STATE_PATH, vc.OVERLAY_PATH)}
        self.hid = {}
        self.hide_source = 0
        self.fade_source = 0
        self.save_pos_source = 0
        self.visible_now = False

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.stick()

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.get_style_context().add_class("panel")
        self.add(panel)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.num_label = Gtk.Label(xalign=0)
        self.num_label.get_style_context().add_class("layer-num")
        self.name_label = Gtk.Label(xalign=0, ellipsize=3, max_width_chars=24)
        self.name_label.get_style_context().add_class("layer-name")
        head.pack_start(self.num_label, False, False, 0)
        head.pack_start(self.name_label, False, False, 0)
        panel.pack_start(head, False, False, 0)

        self.grid = Gtk.Grid(row_spacing=5, column_spacing=5)
        self.cells = []
        for i in range(vc.NUM_KEYS):
            c = Cell(i)
            self.grid.attach(c, i % 3, i // 3, 1, 1)
            self.cells.append(c)
        panel.pack_start(self.grid, False, False, 0)

        self.last_label = Gtk.Label(label="Bereit", xalign=0, ellipsize=3, max_width_chars=26)
        self.last_label.get_style_context().add_class("last")
        self.last_label.get_style_context().add_class("last-dim")
        panel.pack_start(self.last_label, False, False, 0)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_button)
        self.connect("configure-event", self.on_configure)
        self.connect("destroy", lambda *_: Gtk.main_quit())

        self.render_layer()
        panel.show_all()
        self.apply_compact()
        GLib.timeout_add(250, self.poll)
        GLib.timeout_add_seconds(3, self.open_pad)
        self.open_pad()

        # Beim Start immer kurz zeigen, damit man sieht, dass es laeuft
        self.appear(persistent=self.settings["mode"] == "always")

    # ---- Fenster zeigen / ausblenden ---------------------------------------
    def place(self):
        x, y = self.settings["x"], self.settings["y"]
        if x is None or y is None:
            display = Gdk.Display.get_default()
            mon = display.get_primary_monitor() or display.get_monitor(0)
            geo = mon.get_workarea()
            w, _h = self.get_size()
            x, y = geo.x + geo.width - w - 24, geo.y + 24
        self.move(x, y)

    def appear(self, persistent=False):
        if self.fade_source:
            GLib.source_remove(self.fade_source)
            self.fade_source = 0
        if not self.visible_now:
            self.place()
            self.show()
            self.set_keep_above(True)
            self.visible_now = True
        self.set_opacity(self.settings["opacity"])
        if self.hide_source:
            GLib.source_remove(self.hide_source)
            self.hide_source = 0
        if not persistent and self.settings["mode"] == "auto":
            self.hide_source = GLib.timeout_add(SHOW_MS, self.start_fade)

    def start_fade(self):
        self.hide_source = 0
        self.fade_source = GLib.timeout_add(FADE_STEP_MS, self.fade_step)
        return False

    def fade_step(self):
        op = self.get_opacity() - 0.08
        if op <= 0.05:
            self.fade_source = 0
            self.hide()
            self.visible_now = False
            return False
        self.set_opacity(op)
        return True

    def apply_compact(self):
        self.grid.set_visible(not self.settings["compact"])
        self.resize(1, 1)

    # ---- Inhalt ------------------------------------------------------------
    def render_layer(self):
        layers = self.cfg["layers"]
        self.layer = min(self.layer, len(layers) - 1)
        self.num_label.set_text(f"EBENE {self.layer + 1} / {len(layers)}")
        self.name_label.set_text(layers[self.layer]["name"])
        for cell, action in zip(self.cells, layers[self.layer]["keys"]):
            cell.set_action(action)

    def flash_layer(self):
        ctx = self.name_label.get_style_context()
        ctx.add_class("layer-flash")
        GLib.timeout_add(600, lambda: ctx.remove_class("layer-flash") or False)

    def on_key(self, key, pressed):
        self.cells[key].set_pressed(pressed)
        if not pressed:
            return
        action = self.cfg["layers"][self.layer]["keys"][key]
        text = vc.describe(action) if action else f"F{13 + key}"
        if action:
            text = f"{vc.ACTION_INFO[action['type']][0]}: {text}"
        self.last_label.set_text(f"Taste {key + 1} · {text}")
        self.last_label.get_style_context().remove_class("last-dim")
        self.appear()

    # ---- Dateien beobachten ------------------------------------------------
    def poll(self):
        changed = {p for p, m in self.mtimes.items() if vc.file_mtime(p) != m}
        for p in changed:
            self.mtimes[p] = vc.file_mtime(p)
        if vc.OVERLAY_PATH in changed:
            old = self.settings
            self.settings = vc.load_overlay()
            if self.settings["compact"] != old["compact"]:
                self.apply_compact()
            if self.settings["x"] is None and old["x"] is not None:
                self.place()
            if self.settings["mode"] != old["mode"] or self.settings["opacity"] != old["opacity"]:
                self.appear(persistent=self.settings["mode"] == "always")
        if vc.CONFIG_PATH in changed:
            self.cfg = vc.load_config()
            self.render_layer()
        if vc.STATE_PATH in changed:
            layer = vc.read_state()
            if layer is not None and layer != self.layer:
                self.layer = layer
                self.render_layer()
                self.flash_layer()
                self.appear()
        return True

    # ---- Pad lesen ---------------------------------------------------------
    def open_pad(self):
        if self.hid:
            return True
        for dev in vc.find_hidraw():
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            cond = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR
            self.hid[fd] = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, cond, self.on_hid)
        return True

    def close_pad(self):
        for fd, src in self.hid.items():
            GLib.source_remove(src)
            try:
                os.close(fd)
            except OSError:
                pass
        self.hid = {}
        for c in self.cells:
            c.set_pressed(False)
        return False

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
            self.on_key(*parsed)
        return True

    # ---- Maus --------------------------------------------------------------
    def on_button(self, _w, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        elif event.button == 3:
            self.build_menu().popup_at_pointer(event)
        return True

    def on_configure(self, *_):
        if self.save_pos_source:
            GLib.source_remove(self.save_pos_source)
        self.save_pos_source = GLib.timeout_add(600, self.save_position)
        return False

    def save_position(self):
        self.save_pos_source = 0
        if not self.visible_now:
            return False
        x, y = self.get_position()
        if (x, y) != (self.settings["x"], self.settings["y"]):
            self.settings["x"], self.settings["y"] = x, y
            vc.update_overlay(x=x, y=y)
            self.mtimes[vc.OVERLAY_PATH] = vc.file_mtime(vc.OVERLAY_PATH)
        return False

    def build_menu(self):
        menu = Gtk.Menu()

        def radio(label, group, active, cb):
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            item.set_active(active)
            item.connect("toggled", lambda it: it.get_active() and cb())
            menu.append(item)
            return item

        s = self.settings
        g = radio("Immer sichtbar", None, s["mode"] == "always", lambda: vc.update_overlay(mode="always"))
        radio("Nur bei Tastendruck", g, s["mode"] == "auto", lambda: vc.update_overlay(mode="auto"))
        menu.append(Gtk.SeparatorMenuItem())
        g = radio("Normal", None, not s["compact"], lambda: vc.update_overlay(compact=False))
        radio("Kompakt", g, s["compact"], lambda: vc.update_overlay(compact=True))
        menu.append(Gtk.SeparatorMenuItem())
        g = None
        for pct in (100, 85, 70, 50):
            item = radio(f"Deckkraft {pct} %", g, abs(s["opacity"] - pct / 100) < 0.03,
                         lambda p=pct: vc.update_overlay(opacity=p / 100))
            g = g or item
        menu.append(Gtk.SeparatorMenuItem())
        reset = Gtk.MenuItem(label="Position zurücksetzen")
        reset.connect("activate", lambda *_: vc.update_overlay(x=None, y=None))
        menu.append(reset)
        quit_item = Gtk.MenuItem(label="Overlay schließen")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(quit_item)
        menu.show_all()
        return menu


def main():
    lock = acquire_lock()
    if lock is None:
        print("Overlay läuft bereits.")
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Overlay()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
