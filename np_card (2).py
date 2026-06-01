"""
np_card.py — Generador de tarjetas NowPlaying personalizables
=============================================================
Genera imágenes PNG para el comando .np del bot de Discord.

INSTALACIÓN:
    pip install Pillow aiohttp

USO BÁSICO desde el bot:
    from np_card import generate_np_card, DEFAULT_CARD_STYLE

    # En tu comando .np, reemplaza el embed por esto:
    style = load_card_style(user_id)  # carga preferencias del usuario desde JSON
    img_bytes = await generate_np_card(
        song=song, artist=artist, album=album,
        album_art_url=image, username=username,
        display_name=target.display_name,
        avatar_url=str(target.display_avatar.url),
        now_playing=now_playing,
        loved=loved,
        artist_plays=artist_plays,
        style=style,
    )
    file = discord.File(fp=img_bytes, filename="nowplaying.png")
    await ctx.reply(file=file, mention_author=False)
"""

from __future__ import annotations

import asyncio
import colorsys
import io
import json
import math
import os
import textwrap
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

# ─── Ruta donde se guardan los estilos de los usuarios ────────────────────────
STYLES_FILE = "/data/np_card_styles.json"

# ─── FUENTES ──────────────────────────────────────────────────────────────────
# El bot usa fuentes del sistema. Puedes cambiarlas a .ttf que descargues.
# Recomendadas (descargar de Google Fonts y poner en /data/fonts/):
#   - Geist Mono (moderna, limpia)
#   - Space Grotesk (display fuerte)
#   - DM Sans (legible)
#   - Unbounded (impacto)
FONTS_DIR = Path("/data/fonts")

