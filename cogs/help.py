import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import embed
from utils.config import icon


# ── Category data (single source of truth used by both slash and prefix) ──────

CATEGORIES: dict[str, dict] = {
    "mod": {
        "title": f"{icon('mod')} Moderation Commands",
        "commands": [
            ("?kick @user [reason]",                    "Kick a member"),
            ("?ban @user [reason]",                     "Ban a member"),
            ("?unban <user_id> [reason]",               "Unban by user ID"),
            ("?softban @user [reason]",                 "Ban + instant unban to wipe message history"),
            ("?baninfo <user_id>",                      "Check if a user is currently banned"),
            ("?mute @user [duration] [reason]",         "Timeout — formats: 30s, 10m, 2h, 1d (default 10m)"),
            ("?unmute @user [reason]",                  "Remove a timeout"),
            ("?purge [amount]",                         "Bulk delete last N messages (default 100)"),
            ("?purge @user [amount]",                   "Delete messages from a specific user"),
            ("?purge banned",                           "Delete messages from all banned users"),
            ("?cleanup [amount]",                       "Delete bot messages from this channel (default 20)"),
            ("?slowmode [seconds]",                     "Set channel slowmode (0 to disable)"),
            ("?lock [reason]",                          "Lock the current channel"),
            ("?unlock",                                 "Unlock the current channel"),
            ("?nickname @user [new_name]",              "Change or reset a member's nickname"),
            ("?raid on",                                "Manually activate raid mode — locks all channels"),
            ("?raid off",                               "Deactivate raid mode and restore channels"),
            ("?raid status",                            "Show current anti-raid settings"),
            ("?raidconfig <key> <value>",               "Tune thresholds — keys: threshold, window, action, mention_limit, mention_mute_mins"),
        ],
    },
    "warn": {
        "title": f"{icon('warn')} Warning Commands",
        "commands": [
            ("?warn @user [reason]",                             "Issue a warning"),
            ("?warnings @user",                                  "View warnings for a user"),
            ("?clearwarnings @user",                             "Clear all warnings for a user"),
            ("?delwarning <warning_id>",                         "Delete one specific warning by ID"),
            ("?warnconfig <mute_at> <kick_at> <ban_at> [hours]","Set auto-escalation thresholds"),
        ],
    },
    "automod": {
        "title": f"{icon('automod')} Auto-Mod Commands",
        "commands": [
            ("?automod",                               "View current auto-mod settings"),
            ("?automod toggle",                        "Enable / disable auto-mod"),
            ("?automod invites",                       "Toggle Discord invite link blocking"),
            ("?automod links",                         "Toggle external link blocking"),
            ("?automod addbadword <word>",             "Add a banned word"),
            ("?automod removebadword <word>",          "Remove a banned word"),
            ("?automod listbadwords",                  "List all banned words"),
            ("?automod spamconfig <limit> <seconds>",  "Set spam detection thresholds"),
        ],
    },
    "logs": {
        "title": f"{icon('log')} Log Commands",
        "commands": [
            ("?setlogchannel [#channel]", "Set the mod-log channel (defaults to current)"),
            ("?modlogs [limit]",          "View recent mod actions (default 10)"),
            ("?clearlogs",                "Clear all stored mod logs for this server"),
        ],
    },
    "welcome": {
        "title": f"{icon('welcome')} Welcome & Leave Commands",
        "commands": [
            ("?setwelcome [#channel]",         "Set the welcome channel"),
            ("?setwelcomemsg <message>",       "Set welcome message — {user}, {username}, {server}, {count}"),
            ("?testwelcome",                   "Fire a test welcome message"),
            ("?togglewelcome",                 "Enable / disable welcome messages"),
            ("?setleave [#channel]",           "Set the leave / goodbye channel"),
            ("?setleavemsg <message>",         "Set leave message — {user}, {username}, {server}"),
            ("?testleave",                     "Fire a test leave message"),
            ("?toggleleave",                   "Enable / disable leave messages"),
            ("?setautorole <role>",            "Auto-assign a role when members join"),
            ("?clearautorole",                 "Remove the auto-role assignment"),
        ],
    },
    "roles": {
        "title": f"{icon('role')} Role Commands",
        "commands": [
            ("?addrole @user <role>",          "Add a role to a member"),
            ("?removerole @user <role>",       "Remove a role from a member"),
            ("?massrole <add|remove> <role>",  "Add / remove a role from all members"),
            ("?setautorole <role>",            "Set auto-role for new members"),
            ("?clearautorole",                 "Remove auto-role"),
            ("?iam <role>",                    "Self-assign a role (toggles)"),
            ("?iamnot <role>",                 "Remove a self-assigned role from yourself"),
            ("?addselfrole <role>",            "Make a role self-assignable (Admin)"),
            ("?removeselfrole <role>",         "Remove a role from the self-assignable list (Admin)"),
            ("?listselfroles",                 "List all self-assignable roles"),
            ("?roleinfo <role>",               "View role information"),
        ],
    },
    "fun": {
        "title": f"{icon('joke')} Fun Commands",
        "commands": [
            ("?joke",                       "Get a random joke"),
            ('?poll "question" opt1 opt2',  "Create a reaction poll (up to 10 options)"),
            ("?8ball <question>",            "Ask the magic 8-ball"),
            ("?coinflip",                   "Flip a coin"),
            ("?rng [min] [max]",            "Random number (default 1–100)"),
            ("?roll [XdY]",                 "Roll dice — e.g. 2d6, 1d20 (default 1d6)"),
            ("?mock <text>",                "Convert text to aLtErNaTiNg CaPs"),
            ("?serverinfo",                 "View server information"),
            ("?userinfo [@user]",           "View user information"),
            ("?avatar [@user]",             "Show a user's avatar"),
            ("?choose opt1 opt2 ...",       "Pick a random option"),
            ("?ship @user1 [@user2]",       "Calculate ship compatibility"),
            ("?reverse <text>",             "Reverse any text"),
            ("?trivia",                     "Answer a random trivia question"),
        ],
    },
    "games": {
        "title": "🎮 Party Game Commands",
        "commands": [
            ("/todlaunch",                    "Open a Truth or Dare lobby with a Join button"),
            ("/stod",                         "Start the game once enough players have joined (host only)"),
            ("/tod  or  ?tod",                "Get a single AI-generated Truth or Dare prompt"),
            ("/nr   or  ?nr",                 "AI Never Have I Ever — click 'I Have!' to reveal yourself"),
        ],
    },
    "ai": {
        "title": f"{icon('ai')} AI Commands (Groq)",
        "commands": [
            ("?ask <question>",               "Ask Jiro a question"),
            ("?summarize <text>",             "Summarize a block of text"),
            ("?roast @user",                  "Have Jiro roast a member (playfully)"),
            ("?translate <language> <text>",  "Translate text to any language"),
            ("?compliment @user",             "Give a member a heartfelt compliment"),
            ("?explain <topic>",              "Get a simple explanation of any topic"),
            ("?debate <for|against> <topic>", "Argue a side of a debate"),
            ("?aimodel",                      "Show the current AI model and status"),
            ("?aion",                         "Enable AI for this server (Admin)"),
            ("?aioff",                        "Disable AI for this server (Admin)"),
            ("?setmodel <model_id>",          "Set the Groq model for this server (Admin)"),
            ("?setprompt <prompt>",           "Set a custom AI system prompt (Admin)"),
            ("?clearprompt",                  "Reset prompt to default (Admin)"),
            ("@Jiro <message>",               "Mention Jiro anywhere for an AI reply"),
            ("!chatchannelset [#channel]",    "Set a channel where Jiro auto-replies to every message — no ping needed (Admin)"),
            ("!chatchannelclear",             "Remove the auto-reply chat channel (Admin)"),
        ],
    },
    "sharedmod": {
        "title": f"{icon('sharedmod')} Shared Moderation Commands",
        "commands": [
            ("?sharemod @user <action> [duration] [reason]",
             "Post a moderation with Claim / Donate / Leave Open buttons"),
            ("?modtrack [@mod]",
             "Show mod stats: actions done, claimed, donated, received"),
            ("?sharedlist [open|claimed|donated|all]",
             "List shared moderations by status (default: open)"),
            ("?setsharedchannel #channel",
             "Set the shared mod channel (Admin)"),
        ],
    },
    "afk": {
        "title": f"{icon('afk')} AFK & Reports",
        "commands": [
            ("?afk [reason]",              "Mark yourself as AFK with an optional reason. Auto-clears when you next speak."),
            ("?afklist",                   "List all currently AFK members in this server."),
            ("?report <message>",          "Submit a report — Jiro will triage it and DM you back."),
            ("?userreports",               "Jump to the report channel (Owner only)"),
            ("?userreports <keyword>",     "Search the last 100 report messages for a keyword (Owner only)"),
            ("?userreports clear",         "Delete the last 50 messages in the report channel (Owner only)"),
        ],
    },
    "levels": {
        "title": f"{icon('level')} Levels & XP",
        "commands": [
            ("?rank [@user]",              "Show your XP card or another member's."),
            ("?leaderboard",               "Top 10 XP members in this server."),
            ("?setxp @user <xp>",         "Manually set a member's XP (Admin)."),
            ("?resetxp @user",            "Reset a member's XP and level to zero (Admin)."),
        ],
    },
    "giveaways": {
        "title": "🎉 Giveaways",
        "commands": [
            ("?gstart <duration> <winners> <prize>", "Start a giveaway — e.g. !gstart 1h 1 Nitro Classic"),
            ("?gend <message_id>",                   "Force-end a giveaway early."),
            ("?greroll <message_id>",                "Reroll a winner for an ended giveaway."),
            ("?glist",                               "List all active giveaways in this server."),
        ],
    },
    "reminders": {
        "title": f"{icon('time')} Reminders",
        "commands": [
            ("?remind <duration> <message>", "Set a personal reminder — e.g. !remind 2h check the oven"),
            ("?reminders",                   "List your pending reminders."),
            ("?delreminder <id>",            "Cancel a reminder by its ID."),
        ],
    },
    "notes": {
        "title": f"{icon('note')} Staff Notes",
        "commands": [
            ("?note add @user <text>",      "Add a private staff note to a member."),
            ("?note list @user",            "View all notes for a member."),
            ("?note remove @user <id>",     "Delete a specific note by ID."),
            ("?note clear @user",           "Delete all notes for a member (Admin)."),
        ],
    },
}

