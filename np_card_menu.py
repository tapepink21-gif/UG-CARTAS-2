"""
np_card_menu.py — Menú interactivo para personalizar la tarjeta NowPlaying
===========================================================================
Agrega el comando .personalizar al bot con un menú de botones por categoría.

USO en bot_final.py:
    from np_card_menu import setup_personalizar
    setup_personalizar(bot)
"""

import discord
from discord.ext import commands
from discord.ui import View, Button, Select
import asyncio
from np_card import (
    CardStyle, load_card_style, save_card_style,
    generate_np_card, apply_template, TEMPLATE_PRESETS,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bool_emoji(val: bool) -> str:
    return "✅" if val else "❌"

def _style_summary(s: CardStyle) -> str:
    lines = [
        f"**Template:** `{s.template}`",
        f"**Modo:** `{s.card_mode}`",
        f"**Fondo:** `{s.bg_type}` blur=`{s.bg_blur}` brillo=`{int(s.bg_brightness*100)}%`",
        f"**Acento:** `{s.text_accent}` {'(auto)' if s.use_accent_from_art else ''}",
        f"**Fuente:** `{s.font_title}` título=`{s.font_size_title}px` body=`{s.font_size_body}px`",
        f"**Art:** `{s.art_shape}` pos=`{s.art_position}` size=`{s.art_size}px`",
        f"**Texto:** align=`{s.text_align}` upper={_bool_emoji(s.text_uppercase)} shadow={_bool_emoji(s.text_shadow)}",
        f"**Efectos:** vignette={_bool_emoji(s.vignette)} grain={_bool_emoji(s.grain)} glitch={_bool_emoji(s.glitch)} scanlines={_bool_emoji(s.scanlines)}",
        f"**Glow/sombra:** art={_bool_emoji(s.art_glow)} card={_bool_emoji(s.card_glow)} shadow={_bool_emoji(s.card_shadow)}",
        f"**Info:** album={_bool_emoji(s.show_album)} scrobbles={_bool_emoji(s.show_scrobble_count)} loved={_bool_emoji(s.show_loved)}",
        f"**Color:** mono={_bool_emoji(s.monochrome)} palette_auto={_bool_emoji(s.palette_from_art)}",
    ]
    return "\n".join(lines)

# ─── Vistas por categoría ─────────────────────────────────────────────────────

class MainMenuView(View):
    def __init__(self, user_id: int, style: CardStyle, get_lastfm, lastfm_get):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.get_lastfm = get_lastfm
        self.lastfm_get = lastfm_get

    async def _refresh(self, interaction: discord.Interaction):
        embed = _main_embed(self.style)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎨 Colores", style=discord.ButtonStyle.secondary, row=0)
    async def cat_colors(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = ColorsView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("🎨 Colores", self.style), view=view)

    @discord.ui.button(label="🖼️ Fondo", style=discord.ButtonStyle.secondary, row=0)
    async def cat_bg(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = BackgroundView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("🖼️ Fondo", self.style), view=view)

    @discord.ui.button(label="🅰️ Texto", style=discord.ButtonStyle.secondary, row=0)
    async def cat_text(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = TextStyleView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=view)

    @discord.ui.button(label="💿 Album Art", style=discord.ButtonStyle.secondary, row=1)
    async def cat_art(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = ArtView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=view)

    @discord.ui.button(label="✨ Efectos", style=discord.ButtonStyle.secondary, row=1)
    async def cat_effects(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = EffectsView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("✨ Efectos", self.style), view=view)

    @discord.ui.button(label="📋 Layout", style=discord.ButtonStyle.secondary, row=1)
    async def cat_layout(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = LayoutView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("📋 Layout", self.style), view=view)

    @discord.ui.button(label="🎭 Template", style=discord.ButtonStyle.primary, row=2)
    async def cat_template(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        view = TemplateView(self.user_id, self.style, self)
        await interaction.response.edit_message(embed=_category_embed("🎭 Template", self.style), view=view)

    @discord.ui.button(label="👁️ Preview", style=discord.ButtonStyle.success, row=2)
    async def preview(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        await interaction.response.defer()
        await _send_preview(interaction, self.style, self.get_lastfm, self.lastfm_get)

    @discord.ui.button(label="🔄 Reset", style=discord.ButtonStyle.danger, row=2)
    async def reset(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        self.style = CardStyle()
        save_card_style(self.user_id, self.style)
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self)

    @discord.ui.button(label="💾 Guardar y cerrar", style=discord.ButtonStyle.success, row=3)
    async def save_close(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Este menú no es tuyo.", ephemeral=True)
        save_card_style(self.user_id, self.style)
        await interaction.response.defer()
        await _send_preview(interaction, self.style, self.get_lastfm, self.lastfm_get, closing=True)
        self.stop()


# ─── Categoría: Colores ───────────────────────────────────────────────────────

class ColorsView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        # Dropdown de acento
        self.add_item(AccentSelect(style))

    @discord.ui.button(label="Acento auto 🎨", style=discord.ButtonStyle.secondary, row=1)
    async def accent_auto(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.use_accent_from_art = not self.style.use_accent_from_art
        save_card_style(self.user_id, self.style)
        button.label = f"Acento auto {'✅' if self.style.use_accent_from_art else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("🎨 Colores", self.style), view=self)

    @discord.ui.button(label="Paleta del art 🖌️", style=discord.ButtonStyle.secondary, row=1)
    async def palette_auto(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.palette_from_art = not self.style.palette_from_art
        save_card_style(self.user_id, self.style)
        button.label = f"Paleta del art {'✅' if self.style.palette_from_art else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("🎨 Colores", self.style), view=self)

    @discord.ui.button(label="Monocromático", style=discord.ButtonStyle.secondary, row=1)
    async def monochrome_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.monochrome = not self.style.monochrome
        save_card_style(self.user_id, self.style)
        button.label = f"Monocromático {'✅' if self.style.monochrome else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("🎨 Colores", self.style), view=self)

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)


class AccentSelect(Select):
    PRESETS = {
        "Rojo 🔴": "#ff3040",
        "Azul 💙": "#3b82f6",
        "Verde 💚": "#22c55e",
        "Morado 💜": "#a855f7",
        "Naranja 🟠": "#f97316",
        "Rosa 🩷": "#ec4899",
        "Cyan 🩵": "#06b6d4",
        "Amarillo 💛": "#eab308",
        "Blanco ⬜": "#ffffff",
    }
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=k, value=v) for k, v in self.PRESETS.items()]
        super().__init__(placeholder="Color de acento...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.style.text_accent = self.values[0]
        self.style.use_accent_from_art = False
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🎨 Colores", self.style), view=self.view)


# ─── Categoría: Fondo ─────────────────────────────────────────────────────────

class BackgroundView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        self.add_item(BgTypeSelect(style))
        self.add_item(BgBlurSelect(style))
        self.add_item(BgBrightnessSelect(style))

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)

class BgTypeSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label="Blur del cover", value="blur_art", emoji="🌫️"),
            discord.SelectOption(label="Color sólido oscuro", value="solid_dark", emoji="⬛"),
            discord.SelectOption(label="Gradiente azul-morado", value="grad_blue", emoji="🟣"),
            discord.SelectOption(label="Gradiente rojo-naranja", value="grad_red", emoji="🔴"),
            discord.SelectOption(label="Gradiente verde-cyan", value="grad_green", emoji="🟢"),
        ]
        super().__init__(placeholder="Tipo de fondo...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]
        if v == "blur_art":
            self.style.bg_type = "blur_art"
        elif v == "solid_dark":
            self.style.bg_type = "solid"
            self.style.bg_color = "#0d0d0d"
        elif v == "grad_blue":
            self.style.bg_type = "gradient"
            self.style.bg_color = "#0f0c29"
            self.style.bg_color2 = "#302b63"
        elif v == "grad_red":
            self.style.bg_type = "gradient"
            self.style.bg_color = "#200122"
            self.style.bg_color2 = "#cc2020"
        elif v == "grad_green":
            self.style.bg_type = "gradient"
            self.style.bg_color = "#0f2027"
            self.style.bg_color2 = "#2c7873"
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🖼️ Fondo", self.style), view=self.view)

class BgBlurSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=f"Blur {v}", value=str(v)) for v in [0, 10, 20, 30, 40, 50, 60]]
        super().__init__(placeholder="Intensidad de blur...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.style.bg_blur = int(self.values[0])
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🖼️ Fondo", self.style), view=self.view)

class BgBrightnessSelect(Select):
    OPTIONS = [("Muy oscuro (10%)", "0.1"), ("Oscuro (25%)", "0.25"), ("Medio (45%)", "0.45"),
               ("Claro (65%)", "0.65"), ("Muy claro (85%)", "0.85"), ("Original (100%)", "1.0")]
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=l, value=v) for l, v in self.OPTIONS]
        super().__init__(placeholder="Brillo del fondo...", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.style.bg_brightness = float(self.values[0])
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🖼️ Fondo", self.style), view=self.view)


# ─── Categoría: Texto ─────────────────────────────────────────────────────────

class TextStyleView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        self.add_item(FontSelect(style))
        self.add_item(FontSizeSelect(style))
        self.add_item(TextAlignSelect(style))

    @discord.ui.button(label="Sombra", style=discord.ButtonStyle.secondary, row=3)
    async def shadow_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.text_shadow = not self.style.text_shadow
        save_card_style(self.user_id, self.style)
        button.label = f"Sombra {'✅' if self.style.text_shadow else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=self)

    @discord.ui.button(label="Mayúsculas", style=discord.ButtonStyle.secondary, row=3)
    async def uppercase_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.text_uppercase = not self.style.text_uppercase
        save_card_style(self.user_id, self.style)
        button.label = f"Mayúsculas {'✅' if self.style.text_uppercase else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=self)

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)

