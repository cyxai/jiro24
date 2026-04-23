"""
cogs/games.py — Interactive party games for Jiro
  • /todlaunch   — Open a Truth or Dare lobby with a Join button
  • /stod        — Start the game (host only, min 2 players)
  • /tod  ?tod   — Single AI-generated Truth or Dare prompt
  • /nr   ?nr    — AI Never Have I Ever statement

Truth or Dare verification modes
  • Full Member  — bot is guild-installed; uses AI to judge responses (60 s window)
  • External App — bot is user-installed; just posts questions, no judgment
"""

import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import embed
from utils.config import icon, safe_defer, safe_send
import asyncio
import random
import logging

log = logging.getLogger(__name__)

# ── In-memory game registry ───────────────────────────────────────────────────
_tod_games: dict[int, "TodGame"] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Game State
# ─────────────────────────────────────────────────────────────────────────────

class TodGame:
    """Holds the full state of one Truth or Dare session per guild."""

    __slots__ = (
        "guild_id", "channel_id", "host_id",
        "players",           # member ids in join order
        "order",             # shuffled turn order (eliminated players are removed)
        "current_idx",       # index into self.order
        "active",            # True once /stod is called
        "waiting_member_id", # id of the player currently on the hot seat
        "launch_message",    # discord.Message that holds the Join button
    )

    def __init__(self, guild_id: int, channel_id: int, host_id: int):
        self.guild_id      = guild_id
        self.channel_id    = channel_id
        self.host_id       = host_id
        self.players: list[int] = [host_id]
        self.order:   list[int] = []
        self.current_idx   = 0
        self.active        = False
        self.waiting_member_id: int | None = None
        self.launch_message: discord.Message | None = None

    @property
    def current_player_id(self) -> int | None:
        if not self.order:
            return None
        return self.order[self.current_idx % len(self.order)]

    def advance(self):
        """Move to the next player (wraps around; eliminated players already removed)."""
        if self.order:
            self.current_idx = (self.current_idx + 1) % len(self.order)

    def eliminate(self, member_id: int):
        """Remove a player and fix the index so the next call to advance() is correct."""
        if member_id not in self.order:
            return
        idx = self.order.index(member_id)
        self.order.remove(member_id)
        # If we removed someone before or at current position, step back so advance() lands right
        if idx <= self.current_idx and self.current_idx > 0:
            self.current_idx -= 1


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────

class JoinTodView(discord.ui.View):
    """Green Join button shown in the lobby embed."""

    def __init__(self, game: TodGame):
        super().__init__(timeout=None)   # No timeout — host starts it manually
        self.game = game

    @discord.ui.button(label="✅  Join Game", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.game

        if game.active:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('error')} Game Already Started",
                    "The game has begun — no new players can join now.",
                    color="error"),
                ephemeral=True)

        if interaction.user.id in game.players:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('warn')} Already Joined",
                    "You're already in the lobby!", color="warn"),
                ephemeral=True)

        game.players.append(interaction.user.id)

        await interaction.response.send_message(
            embed=embed(
                "🎮 Player Joined!",
                f"{interaction.user.mention} has joined **Truth or Dare**!\n"
                f"**Players in lobby:** {len(game.players)}",
                color="success"))


class TruthDareChoiceView(discord.ui.View):
    """Truth / Dare choice buttons shown to the active player."""

    def __init__(self, game: TodGame, player: discord.Member, cog: "Games"):
        super().__init__(timeout=30.0)
        self.game     = game
        self.player   = player
        self.cog      = cog
        self.answered = False

    # ── Guard: only the active player may press ───────────────────────────
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embed(
                    f"{icon('error')} Not Your Turn",
                    f"It's **{self.player.display_name}'s** turn right now!",
                    color="error"),
                ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💬  Truth", style=discord.ButtonStyle.primary)
    async def truth_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.answered:
            return
        self.answered = True
        self.stop()
        await self.cog._handle_choice(interaction, self.game, self.player, "truth")

    @discord.ui.button(label="🎯  Dare", style=discord.ButtonStyle.danger)
    async def dare_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.answered:
            return
        self.answered = True
        self.stop()
        await self.cog._handle_choice(interaction, self.game, self.player, "dare")

    async def on_timeout(self):
        """Player ignored the prompt — eliminate and move on."""
        if self.answered:
            return
        game    = self.game
        channel = self.cog.bot.get_channel(game.channel_id)

        game.eliminate(self.player.id)

        if channel:
            try:
                await channel.send(embed=embed(
                    "⏰ Time's Up!",
                    f"{self.player.mention} didn't choose in time and is **out**!\n"
                    f"**{len(game.order)} player(s) remaining.**",
                    color="error"))
            except Exception as exc:
                log.warning(f"[Games/ToD] Could not send timeout message: {exc}")

        await self.cog._after_turn(channel, game)


