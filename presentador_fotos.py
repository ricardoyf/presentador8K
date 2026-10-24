#!/usr/bin/python3
"""PresentadorFotos NAS: pase aleatorio global de una o cuatro fotos."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import random
import re
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


APP_VERSION = "1.1"
APP_ID = "local.ricardo.PresentadorFotosNAS"
DEFAULT_URI = "smb://dsplay214.local/photo/"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "presentador-fotos/config.json"
MONTHS = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
MAX_RENDER_WIDTH = 1920
MAX_RENDER_HEIGHT = 1080
MAX_HISTORY = 40
NAME_FILTER = re.compile(r"(?:copia|enc)", re.IGNORECASE)
DATE_IN_NAME = re.compile(r"(?<!\d)(?P<year>(?:19|20)\d{2})[-_.]?(?P<month>0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?!\d)")
YEAR_PART = re.compile(r"^(?:19|20)\d{2}$")
MONTH_PART = re.compile(r"^(0?[1-9]|1[0-2])(?:\D|$)")


def photo_year_month(path: Path, root: Path) -> tuple[int, int] | None:
    """Obtiene ano/mes del nombre y, como respaldo, de la jerarquia de carpetas."""
    match = DATE_IN_NAME.search(path.stem)
    if match:
        return int(match["year"]), int(match["month"])

    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    for index, part in enumerate(parts):
        if not YEAR_PART.fullmatch(part):
            continue
        year = int(part)
        if index + 1 < len(parts):
            month = MONTH_PART.match(parts[index + 1])
            if month:
                return year, int(month[1])
        # Fotos directamente bajo /ANO: intentar obtener el mes del nombre.
        loose = re.search(r"(?<!\d)(0[1-9]|1[0-2])[-_.](?:0[1-9]|[12]\d|3[01])(?!\d)", path.stem)
        if loose:
            return year, int(loose[1])
    return None


def selected_photos(root: Path, year: int, months: set[int]) -> list[Path]:
    """Escanea una vez y devuelve el conjunto global de fotos validas."""
    year_root = root / str(year)
    scan_root = year_root if year_root.is_dir() else root
    found: list[Path] = []

    def scan_error(error: OSError) -> None:
        raise error

    for base, _, files in os.walk(scan_root, onerror=scan_error):
        for name in files:
            path = Path(base) / name
            if path.suffix.lower() not in PHOTO_EXTS or not NAME_FILTER.search(path.stem):
                continue
            stamp = photo_year_month(path, root)
            if stamp and stamp[0] == year and stamp[1] in months:
                found.append(path)
    return sorted(set(found), key=lambda item: str(item).casefold())


class RandomDeck:
    """Baraja global: cada elemento aparece una vez antes de repetir."""

    def __init__(self, photos: list[Path], rng: random.Random | None = None):
        if not photos:
            raise ValueError("La baraja necesita al menos una foto.")
        self.photos = list(photos)
        self.rng = rng or random.Random()
        self.remaining: list[Path] = []
        self.last: Path | None = None

    def draw(self, amount: int) -> list[Path]:
        result: list[Path] = []
        while len(result) < min(amount, len(self.photos)):
            if not self.remaining:
                self.remaining = self.photos.copy()
                self.rng.shuffle(self.remaining)
                if self.last and len(self.remaining) > 1 and self.remaining[-1] == self.last:
                    self.remaining[0], self.remaining[-1] = self.remaining[-1], self.remaining[0]
            candidate = self.remaining.pop()
            if candidate not in result:
                result.append(candidate)
        self.last = result[-1]
        return result


def render_size(width: int, height: int) -> tuple[int, int]:
    """Limita el trabajo de decodificacion a lo que realmente puede verse."""
    return (
        max(1, min(width, MAX_RENDER_WIDTH)),
        max(1, min(height, MAX_RENDER_HEIGHT)),
    )


def load_pixbuf(path: Path, width: int, height: int) -> GdkPixbuf.Pixbuf:
    """Decodifica ya reducida; nunca crea primero el bitmap original gigante."""
    width, height = render_size(width, height)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(path), width, height, True,
    )
    return pixbuf.apply_embedded_orientation()


class Slideshow(Gtk.Window):
    def __init__(self, photos: list[Path], duration: float, count: int):
        super().__init__(title=f"PresentadorFotos NAS v{APP_VERSION}")
        self.set_icon_name("image-x-generic")
        self.set_decorated(False)
        self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("black"))
        self.connect("key-press-event", self.on_key)
        self.connect("button-press-event", lambda *_: self.next_group())
        self.connect("destroy", self.on_destroy)
        self.duration_ms = max(250, round(duration * 1000))
        self.count = count
        self.deck = RandomDeck(photos)
        self.history: list[list[Path]] = []
        self.position = -1
        self.paused = False
        self.timer_id = 0
        self.resize_id = 0
        self.last_render_size = (0, 0)
        self.grid = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(4)
        self.add(self.grid)
        self.connect("size-allocate", self.on_resize)
        self.fullscreen()
        self.show_all()
        GLib.idle_add(self.next_group)

    def on_resize(self, *_):
        if self.position < 0:
            return
        allocation = self.get_allocation()
        size = render_size(allocation.width, allocation.height)
        if size == self.last_render_size:
            return
        if self.resize_id:
            GLib.source_remove(self.resize_id)
        self.resize_id = GLib.timeout_add(300, self.render_after_resize)

    def render_after_resize(self):
        self.resize_id = 0
        if self.position >= 0:
            self.render(self.history[self.position])
        return GLib.SOURCE_REMOVE

    def on_destroy(self, *_):
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = 0
        if self.resize_id:
            GLib.source_remove(self.resize_id)
            self.resize_id = 0

    def render(self, paths: list[Path]):
        for child in self.grid.get_children():
            self.grid.remove(child)
        allocation = self.get_allocation()
        columns = 2 if self.count == 4 else 1
        rows = 2 if self.count == 4 else 1
        cell_width = max(100, allocation.width // columns - 8)
        cell_height = max(100, allocation.height // rows - 8)
        self.last_render_size = render_size(allocation.width, allocation.height)
        for index, path in enumerate(paths):
            frame = Gtk.EventBox()
            frame.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("black"))
            try:
                image = Gtk.Image.new_from_pixbuf(load_pixbuf(path, cell_width, cell_height))
            except GLib.Error:
                image = Gtk.Label(label=f"No se pudo abrir:\n{path.name}")
                image.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
            frame.add(image)
            frame.set_tooltip_text(str(path))
            self.grid.attach(frame, index % columns, index // columns, 1, 1)
        self.grid.show_all()

    def schedule(self):
        if self.timer_id:
            GLib.source_remove(self.timer_id)
        self.timer_id = GLib.timeout_add(self.duration_ms, self.next_group)

    def next_group(self):
        if self.position + 1 < len(self.history):
            self.position += 1
        else:
            self.history.append(self.deck.draw(self.count))
            self.position += 1
            if len(self.history) > MAX_HISTORY:
                excess = len(self.history) - MAX_HISTORY
                del self.history[:excess]
                self.position -= excess
        self.render(self.history[self.position])
        if not self.paused:
            self.schedule()
        return GLib.SOURCE_REMOVE

    def previous_group(self):
        if self.position > 0:
            self.position -= 1
            self.render(self.history[self.position])
            if not self.paused:
                self.schedule()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused and self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = 0
        elif not self.paused:
            self.schedule()

    def on_key(self, _, event):
        key = Gdk.keyval_name(event.keyval)
        if key in {"Escape", "q", "Q"}:
            self.close()
        elif key in {"Right", "Page_Down", "Return"}:
            self.next_group()
        elif key in {"Left", "Page_Up"}:
            self.previous_group()
        elif key == "space":
            self.toggle_pause()
        elif key in {"f", "F", "F11"}:
            if self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                self.unfullscreen()
            else:
                self.fullscreen()
        return True


class PresentadorApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        today = dt.date.today()
        self.window = Gtk.ApplicationWindow(application=self, title="Presentador Fotos NAS")
        self.window.set_default_size(680, 565)
        self.window.set_icon_name("image-x-generic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13, margin=22)
        self.window.add(box)
        title = Gtk.Label(xalign=0)
        title.set_markup("<big><b>Presentador de fotos del NAS</b></big>")
        box.pack_start(title, False, False, 0)
        box.pack_start(Gtk.Label(label="Fotos cuyo nombre contenga ‘copia’ o ‘ENC’.", xalign=0), False, False, 0)

        source_row = Gtk.Box(spacing=8)
        self.source = Gtk.Entry(text=saved.get("source", DEFAULT_URI))
        self.source.set_tooltip_text("Carpeta que contiene las carpetas anuales")
        source_row.pack_start(self.source, True, True, 0)
        choose = Gtk.Button(label="Elegir carpeta…")
        choose.connect("clicked", self.choose_folder)
        source_row.pack_start(choose, False, False, 0)
        box.pack_start(source_row, False, False, 0)

        year_row = Gtk.Box(spacing=10)
        year_row.pack_start(Gtk.Label(label="Año:"), False, False, 0)
        self.year = Gtk.SpinButton.new_with_range(1900, 2100, 1)
        self.year.set_value(saved.get("year", today.year))
        year_row.pack_start(self.year, False, False, 0)
        all_months = Gtk.Button(label="Todos los meses")
        all_months.connect("clicked", lambda _: [item.set_active(True) for item in self.months])
        year_row.pack_end(all_months, False, False, 0)
        box.pack_start(year_row, False, False, 0)

        month_grid = Gtk.Grid(column_spacing=24, row_spacing=10)
        self.months: list[Gtk.CheckButton] = []
        for index, name in enumerate(MONTHS):
            checkbox = Gtk.CheckButton(label=name)
            checkbox.set_active(index + 1 in saved.get("months", [today.month]))
            self.months.append(checkbox)
            month_grid.attach(checkbox, index % 3, index // 3, 1, 1)
        box.pack_start(month_grid, False, False, 0)

        options = Gtk.Box(spacing=24)
        options.pack_start(Gtk.Label(label="Segundos por pase:"), False, False, 0)
        self.duration = Gtk.SpinButton.new_with_range(2, 120, 0.5)
        self.duration.set_digits(1)
        self.duration.set_value(max(2, float(saved.get("duration", 5))))
        options.pack_start(self.duration, False, False, 0)
        self.four = Gtk.CheckButton(label="Mostrar 4 fotos a la vez")
        self.four.set_active(bool(saved.get("four", False)))
        options.pack_start(self.four, False, False, 0)
        box.pack_start(options, False, False, 0)

        box.pack_start(Gtk.Label(label="Modo ligero: imágenes adaptadas a pantalla y recursos limitados.", xalign=0), False, False, 0)
        self.status = Gtk.Label(label="Selecciona año y meses y pulsa Iniciar presentación.", xalign=0)
        self.status.set_line_wrap(True)
        box.pack_start(self.status, True, True, 0)
        self.play = Gtk.Button(label="▶ Iniciar presentación")
        self.play.get_style_context().add_class("suggested-action")
        self.play.connect("clicked", self.prepare)
        box.pack_start(self.play, False, False, 0)
        box.pack_start(Gtk.Label(label="Durante el pase: Espacio pausa · ←/→ navegan · Esc sale", xalign=0), False, False, 0)
        version = Gtk.Label(label=f"Versión {APP_VERSION}", xalign=1)
        version.get_style_context().add_class("dim-label")
        box.pack_start(version, False, False, 0)
        self.window.show_all()

    def choose_folder(self, _button):
        dialog = Gtk.FileChooserDialog(
            title="Carpeta de fotos (contiene los años)", parent=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Elegir", Gtk.ResponseType.OK)
        dialog.set_local_only(False)
        dialog.set_current_folder_uri(self.source.get_text())
        if dialog.run() == Gtk.ResponseType.OK:
            self.source.set_text(dialog.get_uri())
        dialog.destroy()

    def prepare(self, _button):
        months = {index + 1 for index, item in enumerate(self.months) if item.get_active()}
        if not months:
            self.status.set_text("Selecciona al menos un mes.")
            return
        self.selection = {
            "source": self.source.get_text().strip(),
            "year": self.year.get_value_as_int(),
            "months": sorted(months),
            "duration": self.duration.get_value(),
            "four": self.four.get_active(),
        }
        self.play.set_sensitive(False)
        self.status.set_text("Conectando con el NAS…")
        source = Gio.File.new_for_commandline_arg(self.selection["source"])
        if source.get_uri_scheme() == "file":
            self.start_scan(source)
        else:
            operation = Gtk.MountOperation.new(self.window)
            source.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, None, self.mounted)

    def mounted(self, source, result):
        try:
            source.mount_enclosing_volume_finish(result)
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                self.error(f"No se pudo conectar al NAS: {error.message}")
                return
        self.start_scan(source)

    def start_scan(self, source):
        path = source.get_path()
        if not path:
            self.error("La carpeta no está disponible. Ábrela en Archivos y vuelve a intentarlo.")
            return
        selection = self.selection.copy()
        self.status.set_text("Buscando todas las fotos válidas de los meses seleccionados…")

        def worker():
            try:
                photos = selected_photos(Path(path), selection["year"], set(selection["months"]))
                GLib.idle_add(self.start_slideshow, photos, selection)
            except Exception as error:  # El error se muestra en la interfaz.
                GLib.idle_add(self.error, str(error))

        threading.Thread(target=worker, daemon=True).start()

    def error(self, message):
        self.status.set_text(message)
        self.play.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def start_slideshow(self, photos, selection):
        if not photos:
            return self.error("No se encontraron fotos con ‘copia’ o ‘ENC’ para ese año y esos meses.")
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.status.set_text(f"Encontradas {len(photos)} fotos. Presentación iniciada.")
        self.play.set_sensitive(True)
        Slideshow(photos, selection["duration"], 4 if selection["four"] else 1)
        return GLib.SOURCE_REMOVE


def cli_scan(args) -> int:
    photos = selected_photos(args.scan_only, args.year, set(args.months))
    print(f"PresentadorFotos NAS v{APP_VERSION}: {len(photos)} fotos")
    for path in photos:
        print(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"PresentadorFotos NAS v{APP_VERSION}")
    parser.add_argument("--scan-only", type=Path, help="Escanea una ruta local sin abrir la interfaz")
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument("--months", type=int, nargs="+", default=list(range(1, 13)))
    args = parser.parse_args()
    if args.scan_only:
        return cli_scan(args)
    return PresentadorApp().run(sys.argv[:1])


if __name__ == "__main__":
    raise SystemExit(main())