class FontSelect(Select):
    FONTS = ["SpaceGrotesk", "Unbounded", "DM_Sans", "default"]
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=f, value=f) for f in self.FONTS]
        super().__init__(placeholder="Fuente...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.style.font_title = self.values[0]
        self.style.font_body = self.values[0]
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=self.view)

class FontSizeSelect(Select):
    OPTIONS = [("Título pequeño (28px)", "28"), ("Título normal (36px)", "36"),
               ("Título grande (44px)", "44"), ("Título muy grande (52px)", "52")]
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=l, value=v) for l, v in self.OPTIONS]
        super().__init__(placeholder="Tamaño de título...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.style.font_size_title = int(self.values[0])
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=self.view)

class TextAlignSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label="Izquierda", value="left", emoji="◀️"),
            discord.SelectOption(label="Centro", value="center", emoji="🔲"),
            discord.SelectOption(label="Derecha", value="right", emoji="▶️"),
        ]
        super().__init__(placeholder="Alineación del texto...", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.style.text_align = self.values[0]
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("🅰️ Texto", self.style), view=self.view)


# ─── Categoría: Album Art ─────────────────────────────────────────────────────

class ArtView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        self.add_item(ArtPositionSelect(style))
        self.add_item(ArtShapeSelect(style))
        self.add_item(ArtSizeSelect(style))

    @discord.ui.button(label="Sombra del art", style=discord.ButtonStyle.secondary, row=3)
    async def shadow_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.art_shadow = not self.style.art_shadow
        save_card_style(self.user_id, self.style)
        button.label = f"Sombra del art {'✅' if self.style.art_shadow else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self)

    @discord.ui.button(label="Glow del art", style=discord.ButtonStyle.secondary, row=3)
    async def glow_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.art_glow = not self.style.art_glow
        save_card_style(self.user_id, self.style)
        button.label = f"Glow del art {'✅' if self.style.art_glow else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self)

    @discord.ui.button(label="Reflejo", style=discord.ButtonStyle.secondary, row=3)
    async def reflection_toggle(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.art_reflection = not self.style.art_reflection
        save_card_style(self.user_id, self.style)
        button.label = f"Reflejo {'✅' if self.style.art_reflection else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self)

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)

class ArtPositionSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label="Izquierda", value="left", emoji="◀️"),
            discord.SelectOption(label="Derecha", value="right", emoji="▶️"),
            discord.SelectOption(label="Centro", value="center", emoji="🔲"),
            discord.SelectOption(label="Oculto", value="hidden", emoji="🚫"),
        ]
        super().__init__(placeholder="Posición del art...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.style.art_position = self.values[0]
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self.view)

class ArtShapeSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label="Cuadrado", value="square", emoji="⬛"),
            discord.SelectOption(label="Círculo", value="circle", emoji="⚫"),
            discord.SelectOption(label="Hexágono", value="hexagon", emoji="🔷"),
        ]
        super().__init__(placeholder="Forma del art...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.style.art_shape = self.values[0]
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self.view)

class ArtSizeSelect(Select):
    OPTIONS = [("Pequeño (130px)", "130"), ("Normal (170px)", "170"),
               ("Grande (200px)", "200"), ("Muy grande (230px)", "230")]
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=l, value=v) for l, v in self.OPTIONS]
        super().__init__(placeholder="Tamaño del art...", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.style.art_size = int(self.values[0])
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("💿 Album Art", self.style), view=self.view)


# ─── Categoría: Efectos ───────────────────────────────────────────────────────

class EffectsView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent

    async def _toggle(self, interaction, attr, label):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        setattr(self.style, attr, not getattr(self.style, attr))
        save_card_style(self.user_id, self.style)
        for child in self.children:
            if hasattr(child, "_attr") and child._attr == attr:
                child.label = f"{label} {'✅' if getattr(self.style, attr) else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("✨ Efectos", self.style), view=self)

    @discord.ui.button(label="Vignette ✅", style=discord.ButtonStyle.secondary, row=0)
    async def vignette_btn(self, interaction, button):
        button._attr = "vignette"
        await self._toggle(interaction, "vignette", "Vignette")

    @discord.ui.button(label="Grain ❌", style=discord.ButtonStyle.secondary, row=0)
    async def grain_btn(self, interaction, button):
        button._attr = "grain"
        await self._toggle(interaction, "grain", "Grain")

    @discord.ui.button(label="Glitch ❌", style=discord.ButtonStyle.secondary, row=0)
    async def glitch_btn(self, interaction, button):
        button._attr = "glitch"
        await self._toggle(interaction, "glitch", "Glitch")

    @discord.ui.button(label="Scanlines ❌", style=discord.ButtonStyle.secondary, row=1)
    async def scanlines_btn(self, interaction, button):
        button._attr = "scanlines"
        await self._toggle(interaction, "scanlines", "Scanlines")

    @discord.ui.button(label="Glow tarjeta ❌", style=discord.ButtonStyle.secondary, row=1)
    async def card_glow_btn(self, interaction, button):
        button._attr = "card_glow"
        await self._toggle(interaction, "card_glow", "Glow tarjeta")

    @discord.ui.button(label="Sombra tarjeta ❌", style=discord.ButtonStyle.secondary, row=1)
    async def card_shadow_btn(self, interaction, button):
        button._attr = "card_shadow"
        await self._toggle(interaction, "card_shadow", "Sombra tarjeta")

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)


