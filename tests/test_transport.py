import io
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.transport import prepare_upload


class UploadTests(unittest.TestCase):
    def test_small_images_are_unchanged(self):
        self.assertEqual(prepare_upload(b"small cached image"), b"small cached image")

    def test_compression_preserves_dimensions_and_fits_budget(self):
        image = Image.frombytes(
            "RGB", (512, 512), random.Random(9).randbytes(512 * 512 * 3)
        )
        output = io.BytesIO()
        image.save(output, "JPEG", quality=100)
        data = prepare_upload(output.getvalue(), 140000)
        self.assertLessEqual(len(data), 140000)
        with Image.open(io.BytesIO(data)) as decoded:
            self.assertEqual(decoded.size, (512, 512))
            decoded.verify()

    def test_retry_resizes_whole_image_without_cropping(self):
        image = Image.new("RGB", (64, 256), "white")
        output = io.BytesIO()
        image.save(output, "PNG")
        data = prepare_upload(output.getvalue(), 10000, 128)
        with Image.open(io.BytesIO(data)) as decoded:
            self.assertEqual(decoded.size, (32, 128))

    def test_small_file_is_still_bounded_by_pixel_count(self):
        output = io.BytesIO()
        Image.new("RGB", (200, 1000), "white").save(output, "PNG")
        data = prepare_upload(output.getvalue(), 100000, 16000, 50000)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (100, 500))

    def test_safe_bounded_image_avoids_decoding_and_copying(self):
        output = io.BytesIO()
        Image.new("RGB", (100, 200), "white").save(output, "JPEG")
        with patch.object(
            Image.Image,
            "convert",
            side_effect=AssertionError("unnecessary full decode"),
        ):
            self.assertEqual(
                prepare_upload(output.getvalue(), 100000, 16000, 18_000_000),
                output.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