def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Carga fuente .ttf si existe, si no usa la default de Pillow."""
    candidates = [
        FONTS_DIR / f"{name}.ttf",
        FONTS_DIR / f"{name}-Regular.ttf",
        FONTS_DIR / f"{name}-Bold.ttf",
        Path(f"/usr/share/fonts/truetype/{name.lower()}.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    # Fallback: fuente default de Pillow (no escalable)
    return ImageFont.load_default()


# ─── DATACLASS DE ESTILO ──────────────────────────────────────────────────────
@dataclass
class CardStyle:
    """Todas las opciones estéticas que el usuario puede personalizar."""

    # ── Template base ──────────────────────────────────────────────────────────
    # Opciones: "default" | "minimal" | "blur" | "retro" | "glass" | "cassette"
    template: str = "default"

    # ── Fondo ──────────────────────────────────────────────────────────────────
    # Si bg_image_url está vacío, usa color sólido o gradiente
    bg_type: str = "blur_art"          # "solid" | "gradient" | "blur_art" | "custom_image"
    bg_color: str = "#0d0d0d"          # color hex
    bg_color2: str = "#1a1a2e"         # segundo color para gradiente
    bg_gradient_angle: int = 135       # ángulo del gradiente en grados
    bg_image_url: str = ""             # URL de imagen personalizada de fondo
    bg_blur: int = 30                  # intensidad del blur (0–60)
    bg_brightness: float = 0.45        # oscuridad del fondo (0.0–1.0)

    # ── Overlay ────────────────────────────────────────────────────────────────
    overlay_color: str = "#000000"     # color del overlay encima del fondo
    overlay_alpha: int = 80            # opacidad 0–255

    # ── Colores de texto ───────────────────────────────────────────────────────
    text_primary: str = "#ffffff"      # título de canción
    text_secondary: str = "#cccccc"    # artista / álbum
    text_accent: str = "#ff3040"       # color de acento (scrobbles, loved, etc.)
    use_accent_from_art: bool = True   # extrae acento del album art automáticamente

    # ── Fuentes ────────────────────────────────────────────────────────────────
    font_title: str = "SpaceGrotesk"   # nombre del .ttf en /data/fonts/
    font_body: str = "DM_Sans"
    font_size_title: int = 36
    font_size_body: int = 22

    # ── Album art ─────────────────────────────────────────────────────────────
    art_position: str = "left"         # "left" | "right" | "center" | "hidden"
    art_size: int = 200                # px de lado del cuadrado
    art_rounded: int = 16             # radio esquinas (0 = cuadrado)
    art_shadow: bool = True

    # ── Barra de progreso ─────────────────────────────────────────────────────
    show_progress_bar: bool = False    # requiere scrobble timestamp (futuro)
    progress_color: str = ""          # vacío = usar acento

    # ── Info extra ────────────────────────────────────────────────────────────
    show_scrobble_count: bool = True
    show_loved: bool = True
    show_username: bool = True
    show_avatar: bool = True

    # ── Dimensiones ────────────────────────────────────────────────────────────
    width: int = 900
    height: int = 280

    # ── Efectos ───────────────────────────────────────────────────────────────
    vignette: bool = True              # oscurecimiento en bordes
    grain: bool = False                # ruido de película
    card_rounded: int = 20            # radio esquinas de la tarjeta entera


DEFAULT_CARD_STYLE = CardStyle()

TEMPLATE_PRESETS: dict[str, dict] = {
    "default": {},   # usa CardStyle defaults
    "minimal": {
        "bg_type": "solid",
        "bg_color": "#111111",
        "art_position": "left",
        "art_rounded": 0,
        "vignette": False,
        "show_scrobble_count": True,
        "font_title": "SpaceGrotesk",
        "overlay_alpha": 0,
    },
    "blur": {
        "bg_type": "blur_art",
        "bg_blur": 40,
        "bg_brightness": 0.35,
        "art_rounded": 12,
        "vignette": True,
        "overlay_alpha": 60,
    },
    "retro": {
        "bg_type": "gradient",
        "bg_color": "#1a0533",
        "bg_color2": "#2d0b00",
        "text_accent": "#ff6b35",
        "art_rounded": 0,
        "font_title": "Unbounded",
        "grain": True,
        "vignette": True,
    },
    "glass": {
        "bg_type": "blur_art",
        "bg_blur": 50,
        "bg_brightness": 0.30,
        "overlay_alpha": 40,
        "overlay_color": "#ffffff",
        "text_primary": "#ffffff",
        "art_rounded": 20,
        "card_rounded": 28,
        "vignette": False,
    },
    "cassette": {
        "bg_type": "solid",
        "bg_color": "#1c1c1c",
        "art_position": "right",
        "art_rounded": 4,
        "text_accent": "#f5c518",
        "font_title": "Unbounded",
        "font_body": "SpaceGrotesk",
        "grain": True,
        "vignette": False,
    },
}


# ─── CARGA / GUARDADO DE ESTILOS POR USUARIO ─────────────────────────────────

def load_card_style(user_id: int) -> CardStyle:
    """Carga el estilo guardado del usuario o retorna el default."""
    try:
        with open(STYLES_FILE, "r") as f:
            all_styles: dict = json.load(f)
        user_data = all_styles.get(str(user_id))
        if not user_data:
            return CardStyle()
        return CardStyle(**{k: v for k, v in user_data.items() if k in CardStyle.__dataclass_fields__})
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return CardStyle()


def save_card_style(user_id: int, style: CardStyle) -> None:
    """Guarda el estilo del usuario en el JSON."""
    os.makedirs(os.path.dirname(STYLES_FILE), exist_ok=True)
    try:
        with open(STYLES_FILE, "r") as f:
            all_styles: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        all_styles = {}
    all_styles[str(user_id)] = asdict(style)
    with open(STYLES_FILE, "w") as f:
        json.dump(all_styles, f, indent=2)


def apply_template(style: CardStyle, template_name: str) -> CardStyle:
    """Aplica un preset de template encima del estilo actual."""
    preset = TEMPLATE_PRESETS.get(template_name, {})
    data = asdict(style)
    data.update(preset)
    data["template"] = template_name
    return CardStyle(**data)


# ─── UTILIDADES DE COLOR ──────────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_palette(img: Image.Image, n: int = 8) -> list[Tuple[int, int, int]]:
    """Extrae colores dominantes vibrantes de una imagen."""
    import colorsys
    from collections import Counter
    small = img.convert("RGB").resize((80, 80))
    pixels = list(small.getdata())
    def to_hsv(r, g, b):
        return colorsys.rgb_to_hsv(r/255, g/255, b/255)
    vibrant = [(r,g,b) for r,g,b in pixels if to_hsv(r,g,b)[1] > 0.2 and 0.1 < to_hsv(r,g,b)[2] < 0.95]
    if len(vibrant) < 30:
        vibrant = pixels
    buckets = Counter(((r>>3)<<3, (g>>3)<<3, (b>>3)<<3) for r,g,b in vibrant)
    def score(c):
        h, s, v = to_hsv(*c)
        return s * (1 - abs(v - 0.55) * 0.6)
    top = sorted([c for c, _ in buckets.most_common(30)], key=score, reverse=True)
    return top[:n]


def make_gradient(size: Tuple[int, int], color1: str, color2: str, angle: int = 135) -> Image.Image:
    """Crea un gradiente lineal entre dos colores."""
    w, h = size
    img = Image.new("RGB", size)
    c1 = hex_to_rgb(color1)
    c2 = hex_to_rgb(color2)
    rad = math.radians(angle)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            # proyección sobre el eje del gradiente
            t = (x * cos_a + y * sin_a) / (w * abs(cos_a) + h * abs(sin_a) + 1)
            t = max(0.0, min(1.0, t))
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            row.append((r, g, b))
        pixels.extend(row)
    img.putdata(pixels)
    return img


def add_vignette(img: Image.Image, strength: float = 0.6) -> Image.Image:
    """Añade vignette (oscurecimiento en bordes)."""
    w, h = img.size
    vignette = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(vignette)
    for i in range(min(w, h) // 2):
        alpha = int(255 * strength * (1 - i / (min(w, h) / 2)))
        draw.rectangle([i, i, w-i-1, h-i-1], outline=alpha)
    # Suavizar la vignette
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 6))
    # Aplicar como oscurecimiento
    darkener = Image.new("RGB", (w, h), (0, 0, 0))
    img = img.copy()
    img.paste(darkener, mask=vignette)
    return img


def add_grain(img: Image.Image, intensity: float = 0.04) -> Image.Image:
    """Añade ruido de grano de película."""
    import random
    noise = Image.new("RGB", img.size)
    draw = ImageDraw.Draw(noise)
    for _ in range(int(img.width * img.height * intensity)):
        x = random.randint(0, img.width - 1)
        y = random.randint(0, img.height - 1)
        v = random.randint(180, 255)
        draw.point((x, y), fill=(v, v, v))
    noise = noise.filter(ImageFilter.GaussianBlur(radius=0.4))
    return Image.blend(img, noise.convert(img.mode), alpha=0.07)


def rounded_rectangle_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    """Crea una máscara de esquinas redondeadas."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=radius, fill=255)
    return mask


