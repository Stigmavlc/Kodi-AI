#!/usr/bin/env python3
"""Generate branded icon + fanart + setup-flow assets for Kodi-AI.

Outputs (deterministic, regenerated from this script):
- service.kodi.ai/icon.png                              (256x256)
- service.kodi.ai/fanart.jpg                            (1920x1080)
- service.kodi.ai/resources/media/setup_bg.png          (1280x720 — dialog background)
- service.kodi.ai/resources/media/btn_focus.png         (40x40 — button focus)
- service.kodi.ai/resources/media/btn_nofocus.png       (40x40 — button unfocused)
- service.kodi.ai/resources/media/step_pending.png      (32x32 — pending step glyph)
- service.kodi.ai/resources/media/step_done.png         (32x32 — done step glyph)

Run after editing the design:
    python tools/build_assets.py
"""
from __future__ import annotations

import math
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ACCENT = (0, 210, 255)          # cyan glow
ACCENT_DIM = (0, 162, 219)      # secondary cyan
BG_TOP = (8, 14, 26)            # near-black blue
BG_MID = (16, 28, 52)
BG_BOTTOM = (28, 44, 80)
TEXT_PRIMARY = (240, 248, 255)
TEXT_SECONDARY = (160, 200, 230)
GRID = (40, 80, 130, 80)


def _gradient_bg(w: int, h: int, top, mid, bottom) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        if t < 0.5:
            t2 = t * 2
            r = int(top[0] + (mid[0] - top[0]) * t2)
            g = int(top[1] + (mid[1] - top[1]) * t2)
            b = int(top[2] + (mid[2] - top[2]) * t2)
        else:
            t2 = (t - 0.5) * 2
            r = int(mid[0] + (bottom[0] - mid[0]) * t2)
            g = int(mid[1] + (bottom[1] - mid[1]) * t2)
            b = int(mid[2] + (bottom[2] - mid[2]) * t2)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _circuit_overlay(w: int, h: int, density: float = 0.0025) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    rng = random.Random(0xC0DE_A1)
    n = int(w * h * density)
    for _ in range(n):
        x = rng.randrange(w)
        y = rng.randrange(h)
        size = rng.choice([1, 1, 1, 2, 3])
        alpha = rng.randint(40, 140)
        d.ellipse((x - size, y - size, x + size, y + size),
                  fill=(*ACCENT, alpha))
    for _ in range(n // 12):
        x1 = rng.randrange(w)
        y1 = rng.randrange(h)
        length = rng.randint(30, 120)
        if rng.random() < 0.5:
            x2, y2 = x1 + length, y1
        else:
            x2, y2 = x1, y1 + length
        alpha = rng.randint(20, 60)
        d.line((x1, y1, x2, y2), fill=(*ACCENT_DIM, alpha), width=1)
    return overlay


def _hex_ring(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color, width: int = 4):
    pts = []
    for i in range(6):
        angle = math.radians(-90 + i * 60)
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    pts.append(pts[0])
    d.line(pts, fill=color, width=width, joint="curve")


def _load_font(size: int, bold: bool = True):
    # macOS system fonts; fall back to PIL default if unavailable.
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=2 if bold and path.endswith(".ttc") else 0)
            except OSError:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default()


def _glow_text(base: Image.Image, xy, text, font, fill, glow_color, glow_radius=6):
    # Draw glow by writing to a separate RGBA layer and blurring.
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=font, fill=(*glow_color, 200))
    blurred = layer.filter(ImageFilter.GaussianBlur(glow_radius))
    base.alpha_composite(blurred)
    # Crisp text on top.
    d2 = ImageDraw.Draw(base)
    d2.text(xy, text, font=font, fill=(*fill, 255))