# Aliases → canonical keys
ALIASES: dict[str, str] = {
    "moderation": "mod",
    "warning":    "warn",
    "warnings":   "warn",
    "log":        "logs",
    "auto":       "automod",
    "am":         "automod",
    "role":       "roles",
    "shared":     "sharedmod",
    "game":       "games",
    "tod":        "games",
    "nr":         "games",
    "party":      "games",
    "nhie":       "games",
    "afkreport":  "afk",
    "report":     "afk",
    "xp":         "levels",
    "level":      "levels",
    "lb":         "levels",
    "giveaway":   "giveaways",
    "gw":         "giveaways",
    "reminder":   "reminders",
    "remind":     "reminders",
    "note":       "notes",
    "raid":       "mod",
    "antiraid":   "mod",
}


def _build_main_embed() -> discord.Embed:
    e = embed(f"{icon('bot')} Jiro — Command List", color="mod")
    e.description = (
        "Use `?help <category>` or `/help category:<name>` for details.\n"
        "Both `?` and `!` prefixes work.\n"
        "Slash commands are available via `/`\n"
        "You can also **@mention Jiro** to get a direct AI response!"
    )
    e.add_field(name=f"{icon('mod')} Moderation",   value="`?help mod`",       inline=True)
    e.add_field(name=f"{icon('warn')} Warnings",    value="`?help warn`",      inline=True)
    e.add_field(name=f"{icon('automod')} Auto-Mod", value="`?help automod`",   inline=True)
    e.add_field(name=f"{icon('log')} Logs",         value="`?help logs`",      inline=True)
    e.add_field(name=f"{icon('welcome')} Welcome",  value="`?help welcome`",   inline=True)
    e.add_field(name=f"{icon('role')} Roles",       value="`?help roles`",     inline=True)
    e.add_field(name=f"{icon('joke')} Fun",         value="`?help fun`",       inline=True)
    e.add_field(name="🎮 Games",                    value="`?help games`",     inline=True)
    e.add_field(name=f"{icon('ai')} AI",            value="`?help ai`",        inline=True)
    e.add_field(name=f"{icon('sharedmod')} Shared", value="`?help sharedmod`", inline=True)
    e.add_field(name=f"{icon('afk')} AFK & Reports",value="`?help afk`",       inline=True)
    e.add_field(name=f"{icon('level')} Levels",     value="`?help levels`",    inline=True)
    e.add_field(name="🎉 Giveaways",                value="`?help giveaways`", inline=True)
    e.add_field(name=f"{icon('time')} Reminders",   value="`?help reminders`", inline=True)
    e.add_field(name=f"{icon('note')} Staff Notes", value="`?help notes`",     inline=True)
    e.set_footer(text="Tip: Most commands also work as /slash commands!")
    return e


