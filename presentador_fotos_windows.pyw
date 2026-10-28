# -*- coding: utf-8 -*-
"""Presentador Fotos NAS v2.4 para Windows."""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import queue
import random
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


APP_VERSION = "2.4"
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
NAME_FILTER = re.compile(r"(?:copia|enc)", re.IGNORECASE)
DATE_IN_NAME = re.compile(r"(?<!\d)(?P<year>(?:19|20)\d{2})[-_.]?(?P<month>0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?!\d)")
YEAR_PART = re.compile(r"^(?:19|20)\d{2}$")
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "PresentadorFotosNAS" / "config.json"


def photo_year(path: Path, root: Path) -> int | None:
    match = DATE_IN_NAME.search(path.stem)
    if match:
        return int(match["year"])
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    for part in parts:
        if YEAR_PART.fullmatch(part):
            return int(part)
    return None


def scan_year(root: Path, year: int) -> list[Path]:
    scan_root = root / str(year)
    if not scan_root.is_dir():
        scan_root = root
    photos = []
    for base, _, files in os.walk(scan_root):
        for name in files:
            path = Path(base) / name
            if path.suffix.lower() not in PHOTO_EXTS or not NAME_FILTER.search(path.stem):
                continue
            if photo_year(path, root) == year:
                photos.append(path)
    random.shuffle(photos)
    return photos


class RandomDeck:
    def __init__(self, photos: list[Path]):
        self.photos: list[Path] = []
        self.known: set[Path] = set()
        self.remaining: list[Path] = []
        self.last_group: set[Path] = set()
        self.add(photos)

    def add(self, photos: list[Path]) -> None:
        new = [photo for photo in photos if photo not in self.known]
        self.known.update(new)
        self.photos.extend(new)
        random.shuffle(new)
        self.remaining.extend(new)

    def draw(self, amount: int) -> list[Path]:
        if len(self.photos) < amount:
            raise ValueError("Se necesitan al menos cuatro fotos distintas.")
        chosen = []
        attempts = 0
        while len(chosen) < amount:
            if not self.remaining:
                self.remaining = self.photos.copy()
                random.shuffle(self.remaining)
            photo = self.remaining.pop()
            if photo in chosen or (photo in self.last_group and attempts < len(self.photos) * 2):
                self.remaining.insert(0, photo)
                attempts += 1
                continue
            chosen.append(photo)
        self.last_group = set(chosen)
        return chosen


