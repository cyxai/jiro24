"""
utils/embeds.py — Embed factory for 07Dipper / Jiro
All embeds share the same footer and color scheme from BOT_CONFIG.
"""

import discord
from utils.config import BOT_CONFIG, icon, color as cfg_color


def _base(e: discord.Embed) -> discord.Embed:
    """Apply shared footer and optional thumbnail to any embed."""
    e.set_footer(text=BOT_CONFIG["footer"])
    if BOT_CONFIG.get("thumbnail_url"):
        e.set_thumbnail(url=BOT_CONFIG["thumbnail_url"])
    return e


def embed(title: str = "", description: str = None, color: str = "info") -> discord.Embed:
    """
    General-purpose embed factory.

    color: "info" | "error" | "warn" | "success" | "mod" | "log"
    """
    e = discord.Embed(
        title=title,
        description=description,
        color=cfg_color(color),
    )
    return _base(e)


def mod_embed(
    action: str,
    target: discord.Member,
    mod: discord.Member,
    reason: str,
    extra_fields: dict = None,
    color: str = "mod",
) -> discord.Embed:
    """
    Standardised moderation action embed.
    Used by kick, ban, mute, warn, etc.
    """
    e = discord.Embed(
        title=f"{icon('mod')} {action}",
        color=cfg_color(color),
    )
    e.add_field(name=f"{icon('target')} Member",    value=f"{target.mention} (`{target.id}`)", inline=True)
    e.add_field(name=f"{icon('moderator')} Mod",    value=mod.mention,                          inline=True)
    e.add_field(name=f"{icon('reason')} Reason",    value=reason,                               inline=False)
    if extra_fields:
        for name, val in extra_fields.items():
            e.add_field(name=name, value=val, inline=True)
    e.set_thumbnail(url=target.display_avatar.url)
    return _base(e)
