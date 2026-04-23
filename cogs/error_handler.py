"""
cogs/error_handler.py — Global error handler for 07Dipper / Jiro
Load this cog FIRST so it catches errors in every other cog.
Every failure shows the user exactly what went wrong and what to do.
"""

import discord
from discord import app_commands
from discord.ext import commands
import traceback

from utils.embeds import embed
from utils.config import icon, safe_send


# ── Usage hints injected into relevant errors ─────────────────────────────────
USAGE_HINTS: dict[str, str] = {
    # Moderation
    "kick":            "?kick @user [reason]",
    "ban":             "?ban @user [reason]",
    "unban":           "?unban <user_id> [reason]",
    "mute":            "?mute @user [duration] [reason]  — e.g. 30s / 10m / 2h / 1d",
    "unmute":          "?unmute @user [reason]",
    "purge":           "?purge [amount]  |  ?purge @user  |  ?purge banned",
    "slowmode":        "?slowmode [seconds]  (0 to disable)",
    "lock":            "?lock [reason]",
    "nickname":        "?nickname @user [new_name]",
    "softban":         "?softban @user [reason]",
    "baninfo":         "?baninfo <user_id>",
    "cleanup":         "?cleanup [amount]",
    # Warnings
    "warn":            "?warn @user [reason]",
    "warnings":        "?warnings @user",
    "clearwarnings":   "?clearwarnings @user",
    "delwarning":      "?delwarning <warning_id>",
    "warnconfig":      "?warnconfig <mute_at> <kick_at> <ban_at> [mute_hours]",
    # Roles
    "addrole":         "?addrole @user <role>",
    "removerole":      "?removerole @user <role>",
    "iam":             "?iam <role>  — role must be on the self-assignable list",
    "iamnot":          "?iamnot <role>",
    "addselfrole":     "?addselfrole <role>",
    "removeselfrole":  "?removeselfrole <role>",
    "massrole":        "?massrole <add|remove> <role>",
    "setautorole":     "?setautorole <role>",
    # Fun
    "poll":            '?poll "question" option1 option2 [option3 ...]',
    "8ball":           "?8ball <your question>",
    "choose":          "?choose option1 option2 option3 ...",
    "ship":            "?ship @user1 [@user2]",
    "roll":            "?roll [XdY]  — e.g. 1d6, 2d20",
    "rng":             "?rng [min] [max]",
    "reverse":         "?reverse <text>",
    "mock":            "?mock <text>",
    "avatar":          "?avatar [@user]",
    "serverinfo":      "?serverinfo",
    "userinfo":        "?userinfo [@user]",
    # Games
    "todlaunch":       "/todlaunch  — opens a Truth or Dare lobby",
    "stod":            "/stod  — starts the game (host only, min 2 players)",
    "tod":             "?tod  or  /tod  — single AI Truth or Dare prompt",
    "nr":              "?nr  or  /nr  — AI Never Have I Ever statement",
    "nhie":            "?nr  or  /nr  — AI Never Have I Ever statement",
    "neverhaveiever":  "?nr  or  /nr",
    "truthordare":     "?tod  or  /todlaunch for a full game",
    # AI
    "ask":             "?ask <question>",
    "summarize":       "?summarize <text>",
    "translate":       "?translate <language> <text>",
    "roast":           "?roast @user",
    "compliment":      "?compliment @user",
    "explain":         "?explain <topic>",
    "debate":          "?debate <for|against> <topic>",
    "setmodel":        "?setmodel <groq_model_id>",
    "setprompt":       "?setprompt <custom system prompt>",
    # Logs
    "setlogchannel":   "?setlogchannel [#channel]",
    "modlogs":         "?modlogs [limit]",
    # Welcome
    "setwelcome":      "?setwelcome [#channel]",
    "setwelcomemsg":   "?setwelcomemsg <message>  (use {user}, {server}, {count})",
    "setleave":        "?setleave [#channel]",
    "setleavemsg":     "?setleavemsg <message>  (use {user}, {username}, {server})",
    # Shared mod
    "sharemod":        "?sharemod @user <action> [duration] [reason]",
    "sharedlist":      "?sharedlist [open|claimed|donated|all]",
}