def paste_rounded(base: Image.Image, overlay: Image.Image, pos: Tuple[int,int], radius: int) -> Image.Image:
    """Pega una imagen con esquinas redondeadas."""
    mask = rounded_rectangle_mask(overlay.size, radius)
    base = base.copy()
    base.paste(overlay, pos, mask=mask)
    return base


def draw_shadow(draw: ImageDraw.ImageDraw, rect: Tuple, radius: int = 8, color=(0,0,0,120)):
    """Dibuja una sombra suave detrás de un rectángulo."""
    for offset in range(6, 0, -1):
        alpha = int(color[3] * (offset / 6))
        shadow_rect = [rect[0]+offset, rect[1]+offset, rect[2]+offset, rect[3]+offset]
        draw.rounded_rectangle(shadow_rect, radius=radius, fill=(*color[:3], alpha))


# ─── DESCARGA DE IMÁGENES ─────────────────────────────────────────────────────

async def _fetch_image(url: str) -> Optional[Image.Image]:
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


# ─── GENERADOR PRINCIPAL ──────────────────────────────────────────────────────

async def generate_np_card(
    *,
    song: str,
    artist: str,
    album: str = "",
    album_art_url: str = "",
    username: str = "",
    display_name: str = "",
    avatar_url: str = "",
    now_playing: bool = True,
    loved: bool = False,
    artist_plays: Optional[int] = None,
    style: Optional[CardStyle] = None,
) -> io.BytesIO:
    """
    Genera la tarjeta NowPlaying y devuelve un BytesIO con la imagen PNG.
    """
    if style is None:
        style = CardStyle()

    W, H = style.width, style.height
    PAD = 30  # padding general

    # ── 1. Descargar imágenes en paralelo ─────────────────────────────────────
    album_art_task = asyncio.create_task(_fetch_image(album_art_url))
    avatar_task    = asyncio.create_task(_fetch_image(avatar_url)) if style.show_avatar and avatar_url else None
    bg_task        = asyncio.create_task(_fetch_image(style.bg_image_url)) if style.bg_type == "custom_image" and style.bg_image_url else None

    album_art = await album_art_task
    avatar    = await avatar_task if avatar_task else None
    bg_img    = await bg_task if bg_task else None

    # ── 2. Color de acento ────────────────────────────────────────────────────
    accent_rgb = hex_to_rgb(style.text_accent)
    if style.use_accent_from_art and album_art:
        palette = extract_palette(album_art)
        if palette:
            accent_rgb = palette[0]

    accent_hex = rgb_to_hex(*accent_rgb)

    # ── 3. Construir fondo ────────────────────────────────────────────────────
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    if style.bg_type == "blur_art" and album_art:
        # Escalar el art para cubrir toda la tarjeta
        art_bg = album_art.convert("RGB").resize((W, H), Image.LANCZOS)
        art_bg = art_bg.filter(ImageFilter.GaussianBlur(radius=style.bg_blur))
        art_bg = ImageEnhance.Brightness(art_bg).enhance(style.bg_brightness)
        canvas.paste(art_bg.convert("RGBA"), (0, 0))

    elif style.bg_type == "gradient":
        grad = make_gradient((W, H), style.bg_color, style.bg_color2, style.bg_gradient_angle)
        canvas.paste(grad.convert("RGBA"), (0, 0))

    elif style.bg_type == "custom_image" and bg_img:
        bg_resized = bg_img.convert("RGB").resize((W, H), Image.LANCZOS)
        bg_resized = ImageEnhance.Brightness(bg_resized).enhance(style.bg_brightness)
        canvas.paste(bg_resized.convert("RGBA"), (0, 0))

    else:  # solid
        canvas.paste(Image.new("RGBA", (W, H), (*hex_to_rgb(style.bg_color), 255)), (0, 0))

    # ── 4. Overlay de color ───────────────────────────────────────────────────
    if style.overlay_alpha > 0:
        overlay = Image.new("RGBA", (W, H), (*hex_to_rgb(style.overlay_color), style.overlay_alpha))
        canvas = Image.alpha_composite(canvas, overlay)

    # ── 5. Vignette ───────────────────────────────────────────────────────────
    if style.vignette:
        canvas = add_vignette(canvas.convert("RGB"), strength=0.55).convert("RGBA")

    # ── 6. Grain ──────────────────────────────────────────────────────────────
    if style.grain:
        canvas = add_grain(canvas.convert("RGB")).convert("RGBA")

    # ── 7. Dibujar album art ──────────────────────────────────────────────────
    art_x, art_y = PAD, (H - style.art_size) // 2
    text_start_x = PAD

    if style.art_position != "hidden" and album_art:
        art_square = album_art.convert("RGBA").resize((style.art_size, style.art_size), Image.LANCZOS)

        if style.art_position == "right":
            art_x = W - PAD - style.art_size
            text_start_x = PAD
        elif style.art_position == "center":
            art_x = (W - style.art_size) // 2
            text_start_x = PAD
        else:  # left
            text_start_x = PAD + style.art_size + PAD

        # Sombra del art
        if style.art_shadow:
            shadow_layer = Image.new("RGBA", (W, H), (0,0,0,0))
            sd = ImageDraw.Draw(shadow_layer)
            sr = [art_x+6, art_y+6, art_x+style.art_size+6, art_y+style.art_size+6]
            sd.rounded_rectangle(sr, radius=style.art_rounded+4, fill=(0,0,0,100))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=12))
            canvas = Image.alpha_composite(canvas, shadow_layer)

        # Pegar art con esquinas redondeadas
        canvas = paste_rounded(canvas, art_square, (art_x, art_y), style.art_rounded)

    # ── 8. Fuentes ────────────────────────────────────────────────────────────
    font_title  = _load_font(style.font_title, style.font_size_title)
    font_body   = _load_font(style.font_body, style.font_size_body)
    font_small  = _load_font(style.font_body, 16)
    font_status = _load_font(style.font_body, 15)

    draw = ImageDraw.Draw(canvas)

    # ── 9. Área de texto ──────────────────────────────────────────────────────
    text_x = text_start_x
    # Si el art está a la derecha, el texto ocupa la izquierda
    if style.art_position == "right" and style.art_position != "hidden":
        text_max_w = W - PAD - style.art_size - PAD*2 - text_x
    elif style.art_position == "left" and style.art_position != "hidden":
        text_max_w = W - text_start_x - PAD
        if style.show_avatar:
            text_max_w -= 50
    else:
        text_max_w = W - text_start_x*2

    text_area_top = PAD + 10

    # ── 10. Estado (now playing / last track) ─────────────────────────────────
    status_y = text_area_top
    status_text = "▶  NOW PLAYING" if now_playing else "⏸  LAST TRACK"
    status_color = accent_rgb if now_playing else (160, 160, 160)
    draw.text((text_x, status_y), status_text, font=font_status, fill=(*status_color, 220))

    # ── 11. Nombre de canción ─────────────────────────────────────────────────
    title_y = status_y + 26
    # Truncar título si es muy largo
    song_display = song if len(song) <= 36 else song[:34] + "…"
    draw.text((text_x, title_y), song_display, font=font_title, fill=(*hex_to_rgb(style.text_primary), 255))

    # ── 12. Artista + álbum ───────────────────────────────────────────────────
    body_y = title_y + style.font_size_title + 8
    artist_line = artist
    if album:
        artist_line += f"  ·  {album}"
    # Truncar
    if len(artist_line) > 48:
        artist_line = artist_line[:46] + "…"
    draw.text((text_x, body_y), artist_line, font=font_body, fill=(*hex_to_rgb(style.text_secondary), 200))

    # ── 13. Línea de acento decorativa ───────────────────────────────────────
    line_y = body_y + style.font_size_body + 14
    line_w = min(180, text_max_w // 2)
    draw.rectangle([text_x, line_y, text_x + line_w, line_y + 2], fill=(*accent_rgb, 200))

    # ── 14. Stats (scrobbles, loved) ──────────────────────────────────────────
    stats_y = line_y + 14
    stats_parts = []
    if style.show_scrobble_count and artist_plays:
        stats_parts.append(f"♫ {artist_plays:,} scrobbles")
    if style.show_loved and loved:
        stats_parts.append("❤  Loved")
    if stats_parts:
        draw.text((text_x, stats_y), "  ·  ".join(stats_parts), font=font_small, fill=(*accent_rgb, 180))

    # ── 15. Username + avatar (esquina inferior derecha) ──────────────────────
    if style.show_username and username:
        user_text = f"last.fm/{username}"
        bbox = draw.textbbox((0, 0), user_text, font=font_small)
        tw = bbox[2] - bbox[0]
        ux = W - PAD - tw
        uy = H - PAD - 18

        # Avatar pequeño al lado del username
        if style.show_avatar and avatar:
            av_size = 22
            av_small = avatar.convert("RGBA").resize((av_size, av_size), Image.LANCZOS)
            av_mask = rounded_rectangle_mask((av_size, av_size), av_size // 2)
            canvas.paste(av_small, (ux - av_size - 6, uy - 2), mask=av_mask)

        draw = ImageDraw.Draw(canvas)  # redraw tras paste
        draw.text((ux, uy), user_text, font=font_small, fill=(*hex_to_rgb(style.text_secondary), 160))

    # ── 16. Borde de la tarjeta (acento sutil) ────────────────────────────────
    border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_layer)
    bd.rounded_rectangle(
        [0, 0, W-1, H-1],
        radius=style.card_rounded,
        outline=(*accent_rgb, 60),
        width=1,
    )
    canvas = Image.alpha_composite(canvas, border_layer)

    # ── 17. Aplicar esquinas redondeadas a toda la tarjeta ────────────────────
    if style.card_rounded > 0:
        mask = rounded_rectangle_mask((W, H), style.card_rounded)
        final = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        final.paste(canvas, (0, 0), mask=mask)
    else:
        final = canvas

    # ── 18. Exportar ──────────────────────────────────────────────────────────
    output = io.BytesIO()
    final.convert("RGBA").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


# ─── COMANDOS DEL BOT PARA CONFIGURAR EL ESTILO ───────────────────────────────
"""
Pega estos comandos en tu bot.py principal.

DEPENDENCIAS EXTRA NECESARIAS EN EL BOT:
    from np_card import (
        generate_np_card, load_card_style, save_card_style,
        apply_template, CardStyle, TEMPLATE_PRESETS, asdict
    )

──────────────────────────────────────────────────────────────────────────────
PASO 1: Modifica tu comando .np para generar imagen

Reemplaza (aproximadamente la línea 11477 en tu bot):

    msg = await ctx.reply(embed=embed, mention_author=False)

Por:

    style = load_card_style(target.id)
    try:
        img_bytes = await generate_np_card(
            song=song, artist=artist, album=album,
            album_art_url=image or "", username=username,
            display_name=target.display_name,
            avatar_url=str(target.display_avatar.url),
            now_playing=now_playing, loved=loved,
            artist_plays=artist_plays, style=style,
        )
        file = discord.File(fp=img_bytes, filename="nowplaying.png")
        msg = await ctx.reply(file=file, mention_author=False)
    except Exception as e:
        # Fallback al embed original si falla la imagen
        msg = await ctx.reply(embed=embed, mention_author=False)

──────────────────────────────────────────────────────────────────────────────
PASO 2: Comando .setcard — menú de personalización

@bot.command(name="setcard", aliases=["cardset", "npset"])
async def setcard_cmd(ctx, setting: str = "", *, value: str = ""):
    \"\"\"
    Personaliza tu tarjeta NowPlaying.
    Uso:
      .setcard                    — ver tu estilo actual
      .setcard template <nombre>  — cambiar template (default/minimal/blur/retro/glass/cassette)
      .setcard bg <color hex>     — color de fondo (#1a1a2e)
      .setcard bg gradient #color1 #color2 — gradiente
      .setcard bgblur <0-60>      — intensidad de blur
      .setcard textcolor <hex>    — color del texto principal
      .setcard accent <hex>       — color de acento
      .setcard art <left|right|hidden> — posición del album art
      .setcard artsize <px>       — tamaño del art (100-250)
      .setcard font <nombre>      — fuente (SpaceGrotesk/Unbounded/DM_Sans)
      .setcard vignette <on|off>  — vignette
      .setcard grain <on|off>     — grano de película
      .setcard reset              — restablecer todo
    \"\"\"
    user_id = ctx.author.id
    style = load_card_style(user_id)
    setting = setting.lower().strip()

    if not setting:
        # Mostrar estilo actual
        embed = discord.Embed(
            title="🎨 Tu estilo de tarjeta NowPlaying",
            color=0x2b2d31,
        )
        embed.add_field(name="Template",  value=style.template,  inline=True)
        embed.add_field(name="Fondo",     value=f"{style.bg_type} {style.bg_color}", inline=True)
        embed.add_field(name="Acento",    value=style.text_accent, inline=True)
        embed.add_field(name="Art",       value=f"{style.art_position} ({style.art_size}px)", inline=True)
        embed.add_field(name="Fuente",    value=style.font_title, inline=True)
        embed.add_field(name="Efectos",   value=f"vignette={'✅' if style.vignette else '❌'}  grain={'✅' if style.grain else '❌'}", inline=True)
        embed.set_footer(text="Usa .setcard <opción> <valor> para cambiar")
        return await ctx.reply(embed=embed, mention_author=False)

    if setting == "reset":
        save_card_style(user_id, CardStyle())
        return await ctx.reply("✅ Estilo restablecido al default.", mention_author=False)

    if setting == "template":
        templates = list(TEMPLATE_PRESETS.keys())
        if value not in templates:
            return await ctx.reply(f"❌ Templates disponibles: {', '.join(f'`{t}`' for t in templates)}", mention_author=False)
        style = apply_template(style, value)
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Template cambiado a `{value}`.", mention_author=False)

    if setting == "bg":
        parts = value.split()
        if len(parts) == 3 and parts[0] == "gradient":
            style.bg_type = "gradient"
            style.bg_color = parts[1] if parts[1].startswith("#") else f"#{parts[1]}"
            style.bg_color2 = parts[2] if parts[2].startswith("#") else f"#{parts[2]}"
        elif parts[0].startswith("#"):
            style.bg_type = "solid"
            style.bg_color = parts[0]
        else:
            return await ctx.reply("❌ Uso: `.setcard bg #hex` o `.setcard bg gradient #color1 #color2`", mention_author=False)
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Fondo actualizado.", mention_author=False)

    if setting == "bgblur":
        try:
            v = max(0, min(60, int(value)))
            style.bg_blur = v
            style.bg_type = "blur_art"
            save_card_style(user_id, style)
            return await ctx.reply(f"✅ Blur de fondo: `{v}`.", mention_author=False)
        except ValueError:
            return await ctx.reply("❌ Valor inválido. Usa un número entre 0 y 60.", mention_author=False)

    if setting == "accent":
        c = value.strip() if value.startswith("#") else f"#{value.strip()}"
        style.text_accent = c
        style.use_accent_from_art = False
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Color de acento: `{c}`. Tip: usa `.setcard accent auto` para extraerlo del album art.", mention_author=False)

    if setting == "accent" and value.lower() == "auto":
        style.use_accent_from_art = True
        save_card_style(user_id, style)
        return await ctx.reply("✅ Acento automático activado (se extrae del album art).", mention_author=False)

    if setting == "textcolor":
        c = value.strip() if value.startswith("#") else f"#{value.strip()}"
        style.text_primary = c
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Color de texto: `{c}`.", mention_author=False)

    if setting == "art":
        opts = ["left", "right", "center", "hidden"]
        if value not in opts:
            return await ctx.reply(f"❌ Posiciones: {', '.join(f'`{o}`' for o in opts)}", mention_author=False)
        style.art_position = value
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Posición del art: `{value}`.", mention_author=False)

    if setting == "artsize":
        try:
            v = max(100, min(250, int(value)))
            style.art_size = v
            save_card_style(user_id, style)
            return await ctx.reply(f"✅ Tamaño del art: `{v}px`.", mention_author=False)
        except ValueError:
            return await ctx.reply("❌ Valor inválido. Usa un número entre 100 y 250.", mention_author=False)

    if setting == "font":
        # Las fuentes disponibles son las que tengas en /data/fonts/
        style.font_title = value
        style.font_body = value
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Fuente cambiada a `{value}`. (Asegúrate de tener el .ttf en /data/fonts/)", mention_author=False)

    if setting == "vignette":
        style.vignette = value.lower() in ("on", "true", "1", "si", "sí")
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Vignette: {'activada' if style.vignette else 'desactivada'}.", mention_author=False)

    if setting == "grain":
        style.grain = value.lower() in ("on", "true", "1", "si", "sí")
        save_card_style(user_id, style)
        return await ctx.reply(f"✅ Grain: {'activado' if style.grain else 'desactivado'}.", mention_author=False)

    await ctx.reply(
        "❌ Opción no reconocida. Usa `.setcard` para ver todas las opciones.",
        mention_author=False,
    )

──────────────────────────────────────────────────────────────────────────────
PASO 3: .cardpreview — previsualizar sin cambiar nada

@bot.command(name="cardpreview", aliases=["previewcard", "nppreview"])
async def cardpreview_cmd(ctx, template: str = ""):
    \"\"\"Previsualiza un template sin guardar cambios.\"\"\"
    style = load_card_style(ctx.author.id)
    if template:
        style = apply_template(style, template)

    username = get_lastfm_user(ctx.author.id)
    if not username:
        return await ctx.reply("❌ Conecta tu Last.fm primero con `.fmset`.", mention_author=False)

    recent = await lastfm_get({"method": "user.getrecenttracks", "user": username, "limit": 1, "extended": 1})
    if not recent or "error" in recent:
        return await ctx.reply("❌ No pude obtener tu canción actual.", mention_author=False)

    tracks = recent.get("recenttracks", {}).get("track", [])
    if not tracks:
        return await ctx.reply("❌ Sin scrobbles recientes.", mention_author=False)

    track = tracks[0] if isinstance(tracks, list) else tracks
    _a = track.get("artist", {})
    artist = ((_a.get("name") or _a.get("#text") or "?") if isinstance(_a, dict) else str(_a)).strip()
    song = track.get("name", "?")
    album = track.get("album", {}).get("#text", "")
    image_url = next((i["#text"] for i in track.get("image", []) if i.get("size") == "extralarge" and i.get("#text")), None)
    if image_url:
        import re as _re
        image_url = _re.sub(r'/i/u/\\d+x\\d+/', '/i/u/', image_url)
    image_url = _clean_lfm_image(image_url)

    img_bytes = await generate_np_card(
        song=song, artist=artist, album=album,
        album_art_url=image_url or "",
        username=username,
        display_name=ctx.author.display_name,
        avatar_url=str(ctx.author.display_avatar.url),
        now_playing=track.get("@attr", {}).get("nowplaying") == "true",
        loved=track.get("loved") == "1",
        style=style,
    )
    label = f"Preview — template `{template}`" if template else "Preview — tu estilo actual"
    file = discord.File(fp=img_bytes, filename="preview_card.png")
    await ctx.reply(f"🎨 {label}", file=file, mention_author=False)
"""