def make_icon(path: str, size: int = 256) -> None:
    bg = _gradient_bg(size, size, BG_TOP, BG_MID, BG_BOTTOM)
    bg = bg.convert("RGBA")
    bg.alpha_composite(_circuit_overlay(size, size, density=0.004))

    d = ImageDraw.Draw(bg)
    cx, cy = size // 2, size // 2

    # Outer hex ring
    _hex_ring(d, cx, cy, r=int(size * 0.46), color=(*ACCENT, 220), width=3)
    _hex_ring(d, cx, cy, r=int(size * 0.40), color=(*ACCENT_DIM, 160), width=1)

    # Neural-network style nodes around centre
    rng = random.Random(0xA1)
    for i in range(7):
        angle = math.radians(i * (360 / 7) - 90)
        nr = int(size * 0.32)
        nx = cx + nr * math.cos(angle)
        ny = cy + nr * math.sin(angle)
        d.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=(*ACCENT, 220))
        d.line((cx, cy, nx, ny), fill=(*ACCENT_DIM, 110), width=1)
    # Central core
    d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(*TEXT_PRIMARY, 255))
    d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=ACCENT + (255,))

    # "AI" wordmark below the core
    font_main = _load_font(int(size * 0.28))
    text = "AI"
    bbox = d.textbbox((0, 0), text, font=font_main)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw // 2 - bbox[0]
    ty = int(size * 0.62) - bbox[1]
    _glow_text(bg, (tx, ty), text, font_main, TEXT_PRIMARY, ACCENT, glow_radius=8)

    # "KODI" subtitle above the core
    font_sub = _load_font(int(size * 0.10))
    text = "KODI"
    bbox = d.textbbox((0, 0), text, font=font_sub)
    tw = bbox[2] - bbox[0]
    tx = cx - tw // 2 - bbox[0]
    ty = int(size * 0.10) - bbox[1]
    ImageDraw.Draw(bg).text((tx, ty), text, font=font_sub, fill=(*TEXT_SECONDARY, 220))

    bg.convert("RGB").save(path, "PNG", optimize=True)


def make_fanart(path: str, w: int = 1920, h: int = 1080) -> None:
    bg = _gradient_bg(w, h, BG_TOP, BG_MID, BG_BOTTOM)
    bg = bg.convert("RGBA")
    bg.alpha_composite(_circuit_overlay(w, h, density=0.0018))

    # Soft cyan glow blob lower-right
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((int(w * 0.62), int(h * 0.35), int(w * 1.10), int(h * 1.05)),
               fill=(*ACCENT, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    bg.alpha_composite(glow)

    d = ImageDraw.Draw(bg)

    # Hex ring on the right side
    cx, cy = int(w * 0.78), int(h * 0.50)
    _hex_ring(d, cx, cy, r=240, color=(*ACCENT, 180), width=4)
    _hex_ring(d, cx, cy, r=200, color=(*ACCENT_DIM, 120), width=2)
    _hex_ring(d, cx, cy, r=320, color=(*ACCENT_DIM, 70), width=1)

    # Neural-network style nodes
    rng = random.Random(0xB2)
    nodes = []
    for i in range(11):
        angle = math.radians(i * (360 / 11) - 30)
        nr = 180
        nx = cx + nr * math.cos(angle)
        ny = cy + nr * math.sin(angle)
        nodes.append((nx, ny))
        d.ellipse((nx - 6, ny - 6, nx + 6, ny + 6), fill=(*ACCENT, 230))
    for i, (x, y) in enumerate(nodes):
        for j in (i + 1, i + 3, i + 5):
            j %= len(nodes)
            x2, y2 = nodes[j]
            d.line((x, y, x2, y2), fill=(*ACCENT_DIM, 80), width=1)
    d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), fill=(*TEXT_PRIMARY, 255))
    d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=ACCENT + (255,))

    # Wordmark left side
    title_font = _load_font(180)
    sub_font = _load_font(48)
    micro_font = _load_font(28)

    title = "Kodi-AI"
    tx, ty = 120, int(h * 0.30)
    _glow_text(bg, (tx, ty), title, title_font, TEXT_PRIMARY, ACCENT, glow_radius=14)

    sub = "AI-assisted diagnostics + auto-fix"
    d.text((tx + 6, ty + 200), sub, font=sub_font, fill=(*TEXT_SECONDARY, 235))

    micro = "via Telegram  ·  open-source  ·  on-device"
    d.text((tx + 6, ty + 270), micro, font=micro_font, fill=(*TEXT_SECONDARY, 180))

    # Bottom accent line
    d.rectangle((0, h - 6, w, h), fill=(*ACCENT_DIM, 220))

    bg.convert("RGB").save(path, "JPEG", quality=88, optimize=True)