# ─── Categoría: Layout ────────────────────────────────────────────────────────

class LayoutView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        self.add_item(CardHeightSelect(style))
        self.add_item(BadgeStyleSelect(style))

    async def _toggle(self, interaction, attr, label):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        setattr(self.style, attr, not getattr(self.style, attr))
        save_card_style(self.user_id, self.style)
        for child in self.children:
            if hasattr(child, "_attr") and child._attr == attr:
                child.label = f"{label} {'✅' if getattr(self.style, attr) else '❌'}"
        await interaction.response.edit_message(embed=_category_embed("📋 Layout", self.style), view=self)

    @discord.ui.button(label="Mostrar álbum ✅", style=discord.ButtonStyle.secondary, row=2)
    async def album_btn(self, interaction, button):
        button._attr = "show_album"
        await self._toggle(interaction, "show_album", "Mostrar álbum")

    @discord.ui.button(label="Mostrar scrobbles ✅", style=discord.ButtonStyle.secondary, row=2)
    async def scrobbles_btn(self, interaction, button):
        button._attr = "show_scrobble_count"
        await self._toggle(interaction, "show_scrobble_count", "Mostrar scrobbles")

    @discord.ui.button(label="Mostrar loved ✅", style=discord.ButtonStyle.secondary, row=2)
    async def loved_btn(self, interaction, button):
        button._attr = "show_loved"
        await self._toggle(interaction, "show_loved", "Mostrar loved")

    @discord.ui.button(label="Barra progreso ❌", style=discord.ButtonStyle.secondary, row=3)
    async def progress_btn(self, interaction, button):
        button._attr = "show_progress_fake"
        await self._toggle(interaction, "show_progress_fake", "Barra progreso")

    @discord.ui.button(label="Modo embed ❌", style=discord.ButtonStyle.secondary, row=3)
    async def mode_btn(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.style.card_mode = "embed" if self.style.card_mode == "imagen" else "imagen"
        save_card_style(self.user_id, self.style)
        button.label = f"Modo {'embed ✅' if self.style.card_mode == 'embed' else 'imagen ✅'}"
        await interaction.response.edit_message(embed=_category_embed("📋 Layout", self.style), view=self)

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=4)
    async def back(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)

