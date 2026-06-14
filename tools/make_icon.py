from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PNG_PATH = ASSETS / "app_icon.png"
ICO_PATH = ASSETS / "app_icon.ico"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for item in candidates:
        try:
            return ImageFont.truetype(item, size)
        except Exception:
            continue
    return ImageFont.load_default()


def rounded_gradient(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x * 0.65 + y * 0.35) / size
            r = int(12 + 18 * t)
            g = int(120 + 70 * t)
            b = int(230 + 20 * t)
            px[x, y] = (r, g, b, 255)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((38, 38, size - 38, size - 38), radius=230, fill=255)
    img.putalpha(mask)
    return img


def draw_paper_plane(draw: ImageDraw.ImageDraw) -> None:
    # Shadow
    shadow = [(270, 430), (780, 245), (610, 740), (510, 560), (390, 650)]
    draw.polygon([(x + 18, y + 22) for x, y in shadow], fill=(0, 50, 120, 95))

    # Plane body
    plane = [(260, 410), (790, 215), (610, 720), (505, 540), (380, 630)]
    draw.polygon(plane, fill=(255, 255, 255, 255))

    # Inner fold
    draw.polygon([(505, 540), (790, 215), (445, 590)], fill=(215, 238, 255, 255))
    draw.polygon([(505, 540), (610, 720), (555, 570)], fill=(185, 220, 252, 255))


def draw_database(draw: ImageDraw.ImageDraw) -> None:
    x0, y0, x1, y1 = 250, 635, 775, 875
    outline = (255, 214, 86, 255)
    fill = (5, 73, 150, 215)
    draw.ellipse((x0, y0, x1, y0 + 105), fill=(10, 91, 180, 245), outline=outline, width=12)
    draw.rectangle((x0, y0 + 52, x1, y1 - 52), fill=fill)
    draw.line((x0, y0 + 52, x0, y1 - 52), fill=outline, width=12)
    draw.line((x1, y0 + 52, x1, y1 - 52), fill=outline, width=12)
    draw.ellipse((x0, y1 - 105, x1, y1), fill=(6, 68, 148, 245), outline=outline, width=12)
    for yy in (730, 805):
        draw.arc((x0, yy - 52, x1, yy + 52), 0, 180, fill=(255, 240, 170, 210), width=8)


def draw_text(draw: ImageDraw.ImageDraw, size: int) -> None:
    title = "万青"
    subtitle = "TG采集"
    f1 = font(120, bold=True)
    f2 = font(62, bold=True)

    b1 = draw.textbbox((0, 0), title, font=f1)
    b2 = draw.textbbox((0, 0), subtitle, font=f2)
    x1 = (size - (b1[2] - b1[0])) // 2
    x2 = (size - (b2[2] - b2[0])) // 2

    draw.text((x1 + 5, 94 + 6), title, font=f1, fill=(0, 40, 100, 120))
    draw.text((x1, 94), title, font=f1, fill=(255, 255, 255, 255))
    draw.text((x2 + 3, 230 + 4), subtitle, font=f2, fill=(0, 40, 100, 110))
    draw.text((x2, 230), subtitle, font=f2, fill=(235, 248, 255, 245))


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    size = 1024
    img = rounded_gradient(size)

    # Soft shine
    shine = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shine_draw = ImageDraw.Draw(shine)
    shine_draw.ellipse((-260, -360, 780, 520), fill=(255, 255, 255, 60))
    img = Image.alpha_composite(img, shine.filter(ImageFilter.GaussianBlur(2)))

    draw = ImageDraw.Draw(img)
    draw_text(draw, size)
    draw_paper_plane(draw)
    draw_database(draw)

    # Outer border
    draw.rounded_rectangle((38, 38, size - 38, size - 38), radius=230, outline=(255, 255, 255, 160), width=18)
    draw.rounded_rectangle((58, 58, size - 58, size - 58), radius=210, outline=(12, 80, 180, 80), width=6)

    img.save(PNG_PATH)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ICO_PATH, sizes=sizes)
    print(f"图标已生成：{PNG_PATH}")
    print(f"ICO 已生成：{ICO_PATH}")


if __name__ == "__main__":
    main()
