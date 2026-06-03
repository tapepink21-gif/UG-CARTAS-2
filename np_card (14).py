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

# Fuentes del sistema que casi siempre existen en Linux
_SYSTEM_FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
_SYSTEM_FONT_PATH = next((p for p in _SYSTEM_FONT_FALLBACKS if Path(p).exists()), None)

def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Carga fuente .ttf si existe, si no usa una fuente del sistema escalable."""
    candidates = [
        FONTS_DIR / f"{name}.ttf",
        FONTS_DIR / f"{name}-Regular.ttf",
        FONTS_DIR / f"{name}-Bold.ttf",
        Path(f"/usr/share/fonts/truetype/{name.lower()}.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    # Fallback: fuente del sistema que sí respeta el tamaño
    if _SYSTEM_FONT_PATH:
        try:
            return ImageFont.truetype(_SYSTEM_FONT_PATH, size)
        except Exception:
            pass
    # Último recurso: default de Pillow (no escalable, se ve chica)
    return ImageFont.load_default(size=size) if hasattr(ImageFont, "load_default") else ImageFont.load_default()


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
    font_size_title: int = 42
    font_size_body: int = 26

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
    custom_avatar_url: str = ""        # URL de avatar personalizado (vacio = usar el de Discord)

    # ── Dimensiones ────────────────────────────────────────────────────────────
    width: int = 900
    height: int = 280

    # ── Efectos ───────────────────────────────────────────────────────────────
    vignette: bool = True              # oscurecimiento en bordes
    grain: bool = False                # ruido de película
    card_rounded: int = 20            # radio esquinas de la tarjeta entera

    # ── Modo de respuesta ─────────────────────────────────────────────────────
    card_mode: str = "imagen"          # "imagen" | "embed"

    # ── Texto y tipografía ────────────────────────────────────────────────────
    text_shadow: bool = False          # sombra en el texto
    text_align: str = "left"           # "left" | "center" | "right"
    text_uppercase: bool = False       # título en mayúsculas

    # ── Layout ────────────────────────────────────────────────────────────────
    show_album: bool = True            # mostrar nombre del álbum
    show_progress_fake: bool = False   # barra de progreso decorativa
    card_height: int = 280             # altura de la tarjeta (200–400)
    np_badge_style: str = "default"    # "default" | "pill" | "dot" | "none"

    # ── Forma del art ─────────────────────────────────────────────────────────
    art_shape: str = "square"          # "square" | "circle" | "hexagon"
    art_glow: bool = False             # glow del color de acento alrededor del art
    art_border_color: str = ""         # color del borde del art (vacío = sin borde)
    art_border_width: int = 0          # grosor del borde en px

    # ── Efectos visuales extra ────────────────────────────────────────────────
    glitch: bool = False               # efecto glitch RGB
    scanlines: bool = False            # líneas CRT horizontales
    card_glow: bool = False            # glow exterior de la tarjeta
    card_shadow: bool = False          # sombra exterior de la tarjeta
    art_reflection: bool = False       # reflejo del art debajo

    # ── Color ─────────────────────────────────────────────────────────────────
    monochrome: bool = False           # todo en un solo tono
    monochrome_color: str = "#ffffff"  # color base del modo monocromático
    palette_from_art: bool = False     # extraer toda la paleta del art automáticamente


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


def _fill_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Escala la imagen manteniendo proporción y recorta al centro (cover fit)."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


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

def _is_animated(img: Image.Image) -> bool:
    """Devuelve True si la imagen tiene más de un frame (GIF animado)."""
    try:
        img.seek(1)
        img.seek(0)
        return True
    except EOFError:
        return False


def _extract_frames(img: Image.Image) -> list[tuple[Image.Image, int]]:
    """Extrae todos los frames de un GIF y sus duraciones en ms."""
    frames = []
    try:
        while True:
            duration = img.info.get("duration", 80)
            frames.append((img.convert("RGBA").copy(), duration))
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    return frames


async def _fetch_image_raw(url: str):
    """Descarga imagen y devuelve bytes crudos para detectar GIF animado."""
    if not url:
        return None, None
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None, None
                data = await resp.read()
        img = Image.open(io.BytesIO(data))
        return img, data
    except Exception:
        return None, None


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
    Genera la tarjeta NowPlaying. Si el album art es un GIF animado,
    devuelve un GIF animado. Si no, devuelve PNG.
    """
    if style is None:
        style = CardStyle()

    W, H = style.width, style.height
    PAD = 30  # padding general

    # ── 1. Descargar imágenes en paralelo ────────────────────────────────────
    album_art_task = asyncio.create_task(_fetch_image_raw(album_art_url))
    _avatar_src = style.custom_avatar_url if style.custom_avatar_url else avatar_url
    avatar_task    = asyncio.create_task(_fetch_image(_avatar_src)) if style.show_avatar and _avatar_src else None
    bg_task        = asyncio.create_task(_fetch_image_raw(style.bg_image_url)) if style.bg_type == "custom_image" and style.bg_image_url else None

    album_art_img, _album_art_raw = await album_art_task
    avatar    = await avatar_task if avatar_task else None
    bg_img_raw = await bg_task if bg_task else (None, None)
    bg_img = bg_img_raw[0] if bg_img_raw else None

    # Detectar si el fondo personalizado es un GIF animado
    bg_animated = bg_img is not None and _is_animated(bg_img)
    if bg_animated:
        bg_frames = _extract_frames(bg_img)
        bg_frames = bg_frames  # sin límite de frames, animación completa
    else:
        bg_frames = [(bg_img, 80)] if bg_img else [(None, 80)]

    # Detectar si el album art es un GIF animado
    art_is_animated = album_art_img is not None and _is_animated(album_art_img)
    if art_is_animated:
        art_frames = _extract_frames(album_art_img)
        art_frames = art_frames  # sin límite de frames, animación completa
    else:
        art_frames = [(album_art_img, 80)] if album_art_img else [(None, 80)]

    # Animado si el art o el fondo son GIF
    animated = art_is_animated or bg_animated

    # Si blur_art + cover animado, el fondo usa los mismos frames del cover
    if art_is_animated and style.bg_type == "blur_art":
        animated = True
        bg_frames = art_frames  # mismo GIF, mismo loop

    # Normalizar número de frames: el más largo cicla en loop
    n_frames = max(len(art_frames), len(bg_frames)) if animated else 1
    if animated:
        if len(art_frames) < n_frames:
            art_frames = (art_frames * ((n_frames // len(art_frames)) + 1))[:n_frames]
        if len(bg_frames) < n_frames:
            bg_frames = (bg_frames * ((n_frames // len(bg_frames)) + 1))[:n_frames]

    album_art = album_art_img  # compatibilidad con el resto del codigo

    # ── 2. Color de acento ────────────────────────────────────────────────────
    accent_rgb = hex_to_rgb(style.text_accent)
    if style.use_accent_from_art and album_art:
        palette = extract_palette(album_art)
        if palette:
            accent_rgb = palette[0]

    accent_hex = rgb_to_hex(*accent_rgb)

    # ── 3. Construir fondo ────────────────────────────────────────────────────
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    _blur_filter = ImageFilter.GaussianBlur(radius=max(1, style.bg_blur))

    def _build_bg_frame(frame_img=None) -> Image.Image:
        """Construye el fondo para un frame específico (o el estático)."""
        bg_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        src_img = frame_img or album_art
        if style.bg_type == "blur_art" and src_img:
            art_bg = _fill_crop(src_img.convert("RGB"), W, H)
            art_bg = art_bg.filter(_blur_filter)
            art_bg = ImageEnhance.Brightness(art_bg).enhance(style.bg_brightness)
            bg_canvas.paste(art_bg.convert("RGBA"), (0, 0))
        elif style.bg_type == "gradient":
            grad = make_gradient((W, H), style.bg_color, style.bg_color2, style.bg_gradient_angle)
            bg_canvas.paste(grad.convert("RGBA"), (0, 0))
        elif style.bg_type == "custom_image":
            _src = frame_img or (bg_frames[0][0] if bg_frames and bg_frames[0][0] else bg_img)
            if _src:
                bg_resized = _fill_crop(_src.convert("RGB"), W, H)
                bg_resized = ImageEnhance.Brightness(bg_resized).enhance(style.bg_brightness)
                bg_canvas.paste(bg_resized.convert("RGBA"), (0, 0))
        else:  # solid
            bg_canvas.paste(Image.new("RGBA", (W, H), (*hex_to_rgb(style.bg_color), 255)), (0, 0))
        return bg_canvas

    # Fondo estático (primer frame) para construir el resto de capas encima
    canvas = _build_bg_frame()

    # ── 4. Overlay de color ───────────────────────────────────────────────────
    # Para animados: guardamos el overlay en capa separada para reusar en cada frame
    overlay_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if style.overlay_alpha > 0:
        overlay_layer = Image.new("RGBA", (W, H), (*hex_to_rgb(style.overlay_color), style.overlay_alpha))
        canvas = Image.alpha_composite(canvas, overlay_layer)

    # ── 5. Vignette ───────────────────────────────────────────────────────────
    if style.vignette:
        canvas = add_vignette(canvas.convert("RGB"), strength=0.55).convert("RGBA")

    # ── 6. Grain ──────────────────────────────────────────────────────────────
    if style.grain:
        canvas = add_grain(canvas.convert("RGB")).convert("RGBA")

    # ── 7. Posición del album art (calculamos coords pero NO pegamos aún) ────────
    # Clamp art_size so it never overflows the card height
    _max_art = H - PAD * 2
    _art_size = min(style.art_size, _max_art)
    art_x, art_y = PAD, (H - _art_size) // 2
    text_start_x = PAD

    if style.art_position != "hidden" and album_art:
        if style.art_position == "right":
            art_x = W - PAD - _art_size
            text_start_x = PAD
        elif style.art_position == "center":
            art_x = (W - _art_size) // 2
            text_start_x = PAD
        else:  # left
            text_start_x = PAD + _art_size + PAD

    # ── 8. Fuentes ────────────────────────────────────────────────────────────
    font_title  = _load_font(style.font_title, style.font_size_title)
    font_body   = _load_font(style.font_body, style.font_size_body)
    # font_small y font_status escalan con el tamaño del body
    _small_size  = max(14, style.font_size_body - 4)
    _status_size = max(13, style.font_size_body - 5)
    font_small  = _load_font(style.font_body, _small_size)
    font_status = _load_font(style.font_body, _status_size)
    _status_h   = _status_size + 6
    _title_h    = style.font_size_title + 8
    _body_h     = style.font_size_body + 8
    _line_h     = 14
    _stats_h    = _small_size + 6
    _progress_h = 32 if getattr(style, "show_progress_fake", False) else 0
    _total_text_h = _status_h + _title_h + _body_h + _line_h + _stats_h + _progress_h

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

    text_area_top = max(PAD, (H - _total_text_h) // 2)

    # ── 9b. Caja semitransparente detrás del texto para legibilidad ───────────
    # Solo si el fondo es muy caótico (blur_art o custom_image)
    if style.bg_type in ("blur_art", "custom_image") or style.bg_image_url:
        _box_x1 = text_x - 10
        _box_y1 = text_area_top - 8
        _box_x2 = text_x + text_max_w + 10
        _box_y2 = H - PAD + 8
        _box_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _box_draw  = ImageDraw.Draw(_box_layer)
        _box_draw.rounded_rectangle(
            [_box_x1, _box_y1, _box_x2, _box_y2],
            radius=12,
            fill=(0, 0, 0, 110),
        )
        _box_layer = _box_layer.filter(ImageFilter.GaussianBlur(radius=3))
        canvas = Image.alpha_composite(canvas, _box_layer)
        draw = ImageDraw.Draw(canvas)

    # ── 10. Estado (now playing / last track) ─────────────────────────────────
    status_y = text_area_top
    badge = style.np_badge_style if hasattr(style, "np_badge_style") else "default"
    status_color = accent_rgb if now_playing else (160, 160, 160)
    if badge != "none":
        if badge == "dot":
            dot_r = 5
            draw.ellipse([text_x, status_y + 5, text_x + dot_r*2, status_y + 5 + dot_r*2], fill=(*status_color, 220))
            status_text = "  NOW PLAYING" if now_playing else "  LAST TRACK"
            draw.text((text_x + dot_r*2 + 4, status_y), status_text, font=font_status, fill=(*status_color, 220))
        elif badge == "pill":
            pill_text = "NOW PLAYING" if now_playing else "LAST TRACK"
            bbox = draw.textbbox((0, 0), pill_text, font=font_status)
            pw, ph = bbox[2]-bbox[0]+16, bbox[3]-bbox[1]+6
            draw.rounded_rectangle([text_x, status_y, text_x+pw, status_y+ph], radius=ph//2, fill=(*status_color, 60), outline=(*status_color, 160), width=1)
            draw.text((text_x+8, status_y+3), pill_text, font=font_status, fill=(*status_color, 255))
        else:  # default
            status_text = "▶  NOW PLAYING" if now_playing else "⏸  LAST TRACK"
            draw.text((text_x, status_y), status_text, font=font_status, fill=(*status_color, 220))

    # ── 11. Nombre de canción ─────────────────────────────────────────────────
    title_y = status_y + _status_h
    song_display = song if len(song) <= 36 else song[:34] + "…"
    if getattr(style, "text_uppercase", False):
        song_display = song_display.upper()

    # Alineación del texto
    _align = getattr(style, "text_align", "left")
    def _aligned_x(text, font, base_x, max_w):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        if _align == "center": return base_x + max(0, (max_w - tw) // 2)
        if _align == "right":  return base_x + max(0, max_w - tw)
        return base_x

    tx = _aligned_x(song_display, font_title, text_x, text_max_w)
    if getattr(style, "text_shadow", False):
        draw.text((tx+2, title_y+2), song_display, font=font_title, fill=(0, 0, 0, 120))
    # Stroke negro para que el título se lea sobre cualquier fondo
    draw.text((tx, title_y), song_display, font=font_title,
              fill=(*hex_to_rgb(style.text_primary), 255),
              stroke_width=2, stroke_fill=(0, 0, 0, 180))

    # ── 12. Artista + álbum ───────────────────────────────────────────────────
    body_y = title_y + _title_h
    artist_line = artist
    if getattr(style, "show_album", True) and album:
        artist_line += f"  ·  {album}"
    if len(artist_line) > 48:
        artist_line = artist_line[:46] + "…"
    if getattr(style, "text_uppercase", False):
        artist_line = artist_line.upper()
    bx = _aligned_x(artist_line, font_body, text_x, text_max_w)
    if getattr(style, "text_shadow", False):
        draw.text((bx+2, body_y+2), artist_line, font=font_body, fill=(0, 0, 0, 100))
    draw.text((bx, body_y), artist_line, font=font_body,
              fill=(*hex_to_rgb(style.text_secondary), 200),
              stroke_width=1, stroke_fill=(0, 0, 0, 160))

    # ── 13. Línea de acento decorativa ───────────────────────────────────────
    line_y = body_y + _body_h
    line_w = min(180, text_max_w // 2)
    draw.rectangle([text_x, line_y, text_x + line_w, line_y + 2], fill=(*accent_rgb, 200))

    # ── 14. Stats (scrobbles, loved) + barra de progreso ────────────────────
    stats_y = line_y + 14
    stats_parts = []
    if style.show_scrobble_count and artist_plays:
        stats_parts.append(f"♫ {artist_plays:,} scrobbles")
    if style.show_loved and loved:
        stats_parts.append("❤  Loved")
    if stats_parts:
        sx = _aligned_x("  ·  ".join(stats_parts), font_small, text_x, text_max_w)
        draw.text((sx, stats_y), "  ·  ".join(stats_parts), font=font_small, fill=(*accent_rgb, 180))

    # Barra de progreso decorativa
    if getattr(style, "show_progress_fake", False):
        import random as _rand
        bar_y = stats_y + 22
        bar_w = min(text_max_w, 220)
        prog = _rand.uniform(0.15, 0.85)  # posición aleatoria decorativa
        draw.rounded_rectangle([text_x, bar_y, text_x + bar_w, bar_y + 3], radius=2, fill=(*accent_rgb, 40))
        draw.rounded_rectangle([text_x, bar_y, text_x + int(bar_w * prog), bar_y + 3], radius=2, fill=(*accent_rgb, 200))
        # Tiempo fake
        total_s = _rand.randint(150, 300)
        curr_s  = int(total_s * prog)
        t_curr  = f"{curr_s//60}:{curr_s%60:02d}"
        t_total = f"{total_s//60}:{total_s%60:02d}"
        draw.text((text_x, bar_y + 6), t_curr, font=font_small, fill=(*hex_to_rgb(style.text_secondary), 140))
        bbox_total = draw.textbbox((0,0), t_total, font=font_small)
        draw.text((text_x + bar_w - (bbox_total[2]-bbox_total[0]), bar_y + 6), t_total, font=font_small, fill=(*hex_to_rgb(style.text_secondary), 140))

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

    # ── 16. Efectos extra ────────────────────────────────────────────────────
    # Glitch RGB
    if getattr(style, "glitch", False):
        r, g, b, a = canvas.split()
        shift = 4
        r = r.transform(r.size, Image.AFFINE, (1, 0, shift, 0, 1, 0))
        b = b.transform(b.size, Image.AFFINE, (1, 0, -shift, 0, 1, 0))
        canvas = Image.merge("RGBA", (r, g, b, a))

    # Scanlines CRT
    if getattr(style, "scanlines", False):
        scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scan)
        for sy in range(0, H, 4):
            sd.line([(0, sy), (W, sy)], fill=(0, 0, 0, 55))
        canvas = Image.alpha_composite(canvas, scan)

    # Monocromático
    if getattr(style, "monochrome", False):
        mono_base = hex_to_rgb(getattr(style, "monochrome_color", "#ffffff"))
        gray = canvas.convert("L")
        colored = Image.merge("RGBA", [
            gray.point(lambda p: int(p * mono_base[0] / 255)),
            gray.point(lambda p: int(p * mono_base[1] / 255)),
            gray.point(lambda p: int(p * mono_base[2] / 255)),
            canvas.split()[3],
        ])
        canvas = colored

    # Borde de la tarjeta (acento sutil)
    border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_layer)
    bd.rounded_rectangle(
        [0, 0, W-1, H-1],
        radius=style.card_rounded,
        outline=(*accent_rgb, 60),
        width=1,
    )
    canvas = Image.alpha_composite(canvas, border_layer)

    # Glow exterior de la tarjeta
    if getattr(style, "card_glow", False):
        glow = Image.new("RGBA", (W + 40, H + 40), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rounded_rectangle([20, 20, W+20, H+20], radius=style.card_rounded+10, fill=(*accent_rgb, 60))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=15))
        composite = Image.new("RGBA", (W + 40, H + 40), (0, 0, 0, 0))
        composite.paste(glow, (0, 0))
        composite.paste(canvas, (20, 20), mask=canvas.split()[3])
        canvas = composite.crop((20, 20, W+20, H+20))

    # Sombra exterior de la tarjeta
    if getattr(style, "card_shadow", False):
        shadow = Image.new("RGBA", (W + 30, H + 30), (0, 0, 0, 0))
        sdd = ImageDraw.Draw(shadow)
        sdd.rounded_rectangle([15, 18, W+15, H+18], radius=style.card_rounded, fill=(0, 0, 0, 120))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
        composite = Image.new("RGBA", (W + 30, H + 30), (0, 0, 0, 0))
        composite.paste(shadow, (0, 0))
        composite.paste(canvas, (15, 12), mask=canvas.split()[3])
        canvas = composite.crop((15, 12, W+15, H+12))

    # ── 17. Aplicar esquinas redondeadas a toda la tarjeta ────────────────────
    if style.card_rounded > 0:
        mask = rounded_rectangle_mask((W, H), style.card_rounded)
        final = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        final.paste(canvas, (0, 0), mask=mask)
    else:
        final = canvas

    # canvas_text_only: texto, stats, avatar, etc. sobre fondo transparente
    # Permite reemplazar el fondo frame a frame en el loop animado.
    # Usando ImageChops de Pillow puro (sin numpy)
    if animated:
        from PIL import ImageChops
        static_bg_for_diff = _build_bg_frame()
        if style.overlay_alpha > 0:
            static_bg_for_diff = Image.alpha_composite(static_bg_for_diff, overlay_layer)

        # Diferencia entre final y el fondo estático
        diff = ImageChops.difference(
            final.convert("RGB"),
            static_bg_for_diff.convert("RGB")
        )
        # Convertir diff a escala de grises — píxeles iguales al fondo = negro (0)
        diff_gray = diff.convert("L")
        # Threshold: si diff < 12 → transparente, si no → opaco
        threshold = diff_gray.point(lambda p: 0 if p < 12 else 255)
        # Aplicar como alpha mask al final
        canvas_text_only = final.copy()
        canvas_text_only.putalpha(threshold)

    # ── 18. Exportar ──────────────────────────────────────────────────────────
    # Si es animado: renderizar un frame por cada frame del GIF
    if animated:
        rendered_frames = []
        durations = []

        # Pre-computar todos los fondos en paralelo (evita recalcular blur por frame)
        precomputed_bgs = []
        for _af, _bf in zip(art_frames, bg_frames):
            _art_f, _ = _af
            _bg_f, _  = _bf
            if style.bg_type == "blur_art" and _art_f is not None:
                precomputed_bgs.append(_build_bg_frame(_art_f))
            elif style.bg_type == "custom_image" and bg_animated and _bg_f is not None:
                precomputed_bgs.append(_build_bg_frame(_bg_f))
            else:
                precomputed_bgs.append(_build_bg_frame())

        for i, ((art_frame_img, art_dur), (bg_frame_img, bg_dur)) in enumerate(zip(art_frames, bg_frames)):
            frame_duration = art_dur or bg_dur or 80

            # Reconstruir el fondo animado para este frame (bg pre-computado)
            if (style.bg_type == "blur_art" and art_frame_img is not None) or                (style.bg_type == "custom_image" and bg_animated and bg_frame_img is not None):
                base = precomputed_bgs[i].copy()
                if style.overlay_alpha > 0:
                    base = Image.alpha_composite(base, overlay_layer)
                base = Image.alpha_composite(base, canvas_text_only)
                frame_canvas = base
            else:
                frame_canvas = final.copy()

            if art_frame_img is None:
                rendered_frames.append(frame_canvas)
                durations.append(frame_duration)
                continue

            art_frame_rgba = _fill_crop(art_frame_img.convert("RGBA"), _art_size, _art_size)

            # Sombra
            if style.art_shadow:
                shadow_layer = Image.new("RGBA", (W, H), (0,0,0,0))
                sd = ImageDraw.Draw(shadow_layer)
                sr = [art_x+6, art_y+6, art_x+_art_size+6, art_y+_art_size+6]
                sd.rounded_rectangle(sr, radius=style.art_rounded+4, fill=(0,0,0,100))
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=12))
                frame_canvas = Image.alpha_composite(frame_canvas, shadow_layer)

            # Pegar frame del art
            frame_canvas = paste_rounded(frame_canvas, art_frame_rgba, (art_x, art_y), style.art_rounded)

            # Aplicar esquinas redondeadas a la tarjeta
            if style.card_rounded > 0:
                card_mask = rounded_rectangle_mask((W, H), style.card_rounded)
                frame_final = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                frame_final.paste(frame_canvas, (0, 0), mask=card_mask)
            else:
                frame_final = frame_canvas

            rendered_frames.append(frame_final.convert("RGBA"))
            durations.append(frame_duration)

        def _quantize(img):
            return img.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=1)

        def _save_gif(frames, durs, scale=1.0):
            buf = io.BytesIO()
            w = int(W * scale)
            h = int(H * scale)
            resized = [f.resize((w, h), Image.LANCZOS) if scale < 1.0 else f for f in frames]
            q = [_quantize(f) for f in resized]
            q[0].save(buf, format="GIF", save_all=True, append_images=q[1:],
                      duration=durs, loop=0, optimize=True, disposal=2)
            return buf

        # Intentar con tamaño completo, luego reducir frames, luego reducir resolución
        output = _save_gif(rendered_frames, durations)
        size = output.tell()

        if size > 7 * 1024 * 1024:
            # Reducir a 1 de cada 2 frames
            step = 2
            rf = rendered_frames[::step]
            rd = [d * step for d in durations[::step]]
            output = _save_gif(rf, rd)
            size = output.tell()

        if size > 7 * 1024 * 1024:
            # Reducir a 1 de cada 3 frames
            step = 3
            rf = rendered_frames[::step]
            rd = [d * step for d in durations[::step]]
            output = _save_gif(rf, rd)
            size = output.tell()

        if size > 7 * 1024 * 1024:
            # Reducir resolución al 75%
            output = _save_gif(rendered_frames[::2], [d*2 for d in durations[::2]], scale=0.75)
            size = output.tell()

        if size > 7 * 1024 * 1024:
            # Reducir resolución al 50%
            output = _save_gif(rendered_frames[::3], [d*3 for d in durations[::3]], scale=0.5)

        output.seek(0)
        return output

    else:
        # Pegar el art estático normal
        if style.art_position != "hidden" and album_art:
            art_square = _fill_crop(album_art.convert("RGBA"), _art_size, _art_size)
            if style.art_shadow:
                shadow_layer = Image.new("RGBA", (W, H), (0,0,0,0))
                sd = ImageDraw.Draw(shadow_layer)
                sr = [art_x+6, art_y+6, art_x+_art_size+6, art_y+_art_size+6]
                sd.rounded_rectangle(sr, radius=style.art_rounded+4, fill=(0,0,0,100))
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=12))
                final = Image.alpha_composite(final, shadow_layer)
            final = paste_rounded(final, art_square, (art_x, art_y), style.art_rounded)

        output = io.BytesIO()
        # Guardar como PNG optimizado — RGB sin canal alpha es más liviano
        final_rgb = final.convert("RGB")
        final_rgb.save(output, format="PNG", compress_level=3, optimize=True)
        # Si pesa más de 7MB, reducir resolución a la mitad y reintentar
        if output.tell() > 7 * 1024 * 1024:
            output = io.BytesIO()
            w2, h2 = final_rgb.width // 2, final_rgb.height // 2  # should not happen at 900x280
            final_rgb.resize((w2, h2), Image.LANCZOS).save(output, format="PNG", compress_level=4)
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
