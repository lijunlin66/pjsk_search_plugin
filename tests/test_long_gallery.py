import io
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.rendering.render import Renderer
from astrbot_plugin_pjsk.services.service import Service


class LongImageTests(unittest.TestCase):
    def test_54_cards_have_all_18_rows(self):
        self.assertEqual(Renderer.gallery_size(54), (1500, 6202))

    def test_streamed_png_preserves_first_and_last_rows(self):
        parts = [Image.new("RGB", (9, 3), "red"), Image.new("RGB", (9, 4), "blue")]
        data = Renderer.encode_png_rows(9, 7, iter(parts))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (9, 7))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(image.getpixel((8, 6)), (0, 0, 255))

    def test_png_supports_height_beyond_jpeg_limit(self):
        data = Renderer.encode_png_rows(
            1, 66000, (Image.new("RGB", (1, 1000), "white") for _ in range(66))
        )
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1, 66000))


class GalleryBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_gallery_download_budget_scales_without_slicing(self):
        service = Service.__new__(Service)
        service.config = {"image_budget": 12}
        service.image_url = lambda card, after=False, thumb=False: (
            f"{card['id']}-{after}"
        )
        service.images = AsyncMock(
            side_effect=lambda urls, **kwargs: [b"cached"] * len(urls)
        )
        cards = [{"id": i, "cardRarityType": "rarity_4"} for i in range(54)]
        pairs = await service.gallery_images(cards)
        self.assertEqual(len(pairs), 54)
        self.assertTrue(all(pair == (b"cached", b"cached") for pair in pairs))
        self.assertEqual(len(service.images.call_args.args[0]), 108)
        self.assertGreater(service.images.call_args.kwargs["budget"], 12)
        self.assertLessEqual(service.images.call_args.kwargs["budget"], 180)


if __name__ == "__main__":
    unittest.main()
