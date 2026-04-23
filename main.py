"""
main.py — 07Dipper / Jiro Discord Bot
NixAI • by Blueey

Run with: python main.py
"""

import os
import asyncio
import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

# ── Load environment variables ─────────────────────────────
load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN")
GROQ_KEY     = os.getenv("GROQ_KEY")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "cyanix/axion-5-ensemble")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PREFIX       = os.getenv("PREFIX", "?")

missing = []
if not BOT_TOKEN: missing.append("BOT_TOKEN")
if not SUPABASE_URL or not SUPABASE_KEY: missing.append("SUPABASE_URL/SUPABASE_KEY")
if not GROQ_KEY: missing.append("GROQ_KEY")
if missing:
    raise ValueError(f"Missing required environment variable(s): {', '.join(missing)}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class Jiro(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX, "!"),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.groq_key    = GROQ_KEY
        self.groq_model  = GROQ_MODEL
        self.axion_url   = (
            f"{SUPABASE_URL}/functions/v1/axion-5-ensemble"
            if SUPABASE_URL else None
        )
        self.axion_key   = SUPABASE_KEY   # Supabase anon key authorises edge functions
        self._session: aiohttp.ClientSession | None = None

        from database import Database
        self.db = Database(url=SUPABASE_URL, anon_key=SUPABASE_KEY)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def ask_groq(self, prompt: str, *, system: str = None, model: str = None) -> str:
        model = model or self.groq_model

        # Route Axion ensemble requests to the Supabase edge function
        if model == "cyanix/axion-5-ensemble":
            return await self._ask_axion(prompt, system=system)

        session  = await self.get_session()
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        try:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.7},
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    return f"[Groq error {resp.status}: {(await resp.text())[:200]}]"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            return "[Groq timed out — try again]"
        except Exception as e:
            return f"[Groq error: {e}]"

    async def _ask_axion(self, prompt: str, *, system: str = None) -> str:
        """
        Call the Axion 5 Ensemble edge function.
        Fans the prompt out to 5 Llama models, scores them, returns the winner.
        Falls back to llama-3.3-70b-versatile if the edge function is unreachable.
        """
        if not self.axion_url or not self.axion_key:
            # Graceful fallback if Supabase isn't configured
            return await self._ask_groq_direct(prompt, system=system, model="llama-3.3-70b-versatile")

        session  = await self.get_session()
        messages = [{"role": "user", "content": prompt}]
        payload  = {"messages": messages, "max_tokens": 1024, "temperature": 0.7}
        if system:
            payload["system"] = system

        try:
            async with session.post(
                self.axion_url,
                headers={
                    "Authorization": f"Bearer {self.axion_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),  # Ensemble needs more time
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"[Axion] Edge function error {resp.status}: {err[:200]} — falling back")
                    return await self._ask_groq_direct(prompt, system=system, model="llama-3.3-70b-versatile")
                data   = await resp.json()
                result = data["choices"][0]["message"]["content"].strip()
                # Log ensemble metadata for debugging
                axion  = data.get("axion", {})
                print(
                    f"[Axion] Winner: {axion.get('winner_model')} "
                    f"score={axion.get('winner_score')} "
                    f"latency={axion.get('latency_ms')}ms"
                )
                return result
        except asyncio.TimeoutError:
            print("[Axion] Edge function timed out — falling back to direct Groq")
            return await self._ask_groq_direct(prompt, system=system, model="llama-3.3-70b-versatile")
        except Exception as e:
            print(f"[Axion] Edge function call failed: {e} — falling back")
            return await self._ask_groq_direct(prompt, system=system, model="llama-3.3-70b-versatile")

    async def _ask_groq_direct(self, prompt: str, *, system: str = None, model: str) -> str:
        """Direct Groq call — used as the Axion fallback path."""
        session  = await self.get_session()
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        try:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.7},
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    return f"[Groq error {resp.status}: {(await resp.text())[:200]}]"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            return "[Groq timed out — try again]"
        except Exception as e:
            return f"[Groq error: {e}]"

    async def ask_groq_vision(self, content: list, *, system: str = None, model: str = None) -> str:
        """
        Send a vision (multi-modal) request to Groq.
        `content` is a list of text/image_url dicts already built by _build_vision_content().
        Falls back to meta-llama/llama-4-scout-17b-16e-instruct which supports images.
        """
        # Use a vision-capable model; fall back gracefully if the guild model doesn't support vision
        vision_model = "meta-llama/llama-4-scout-17b-16e-instruct"
        session = await self.get_session()
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content})
        try:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={"model": vision_model, "messages": messages, "max_tokens": 1024, "temperature": 0.7},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f"[Vision error {resp.status}: {(await resp.text())[:200]}]"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            return "[Vision request timed out — try again]"
        except Exception as e:
            return f"[Vision error: {e}]"

    async def setup_hook(self):
        cog_order = [
            "cogs.error_handler",
            "cogs.automod",
            "cogs.help",
            "cogs.logs",
            "cogs.moderation",
            "cogs.roles",
            "cogs.shared_moderation",
            "cogs.warnings",
            "cogs.welcome",
            "cogs.fun",
            "cogs.ai",
            "cogs.games",
            "cogs.afk_report",
            "cogs.levels",
            "cogs.giveaways",
            "cogs.reminders",
            "cogs.notes",
            "cogs.antiraid",
            "cogs.guild_cache_events",
            "cogs.chats",
            "cogs.guild_sync",
          ]
        for cog in cog_order:
            try:
                await self.load_extension(cog)
                print(f"[OK] Loaded {cog}")
            except Exception as e:
                print(f"[ERR] Failed to load {cog}: {e}")
        try:
            synced = await self.tree.sync()
            print(f"[OK] Synced {len(synced)} slash commands globally")
        except Exception as e:
            print(f"[ERR] Slash command sync failed: {e}")

    async def on_ready(self):
        print(f"\n{'='*40}")
        print(f"  Jiro is online as {self.user} ({self.user.id})")
        print(f"  Guilds: {len(self.guilds)}  |  Prefix: {PREFIX}  |  Model: {self.groq_model}")
        print(f"{'='*40}\n")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name=f"{PREFIX}help | NixAI"))

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.user in message.mentions and message.guild:
            content = message.content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
            if content:
                try:
                    config = await self.db.get_config(message.guild.id)
                    if self.db._bool(config.get("ai_enabled"), default=True):
                        async with message.channel.typing():
                            from cogs.ai import get_system_prompt
                            system = await get_system_prompt(self, message.guild.id)
                            model  = config.get("ai_model") or self.groq_model
                            reply  = await self.ask_groq(content, system=system, model=model)
                        await message.reply(reply[:2000])
                except Exception as e:
                    print(f"[ERR] Mention reply failed: {e}")
        await self.process_commands(message)

    async def close(self):
        await self.db.close()
        if self._session and not self._session.closed:
            await self._session.close()
        await super().close()

async def main():
    bot = Jiro()
    async with bot:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