def make_setup_bg(path: str, w: int = 1280, h: int = 720) -> None:
    """Setup dialog backdrop. Soft cyan gradient + faint circuit overlay.
    1280x720 — Kodi's standard skin canvas. PNG, RGB."""
    bg = _gradient_bg(w, h, BG_TOP, BG_MID, BG_BOTTOM)
    overlay = _circuit_overlay(w, h, density=0.0015)
    overlay = overlay.filter(ImageFilter.GaussianBlur(1.5))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)
    # Faint vignette to focus the eye toward center.
    vignette = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vignette)
    cx, cy = w // 2, h // 2
    for r in range(0, max(w, h), 8):
        alpha = int(min(255, r * 0.35))
        vd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=alpha)
    vignette = vignette.filter(ImageFilter.GaussianBlur(60))
    overlay_v = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay_v.putalpha(vignette)
    bg = Image.alpha_composite(bg, overlay_v)
    bg.convert("RGB").save(path, "PNG", optimize=True)


def _rounded_rect_png(path: str, w: int, h: int, fill, outline=None, radius: int = 8) -> None:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((1, 1, w - 2, h - 2), radius=radius, fill=fill, outline=outline,
                        width=2 if outline else 0)
    img.save(path, "PNG", optimize=True)


def make_btn_focus(path: str) -> None:
    """40x40 cyan-tinted rounded rect for focused buttons."""
    _rounded_rect_png(
        path, 40, 40,
        fill=(0, 212, 255, 90),
        outline=(0, 212, 255, 255),
        radius=10,
    )


def make_btn_nofocus(path: str) -> None:
    """40x40 transparent button background (no-focus state)."""
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    img.save(path, "PNG", optimize=True)


def make_step_pending(path: str) -> None:
    """32x32 hollow gray circle — 'step not yet complete' glyph."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 28, 28), outline=(127, 179, 213, 200), width=2)
    img.save(path, "PNG", optimize=True)


def make_step_done(path: str) -> None:
    """32x32 cyan-filled circle with a white check — 'step complete'."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 30, 30), fill=(0, 212, 255, 255), outline=(0, 212, 255, 255))
    # Check mark — 3-point polyline.
    d.line([(9, 17), (14, 22), (24, 10)], fill=(255, 255, 255, 255), width=3)
    img.save(path, "PNG", optimize=True)


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    addon_dir = os.path.join(here, "service.kodi.ai")
    media_dir = os.path.join(addon_dir, "resources", "media")
    os.makedirs(addon_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)
    icon_path = os.path.join(addon_dir, "icon.png")
    fanart_path = os.path.join(addon_dir, "fanart.jpg")
    print(f"Generating {icon_path}...")
    make_icon(icon_path)
    print(f"Generating {fanart_path}...")
    make_fanart(fanart_path)
    print(f"Generating setup assets in {media_dir}...")
    make_setup_bg(os.path.join(media_dir, "setup_bg.png"))
    make_btn_focus(os.path.join(media_dir, "btn_focus.png"))
    make_btn_nofocus(os.path.join(media_dir, "btn_nofocus.png"))
    make_step_pending(os.path.join(media_dir, "step_pending.png"))
    make_step_done(os.path.join(media_dir, "step_done.png"))
    print("Done.")


if __name__ == "__main__":
    main()
