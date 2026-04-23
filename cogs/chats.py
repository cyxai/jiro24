"""
cogs/chats.py — Savable Chat Sessions & Cross-Chat Memory for Jiro
NixAI • by Blueey

Commands:
  ?newchat [name]         — Start a new saved chat session
  ?chat <message>         — Talk in your active chat
  ?chngchat <number|id>   — Switch to a different chat
  ?listchats              — List all your saved chats
  ?clearchat              — Clear messages in active chat
  ?deletechat <number>    — Delete a chat permanently
  ?chatinfo               — Show info about your active chat
  ?renamechat <name>      — Rename your active chat
  ?memoryadd <fact>       — Manually add a memory fact
  ?memorylist             — List all your memory facts
  ?memoryremove <number>  — Remove a specific memory fact
  ?memoryclear            — Wipe all your memory facts
"""

import discord
from discord.ext import commands
from discord import app_commands
import random
import string
from datetime import datetime, timezone

from utils.embeds import embed
from utils.config import icon
from cogs.ai import _attachment_image_urls

MEMORY_LIMIT  = None  # None = unlimited cross-chat memory per user
HISTORY_LIMIT = None  # None = full history sent to Groq every chat call


# ── Helpers ───────────────────────────────────────────────────

def _short_id(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _ts(iso: str) -> str:
    """Convert ISO timestamp to Discord relative format."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return f"<t:{int(dt.timestamp())}:R>"
    except Exception:
        return iso[:10]


def _short_ts(iso: str) -> str:
    """Short date string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


# ══════════════════════════════════════════════════════════════
# Chats Cog
# ══════════════════════════════════════════════════════════════

class Chats(commands.Cog):
    """Savable AI chat sessions with cross-chat memory."""

    def __init__(self, bot):
        self.bot = bot
        # active chat cache: user_id → chat_id
        self._active: dict[int, str] = {}

    # ── Internal DB helpers ───────────────────────────────────

    async def _get_active(self, user_id: int) -> dict | None:
        """Return the active chat record for a user, or None."""
        chat_id = self._active.get(user_id)
        if chat_id:
            rows = await self.bot.db._get("user_chats", {"chat_id": f"eq.{chat_id}"})
            if rows:
                return rows[0]
        # Fall back to most recently updated chat
        rows = await self.bot.db._get("user_chats", {
            "user_id": f"eq.{user_id}",
            "order":   "updated_at.desc",
            "limit":   "1",
        })
        if rows:
            self._active[user_id] = rows[0]["chat_id"]
            return rows[0]
        return None

    async def _next_chat_number(self, user_id: int) -> int:
        rows = await self.bot.db._get("user_chats", {
            "user_id": f"eq.{user_id}",
            "select":  "chat_number",
            "order":   "chat_number.desc",
            "limit":   "1",
        })
        return (rows[0]["chat_number"] + 1) if rows else 1

    async def _get_history(self, chat_id: str) -> list[dict]:
        """Return full message history for a chat — no limit (unlimited setting)."""
        rows = await self.bot.db._get("chat_messages", {
            "chat_id": f"eq.{chat_id}",
            "order":   "created_at.asc",
        })
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def _add_message(self, chat_id: str, user_id: int, role: str, content: str):
        await self.bot.db._post("chat_messages", {
            "chat_id": chat_id,
            "user_id": str(user_id),
            "role":    role,
            "content": content,
        })
        # Touch updated_at on the parent chat
        await self.bot.db._patch(
            "user_chats",
            {"chat_id": chat_id},
            {"updated_at": datetime.now(timezone.utc).isoformat()},
        )

    async def _get_memory(self, user_id: int) -> list[str]:
        rows = await self.bot.db._get("user_memory", {
            "user_id": f"eq.{user_id}",
            "order":   "created_at.asc",
        })
        return [r["fact"] for r in rows]

    async def _add_memory_fact(self, user_id: int, fact: str):
        """Upsert a memory fact. No cap — memory is unlimited."""
        await self.bot.db._upsert(
            "user_memory",
            {"user_id": str(user_id), "fact": fact},
            "user_id,fact",
        )
        # No pruning — memory is unlimited)

    async def _auto_extract_memory(self, user_id: int, user_msg: str, ai_reply: str):
        """Ask Groq to extract any memorable facts from this exchange."""
        prompt = (
            f"User said: {user_msg}\n"
            f"AI replied: {ai_reply}\n\n"
            "Extract up to 2 short factual things about the user worth remembering "
            "(preferences, name, job, hobbies, etc). "
            "Reply with ONLY a JSON array of strings, e.g. [\"User likes Python\", \"User is a developer\"]. "
            "If nothing is worth remembering, reply with []."
        )
        try:
            raw = await self.bot.ask_groq(prompt)
            raw = raw.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            import json
            facts = json.loads(raw)
            if isinstance(facts, list):
                for fact in facts[:2]:
                    if isinstance(fact, str) and fact.strip():
                        await self._add_memory_fact(user_id, fact.strip())
        except Exception:
            pass  # Memory extraction is best-effort, never crash the chat

    async def _build_system(self, user_id: int, guild_id: int) -> str:
        """Build the system prompt including cross-chat memory."""
        from cogs.ai import get_system_prompt
        base = await get_system_prompt(self.bot, guild_id)
        memory = await self._get_memory(user_id)
        if memory:
            facts = "\n".join(f"- {f}" for f in memory)
            base += f"\n\nWhat you remember about this user:\n{facts}"
        return base

    async def _auto_name_chat(self, chat_id: str, first_message: str) -> str:
        """Use Groq to generate a short chat name from the first message."""
        prompt = (
            f"The user's first message in a chat was: \"{first_message}\"\n"
            "Generate a short chat name (3-5 words max) that summarizes the topic. "
            "Reply with ONLY the name, no quotes, no punctuation at the end."
        )
        try:
            name = await self.bot.ask_groq(prompt)
            name = name.strip().strip('"').strip("'")[:60]
            if name:
                await self.bot.db._patch("user_chats", {"chat_id": chat_id}, {"name": name})
                return name
        except Exception:
            pass
        return "New Chat"

    # ── ?newchat ──────────────────────────────────────────────

    @commands.command(name="newchat", aliases=["nc"])
    async def newchat(self, ctx, *, name: str = None):
        """Start a new saved chat session. ?newchat [name]"""
        chat_id     = _short_id()
        chat_number = await self._next_chat_number(ctx.author.id)
        chat_name   = name[:60] if name else "New Chat"

        rows = await self.bot.db._post("user_chats", {
            "chat_id":     chat_id,
            "user_id":     str(ctx.author.id),
            "chat_number": chat_number,
            "name":        chat_name,
        })

        self._active[ctx.author.id] = chat_id

        e = embed(f"{icon('ai')} New Chat Created", color="success")
        e.add_field(name="Chat #",   value=str(chat_number), inline=True)
        e.add_field(name="Chat ID",  value=f"`{chat_id}`",   inline=True)
        e.add_field(name="Name",     value=chat_name,        inline=True)
        e.set_footer(text="Use ?chat <message> to start talking!")
        await ctx.send(embed=e)

    @app_commands.command(name="newchat", description="Start a new saved chat session")
    async def newchat_slash(self, interaction: discord.Interaction, name: str = None):
        chat_id     = _short_id()
        chat_number = await self._next_chat_number(interaction.user.id)
        chat_name   = name[:60] if name else "New Chat"

        await self.bot.db._post("user_chats", {
            "chat_id":     chat_id,
            "user_id":     str(interaction.user.id),
            "chat_number": chat_number,
            "name":        chat_name,
        })
        self._active[interaction.user.id] = chat_id

        e = embed(f"{icon('ai')} New Chat Created", color="success")
        e.add_field(name="Chat #",  value=str(chat_number), inline=True)
        e.add_field(name="Chat ID", value=f"`{chat_id}`",   inline=True)
        e.add_field(name="Name",    value=chat_name,        inline=True)
        e.set_footer(text="Use /chat to start talking!")
        await interaction.response.send_message(embed=e)

    # ── ?chat ─────────────────────────────────────────────────

    @commands.command(name="chat")
    async def chat(self, ctx, *, message: str):
        """Talk in your active chat session, optionally attach an image. ?chat <message>"""
        chat = await self._get_active(ctx.author.id)
        if not chat:
            return await ctx.send(embed=embed(
                f"{icon('error')} No Active Chat",
                "Start one first with `?newchat`.", color="error"))

        image_urls = _attachment_image_urls(ctx.message)

        async with ctx.typing():
            system   = await self._build_system(ctx.author.id, ctx.guild.id)
            history  = await self._get_history(chat["chat_id"])
            config   = await self.bot.db.get_config(ctx.guild.id)
            model    = config.get("ai_model") or self.bot.groq_model
            reply    = await self._chat_with_history(history, message, system, model, image_urls or None)

            await self._add_message(chat["chat_id"], ctx.author.id, "user",      message)
            await self._add_message(chat["chat_id"], ctx.author.id, "assistant", reply)

            is_first = len(history) == 0 and chat["name"] == "New Chat"
            if is_first:
                chat["name"] = await self._auto_name_chat(chat["chat_id"], message)

            self.bot.loop.create_task(
                self._auto_extract_memory(ctx.author.id, message, reply)
            )

        e = embed(f"{icon('ai')} {chat['name']}", color="info")
        e.add_field(name="You",  value=message[:500], inline=False)
        e.add_field(name="Jiro", value=reply[:1000],  inline=False)
        if image_urls:
            e.set_footer(text=f"🖼️ {len(image_urls)} image(s) analysed • Chat #{chat['chat_number']} • {chat['chat_id']}")
        else:
            e.set_footer(text=f"Chat #{chat['chat_number']} • {chat['chat_id']} • ?listchats to see all")
        await ctx.send(embed=e)

    @app_commands.command(name="chat", description="Talk in your active saved chat session (optionally include an image URL)")
    async def chat_slash(self, interaction: discord.Interaction, message: str,
                         image_url: str = None):
        chat = await self._get_active(interaction.user.id)
        if not chat:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} No Active Chat",
                "Start one first with `/newchat`.", color="error"), ephemeral=True)

        await interaction.response.defer()
        image_urls = [image_url] if image_url else []
        system   = await self._build_system(interaction.user.id, interaction.guild.id)
        history  = await self._get_history(chat["chat_id"])
        config   = await self.bot.db.get_config(interaction.guild.id)
        model    = config.get("ai_model") or self.bot.groq_model
        reply    = await self._chat_with_history(history, message, system, model, image_urls or None)

        await self._add_message(chat["chat_id"], interaction.user.id, "user",      message)
        await self._add_message(chat["chat_id"], interaction.user.id, "assistant", reply)

        is_first = len(history) == 0 and chat["name"] == "New Chat"
        if is_first:
            chat["name"] = await self._auto_name_chat(chat["chat_id"], message)

        self.bot.loop.create_task(
            self._auto_extract_memory(interaction.user.id, message, reply)
        )

        e = embed(f"{icon('ai')} {chat['name']}", color="info")
        e.add_field(name="You",  value=message[:500], inline=False)
        e.add_field(name="Jiro", value=reply[:1000],  inline=False)
        if image_urls:
            e.set_footer(text=f"🖼️ Image analysed • Chat #{chat['chat_number']} • {chat['chat_id']}")
        else:
            e.set_footer(text=f"Chat #{chat['chat_number']} • {chat['chat_id']}")
        await interaction.followup.send(embed=e)

    async def _chat_with_history(self, history: list[dict], new_message: str,
                                 system: str, model: str,
                                 image_urls: list[str] | None = None) -> str:
        """Send a full conversation history to Groq, with optional vision on the latest message."""
        import aiohttp, asyncio
        session = await self.bot.get_session()
        payload_messages = [{"role": "system", "content": system}] + history

        if image_urls:
            # Vision request — use vision model and multi-modal content for the new message
            from cogs.ai import _build_vision_content
            content = await _build_vision_content(session, new_message, image_urls)
            payload_messages.append({"role": "user", "content": content})
            use_model = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            payload_messages.append({"role": "user", "content": new_message})
            use_model = model

        try:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.bot.groq_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       use_model,
                    "messages":    payload_messages,
                    "max_tokens":  1024,
                    "temperature": 0.7,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f"[Groq error {resp.status}]"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            return "[Groq timed out — try again]"
        except Exception as e:
            return f"[Error: {e}]"

    # ── ?chngchat ─────────────────────────────────────────────

    @commands.command(name="chngchat", aliases=["switchchat", "sc"])
    async def chngchat(self, ctx, identifier: str):
        """Switch to a different chat by number or chat ID. ?chngchat <number|id>"""
        user_id = ctx.author.id

        # Try by number first, then by chat_id
        try:
            num  = int(identifier)
            rows = await self.bot.db._get("user_chats", {
                "user_id":     f"eq.{user_id}",
                "chat_number": f"eq.{num}",
            })
        except ValueError:
            rows = await self.bot.db._get("user_chats", {
                "user_id": f"eq.{user_id}",
                "chat_id": f"eq.{identifier}",
            })

        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('error')} Chat Not Found",
                f"No chat found for `{identifier}`. Use `?listchats` to see yours.",
                color="error"))

        chat = rows[0]
        self._active[user_id] = chat["chat_id"]

        msg_rows = await self.bot.db._get("chat_messages", {
            "chat_id": f"eq.{chat['chat_id']}",
            "select":  "id",
        })

        e = embed(f"{icon('ai')} Switched to Chat #{chat['chat_number']}", color="success")
        e.add_field(name="Name",     value=chat["name"],               inline=True)
        e.add_field(name="Chat ID",  value=f"`{chat['chat_id']}`",     inline=True)
        e.add_field(name="Messages", value=str(len(msg_rows)),         inline=True)
        e.add_field(name="Created",  value=_short_ts(chat["created_at"]), inline=True)
        e.set_footer(text="Use ?chat <message> to continue this conversation.")
        await ctx.send(embed=e)

    @app_commands.command(name="chngchat", description="Switch to a different chat by number or ID")
    async def chngchat_slash(self, interaction: discord.Interaction, identifier: str):
        user_id = interaction.user.id
        try:
            num  = int(identifier)
            rows = await self.bot.db._get("user_chats", {
                "user_id": f"eq.{user_id}", "chat_number": f"eq.{num}"})
        except ValueError:
            rows = await self.bot.db._get("user_chats", {
                "user_id": f"eq.{user_id}", "chat_id": f"eq.{identifier}"})

        if not rows:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Chat Not Found",
                f"No chat found for `{identifier}`.", color="error"), ephemeral=True)

        chat = rows[0]
        self._active[user_id] = chat["chat_id"]
        e = embed(f"{icon('ai')} Switched to Chat #{chat['chat_number']}", color="success")
        e.add_field(name="Name",    value=chat["name"],           inline=True)
        e.add_field(name="Chat ID", value=f"`{chat['chat_id']}`", inline=True)
        await interaction.response.send_message(embed=e)

    # ── ?listchats ────────────────────────────────────────────

    @commands.command(name="listchats", aliases=["chats", "lc"])
    async def listchats(self, ctx):
        """List all your saved chat sessions. ?listchats"""
        rows = await self.bot.db._get("user_chats", {
            "user_id": f"eq.{ctx.author.id}",
            "order":   "chat_number.asc",
        })
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('ai')} No Chats Yet",
                "Start your first chat with `?newchat`!", color="info"))

        active_id = self._active.get(ctx.author.id)
        if not active_id:
            chat = await self._get_active(ctx.author.id)
            active_id = chat["chat_id"] if chat else None

        e = embed(f"{icon('ai')} Your Chats ({len(rows)} total)", color="info")
        e.set_footer(text="?chngchat <number> to switch • ?chat <msg> to talk")

        for chat in rows[:15]:
            active_marker = " ◀ active" if chat["chat_id"] == active_id else ""
            e.add_field(
                name=f"#{chat['chat_number']} — {chat['name']}{active_marker}",
                value=(
                    f"**ID:** `{chat['chat_id']}`\n"
                    f"**Created:** {_short_ts(chat['created_at'])}\n"
                    f"**Last used:** {_ts(chat['updated_at'])}"
                ),
                inline=False,
            )

        if len(rows) > 15:
            e.description = f"*Showing 15 of {len(rows)} chats.*"
        await ctx.send(embed=e)

    @app_commands.command(name="listchats", description="List all your saved chat sessions")
    async def listchats_slash(self, interaction: discord.Interaction):
        rows = await self.bot.db._get("user_chats", {
            "user_id": f"eq.{interaction.user.id}",
            "order":   "chat_number.asc",
        })
        if not rows:
            return await interaction.response.send_message(embed=embed(
                f"{icon('ai')} No Chats Yet",
                "Start your first chat with `/newchat`!", color="info"))

        active_id = self._active.get(interaction.user.id)
        e = embed(f"{icon('ai')} Your Chats ({len(rows)} total)", color="info")
        for chat in rows[:15]:
            marker = " ◀ active" if chat["chat_id"] == active_id else ""
            e.add_field(
                name=f"#{chat['chat_number']} — {chat['name']}{marker}",
                value=(
                    f"**ID:** `{chat['chat_id']}`\n"
                    f"**Created:** {_short_ts(chat['created_at'])}\n"
                    f"**Last used:** {_ts(chat['updated_at'])}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── ?chatinfo ─────────────────────────────────────────────

    @commands.command(name="chatinfo", aliases=["ci"])
    async def chatinfo(self, ctx):
        """Show info about your active chat. ?chatinfo"""
        chat = await self._get_active(ctx.author.id)
        if not chat:
            return await ctx.send(embed=embed(
                f"{icon('error')} No Active Chat",
                "Use `?newchat` to start one.", color="error"))

        msg_rows = await self.bot.db._get("chat_messages", {
            "chat_id": f"eq.{chat['chat_id']}",
            "select":  "role",
        })
        user_msgs = sum(1 for m in msg_rows if m["role"] == "user")
        ai_msgs   = sum(1 for m in msg_rows if m["role"] == "assistant")

        e = embed(f"{icon('ai')} Chat Info — {chat['name']}", color="info")
        e.add_field(name="Chat #",      value=str(chat["chat_number"]),    inline=True)
        e.add_field(name="Chat ID",     value=f"`{chat['chat_id']}`",      inline=True)
        e.add_field(name="Created",     value=_short_ts(chat["created_at"]), inline=True)
        e.add_field(name="Last Used",   value=_ts(chat["updated_at"]),     inline=True)
        e.add_field(name="Your Msgs",   value=str(user_msgs),              inline=True)
        e.add_field(name="Jiro Msgs",   value=str(ai_msgs),                inline=True)
        e.set_footer(text="?renamechat <name> to rename • ?clearchat to wipe messages")
        await ctx.send(embed=e)

    # ── ?renamechat ───────────────────────────────────────────

    @commands.command(name="renamechat", aliases=["rnchat"])
    async def renamechat(self, ctx, *, name: str):
        """Rename your active chat. ?renamechat <new name>"""
        chat = await self._get_active(ctx.author.id)
        if not chat:
            return await ctx.send(embed=embed(
                f"{icon('error')} No Active Chat", "Use `?newchat` first.", color="error"))

        name = name[:60]
        await self.bot.db._patch("user_chats", {"chat_id": chat["chat_id"]}, {"name": name})
        await ctx.send(embed=embed(
            f"{icon('ok')} Chat Renamed",
            f"Chat #{chat['chat_number']} is now called **{name}**.", color="success"))

    # ── ?clearchat ────────────────────────────────────────────

    @commands.command(name="clearchat", aliases=["cc"])
    async def clearchat(self, ctx):
        """Clear all messages in your active chat. ?clearchat"""
        chat = await self._get_active(ctx.author.id)
        if not chat:
            return await ctx.send(embed=embed(
                f"{icon('error')} No Active Chat", "Use `?newchat` first.", color="error"))

        await self.bot.db._delete("chat_messages", {"chat_id": chat["chat_id"]})
        await ctx.send(embed=embed(
            f"{icon('ok')} Chat Cleared",
            f"All messages in **{chat['name']}** have been deleted.\n"
            "The chat session still exists — use `?chat` to start fresh.",
            color="success"))

    # ── ?deletechat ───────────────────────────────────────────

    @commands.command(name="deletechat", aliases=["delchat", "dc"])
    async def deletechat(self, ctx, identifier: str):
        """Permanently delete a chat. ?deletechat <number|id>"""
        user_id = ctx.author.id
        try:
            num  = int(identifier)
            rows = await self.bot.db._get("user_chats", {
                "user_id": f"eq.{user_id}", "chat_number": f"eq.{num}"})
        except ValueError:
            rows = await self.bot.db._get("user_chats", {
                "user_id": f"eq.{user_id}", "chat_id": f"eq.{identifier}"})

        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('error')} Chat Not Found",
                f"No chat found for `{identifier}`.", color="error"))

        chat = rows[0]
        # Messages cascade-delete via FK
        await self.bot.db._delete("user_chats", {"chat_id": chat["chat_id"]})

        # Clear from active cache if it was active
        if self._active.get(user_id) == chat["chat_id"]:
            del self._active[user_id]

        await ctx.send(embed=embed(
            f"{icon('ok')} Chat Deleted",
            f"Chat #{chat['chat_number']} **{chat['name']}** has been permanently deleted.",
            color="warn"))

    # ── ?memoryadd ────────────────────────────────────────────

    @commands.command(name="memoryadd", aliases=["madd"])
    async def memoryadd(self, ctx, *, fact: str):
        """Manually add a memory fact. ?memoryadd <fact>"""
        fact = fact[:200]
        await self._add_memory_fact(ctx.author.id, fact)
        count = len(await self._get_memory(ctx.author.id))
        await ctx.send(embed=embed(
            f"{icon('ok')} Memory Saved",
            f"Jiro will remember: *{fact}*\n"
            f"You now have **{count}** memory facts stored.",
            color="success"))

    # ── ?memorylist ───────────────────────────────────────────

    @commands.command(name="memorylist", aliases=["memories", "ml"])
    async def memorylist(self, ctx):
        """List all your memory facts. ?memorylist"""
        facts = await self._get_memory(ctx.author.id)
        if not facts:
            return await ctx.send(embed=embed(
                f"{icon('ai')} No Memories Yet",
                "Jiro will automatically remember things as you chat.\n"
                "Or add one manually with `?memoryadd <fact>`.", color="info"))

        e = embed(f"{icon('ai')} Your Memory Facts ({len(facts)} total)", color="info")
        e.description = "\n".join(f"`{i+1}.` {f}" for i, f in enumerate(facts))
        e.set_footer(text="?memoryremove <number> to delete one • ?memoryclear to wipe all")
        await ctx.send(embed=e)

    # ── ?memoryremove ─────────────────────────────────────────

    @commands.command(name="memoryremove", aliases=["memrm", "mr"])
    async def memoryremove(self, ctx, number: int):
        """Remove a specific memory fact by its list number. ?memoryremove <number>"""
        rows = await self.bot.db._get("user_memory", {
            "user_id": f"eq.{ctx.author.id}",
            "order":   "created_at.asc",
        })
        if not rows or number < 1 or number > len(rows):
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Number",
                f"Use `?memorylist` to see your facts (1–{len(rows)}).", color="error"))

        fact = rows[number - 1]
        await self.bot.db._delete("user_memory", {"id": str(fact["id"])})
        await ctx.send(embed=embed(
            f"{icon('ok')} Memory Removed",
            f"Removed: *{fact['fact']}*", color="warn"))

    # ── ?memoryclear ──────────────────────────────────────────

    @commands.command(name="memoryclear", aliases=["memclear"])
    async def memoryclear(self, ctx):
        """Wipe all your memory facts. ?memoryclear"""
        await self.bot.db._delete("user_memory", {"user_id": str(ctx.author.id)})
        await ctx.send(embed=embed(
            f"{icon('ok')} Memory Cleared",
            "All your memory facts have been wiped.\n"
            "Jiro will start building fresh memories as you chat.",
            color="warn"))

    # ── ?chatchannelset / ?chatchannelclear ─────────────────────────

    @commands.command(name="chatchannelset", aliases=["setchatchannel"])
    @commands.has_permissions(administrator=True)
    async def chatchannelset(self, ctx, channel: discord.TextChannel = None):
        """
        Set a channel where Jiro replies to every message automatically.
        No ping needed — just type and Jiro responds.
        !chatchannelset #channel  (defaults to current channel)
        """
        target = channel or ctx.channel
        await self.bot.db.set_config(ctx.guild.id, "chat_channel_id", str(target.id))
        await ctx.send(embed=embed(
            f"{icon('ai')} Chat Channel Set",
            f"Jiro will now respond to every message in {target.mention}.\n"
            "No ping required — just talk naturally.\n"
            "Use `!chatchannelclear` to disable.",
            color="success",
        ))

    @app_commands.command(name="chatchannelset", description="Set a channel where Jiro auto-replies to every message")
    @app_commands.describe(channel="The channel to use (defaults to current)")
    @app_commands.checks.has_permissions(administrator=True)
    async def chatchannelset_slash(self, interaction: discord.Interaction,
                                   channel: discord.TextChannel = None):
        target = channel or interaction.channel
        await self.bot.db.set_config(interaction.guild.id, "chat_channel_id", str(target.id))
        await interaction.response.send_message(embed=embed(
            f"{icon('ai')} Chat Channel Set",
            f"Jiro will now respond to every message in {target.mention}.\n"
            "No ping required — just talk naturally.\n"
            "Use `!chatchannelclear` to disable.",
            color="success",
        ))

    @commands.command(name="chatchannelclear", aliases=["clearchatchannel"])
    @commands.has_permissions(administrator=True)
    async def chatchannelclear(self, ctx):
        """Remove the auto-reply chat channel. !chatchannelclear"""
        await self.bot.db.set_config(ctx.guild.id, "chat_channel_id", None)
        await ctx.send(embed=embed(
            f"{icon('ok')} Chat Channel Cleared",
            "Jiro will no longer auto-reply in any channel.\n"
            "Use `!chatchannelset` to set a new one.",
            color="info",
        ))

    # ── Auto-reply listener (chat channel + DMs) ──────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Always ignore bots
        if message.author.bot:
            return

        # Ignore command prefixes — let the command handler take those
        if message.content.startswith(("?", "!", "/")):
            return

        is_dm    = isinstance(message.channel, discord.DMChannel)
        is_guild = message.guild is not None

        # DM path — always respond
        if is_dm:
            await self._handle_auto_reply(message, guild_id=None)
            return

        # Guild path — only respond in the configured chat channel
        if not is_guild:
            return
        try:
            config     = await self.bot.db.get_config(message.guild.id)
            chat_ch_id = config.get("chat_channel_id")
        except Exception:
            return

        if not chat_ch_id or str(message.channel.id) != str(chat_ch_id):
            return

        if not self.bot.db._bool(config.get("ai_enabled"), default=True):
            return

        await self._handle_auto_reply(message, guild_id=message.guild.id)

    async def _handle_auto_reply(self, message: discord.Message, guild_id: int | None):
        """
        Core auto-reply logic shared by DMs and chat-channel messages.
        Plugs into the full session + memory system — same quality as ?chat.
        """
        import asyncio
        import aiohttp
        from cogs.ai import DEFAULT_SYSTEM_PROMPT

        user_id = message.author.id
        text    = message.content.strip()
        if not text and not message.attachments:
            return

        # Resolve or auto-create an active session
        try:
            chat = await self._get_active(user_id)
            if not chat:
                number  = await self._next_chat_number(user_id)
                chat_id = _short_id()
                now     = datetime.now(timezone.utc).isoformat()
                await self.bot.db._post("user_chats", {
                    "user_id":     str(user_id),
                    "chat_id":     chat_id,
                    "chat_number": number,
                    "name":        "Chat",
                    "created_at":  now,
                    "updated_at":  now,
                })
                self._active[user_id] = chat_id
                chat = await self._get_active(user_id)
        except Exception as e:
            print(f"[Chats] Session resolve failed: {e}")
            return

        if not chat:
            return

        # Build system prompt with memory
        effective_guild = guild_id or 0
        try:
            system = await self._build_system(user_id, effective_guild)
        except Exception:
            system = DEFAULT_SYSTEM_PROMPT

        # Fetch history
        try:
            history = await self._get_history(chat["chat_id"])
        except Exception:
            history = []

        # Handle image attachments
        image_urls = _attachment_image_urls(message)

        async with message.channel.typing():
            try:
                if image_urls:
                    from cogs.ai import _build_vision_content
                    session = await self.bot.get_session()
                    content = await _build_vision_content(session, text or "What is this?", image_urls)
                    reply   = await self.bot.ask_groq_vision(content, system=system)
                else:
                    messages_payload = [{"role": "system", "content": system}]
                    messages_payload += history
                    messages_payload.append({"role": "user", "content": text})

                    model = self.bot.groq_model
                    if guild_id:
                        try:
                            gc    = await self.bot.db.get_config(guild_id)
                            model = gc.get("ai_model") or model
                        except Exception:
                            pass

                    session = await self.bot.get_session()
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.bot.groq_key}",
                            "Content-Type":  "application/json",
                        },
                        json={"model": model, "messages": messages_payload,
                              "max_tokens": 1024, "temperature": 0.7},
                        timeout=aiohttp.ClientTimeout(total=25),
                    ) as resp:
                        if resp.status == 200:
                            data  = await resp.json()
                            reply = data["choices"][0]["message"]["content"].strip()
                        else:
                            reply = "I couldn't reach my AI backend right now. Please try again."
            except Exception as e:
                print(f"[Chats] Auto-reply Groq call failed: {e}")
                reply = "Something went wrong on my end. Please try again."

        # Persist the exchange
        try:
            await self._add_message(chat["chat_id"], user_id, "user",      text or "[image]")
            await self._add_message(chat["chat_id"], user_id, "assistant", reply)
        except Exception:
            pass

        # Auto-name the chat on first real exchange
        try:
            if chat.get("name") in ("Chat", "New Chat", None) and text:
                asyncio.create_task(
                    self._auto_name_chat(chat["chat_id"], text),
                    name=f"autoname_{chat['chat_id']}",
                )
        except Exception:
            pass

        # Auto-extract memory facts in the background
        try:
            asyncio.create_task(
                self._auto_extract_memory(user_id, text, reply),
                name=f"memory_{user_id}",
            )
        except Exception:
            pass

        # Send — plain messages feel more conversational than embeds here
        try:
            for chunk in [reply[i:i+2000] for i in range(0, len(reply), 2000)]:
                await message.channel.send(chunk)
        except discord.HTTPException:
            pass

    # ── ?chathistory ──────────────────────────────────────────

    @commands.command(name="chathistory", aliases=["ch"])
    async def chathistory(self, ctx, number: int = None):
        """View the last few messages in a chat. ?chathistory [chat number]"""
        if number:
            rows = await self.bot.db._get("user_chats", {
                "user_id":     f"eq.{ctx.author.id}",
                "chat_number": f"eq.{number}",
            })
            if not rows:
                return await ctx.send(embed=embed(
                    f"{icon('error')} Chat Not Found",
                    f"No chat #{number} found.", color="error"))
            chat = rows[0]
        else:
            chat = await self._get_active(ctx.author.id)
            if not chat:
                return await ctx.send(embed=embed(
                    f"{icon('error')} No Active Chat",
                    "Use `?newchat` or specify a chat number.", color="error"))

        msgs = await self.bot.db._get("chat_messages", {
            "chat_id": f"eq.{chat['chat_id']}",
            "order":   "created_at.desc",
            "limit":   "6",
        })
        msgs.reverse()

        if not msgs:
            return await ctx.send(embed=embed(
                f"{icon('ai')} {chat['name']} — No Messages",
                "This chat has no messages yet.", color="info"))

        e = embed(f"{icon('ai')} {chat['name']} — Recent History", color="info")
        for msg in msgs:
            label = "You" if msg["role"] == "user" else "Jiro"
            e.add_field(
                name=label,
                value=msg["content"][:300] + ("…" if len(msg["content"]) > 300 else ""),
                inline=False,
            )
        e.set_footer(text=f"Chat #{chat['chat_number']} • {chat['chat_id']}")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Chats(bot))
