from __future__ import annotations

from io import BytesIO

from PIL import Image
from PIL import ImageChops
from PIL import ImageOps


PALETTE = " .,:;irsXA253hMHGS#9B&@"


def image_bytes_to_ascii(data: bytes, width: int = 34, max_height: int = 22) -> str | None:
    with Image.open(BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if min(image.width, image.height) < 80 or image.width * image.height < 12_000:
            return None
        image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image)
        image = _trim_borders(image)
        target_width = min(width, image.width)
        aspect = image.height / max(1, image.width)
        target_height = max(6, min(max_height, int(target_width * aspect * 0.5)))
        image = image.resize((target_width, target_height))
        pixels = list(image.getdata())
    chars = [PALETTE[pixel * (len(PALETTE) - 1) // 255] for pixel in pixels]
    lines = ["".join(chars[index : index + target_width]) for index in range(0, len(chars), target_width)]
    return "\n".join(lines)


def _trim_borders(image: Image.Image) -> Image.Image:
    background = Image.new("L", image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)