def _usage(ctx_or_name) -> str | None:
    """Return a formatted usage hint for a command if one exists."""
    name = ctx_or_name if isinstance(ctx_or_name, str) else getattr(ctx_or_name, "invoked_with", None)
    if name and name in USAGE_HINTS:
        return f"**Usage:** `{USAGE_HINTS[name]}`"
    return None


class ErrorHandler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error

    # ─────────────────────────────────────────────────────────────────────────
    # SLASH COMMAND ERRORS
    # ─────────────────────────────────────────────────────────────────────────

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        original = getattr(error, "original", error)

        # Expired interaction — nothing we can do
        if isinstance(original, discord.errors.NotFound) and original.code == 10062:
            cmd = interaction.command.name if interaction.command else "unknown"
            print(f"[WARN] Interaction expired for /{cmd} — user: {interaction.user}")
            return

        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            e = embed(f"{icon('error')} You're missing permissions",
                      f"You need: {missing}", color="error")
            return await safe_send(interaction, embed=e, ephemeral=True)

        if isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            e = embed(f"{icon('error')} I'm missing permissions",
                      f"I need: {missing}\nPlease ask an admin to fix my role.", color="error")
            return await safe_send(interaction, embed=e, ephemeral=True)

        if isinstance(error, app_commands.CommandOnCooldown):
            e = embed(f"{icon('warn')} Slow down!",
                      f"This command is on cooldown. Try again in `{error.retry_after:.1f}s`.", color="warn")
            return await safe_send(interaction, embed=e, ephemeral=True)

        if isinstance(error, app_commands.CheckFailure):
            e = embed(f"{icon('error')} Check Failed",
                      "You don't meet the requirements to use this command.", color="error")
            return await safe_send(interaction, embed=e, ephemeral=True)

        if isinstance(error, app_commands.NoPrivateMessage):
            e = embed(f"{icon('error')} Server Only",
                      "This command can only be used inside a server.", color="error")
            return await safe_send(interaction, embed=e, ephemeral=True)

        if isinstance(error, app_commands.TransformerError):
            e = embed(f"{icon('error')} Invalid Argument",
                      f"`{error.value}` couldn't be converted to `{error.type.__name__}`.", color="error")
            return await safe_send(interaction, embed=e, ephemeral=True)

        # Catch-all
        cmd = interaction.command.name if interaction.command else "unknown"
        hint = _usage(cmd)
        desc = f"`{type(original).__name__}: {str(original)[:300]}`"
        if hint:
            desc += f"\n{hint}"
        e = embed(f"{icon('error')} Something went wrong", desc, color="error")
        await safe_send(interaction, embed=e, ephemeral=True)
        print(f"[ERROR] Unhandled slash error for /{cmd}")
        traceback.print_exception(type(original), original, original.__traceback__)

    # ─────────────────────────────────────────────────────────────────────────
    # PREFIX COMMAND ERRORS
    # ─────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        # Let cog-local handlers take priority
        if getattr(ctx.command, "on_error", None):
            return

        hint = _usage(ctx)

        # ── Silently ignore unknown commands ───────────────────────────────
        if isinstance(error, commands.CommandNotFound):
            return

        # ── Missing required argument ──────────────────────────────────────
        if isinstance(error, commands.MissingRequiredArgument):
            desc = f"Missing required argument: `{error.param.name}`"
            if hint:
                desc += f"\n{hint}"
            return await ctx.send(embed=embed(
                f"{icon('error')} Missing Argument", desc, color="error"))

        # ── Too many arguments ─────────────────────────────────────────────
        if isinstance(error, commands.TooManyArguments):
            desc = "You provided too many arguments for this command."
            if hint:
                desc += f"\n{hint}"
            return await ctx.send(embed=embed(
                f"{icon('error')} Too Many Arguments", desc, color="error"))

        # ── Member / user not found ────────────────────────────────────────
        if isinstance(error, commands.MemberNotFound):
            return await ctx.send(embed=embed(
                f"{icon('error')} Member Not Found",
                f"Could not find member `{error.argument}`. "
                "Make sure they're in this server and try mentioning them.", color="error"))

        if isinstance(error, commands.UserNotFound):
            return await ctx.send(embed=embed(
                f"{icon('error')} User Not Found",
                f"No user found for `{error.argument}`. "
                "Try using their numeric user ID instead.", color="error"))

        # ── Role / channel not found ───────────────────────────────────────
        if isinstance(error, commands.RoleNotFound):
            return await ctx.send(embed=embed(
                f"{icon('error')} Role Not Found",
                f"No role found for `{error.argument}`. "
                "Mention the role or use its exact name.", color="error"))

        if isinstance(error, commands.ChannelNotFound):
            return await ctx.send(embed=embed(
                f"{icon('error')} Channel Not Found",
                f"No channel found for `{error.argument}`. "
                "Mention the channel or use its exact name.", color="error"))

        # ── Bad argument / conversion failed ──────────────────────────────
        if isinstance(error, commands.BadArgument):
            desc = str(error)
            if hint:
                desc += f"\n{hint}"
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Argument", desc, color="error"))

        if isinstance(error, commands.BadUnionArgument):
            desc = f"Could not convert `{error.param.name}` to any of the expected types."
            if hint:
                desc += f"\n{hint}"
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Argument", desc, color="error"))

        # ── Permissions ────────────────────────────────────────────────────
        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            return await ctx.send(embed=embed(
                f"{icon('error')} Missing Permissions",
                f"You need: {missing}", color="error"))

        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            return await ctx.send(embed=embed(
                f"{icon('error')} I'm Missing Permissions",
                f"I need: {missing}\nPlease update my role permissions.", color="error"))

        if isinstance(error, commands.NotOwner):
            return await ctx.send(embed=embed(
                f"{icon('error')} Owner Only",
                "This command can only be used by the bot owner.", color="error"))

        if isinstance(error, commands.CheckFailure):
            return await ctx.send(embed=embed(
                f"{icon('error')} Check Failed",
                "You don't meet the requirements to run this command.", color="error"))

        # ── Cooldown ───────────────────────────────────────────────────────
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.send(embed=embed(
                f"{icon('warn')} Slow down!",
                f"Try again in `{error.retry_after:.1f}s`.", color="warn"))

        # ── DMs / disabled ─────────────────────────────────────────────────
        if isinstance(error, commands.NoPrivateMessage):
            return await ctx.send(embed=embed(
                f"{icon('error')} Server Only",
                "This command can only be used inside a server.", color="error"))

        if isinstance(error, commands.DisabledCommand):
            return await ctx.send(embed=embed(
                f"{icon('error')} Command Disabled",
                "This command is currently disabled.", color="error"))

        # ── Invocation error — unwrap and surface the real cause ──────────
        if isinstance(error, commands.CommandInvokeError):
            original = error.original

            if isinstance(original, discord.Forbidden):
                return await ctx.send(embed=embed(
                    f"{icon('error')} Missing Permissions",
                    "I don't have permission to do that. "
                    "Check my role's permissions and channel overrides.", color="error"))

            if isinstance(original, discord.HTTPException):
                return await ctx.send(embed=embed(
                    f"{icon('error')} Discord Error",
                    f"Discord returned an error: `{original.status} — {original.text[:200]}`",
                    color="error"))

            desc = f"`{type(original).__name__}: {str(original)[:300]}`"
            if hint:
                desc += f"\n{hint}"
            await ctx.send(embed=embed(
                f"{icon('error')} Command Failed", desc, color="error"))
            print(f"[ERROR] CommandInvokeError in ?{ctx.command}")
            traceback.print_exception(type(original), original, original.__traceback__)
            return

        # ── Final catch-all ────────────────────────────────────────────────
        await ctx.send(embed=embed(
            f"{icon('error')} Unexpected Error",
            f"`{type(error).__name__}: {str(error)[:300]}`",
            color="error"))
        print(f"[ERROR] Unhandled error in ?{ctx.command}")
        traceback.print_exception(type(error), error, error.__traceback__)


async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorHandler(bot))
