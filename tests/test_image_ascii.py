from io import BytesIO
import unittest

from PIL import Image

from rutracker_tui.image_ascii import image_bytes_to_ascii


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("L", (width, height))
    for y in range(height):
        for x in range(width):
            image.putpixel((x, y), int(255 * (x + y) / max(1, width + height - 2)))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ImageAsciiTest(unittest.TestCase):
    def test_small_images_are_skipped(self):
        self.assertIsNone(image_bytes_to_ascii(_png_bytes(32, 32)))

    def test_large_images_become_compact_ascii(self):
        ascii_art = image_bytes_to_ascii(_png_bytes(160, 240))
        self.assertIsNotNone(ascii_art)
        lines = ascii_art.splitlines()
        self.assertLessEqual(len(lines), 22)
        self.assertLessEqual(max(len(line) for line in lines), 34)


if __name__ == "__main__":
    unittest.main()
