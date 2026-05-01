Now create the utils & core files:
Action: file_editor create /app/jiro/utils/config.py --file-text "\"\"\"Brand & icon constants for Jiro.\"\"\"

BRAND_NAME   = \"Jiro\"
BRAND_FOOTER = \"Jiro • powered by NixAi\"

# Primary palette
COLOR_PRIMARY = 0x7C4DFF   # violet accent
COLOR_BASE    = 0x111214   # near-black base

COLORS = {
    \"default\": COLOR_BASE,
    \"primary\": COLOR_PRIMARY,
    \"info\":    COLOR_PRIMARY,
    \"mod\":     COLOR_PRIMARY,
    \"success\": 0x3BA55D,
    \"warn\":    0xFAA61A,
    \"warning\": 0xFAA61A,
    \"error\":   0xED4245,
    \"muted\":   0x747F8D,
}

# Compact unicode/emoji icons used across embeds
_ICONS = {
    \"ok\":      \"✅\",
    \"error\":   \"❌\",
    \"warn\":    \"⚠️\",
    \"info\":    \"ℹ️\",
    \"mod\":     \"🛡️\",
    \"ban\":     \"🔨\",
    \"kick\":    \"👢\",
    \"mute\":    \"🔇\",
    \"unmute\":  \"🔊\",
    \"lock\":    \"🔒\",
    \"unlock\":  \"🔓\",
    \"purge\":   \"🧹\",
    \"level\":   \"📈\",
    \"xp\":      \"✨\",
    \"ticket\":  \"🎫\",
    \"star\":    \"⭐\",
    \"gift\":    \"🎉\",
    \"tag\":     \"🏷️\",
    \"remind\":  \"⏰\",
    \"role\":    \"🎭\",
    \"user\":    \"👤\",
    \"server\":  \"🏠\",
    \"join\":    \"📥\",
    \"leave\":   \"📤\",
    \"edit\":    \"📝\",
    \"delete\":  \"🗑️\",
    \"voice\":   \"🔉\",
    \"afk\":     \"💤\",
    \"ai\":      \"🤖\",
    \"bug\":     \"🐛\",
    \"raid\":    \"🚨\",
}

def icon(name: str) -> str:
    return _ICONS.get(name, \"\")
"
Observation: Create successful: /app/jiro/utils/config.py # AI / language
        "ai":         "[AI]",
        "summary":    "[TLDR]",
        "roast":      "[ROAST]",
        "translate":  "[TL]",
        "compliment": "[GG]",
        "explain":    "[DOC]",
        "debate_for": "[FOR]",
        "debate_against": "[AGAINST]",
        "model":      "[MODEL]",
        "mention":    "[MENTION]",

        # Fun
        "joke":       "[JOKE]",
        "poll":       "[POLL]",
        "8ball":      "[8BALL]",
        "flip":       "[FLIP]",
        "rng":        "[RNG]",
        "ship":       "[SHIP]",
        "reverse":    "[REV]",
        "trivia":     "[QUIZ]",
        "choose":     "[PICK]",
        "avatar":     "[PFP]",

        # Server / member info
        "server":     "[SERVER]",
        "user":       "[USER]",
        "id":         "[ID]",
        "join":       "[JOIN]",
        "leave":      "[LEAVE]",
        "created":    "[MADE]",
        "joined":     "[JOINED]",
        "top_role":   "[TOP-ROLE]",
        "roles":      "[ROLES]",
        "members":    "[MEMBERS]",
        "channels":   "[CHANNELS]",
        "boosts":     "[BOOSTS]",
        "owner":      "[OWNER]",

        # Moderation
        "mod":        "[MOD]",
        "kick":       "[KICK]",
        "ban":        "[BAN]",
        "unban":      "[UNBAN]",
        "mute":       "[MUTE]",
        "unmute":     "[UNMUTE]",
        "purge":      "[PURGE]",
        "slow":       "[SLOW]",
        "lock":       "[LOCK]",
        "unlock":     "[UNLOCK]",
        "nick":       "[NICK]",
        "reason":     "[REASON]",
        "duration":   "[DURATION]",
        "target":     "[TARGET]",
        "moderator":  "[MOD]",

        # Warnings
        "warning":    "[WARN]",
        "warnings":   "[WARNS]",
        "clear":      "[CLEAR]",

        # Auto-mod
        "automod":    "[AUTO-MOD]",
        "spam":       "[SPAM]",
        "invite":     "[INV]",
        "link":       "[URL]",
        "badword":    "[WORD]",

        # Logs
        "log":        "[LOG]",
        "log_msg_del":"[MSG-DEL]",
        "log_msg_edit":"[MSG-EDIT]",
        "log_join":   "[JOIN]",
        "log_leave":  "[LEAVE]",
        "log_roles":  "[ROLES-CHANGED]",
        "log_nick":   "[NICK-CHANGED]",

        # Welcome
        "welcome":    "[WELCOME]",
        "autorole":   "[AUTO-ROLE]",

        # Roles
        "role":       "[ROLE]",
        "role_add":   "[ROLE+]",
        "role_remove":"[ROLE-]",
        "self_role":  "[IAM]",

        # Shared moderation
        "sharedmod":  "[SHARED]",
        "claim":      "[CLAIM]",
        "donate":     "[DONATE]",
        "open":       "[OPEN]",
        "track":      "[TRACK]",
        "donated":    "[DONATED]",
        "claimed":    "[CLAIMED]",

        # Misc
        "delete":     "[DEL]",
        "edit":       "[EDIT]",
        "check":      "[CHECK]",
        "time":       "[TIME]",
        "trash":      "[DEL]",
        "progress":   "[...]",
        "count":      "[#]",

        # AFK / Reports / Levels / Notes
        "afk":        "[AFK]",
        "report":     "[REPORT]",
        "level":      "[LVL]",
        "note":       "[NOTE]",
    }
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def icon(key: str) -> str:
    """Return the configured icon text for a given key."""
    return BOT_CONFIG["icons"].get(key, f"[{key.upper()}]")


def color(key: str) -> int:
    """Return the hex color int for a given color key."""
    return BOT_CONFIG.get(f"color_{key}", BOT_CONFIG["color_info"])


async def safe_defer(interaction: discord.Interaction, ephemeral: bool = False) -> bool:
    """
    Safely defer an interaction.
    Returns True if successful, False if the interaction already expired (10062).
    Use at the top of every slow slash command (AI, purge, etc.).

    Usage:
        if not await safe_defer(interaction):
            return
    """
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.errors.NotFound:
        return False
    except discord.errors.InteractionResponded:
        return True


async def safe_send(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed = None,
    content: str = None,
    ephemeral: bool = False,
):
    """
    Send a response safely, handling both deferred and non-deferred interactions.
    Falls back to followup if already responded.
    """
    kwargs: dict = {}
    if embed:
        kwargs["embed"] = embed
    if content:
        kwargs["content"] = content
    kwargs["ephemeral"] = ephemeral

    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except (discord.errors.NotFound, discord.errors.HTTPException):
        pass  # Interaction expired — silently drop
