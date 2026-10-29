#!/usr/bin/python3
"""PresentadorFotos NAS: pase aleatorio ligero para una foto o mosaicos Full HD."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import queue
import random
import re
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


APP_VERSION = "2.5"
APP_ID = "local.ricardo.PresentadorFotosNAS"
DEFAULT_URI = "smb://dsplay214.local/photo/"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "presentador-fotos/config.json"
INDEX_FILE = CONFIG.with_name("indice-fotos.json")
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
MAX_RENDER_WIDTH = 1920
MAX_RENDER_HEIGHT = 1080
MAX_HISTORY = 40
DISPLAY_MODES = {
    "single": ("1 foto", 1, 1),
    "grid2x2": ("4 fotos — mosaico 2×2 Full HD", 2, 2),
}
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


def iter_selected_photos(root: Path, year_from: int, year_to: int):
    """Indexa cada año en paralelo para reducir la latencia del NAS."""
    def scan_error(error: OSError) -> None:
        raise error

    # Las carpetas del NAS estan organizadas por ano. Recorrer solo las del
    # intervalo evita escanear toda la fototeca y permite empezar pronto.
    scan_roots = [root / str(year) for year in range(year_from, year_to + 1)]
    scan_roots = [path for path in scan_roots if path.is_dir()]
    if not scan_roots:
        scan_roots = [root]
    results: queue.Queue[Path | None] = queue.Queue(maxsize=4000)

    def scan_one(scan_root: Path) -> None:
        for base, _, files in os.walk(scan_root, onerror=scan_error):
            for name in files:
                path = Path(base) / name
                if path.suffix.lower() not in PHOTO_EXTS or not NAME_FILTER.search(path.stem):
                    continue
                stamp = photo_year_month(path, root)
                if stamp and year_from <= stamp[0] <= year_to:
                    results.put(path)
        results.put(None)

    # El cuello de botella es la espera de red, no la CPU. Un trabajador por
    # año permite que el NAS responda a varias carpetas simultáneamente.
    workers = min(8, len(scan_roots))
    seen: set[Path] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(scan_one, scan_root) for scan_root in scan_roots]
        finished = 0
        while finished < len(futures):
            path = results.get()
            if path is None:
                finished += 1
            elif path not in seen:
                seen.add(path)
                yield path
        for future in futures:
            future.result()


def selected_photos(root: Path, year_from: int, year_to: int) -> list[Path]:
    """Compatibilidad con el modo de diagnostico por consola."""
    return list(iter_selected_photos(root, year_from, year_to))


def save_photo_index(source: str, root: Path, photos: list[Path]) -> None:
    rows = []
    for photo in photos:
        stamp = photo_year_month(photo, root)
        if stamp:
            rows.append({"path": str(photo), "year": stamp[0], "month": stamp[1]})
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = INDEX_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"source": source, "created": dt.datetime.now().isoformat(),
                                     "photos": rows}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(INDEX_FILE)


def load_photo_index(source: str) -> list[dict] | None:
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("photos") if data.get("source") == source else None


class RandomDeck:
    """Baraja global: cada elemento aparece una vez antes de repetir."""

    def __init__(self, photos: list[Path], rng: random.Random | None = None):
        if not photos:
            raise ValueError("La baraja necesita al menos una foto.")
        self.photos = list(photos)
        self.known = set(photos)
        self.rng = rng or random.Random()
        self.remaining: list[Path] = []
        self.last: Path | None = None
        self.last_group: set[Path] = set()

    def add(self, photos: list[Path]):
        """Amplia la baraja mientras el escaneo sigue trabajando en segundo plano."""
        for photo in photos:
            if photo not in self.known:
                self.known.add(photo)
                self.photos.append(photo)
                self.remaining.append(photo)

    def draw(self, amount: int) -> list[Path]:
        result: list[Path] = []
        target = min(amount, len(self.photos))
        attempts = 0
        while len(result) < target:
            if not self.remaining:
                self.remaining = self.photos.copy()
                self.rng.shuffle(self.remaining)
            candidate = self.remaining.pop()
            # Prohibido repetir dentro de la pantalla. Si hay suficientes
            # fotos, tampoco se reutiliza ninguna de la pantalla anterior.
            avoid_previous = len(self.photos) >= amount * 2
            if candidate not in result and (not avoid_previous or candidate not in self.last_group):
                result.append(candidate)
                attempts = 0
            else:
                self.remaining.insert(0, candidate)
                attempts += 1
                if attempts > len(self.photos) * 2:
                    avoid_previous = False
        self.last = result[-1]
        self.last_group = set(result)
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


class Slideshow(Gtk.ApplicationWindow):
    def __init__(self, application, photos: list[Path], duration: float, mode: str, session_minutes: int):
        super().__init__(application=application, title=f"PresentadorFotos NAS v{APP_VERSION}")
        self.set_icon_name("image-x-generic")
        self.set_decorated(False)
        self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("black"))
        self.connect("key-press-event", self.on_key)
        self.connect("button-press-event", lambda *_: self.next_group())
        self.connect("destroy", self.on_destroy)
        self.duration_ms = max(250, round(duration * 1000))
        _label, self.columns, self.rows = DISPLAY_MODES.get(mode, DISPLAY_MODES["single"])
        self.count = self.columns * self.rows
        self.deck = RandomDeck(photos)
        self.history: list[list[Path]] = []
        self.position = -1
        self.paused = False
        self.timer_id = 0
        self.countdown_id = 0
        self.ends_at = time.monotonic() + max(1, session_minutes) * 60
        self.resize_id = 0
        self.last_render_size = (0, 0)
        self.grid = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(4)
        overlay = Gtk.Overlay()
        overlay.add(self.grid)
        self.countdown = Gtk.Label()
        self.countdown.set_halign(Gtk.Align.END)
        self.countdown.set_valign(Gtk.Align.START)
        self.countdown.set_margin_top(10)
        self.countdown.set_margin_end(14)
        self.countdown.set_name("countdown")
        overlay.add_overlay(self.countdown)
        self.add(overlay)
        self.connect("size-allocate", self.on_resize)
        self.fullscreen()
        self.show_all()
        self.present()
        GLib.idle_add(self.hide_pointer)
        GLib.idle_add(self.next_group)
        self.update_countdown()
        self.countdown_id = GLib.timeout_add_seconds(1, self.update_countdown)

    def update_countdown(self):
        remaining = max(0, int(self.ends_at - time.monotonic() + 0.999))
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.countdown.set_markup(
            f'<span foreground="white" background="#80000000" size="large">  {hours:02d}:{minutes:02d}:{seconds:02d}  </span>'
        )
        if remaining <= 0:
            self.close()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def hide_pointer(self):
        """Oculta el puntero durante el pase; vuelve al cerrar la ventana."""
        window = self.get_window()
        if window:
            cursor = Gdk.Cursor.new_for_display(window.get_display(), Gdk.CursorType.BLANK_CURSOR)
            window.set_cursor(cursor)
        return GLib.SOURCE_REMOVE

    def add_photos(self, photos: list[Path]):
        self.deck.add(photos)

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
        if self.countdown_id:
            GLib.source_remove(self.countdown_id)
            self.countdown_id = 0

    def render(self, paths: list[Path]):
        for child in self.grid.get_children():
            self.grid.remove(child)
        allocation = self.get_allocation()
        columns = self.columns
        rows = self.rows
        cell_width = max(80, (allocation.width - (columns - 1) * 4) // columns)
        cell_height = max(80, (allocation.height - (rows - 1) * 4) // rows)
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
        self.slideshow: Slideshow | None = None
        self.rebuild_index = False

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
        self.window.set_default_size(680, 400)
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
        legacy_year = int(saved.get("year", today.year))
        year_row.pack_start(Gtk.Label(label="Desde el año:"), False, False, 0)
        self.year_from = Gtk.SpinButton.new_with_range(1900, 2100, 1)
        self.year_from.set_value(saved.get("year_from", legacy_year))
        year_row.pack_start(self.year_from, False, False, 0)
        year_row.pack_start(Gtk.Label(label="Hasta el año (incluido):"), False, False, 0)
        self.year_to = Gtk.SpinButton.new_with_range(1900, 2100, 1)
        self.year_to.set_value(saved.get("year_to", legacy_year))
        year_row.pack_start(self.year_to, False, False, 0)
        box.pack_start(year_row, False, False, 0)

        options = Gtk.Box(spacing=24)
        options.pack_start(Gtk.Label(label="Segundos por pase:"), False, False, 0)
        self.duration = Gtk.SpinButton.new_with_range(2, 120, 0.5)
        self.duration.set_digits(1)
        self.duration.set_value(max(2, float(saved.get("duration", 5))))
        options.pack_start(self.duration, False, False, 0)
        options.pack_start(Gtk.Label(label="Modo:"), False, False, 0)
        self.mode = Gtk.ComboBoxText()
        for mode_id, (label, _columns, _rows) in DISPLAY_MODES.items():
            self.mode.append(mode_id, label)
        saved_mode = saved.get("mode", "grid2x2")
        self.mode.set_active_id(saved_mode if saved_mode in DISPLAY_MODES else "grid2x2")
        options.pack_start(self.mode, False, False, 0)
        box.pack_start(options, False, False, 0)

        timer_row = Gtk.Box(spacing=10)
        timer_row.pack_start(Gtk.Label(label="Parar automáticamente tras:"), False, False, 0)
        self.session_minutes = Gtk.SpinButton.new_with_range(1, 720, 1)
        self.session_minutes.set_value(max(1, int(saved.get("session_minutes", 60))))
        timer_row.pack_start(self.session_minutes, False, False, 0)
        timer_row.pack_start(Gtk.Label(label="minutos (1 hora por defecto)"), False, False, 0)
        box.pack_start(timer_row, False, False, 0)

        box.pack_start(Gtk.Label(label="Modo ligero: imágenes adaptadas a pantalla y recursos limitados.", xalign=0), False, False, 0)
        self.status = Gtk.Label(label="Selecciona el intervalo de años y pulsa Iniciar presentación.", xalign=0)
        self.status.set_line_wrap(True)
        box.pack_start(self.status, True, True, 0)
        buttons = Gtk.Box(spacing=10)
        self.index_button = Gtk.Button(label="⟳ Crear nuevo índice")
        self.index_button.connect("clicked", self.prepare_index)
        buttons.pack_start(self.index_button, False, False, 0)
        self.play = Gtk.Button(label="▶ Iniciar presentación")
        self.play.get_style_context().add_class("suggested-action")
        self.play.connect("clicked", self.prepare)
        buttons.pack_end(self.play, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        box.pack_start(Gtk.Label(label="Durante el pase: Espacio pausa · ←/→ navegan · Esc sale", xalign=0), False, False, 0)
        version = Gtk.Label(label=f"Versión {APP_VERSION}", xalign=1)
        version.get_style_context().add_class("dim-label")
        box.pack_start(version, False, False, 0)
        self.window.show_all()
        if os.environ.get("PRESENTADOR_AUTOSTART") == "1":
            GLib.timeout_add(700, self.prepare, None)

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
        year_from = self.year_from.get_value_as_int()
        year_to = self.year_to.get_value_as_int()
        if year_from > year_to:
            self.status.set_text("El año inicial no puede ser posterior al año final.")
            return
        self.selection = {
            "source": self.source.get_text().strip(),
            "year_from": year_from,
            "year_to": year_to,
            "duration": self.duration.get_value(),
            "mode": self.mode.get_active_id() or "grid2x2",
            "session_minutes": self.session_minutes.get_value_as_int(),
        }
        self.rebuild_index = False
        self.connect_source()

    def prepare_index(self, _button):
        self.selection = {
            "source": self.source.get_text().strip(),
            "year_from": self.year_from.get_value_as_int(),
            "year_to": self.year_to.get_value_as_int(),
            "duration": self.duration.get_value(),
            "mode": self.mode.get_active_id() or "grid2x2",
            "session_minutes": self.session_minutes.get_value_as_int(),
        }
        self.rebuild_index = True
        self.connect_source()

    def connect_source(self):
        self.play.set_sensitive(False)
        self.index_button.set_sensitive(False)
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
        cached = None if self.rebuild_index else load_photo_index(selection["source"])
        if cached is not None:
            photos = [Path(row["path"]) for row in cached
                      if selection["year_from"] <= int(row["year"]) <= selection["year_to"]]
            if not photos:
                self.error("El índice no contiene fotos para esos años. Si añadiste fotos, pulsa Crear nuevo índice.")
                return
            self.status.set_text(f"Índice recuperado: {len(photos)} fotos. Iniciando…")
            self.start_slideshow(photos, selection)
            return
        if self.rebuild_index:
            self.status.set_text("Creando el índice completo de fotos. Puede tardar; solo hazlo cuando añadas archivos.")
            def index_worker():
                try:
                    photos = list(iter_selected_photos(Path(path), 1900, 2100))
                    save_photo_index(selection["source"], Path(path), photos)
                    GLib.idle_add(self.index_finished, len(photos))
                except Exception as error:
                    GLib.idle_add(self.error, str(error))
            threading.Thread(target=index_worker, daemon=True).start()
            return
        self.status.set_text("Indexando todo el intervalo antes de barajar…")

        def worker():
            try:
                photos: list[Path] = []
                total = 0
                started = False
                for photo in iter_selected_photos(Path(path), selection["year_from"], selection["year_to"]):
                    photos.append(photo)
                    total += 1
                    threshold = 12 if not started else 100
                    if len(photos) >= threshold:
                        random.shuffle(photos)
                        GLib.idle_add(self.accept_scan_batch, photos.copy(), selection)
                        photos.clear()
                        started = True
                if photos:
                    random.shuffle(photos)
                    GLib.idle_add(self.accept_scan_batch, photos.copy(), selection)
                    started = True
                GLib.idle_add(self.finish_scan, total)
            except Exception as error:  # El error se muestra en la interfaz.
                GLib.idle_add(self.error, str(error))

        threading.Thread(target=worker, daemon=True).start()

    def index_finished(self, total):
        self.status.set_text(f"Nuevo índice creado: {total} fotos. Las próximas reproducciones serán inmediatas.")
        self.play.set_sensitive(True)
        self.index_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def scan_complete(self, photos, selection):
        if not photos:
            return self.error("No se encontraron fotos con ‘copia’ o ‘ENC’ en ese intervalo de años.")
        self.status.set_text(f"Índice completo: {len(photos)} fotos. Barajando…")
        return self.start_slideshow(photos, selection)

    def error(self, message):
        self.status.set_text(message)
        self.play.set_sensitive(True)
        self.index_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def accept_scan_batch(self, photos, selection):
        if self.slideshow is None:
            self.start_slideshow(photos, selection)
        else:
            self.slideshow.add_photos(photos)
        return GLib.SOURCE_REMOVE

    def finish_scan(self, total):
        if not total:
            return self.error("No se encontraron fotos con ‘copia’ o ‘ENC’ en ese intervalo de años.")
        self.status.set_text(f"Índice terminado: {total} fotos disponibles.")
        self.play.set_sensitive(True)
        self.index_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def start_slideshow(self, photos, selection):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.status.set_text("Reserva aleatoria preparada. El resto se indexa en segundo plano.")
        self.play.set_sensitive(True)
        self.index_button.set_sensitive(True)
        self.window.hide()
        self.slideshow = Slideshow(
            self, photos, selection["duration"], selection["mode"], selection["session_minutes"]
        )
        self.slideshow.connect("destroy", self.slideshow_closed)
        return GLib.SOURCE_REMOVE

    def slideshow_closed(self, *_):
        self.slideshow = None
        self.window.show_all()
        self.window.present()


def cli_scan(args) -> int:
    photos = selected_photos(args.scan_only, args.year_from, args.year_to)
    print(f"PresentadorFotos NAS v{APP_VERSION}: {len(photos)} fotos")
    for path in photos:
        print(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"PresentadorFotos NAS v{APP_VERSION}")
    parser.add_argument("--scan-only", type=Path, help="Escanea una ruta local sin abrir la interfaz")
    parser.add_argument("--year-from", type=int, default=dt.date.today().year)
    parser.add_argument("--year-to", type=int, default=dt.date.today().year)
    args = parser.parse_args()
    if args.scan_only:
        return cli_scan(args)
    return PresentadorApp().run(sys.argv[:1])


if __name__ == "__main__":
    raise SystemExit(main())