class NhieView(discord.ui.View):
    """Tracks who clicked 'I Have!' for a Never Have I Ever statement."""

    def __init__(self):
        super().__init__(timeout=120.0)
        self.clicked: set[int] = set()

    @discord.ui.button(label="🙋  I Have!", style=discord.ButtonStyle.primary)
    async def i_have(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clicked.add(interaction.user.id)
        count = len(self.clicked)
        await interaction.response.send_message(
            embed=embed(
                "🙋 I Have!",
                f"{interaction.user.mention} has done it!\n\n"
                f"**{count} player{'s' if count != 1 else ''} have** admitted to this.",
                color="warn"))

    async def on_timeout(self):
        # Let buttons go stale silently
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class Games(commands.Cog):
    """Party games — Truth or Dare & Never Have I Ever."""

    def __init__(self, bot):
        self.bot = bot

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _ai(self, guild_id: int, prompt: str, fallback: str) -> str:
        """Call the bot's Groq backend; return fallback string on any failure."""
        try:
            config = await self.bot.db.get_config(guild_id)
            model  = config.get("ai_model") or self.bot.groq_model
            result = await self.bot.ask_groq(prompt, model=model)
            return result.strip() if result and result.strip() else fallback
        except Exception as exc:
            log.warning(f"[Games] AI call failed ({type(exc).__name__}): {exc}")
            return fallback

    def _is_full_member(self, guild: discord.Guild) -> bool:
        """
        True if Jiro is installed as a server (guild) app, meaning it can
        read messages and use AI to verify responses.
        When installed only as a user app, guild.me is None.
        """
        return guild is not None and guild.me is not None

    async def _safe_send(self, channel: discord.abc.Messageable, **kwargs):
        """Send to a channel; swallow HTTP errors gracefully."""
        try:
            return await channel.send(**kwargs)
        except discord.HTTPException as exc:
            log.warning(f"[Games] _safe_send failed: {exc}")
            return None

    # ── End-game ──────────────────────────────────────────────────────────────

    async def _end_game(self, game: TodGame, channel: discord.TextChannel | None):
        _tod_games.pop(game.guild_id, None)
        if not channel:
            return
        if game.order:
            member  = channel.guild.get_member(game.order[0])
            mention = member.mention if member else "Someone"
            desc    = f"🏆 {mention} is the last one standing — **champion!**"
        else:
            desc = "Everyone survived! Great game 🎉"
        await self._safe_send(channel, embed=embed("🎮 Game Over!", desc, color="mod"))

    # ── After a turn: advance or end ──────────────────────────────────────────

    async def _after_turn(self, channel: discord.TextChannel | None, game: TodGame):
        if len(game.order) < 2:
            await self._end_game(game, channel)
            return
        game.advance()
        if channel:
            await asyncio.sleep(3)
            await self._start_turn(channel, game)

    # ── Start a turn ──────────────────────────────────────────────────────────

    async def _start_turn(self, channel: discord.TextChannel, game: TodGame):
        if not game.order:
            await self._end_game(game, channel)
            return

        pid    = game.current_player_id
        member = channel.guild.get_member(pid)

        if not member:
            # Member left the server — skip silently
            game.eliminate(pid)
            await self._after_turn(channel, game)
            return

        game.waiting_member_id = pid
        view = TruthDareChoiceView(game, member, self)

        e = embed("🎮 Truth or Dare — Your Turn!", color="info")
        e.description = (
            f"{member.mention}, pick your fate!\n\n"
            f"You have **30 seconds** to choose, or you're **eliminated**."
        )
        e.set_footer(text=f"Players remaining: {len(game.order)}")
        await self._safe_send(channel, embed=e, view=view)

    # ── Handle a truth/dare choice ────────────────────────────────────────────

    async def _handle_choice(
        self,
        interaction: discord.Interaction,
        game: TodGame,
        player: discord.Member,
        choice: str,
    ):
        guild    = interaction.guild
        channel  = interaction.channel
        is_full  = self._is_full_member(guild)
        label    = "Truth" if choice == "truth" else "Dare"
        icon_str = "💬" if choice == "truth" else "🎯"

        # Build the AI prompt for question/dare generation
        if choice == "truth":
            gen_prompt = (
                "Generate ONE short, fun truth question for a Discord text-based party game. "
                "The player must be able to answer it by typing in chat. "
                "Make it entertaining but safe for a general audience. "
                "Return ONLY the question — no labels, no extra text."
            )
            fallback_prompt = "What's the most embarrassing thing you've done that nobody knows about?"
        else:
            gen_prompt = (
                "Generate ONE fun, creative dare challenge for a Discord text-based party game. "
                "The dare MUST be completable entirely in a text chat "
                "(e.g. post a selfie, type something funny, change your nickname, "
                "send a GIF, copy the last thing in your clipboard, etc.). "
                "Do NOT suggest physical dares. Return ONLY the dare — no labels, no extra text."
            )
            fallback_prompt = "Send the last image you saved to this channel."

        # Defer so we don't time out while the AI thinks
        try:
            await interaction.response.defer()
        except discord.NotFound:
            pass
        except Exception as exc:
            log.warning(f"[Games] defer failed: {exc}")

        prompt_text = await self._ai(guild.id, gen_prompt, fallback_prompt)

        e = embed(f"{icon_str} {label} — {player.display_name}", color="info")
        e.description = f"**{prompt_text}**"

        if is_full:
            e.set_footer(text=f"⏳ {player.display_name} has 60 s to respond in chat. No answer = eliminated!")
        else:
            e.set_footer(text=f"Answer the {label} in chat! The host can call /stod after each round.")

        try:
            await interaction.followup.send(embed=e)
        except Exception as exc:
            log.error(f"[Games] followup.send failed: {exc}")
            return

        # ── Full-member mode: watch for a reply and judge it ──────────────
        if is_full:
            def check(m: discord.Message):
                return m.author.id == player.id and m.channel.id == channel.id

            try:
                response_msg = await self.bot.wait_for("message", timeout=60.0, check=check)
            except asyncio.TimeoutError:
                game.eliminate(player.id)
                await self._safe_send(channel, embed=embed(
                    "⏰ No Response!",
                    f"{player.mention} didn't answer in time and is **eliminated**!\n"
                    f"**{len(game.order)} player(s) remaining.**",
                    color="error"))
                await self._after_turn(channel, game)
                return

            # AI verdict — best-effort, defaults to pass
            judge_prompt = (
                f"In a Truth or Dare game, a player was given this {label}: \"{prompt_text}\"\n"
                f"Their chat response was: \"{response_msg.content[:500]}\"\n"
                f"Did they genuinely attempt to answer / complete it? "
                f"Reply ONLY with YES or NO."
            )
            verdict = await self._ai(guild.id, judge_prompt, "YES")

            if "NO" in verdict.upper():
                await self._safe_send(channel, embed=embed(
                    "🤔 Hmm...",
                    f"Jiro isn't convinced {player.mention} completed the {label}. "
                    f"Other players can decide — but they stay in for now!",
                    color="warn"))
            else:
                await self._safe_send(channel, embed=embed(
                    "✅ Completed!",
                    f"Nice work, {player.mention}! {label} accepted.\n"
                    f"Next player up in 3 seconds...",
                    color="success"))

            await self._after_turn(channel, game)

        # ── External-app mode: no verification, game host advances manually ─
        # (no further auto-advance needed; /stod or a follow-up command manages it)

    # ─────────────────────────────────────────────────────────────────────────
    # /todlaunch — open a lobby
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="todlaunch", description="Open a Truth or Dare lobby for others to join")
    async def todlaunch(self, interaction: discord.Interaction):
        gid = interaction.guild_id

        if gid in _tod_games:
            existing = _tod_games[gid]
            host_mention = f"<@{existing.host_id}>"
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('warn')} Lobby Already Open",
                    f"A game is already running or in lobby (started by {host_mention}).\n"
                    f"The host can type `/stod` to begin, or the game ends when everyone is eliminated.",
                    color="warn"),
                ephemeral=True)

        game = TodGame(gid, interaction.channel_id, interaction.user.id)
        _tod_games[gid] = game

        view = JoinTodView(game)

        e = embed("🎮 Truth or Dare — Lobby Open!", color="mod")
        e.description = (
            f"**{interaction.user.mention}** has started a **Truth or Dare** game!\n\n"
            f"Press **Join Game** to enter the lobby.\n"
            f"When ready, the host types `/stod` to begin.\n\n"
            f"👥 **Players in lobby:** 1"
        )
        e.set_footer(text="Minimum 2 players required • Dares are chat-safe")

        await interaction.response.send_message(embed=e, view=view)

        try:
            game.launch_message = await interaction.original_response()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # /stod — begin the game (host only)
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="stod", description="Start the Truth or Dare game (host only)")
    async def stod(self, interaction: discord.Interaction):
        gid  = interaction.guild_id
        game = _tod_games.get(gid)

        if not game:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('error')} No Active Lobby",
                    "There's no open lobby. Start one with `/todlaunch`.",
                    color="error"),
                ephemeral=True)

        if interaction.user.id != game.host_id:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('error')} Host Only",
                    f"Only the game host (<@{game.host_id}>) can start the game.",
                    color="error"),
                ephemeral=True)

        if game.active:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('warn')} Already Running",
                    "The game is already in progress!",
                    color="warn"),
                ephemeral=True)

        if len(game.players) < 2:
            return await interaction.response.send_message(
                embed=embed(
                    f"{icon('warn')} Not Enough Players",
                    f"You need at least **2 players** to start.\n"
                    f"Currently: **{len(game.players)} player(s)** in lobby.",
                    color="warn"),
                ephemeral=True)

        # Lock in and shuffle
        game.active      = True
        game.order       = game.players.copy()
        random.shuffle(game.order)
        game.current_idx = 0
        game.channel_id  = interaction.channel_id

        player_list = " ".join(f"<@{pid}>" for pid in game.order)

        await interaction.response.send_message(
            embed=embed(
                "🎮 Truth or Dare — Starting!",
                f"**{len(game.order)} players** locked in!\n{player_list}\n\n"
                f"Turn order has been shuffled. First player up in a moment...",
                color="mod"))

        # Disable the lobby Join button
        if game.launch_message:
            try:
                dead_view = discord.ui.View()
                dead_btn  = discord.ui.Button(
                    label="🔒  Game Started", style=discord.ButtonStyle.secondary, disabled=True)
                dead_view.add_item(dead_btn)
                await game.launch_message.edit(view=dead_view)
            except Exception:
                pass

        await asyncio.sleep(2)
        await self._start_turn(interaction.channel, game)

    # ─────────────────────────────────────────────────────────────────────────
    # /tod + ?tod — single AI prompt (no full game)
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="tod", description="Get a single AI-generated Truth or Dare prompt")
    async def tod_slash(self, interaction: discord.Interaction):
        if not await safe_defer(interaction):
            return
        result = await self._single_tod(interaction.guild_id)
        e = embed("🎲 Truth or Dare", color="info")
        e.description = result[:500]
        e.set_footer(text="Use /todlaunch to play a full group game!")
        await interaction.followup.send(embed=e)

    @commands.command(name="tod", aliases=["truthordare"])
    async def tod_prefix(self, ctx: commands.Context):
        """Get a random AI Truth or Dare prompt. ?tod"""
        async with ctx.typing():
            result = await self._single_tod(ctx.guild.id)
        e = embed("🎲 Truth or Dare", color="info")
        e.description = result[:500]
        e.set_footer(text="Use /todlaunch to play a full group game!")
        await ctx.send(embed=e)

    async def _single_tod(self, guild_id: int) -> str:
        prompt = (
            "Generate ONE fun Truth or Dare entry for a Discord chat game. "
            "Start with either 'Truth:' or 'Dare:' (chosen randomly). "
            "If Dare, it must be completable in a text chat. "
            "Return ONLY the labelled entry — no extra text."
        )
        return await self._ai(
            guild_id, prompt,
            "Truth: What's the most embarrassing thing you've ever texted to the wrong person?")

    # ─────────────────────────────────────────────────────────────────────────
    # /nr + ?nr  — Never Have I Ever
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="nr", description="AI-powered Never Have I Ever statement")
    async def nhie_slash(self, interaction: discord.Interaction):
        if not await safe_defer(interaction):
            return
        statement = await self._nhie_statement(interaction.guild_id)
        await interaction.followup.send(embed=self._nhie_embed(statement), view=NhieView())

    @commands.command(name="nr", aliases=["nhie", "neverhaveiever"])
    async def nhie_prefix(self, ctx: commands.Context):
        """AI Never Have I Ever. ?nr / !nr"""
        async with ctx.typing():
            statement = await self._nhie_statement(ctx.guild.id)
        await ctx.send(embed=self._nhie_embed(statement), view=NhieView())

    async def _nhie_statement(self, guild_id: int) -> str:
        prompt = (
            "Generate ONE 'Never Have I Ever...' statement for a party game. "
            "Make it fun, relatable, safe for a general audience, and "
            "specific enough that only some people would have done it. "
            "Start the sentence with 'Never have I ever' and return ONLY that sentence."
        )
        return await self._ai(
            guild_id, prompt,
            "Never have I ever accidentally sent a text meant for someone else.")

    def _nhie_embed(self, statement: str) -> discord.Embed:
        e = embed("🙋 Never Have I Ever", color="info")
        e.description = (
            f"**{statement}**\n\n"
            f"Click **I Have!** if this applies to you!"
        )
        e.set_footer(text="Results are visible to everyone • Use /nr or ?nr for a new statement")
        return e


async def setup(bot):
    await bot.add_cog(Games(bot))