class CardHeightSelect(Select):
    OPTIONS = [("Compacta (220px)", "220"), ("Normal (280px)", "280"),
               ("Alta (340px)", "340"), ("Muy alta (400px)", "400")]
    def __init__(self, style):
        self.style = style
        options = [discord.SelectOption(label=l, value=v) for l, v in self.OPTIONS]
        super().__init__(placeholder="Altura de la tarjeta...", options=options, row=0)

    async def callback(self, interaction):
        self.style.height = int(self.values[0])
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("📋 Layout", self.style), view=self.view)

class BadgeStyleSelect(Select):
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label="Default", value="default"),
            discord.SelectOption(label="Pill (redondeado)", value="pill"),
            discord.SelectOption(label="Punto animado", value="dot"),
            discord.SelectOption(label="Sin badge", value="none"),
        ]
        super().__init__(placeholder="Estilo del badge NP...", options=options, row=1)

    async def callback(self, interaction):
        self.style.np_badge_style = self.values[0]
        save_card_style(interaction.user.id, self.style)
        await interaction.response.edit_message(embed=_category_embed("📋 Layout", self.style), view=self.view)


# ─── Categoría: Template ──────────────────────────────────────────────────────

class TemplateView(View):
    def __init__(self, user_id, style, parent):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.style = style
        self.parent = parent
        self.add_item(TemplateSelect(style))

    @discord.ui.button(label="← Volver", style=discord.ButtonStyle.primary, row=1)
    async def back(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("No es tu menú.", ephemeral=True)
        self.parent.style = self.style
        await interaction.response.edit_message(embed=_main_embed(self.style), view=self.parent)

class TemplateSelect(Select):
    DESCRIPTIONS = {
        "default": "Blur del art, estilo balanceado",
        "minimal": "Fondo negro, sin efectos",
        "blur": "Blur intenso con overlay",
        "retro": "Gradiente oscuro, fuente Unbounded",
        "glass": "Efecto vidrio esmerilado",
        "cassette": "Estilo cassette retro",
    }
    def __init__(self, style):
        self.style = style
        options = [
            discord.SelectOption(label=k, description=v, value=k)
            for k, v in self.DESCRIPTIONS.items()
        ]
        super().__init__(placeholder="Elige un template...", options=options, row=0)

    async def callback(self, interaction):
        self.style = apply_template(self.style, self.values[0])
        save_card_style(interaction.user.id, self.style)
        self.view.style = self.style
        await interaction.response.edit_message(
            embed=_category_embed("🎭 Template", self.style),
            view=self.view
        )


# ─── Embeds de ayuda ──────────────────────────────────────────────────────────

def _main_embed(style: CardStyle) -> discord.Embed:
    e = discord.Embed(
        title="🎨 Personalizar tarjeta NowPlaying",
        description=_style_summary(style),
        color=0x2b2d31,
    )
    e.set_footer(text="Los cambios se guardan automáticamente • Timeout: 2 min")
    return e

def _category_embed(title: str, style: CardStyle) -> discord.Embed:
    descriptions = {
        "🎨 Colores": (
            f"**Acento actual:** `{style.text_accent}`\n"
            f"**Auto del art:** {_bool_emoji(style.use_accent_from_art)}\n"
            f"**Paleta automática:** {_bool_emoji(style.palette_from_art)}\n"
            f"**Monocromático:** {_bool_emoji(style.monochrome)}"
        ),
        "🖼️ Fondo": (
            f"**Tipo:** `{style.bg_type}`\n"
            f"**Blur:** `{style.bg_blur}`\n"
            f"**Brillo:** `{int(style.bg_brightness * 100)}%`\n"
            f"**Imagen personalizada:** {'✅' if style.bg_image_url else '❌'}"
        ),
        "🅰️ Texto": (
            f"**Fuente:** `{style.font_title}`\n"
            f"**Tamaño título:** `{style.font_size_title}px`\n"
            f"**Alineación:** `{style.text_align}`\n"
            f"**Mayúsculas:** {_bool_emoji(style.text_uppercase)}\n"
            f"**Sombra:** {_bool_emoji(style.text_shadow)}"
        ),
        "💿 Album Art": (
            f"**Posición:** `{style.art_position}`\n"
            f"**Forma:** `{style.art_shape}`\n"
            f"**Tamaño:** `{style.art_size}px`\n"
            f"**Sombra:** {_bool_emoji(style.art_shadow)}\n"
            f"**Glow:** {_bool_emoji(style.art_glow)}\n"
            f"**Reflejo:** {_bool_emoji(style.art_reflection)}"
        ),
        "✨ Efectos": (
            f"**Vignette:** {_bool_emoji(style.vignette)}\n"
            f"**Grain:** {_bool_emoji(style.grain)}\n"
            f"**Glitch:** {_bool_emoji(style.glitch)}\n"
            f"**Scanlines:** {_bool_emoji(style.scanlines)}\n"
            f"**Glow tarjeta:** {_bool_emoji(style.card_glow)}\n"
            f"**Sombra tarjeta:** {_bool_emoji(style.card_shadow)}"
        ),
        "📋 Layout": (
            f"**Altura:** `{style.height}px`\n"
            f"**Badge NP:** `{style.np_badge_style}`\n"
            f"**Mostrar álbum:** {_bool_emoji(style.show_album)}\n"
            f"**Scrobbles:** {_bool_emoji(style.show_scrobble_count)}\n"
            f"**Loved:** {_bool_emoji(style.show_loved)}\n"
            f"**Barra progreso:** {_bool_emoji(style.show_progress_fake)}\n"
            f"**Modo:** `{style.card_mode}`"
        ),
        "🎭 Template": (
            f"**Template actual:** `{style.template}`\n\n"
            "Elegir un template sobreescribe tu configuración actual con los valores del preset."
        ),
    }
    e = discord.Embed(title=title, description=descriptions.get(title, ""), color=0x5865f2)
    e.set_footer(text="← Volver para regresar al menú principal")
    return e


# ─── Preview helper ───────────────────────────────────────────────────────────

async def _send_preview(interaction: discord.Interaction, style: CardStyle, get_lastfm, lastfm_get, closing=False):
    import re
    username = get_lastfm(interaction.user.id)
    if not username:
        await interaction.followup.send("❌ Conecta tu Last.fm con `.fmset` para ver la preview.", ephemeral=True)
        return

    try:
        recent = await lastfm_get({"method": "user.getrecenttracks", "user": username, "limit": 1, "extended": 1})
        tracks = recent.get("recenttracks", {}).get("track", [])
        if not tracks:
            raise ValueError("sin tracks")
        track = tracks[0] if isinstance(tracks, list) else tracks
        _a = track.get("artist", {})
        artist = ((_a.get("name") or _a.get("#text") or "?") if isinstance(_a, dict) else str(_a)).strip()
        song   = track.get("name", "?")
        album  = track.get("album", {}).get("#text", "")
        image_url = next((i["#text"] for i in track.get("image", []) if i.get("size") == "extralarge" and i.get("#text")), None)
        if image_url:
            image_url = re.sub(r'/i/u/\d+x\d+/', '/i/u/', image_url)
        now_playing = track.get("@attr", {}).get("nowplaying") == "true"
        loved = track.get("loved") == "1"

        img_bytes = await generate_np_card(
            song=song, artist=artist, album=album,
            album_art_url=image_url or "",
            username=username,
            display_name=interaction.user.display_name,
            avatar_url=str(interaction.user.display_avatar.url),
            now_playing=now_playing, loved=loved,
            style=style,
        )
        ext = "png"
        header = img_bytes.read(6)
        img_bytes.seek(0)
        if header[:6] in (b"GIF87a", b"GIF89a"):
            ext = "gif"

        file = discord.File(fp=img_bytes, filename=f"preview.{ext}")
        msg = "✅ **Cambios guardados.** Así quedó tu tarjeta:" if closing else "👁️ Preview de tu tarjeta actual:"
        await interaction.followup.send(msg, file=file)
    except Exception as e:
        await interaction.followup.send(f"❌ No pude generar la preview: {e}", ephemeral=True)


# ─── Setup ────────────────────────────────────────────────────────────────────

def setup_personalizar(bot, get_lastfm_fn, lastfm_get_fn):
    """
    Registra el comando .personalizar en el bot.

    Parámetros:
        bot            — instancia del bot
        get_lastfm_fn  — función get_lastfm_user(user_id) -> str | None
        lastfm_get_fn  — función async lastfm_get(params) -> dict
    """

    @bot.command(name="personalizar", aliases=["customize", "cardmenu", "npmenu"])
    async def personalizar_cmd(ctx):
        """Abre el menú interactivo para personalizar tu tarjeta NowPlaying."""
        style = load_card_style(ctx.author.id)
        view = MainMenuView(ctx.author.id, style, get_lastfm_fn, lastfm_get_fn)
        embed = _main_embed(style)
        await ctx.reply(embed=embed, view=view, mention_author=False)
