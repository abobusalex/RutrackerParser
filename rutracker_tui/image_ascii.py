from __future__ import annotations

from io import BytesIO

from PIL import Image


PALETTE = " .:-=+*#%@"


def image_bytes_to_ascii(data: bytes, width: int = 56) -> str:
    with Image.open(BytesIO(data)) as image:
        image = image.convert("L")
        aspect = image.height / max(1, image.width)
        height = max(4, int(width * aspect * 0.45))
        image = image.resize((width, height))
        pixels = list(image.getdata())
    chars = [PALETTE[pixel * (len(PALETTE) - 1) // 255] for pixel in pixels]
    lines = ["".join(chars[index : index + width]) for index in range(0, len(chars), width)]
    return "\n".join(lines)
