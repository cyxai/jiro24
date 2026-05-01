
Action: file_editor create /app/jiro/utils/embeds.py --file-text "\"\"\"Standard Jiro embed factory.\"\"\"
from __future__ import annotations
from datetime import datetime, timezone
import discord
from .config import COLORS, BRAND_FOOTER, COLOR_PRIMARY


def embed(title: str | None = None,
          description: str | None = None,
          *,
          color: str | int = \"primary\",
          url: str | None = None,
          footer: str | None = BRAND_FOOTER,
          footer_icon: str | None = None,
          author: str | None = None,
          author_icon: str | None = None,
          thumbnail: str | None = None,
          image: str | None = None,
          timestamp: bool = True) -> discord.Embed:
    \"\"\"Build a Jiro-branded embed.\"\"\"
    if isinstance(color, str):
        col = COLORS.get(color, COLOR_PRIMARY)
    else:
        col = int(color)

    e = discord.Embed(
        title=title or discord.Embed.Empty if hasattr(discord.Embed, \"Empty\") else title,
        description=description,
        color=col,
        url=url,
    )
    if timestamp:
        e.timestamp = datetime.now(timezone.utc)
    if footer:
        e.set_footer(text=footer, icon_url=footer_icon)
    if author:
        e.set_author(name=author, icon_url=author_icon)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    if image:
        e.set_image(url=image)
    return e


def error_embed(message: str, *, title: str = \"❌ Error\") -> discord.Embed:
    return embed(title, message, color=\"error\")


def success_embed(message: str, *, title: str = \"✅ Success\") -> discord.Embed:
    return embed(title, message, color=\"success\")
"
Observation: Create successful: /app/jiro/utils/embeds.py_base(e)