class Slideshow(tk.Toplevel):
    def __init__(self, owner, photos: list[Path], seconds: float, minutes: int):
        super().__init__(owner)
        self.owner = owner
        self.deck = RandomDeck(photos)
        self.seconds = seconds
        self.ends_at = time.monotonic() + minutes * 60
        self.job = None
        self.images = []
        self.configure(bg="black", cursor="none")
        self.attributes("-fullscreen", True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", self.close)
        self.bind("q", self.close)
        self.bind("<Right>", lambda _event: self.show_next())
        self.bind("<Button-1>", lambda _event: self.show_next())

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.timer = tk.Label(self, bg="black", fg="white", font=("Segoe UI", 13))
        self.timer.place(relx=1.0, x=-14, y=10, anchor="ne")
        self.after(100, self.show_next)
        self.update_timer()

    def add_photos(self, photos: list[Path]) -> None:
        self.deck.add(photos)

    def show_next(self) -> None:
        if self.job:
            self.after_cancel(self.job)
        try:
            paths = self.deck.draw(4)
        except ValueError:
            self.job = self.after(500, self.show_next)
            return
        width = max(800, self.winfo_width())
        height = max(600, self.winfo_height())
        cell_w, cell_h = width // 2, height // 2
        loaded = []
        for path in paths:
            try:
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    image.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", (cell_w, cell_h), "black")
                    canvas.paste(image, ((cell_w - image.width) // 2, (cell_h - image.height) // 2))
                loaded.append(ImageTk.PhotoImage(canvas))
            except Exception:
                loaded.append(None)
        self.images = loaded
        self.canvas.delete("photo")
        for index, image in enumerate(loaded):
            if image:
                self.canvas.create_image((index % 2) * cell_w, (index // 2) * cell_h,
                                         image=image, anchor="nw", tags="photo")
        self.job = self.after(max(2000, int(self.seconds * 1000)), self.show_next)

    def update_timer(self) -> None:
        remaining = max(0, int(self.ends_at - time.monotonic()))
        self.timer.config(text=f"{remaining // 60:02d}:{remaining % 60:02d}")
        if remaining <= 0:
            self.close()
        else:
            self.after(1000, self.update_timer)

    def close(self, _event=None) -> None:
        if self.job:
            self.after_cancel(self.job)
        self.destroy()
        self.owner.slideshow = None
        self.owner.deiconify()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Presentador Fotos NAS v{APP_VERSION} — Windows")
        self.resizable(False, False)
        self.scan_queue = queue.Queue()
        self.slideshow = None
        saved = self.load_config()

        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Presentador Fotos NAS", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=f"Windows v{APP_VERSION}").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))
        ttk.Label(frame, text="Carpeta de fotos o ruta de red:").grid(row=2, column=0, columnspan=3, sticky="w")
        self.source = tk.StringVar(value=saved.get("source", ""))
        ttk.Entry(frame, textvariable=self.source, width=62).grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Button(frame, text="Examinar…", command=self.choose).grid(row=3, column=2, padx=(8, 0))

        ttk.Label(frame, text="Desde el año:").grid(row=4, column=0, sticky="w", pady=(14, 0))
        ttk.Label(frame, text="Hasta el año (incluido):").grid(row=4, column=1, sticky="w", pady=(14, 0))
        self.year_from = tk.IntVar(value=saved.get("year_from", 2018))
        self.year_to = tk.IntVar(value=saved.get("year_to", 2020))
        ttk.Spinbox(frame, from_=1900, to=2100, textvariable=self.year_from, width=12).grid(row=5, column=0, sticky="w")
        ttk.Spinbox(frame, from_=1900, to=2100, textvariable=self.year_to, width=12).grid(row=5, column=1, sticky="w")

        ttk.Label(frame, text="Cambio (segundos):").grid(row=6, column=0, sticky="w", pady=(14, 0))
        ttk.Label(frame, text="Parada automática (minutos):").grid(row=6, column=1, sticky="w", pady=(14, 0))
        self.seconds = tk.DoubleVar(value=saved.get("seconds", 4))
        self.minutes = tk.IntVar(value=saved.get("minutes", 60))
        ttk.Spinbox(frame, from_=2, to=120, textvariable=self.seconds, width=12).grid(row=7, column=0, sticky="w")
        ttk.Spinbox(frame, from_=1, to=720, textvariable=self.minutes, width=12).grid(row=7, column=1, sticky="w")

        self.start_button = ttk.Button(frame, text="Iniciar presentación 2×2", command=self.start)
        self.start_button.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(18, 8))
        self.status = ttk.Label(frame, text="Preparado.")
        self.status.grid(row=9, column=0, columnspan=3, sticky="w")

    @staticmethod
    def load_config() -> dict:
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def choose(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona la carpeta raíz de las fotos")
        if selected:
            self.source.set(selected)

    def start(self) -> None:
        root = Path(self.source.get().strip())
        start, end = self.year_from.get(), self.year_to.get()
        if not root.is_dir():
            messagebox.showerror("Presentador", "La carpeta o ruta de red no está disponible.")
            return
        if start > end:
            messagebox.showerror("Presentador", "El año inicial no puede ser posterior al final.")
            return
        config = {"source": str(root), "year_from": start, "year_to": end,
                  "seconds": max(2, self.seconds.get()), "minutes": max(1, self.minutes.get())}
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self.start_button.config(state="disabled")
        self.status.config(text="Indexando los años en paralelo…")
        threading.Thread(target=self.scan, args=(root, start, end, config), daemon=True).start()
        self.after(100, self.poll_scan)

    def scan(self, root: Path, start: int, end: int, config: dict) -> None:
        try:
            years = list(range(start, end + 1))
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(years))) as pool:
                futures = [pool.submit(scan_year, root, year) for year in years]
                for future in concurrent.futures.as_completed(futures):
                    self.scan_queue.put(("batch", future.result(), config))
            self.scan_queue.put(("done", None, config))
        except Exception as error:
            self.scan_queue.put(("error", str(error), config))

    def poll_scan(self) -> None:
        try:
            while True:
                kind, payload, config = self.scan_queue.get_nowait()
                if kind == "batch" and payload:
                    if self.slideshow is None:
                        self.slideshow = Slideshow(self, payload, config["seconds"], config["minutes"])
                        self.withdraw()
                    else:
                        self.slideshow.add_photos(payload)
                elif kind == "done":
                    self.start_button.config(state="normal")
                    if self.slideshow is None:
                        messagebox.showerror("Presentador", "No se encontraron fotos con ‘copia’ o ‘ENC’ en ese intervalo.")
                elif kind == "error":
                    self.start_button.config(state="normal")
                    messagebox.showerror("Presentador", payload)
        except queue.Empty:
            pass
        if self.start_button.instate(["disabled"]):
            self.after(100, self.poll_scan)


if __name__ == "__main__":
    App().mainloop()