def _build_category_embed(category: str) -> discord.Embed | None:
    resolved = ALIASES.get(category, category)
    cat = CATEGORIES.get(resolved)
    if not cat:
        return None
    e = embed(cat["title"], color="mod")
    for cmd, desc in cat["commands"]:
        e.add_field(name=f"`{cmd}`", value=desc, inline=False)
    e.set_footer(text="Arguments in [brackets] are optional. Arguments in <brackets> are required.")
    return e


class Help(commands.Cog):
    """Custom help menu."""

    def __init__(self, bot):
        self.bot = bot

    # ── Prefix: ?help  /  ?help <category> ───────────────────────────────────

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context, category: str = None):
        """Show all commands or a specific category.
        ?help  |  ?help <category>"""
        if category:
            await self._send_category(ctx, category.lower())
        else:
            await ctx.send(embed=_build_main_embed())

    # ── Slash: /help  /  /help category:<name> ───────────────────────────────

    @app_commands.command(name="help", description="Show Jiro's command list or a specific category")
    @app_commands.describe(category="Optional — jump straight to a category (e.g. fun, games, mod, ai)")
    async def help_slash(
        self,
        interaction: discord.Interaction,
        category: str = None,
    ):
        if category:
            cat_embed = _build_category_embed(category.lower().strip())
            if cat_embed:
                await interaction.response.send_message(embed=cat_embed)
            else:
                valid = ", ".join(f"`{k}`" for k in CATEGORIES)
                await interaction.response.send_message(
                    embed=embed(
                        f"{icon('error')} Unknown Category",
                        f"Valid categories: {valid}",
                        color="error"),
                    ephemeral=True)
        else:
            await interaction.response.send_message(embed=_build_main_embed())

    # ── Autocomplete for /help category ──────────────────────────────────────

    @help_slash.autocomplete("category")
    async def category_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        keys = list(CATEGORIES.keys())
        current = current.lower()
        matches = [k for k in keys if k.startswith(current)] or keys
        return [app_commands.Choice(name=k, value=k) for k in matches[:25]]

    # ── Shared helper for prefix ──────────────────────────────────────────────

    async def _send_category(self, ctx: commands.Context, category: str):
        cat_embed = _build_category_embed(category)
        if cat_embed:
            await ctx.send(embed=cat_embed)
        else:
            valid = ", ".join(f"`{k}`" for k in CATEGORIES)
            await ctx.send(embed=embed(
                f"{icon('error')} Unknown Category",
                f"Valid categories: {valid}\n**Usage:** `?help <category>`",
                color="error"))


async def setup(bot):
    await bot.add_cog(Help(bot))
