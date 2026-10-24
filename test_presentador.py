#!/usr/bin/python3
import random
import tempfile
import unittest
from pathlib import Path

from presentador_fotos import (
    MAX_RENDER_HEIGHT,
    MAX_RENDER_WIDTH,
    RandomDeck,
    photo_year_month,
    render_size,
    selected_photos,
)


class PresentadorTests(unittest.TestCase):
    def test_fecha_desde_nombre(self):
        root = Path("/fotos")
        self.assertEqual(photo_year_month(root / "varios/20240318_ENC_copia.jpg", root), (2024, 3))

    def test_fecha_desde_carpetas(self):
        root = Path("/fotos")
        self.assertEqual(photo_year_month(root / "2024/07 Julio/IMG_ENC.jpg", root), (2024, 7))

    def test_filtro_global(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2024/01 Enero/a").mkdir(parents=True)
            (root / "2024/01 Enero/b").mkdir(parents=True)
            (root / "2024/02 Febrero").mkdir(parents=True)
            good = [
                root / "2024/01 Enero/a/uno copia.jpg",
                root / "2024/01 Enero/b/dos ENC.jpeg",
            ]
            for path in good + [root / "2024/02 Febrero/tres copia.jpg", root / "2024/01 Enero/a/no.jpg"]:
                path.touch()
            self.assertEqual(set(selected_photos(root, 2024, {1})), set(good))

    def test_baraja_no_repite_antes_de_agotar(self):
        photos = [Path(str(index)) for index in range(10)]
        deck = RandomDeck(photos, random.Random(7))
        first = deck.draw(4) + deck.draw(4) + deck.draw(2)
        self.assertEqual(len(set(first)), 10)

    def test_render_no_supera_limite_de_recursos(self):
        self.assertEqual(render_size(7680, 4320), (MAX_RENDER_WIDTH, MAX_RENDER_HEIGHT))
        self.assertEqual(render_size(800, 600), (800, 600))


if __name__ == "__main__":
    unittest.main()
