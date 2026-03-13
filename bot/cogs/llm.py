# bot/cogs/llm.py — LLM chat command with agentic tool-call support.
from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import cast
from urllib.parse import unquote

import discord
from discord.ext import commands

from bot.client import Bot
from utils.logger import log, LogLevel
from utils.prompts import SYSTEM_PROMPT, contains_prompt_leak
from tools.llm_api import chat, MAX_TOOL_CALLS
from tools.toolcalls.code_runner import get_manager as _get_sandbox_manager
from tools.toolcalls import tool_registry as _tool_registry
from tools.toolcalls.safety_responder import (
    SAFETY_RESPONSE_TAG,
    CRISIS_RESPONSE as _CRISIS_RESPONSE,
    PR_DEFLECTION_RESPONSE as _PR_DEFLECTION_RESPONSE,
)
from tools import katex_formatter
import settings
from utils.channel_memory import lookup_messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_flags() -> discord.MessageFlags:
    """Return MessageFlags with suppress_notifications set."""
    flags = discord.MessageFlags()
    flags.suppress_notifications = True
    return flags


def _should_silent_all() -> bool:
    return settings.GLOBAL_SILENT


def _should_silent_toolcall() -> bool:
    return settings.GLOBAL_SILENT or settings.TOOLCALL_SILENT


def _should_show_toolcall_notices() -> bool:
    return settings.SHOW_TOOLCALL_NOTICES


_DISCORD_MAX = 2000

# Regex that strips any safety-sentinel lines the LLM may echo in its final
# text reply.  The sentinel is meant to be handled silently by on_tool_call;
# if it leaks into the reply it must be removed before the text is sent.
# Discord also renders __word__ as underlined text, so even a partial leak
# would corrupt the message visually.
_SAFETY_SENTINEL_RE: re.Pattern[str] = re.compile(
    rf"\[{re.escape(SAFETY_RESPONSE_TAG)}=[^\]]*\][^\n]*\n?",
    re.IGNORECASE,
)
_GCAL_CONFLICT_TAG = "__gcal_conflict__"
_GCAL_CONFLICT_RE: re.Pattern[str] = re.compile(
    rf"\[{re.escape(_GCAL_CONFLICT_TAG)}=([^\]]+)\]"
)
_EMAIL_RE: re.Pattern[str] = re.compile(
    r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b"
)
_SENSITIVE_TOOL_KEY_RE: re.Pattern[str] = re.compile(
    r"(?i)(calendar(_id)?|attendee(s)?|email)"
)
_TOOL_INVENTORY_LEAK_RE: re.Pattern[str] = re.compile(
    r"(?is)\b(commands?|functions?)\b.{0,80}\b(can run|available|reference)\b"
)
def _format_iso_brief(iso_str: str | None) -> str:
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone()
        now_local = datetime.now().astimezone()
        today = now_local.date()
        tomorrow = (now_local + timedelta(days=1)).date()

        if dt.date() == today:
            day_label = "Today"
        elif dt.date() == tomorrow:
            day_label = "Tomorrow"
        else:
            day_label = dt.strftime("%a, %b %d")
        return f"{day_label} at {dt.strftime('%I:%M %p').lstrip('0')}"
    except Exception:
        return str(iso_str)


def _extract_conflict_payload(result: str) -> dict | None:
    match = _GCAL_CONFLICT_RE.search(result)
    if not match:
        return None
    try:
        return json.loads(unquote(match.group(1)))
    except Exception:
        return None


def _redact_tool_text(value: str) -> str:
    """Mask explicit email addresses before posting tool-call notices."""
    return _EMAIL_RE.sub("[redacted-email]", value)


def _redact_tool_value(value, key: str | None = None):
    """Recursively sanitize tool args/results for user-facing notices."""
    if isinstance(value, dict):
        return {k: _redact_tool_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_tool_value(v, key) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_tool_value(v, key) for v in value)
    if isinstance(value, str):
        if key and _SENSITIVE_TOOL_KEY_RE.search(key):
            return "[redacted]"
        return _redact_tool_text(value)
    return value


def _looks_like_internal_tool_inventory(reply: str) -> bool:
    """Detect replies that expose internal tool/function inventory."""
    if _TOOL_INVENTORY_LEAK_RE.search(reply):
        return True
    tool_names = list(_tool_registry.TOOLS.keys())
    hits = 0
    lower_reply = reply.lower()
    for name in tool_names:
        if f"{name.lower()}(" in lower_reply or f"`{name.lower()}`" in lower_reply:
            hits += 1
            if hits >= 2:
                return True
    return False


def _extract_reply_context(message: discord.Message) -> str | None:
    """Return a short context block for the referenced message, if any."""
    ref = getattr(message, "reference", None)
    target = getattr(ref, "resolved", None) if ref is not None else None
    if target is None:
        return None

    target_content = str(getattr(target, "content", "") or "").strip()
    if not target_content:
        return None

    target_author = getattr(target, "author", None)
    author_name = (
        getattr(target_author, "display_name", None)
        or getattr(target_author, "global_name", None)
        or getattr(target_author, "name", None)
        or str(target_author or "unknown")
    )
    return (
        "[Referenced message context]\n"
        f"- author: {author_name}\n"
        f"- content: {target_content}\n\n"
    )


def _is_channel_recall_request(prompt: str) -> bool:
    """Detect prompts asking to recall prior discussion in the current channel.

    Uses a small intent heuristic rather than a long exact-phrase list so
    variants like "what was the first stats problem in this channel" still
    route to deterministic channel recall.
    """
    text = prompt.lower()

    exact_phrases = (
        "do you remember",
        "what were we talking about",
        "what were we discussing",
        "what did we talk about",
        "what did i say earlier",
        "what was i asking about",
        "earlier context",
        "previous context",
        "what was talked about before",
        "what had been discussed in the channel before",
    )
    if any(phrase in text for phrase in exact_phrases):
        return True

    local_scope_terms = ("in this channel", "this channel", "here", "we", "earlier here")
    retrieval_terms = ("remember", "look up", "lookup", "pull up", "check", "recall", "review", "find", "what was")
    temporal_terms = ("before", "earlier", "previous", "prior", "back", "first", "earliest", "last")
    content_terms = (
        "talk",
        "talking",
        "discuss",
        "discussed",
        "conversation",
        "context",
        "history",
        "recap",
        "message",
        "problem",
        "topic",
    )

    score = 0
    if any(term in text for term in local_scope_terms):
        score += 1
    if any(term in text for term in retrieval_terms):
        score += 1
    if any(term in text for term in temporal_terms):
        score += 1
    if any(term in text for term in content_terms):
        score += 1

    return score >= 2


def _format_recent_rows(rows: list[dict], *, cap: int) -> str:
    """Render recent channel rows into a compact prompt block."""
    if not rows:
        return ""

    lines: list[str] = []
    for row in rows[-cap:]:
        ts = str(row.get("timestamp", "unknown"))
        author = str(row.get("author", "unknown"))
        content = str(row.get("content", "")).replace("\n", " ").strip()
        if len(content) > 240:
            content = content[:240] + "..."
        lines.append(f"- [{ts}] {author}: {content}")
    return "\n".join(lines)


def _build_recent_context_block(message: discord.Message, author_name: str) -> str:
    """Build a default recent-context block from transient channel memory."""
    if not settings.RECENT_CONTEXT_ENABLED:
        return ""

    lookback = max(1, settings.RECENT_CONTEXT_MESSAGE_COUNT)
    rows = lookup_messages(
        channel_id=int(getattr(message.channel, "id", 0) or 0),
        lookback=lookback + 1,
        include_bot_messages=True,
    )
    if rows:
        latest = rows[-1]
        current_text = str(getattr(message, "content", "") or "").strip()
        if (
            str(latest.get("author", "")) == author_name
            and str(latest.get("content", "")).strip() == current_text
        ):
            rows = rows[:-1]

    rendered = _format_recent_rows(rows, cap=lookback)
    if not rendered:
        return ""
    return f"[Recent channel context]\n{rendered}\n\n"


def _split_smart(text: str, limit: int = _DISCORD_MAX) -> list[str]:
    """Split *text* at natural language boundaries so each chunk ≤ *limit* chars.

    Break priority (highest first):
      1. Paragraph break (\n\n)
      2. Line break (\n)
      3. Sentence-ending punctuation followed by a space (.  !  ?)
      4. Any space (word boundary)
      5. Hard cut at *limit* as a last resort.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = -1
        for sep in ("\n\n", "\n", ". ", "! ", "? ", " "):
            pos = window.rfind(sep)
            if pos > 0:
                cut = pos + len(sep)
                break
        if cut <= 0:
            cut = limit  # absolute fallback — never exceeds limit
        chunks.append(text[:cut])
        text = text[cut:]

    if text:
        chunks.append(text)
    return chunks


def _split_hard(text: str, limit: int = _DISCORD_MAX) -> list[str]:
    """Hard-split *text* into chunks of at most *limit* chars (no crash safety net)."""
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def _send(channel: discord.abc.Messageable, content: str, *, force_silent: bool = False) -> None:
    """Send *content* to *channel*, applying silent flags when configured."""
    if _should_silent_all() or force_silent:
        await channel.send(content, silent=True)
    else:
        await channel.send(content)


async def _send_reply_with_math(
    channel: discord.abc.Messageable,
    reply: str,
    *,
    force_silent: bool = False,
    reply_to: discord.Message | None = None,
) -> None:
    """Send *reply* to *channel*, rendering embedded LaTeX blocks as PNG images.

    The reply is first parsed into alternating text / math segments.  Text
    segments are split at natural boundaries (or hard-cut when SMART_CUTOFF is
    off) and sent as normal messages.  Each math segment is rendered to a PNG
    via :mod:`tools.katex_formatter` and sent as a Discord file attachment so
    it displays inline.  If rendering fails the raw expression is sent as a
    fenced code block instead.

    If *reply_to* is given, the very first chunk (text or image) is sent as a
    Discord reply to that message so the context is visually linked in the
    channel.  All subsequent chunks are sent as regular channel messages.
    """
    segments = katex_formatter.parse_math_segments(reply)

    math_count = sum(1 for s in segments if s["type"] == "math")
    if math_count:
        log(
            f"[LLM] Rendering {math_count} LaTeX expression(s) in reply",
            LogLevel.DEBUG,
        )

    _replied = False  # True once the first chunk has been sent as a Discord reply

    for seg in segments:
        if seg["type"] == "text":
            if settings.SMART_CUTOFF:
                chunks = _split_smart(seg["content"])
            else:
                chunks = _split_hard(seg["content"])
            for chunk in chunks:
                if chunk.strip():
                    if reply_to is not None and not _replied:
                        _replied = True
                        kwargs: dict = {"content": chunk}
                        if _should_silent_all() or force_silent:
                            kwargs["silent"] = True
                        await reply_to.reply(**kwargs)
                    else:
                        await _send(channel, chunk, force_silent=force_silent)
        else:
            expr = seg["expression"]
            try:
                png_path = await asyncio.to_thread(katex_formatter.render, expr)
                try:
                    disc_file = discord.File(str(png_path))
                    if reply_to is not None and not _replied:
                        _replied = True
                        kwargs = {"file": disc_file}
                        if _should_silent_all() or force_silent:
                            kwargs["silent"] = True
                        await reply_to.reply(**kwargs)
                    else:
                        kwargs = {"file": disc_file}
                        if _should_silent_all() or force_silent:
                            kwargs["silent"] = True
                        await channel.send(**kwargs)
                finally:
                    katex_formatter.cleanup(png_path)
            except Exception as exc:
                log(
                    f"[LLM] LaTeX render failed for {expr!r}: {exc}",
                    LogLevel.ERROR,
                )
                if reply_to is not None and not _replied:
                    _replied = True
                    kwargs = {"content": f"```\n{expr}\n```"}
                    if _should_silent_all() or force_silent:
                        kwargs["silent"] = True
                    await reply_to.reply(**kwargs)
                else:
                    # Fall back to a fenced code block so the expression is still readable.
                    await _send(channel, f"```\n{expr}\n```", force_silent=force_silent)


class LLM(commands.Cog):
    """Commands that interact with the language model."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        # user_id -> {"payload": {...}, "expires_at": datetime}
        self._pending_gcal_conflicts: dict[int, dict] = {}

        # Register as the catch-all fallback — only receives messages that no
        # other cog handler claimed, so it can never swallow a known command.
        bot.set_llm_handler(self._ask)

    def _get_pending_conflict(self, user_id: int) -> dict | None:
        row = self._pending_gcal_conflicts.get(user_id)
        if not row:
            return None
        expires_at = row.get("expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
            self._pending_gcal_conflicts.pop(user_id, None)
            return None
        return row.get("payload")

    def _set_pending_conflict(self, user_id: int, payload: dict, *, ttl_minutes: int = 5) -> None:
        self._pending_gcal_conflicts[user_id] = {
            "payload": payload,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        }

    def _clear_pending_conflict(self, user_id: int) -> None:
        self._pending_gcal_conflicts.pop(user_id, None)

    async def _resolve_gcal_conflict_action(self, user_id: int, payload: dict, action: str) -> tuple[str, str]:
        request = dict(payload.get("request", {}))
        request["discord_user_id"] = user_id

        if action == "create_anyway":
            request["allow_overlap"] = True
        elif action == "move":
            suggestions = payload.get("suggestions") or []
            if not suggestions:
                return (
                    "No suggested free time slots were found in the next 24 hours.",
                    "I could not move the event because no open slot was found in the next 24 hours.",
                )
            slot = suggestions[0]
            request["start_iso"] = slot.get("start_iso")
            request["end_iso"] = slot.get("end_iso")
            request["allow_overlap"] = False
        elif action == "cancel":
            self._clear_pending_conflict(user_id)
            return (
                "Cancelled. I did not create the event.",
                "No problem. I cancelled this request and did not create a new event.",
            )
        else:
            return ("Unknown action.", "I could not resolve that action.")

        result = await asyncio.to_thread(_tool_registry.TOOLS["gcal_add_event"], request)
        self._clear_pending_conflict(user_id)
        if action == "create_anyway":
            friendly = "I've created the event for you, even with the overlap."
        else:
            friendly = "I've moved and created the event in the next available suggested slot."
        return result, friendly

    async def _maybe_resolve_conflict_from_text(self, message: discord.Message, prompt: str) -> bool:
        payload = self._get_pending_conflict(message.author.id)
        if not payload:
            return False

        text = prompt.lower().strip()
        action: str | None = None
        if any(k in text for k in ["create anyway", "do it anyway", "go ahead", "create it"]):
            action = "create_anyway"
        elif any(k in text for k in ["move", "reschedule"]):
            action = "move"
        elif any(k in text for k in ["cancel", "nevermind", "never mind", "stop"]):
            action = "cancel"
        else:
            return False

        result, friendly = await self._resolve_gcal_conflict_action(message.author.id, payload, action)
        await message.reply(result)
        await message.reply(friendly)
        return True

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _ask(self, message: discord.Message, prompt: str) -> None:
        """Send *prompt* to the LLM and reply with the response."""
        if await self._maybe_resolve_conflict_from_text(message, prompt):
            return

        log(
            f"[LLM] Prompt from {message.author} (#{message.channel}) "
            f"| {len(prompt)} chars: {prompt!r}"
        )

        loop = asyncio.get_running_loop()
        state = {"handled_conflict_prompt": False}

        # ── Discord attachment → sandbox upload ───────────────────────────────
        # If the message has file attachments, upload each one to /workspace
        # before the LLM call so the model can reference them immediately.
        # Give the model concrete temporal/user context so it can correctly
        # resolve phrases like "today at 5pm" when using calendar tools.
        user_id = int(getattr(message.author, "id", 0))
        user_nickname = (
            getattr(message.author, "display_name", None)
            or getattr(message.author, "nick", None)
            or getattr(message.author, "global_name", None)
            or getattr(message.author, "name", None)
            or str(message.author)
        )
        author_name = (
            getattr(message.author, "display_name", None)
            or str(message.author)
        )
        now_local = datetime.now().astimezone()
        runtime_context = (
            "[System runtime context]\n"
            f"- discord_user_id: {user_id}\n"
            f"- discord_nickname: {user_nickname}\n"
            f"- current_datetime: {now_local.isoformat()}\n"
            f"- current_date: {now_local.date().isoformat()}\n"
            f"- timezone: {now_local.tzname() or 'local'}\n\n"
        )
        reply_context = _extract_reply_context(message) or ""
        recent_context = _build_recent_context_block(message, author_name)
        memory_context = ""
        recall_instruction = ""
        if settings.TEMPORARY_MEMORY_ENABLED and _is_channel_recall_request(prompt):
            memory_context = (
                "[Extended channel context]\n"
                + _tool_registry.channel_history_lookup(
                    channel_id=int(getattr(message.channel, "id", 0) or 0),
                    lookback=max(settings.RECENT_CONTEXT_MESSAGE_COUNT, 12),
                    include_bot_messages=True,
                )
                + "\n\n"
            )
            recall_instruction = (
                "[Recall request handling]\n"
                "- The user is asking about prior discussion in this same channel.\n"
                "- You already have the relevant current-channel context below.\n"
                "- Do not ask for a channel ID.\n"
                "- Summarize the available prior discussion directly from the provided context.\n\n"
            )
        full_prompt = f"{reply_context}{recent_context}{memory_context}{recall_instruction}{runtime_context}{prompt}"
        if message.attachments:
            uploaded: list[str] = []
            try:
                mgr = await loop.run_in_executor(None, _get_sandbox_manager)
                for att in message.attachments:
                    try:
                        file_bytes = await att.read()
                        dest = f"{mgr.work_dir}/{att.filename}"
                        ok = await loop.run_in_executor(
                            None, mgr.copy_to_container, file_bytes, dest
                        )
                        if ok:
                            uploaded.append(att.filename)
                            log(
                                f"[LLM] Attachment '{att.filename}' "
                                f"({len(file_bytes)} bytes) uploaded to sandbox"
                            )
                        else:
                            log(
                                f"[LLM] Failed to upload attachment '{att.filename}'",
                                LogLevel.ERROR,
                            )
                    except Exception as exc:
                        log(
                            f"[LLM] Error uploading '{att.filename}': {exc}",
                            LogLevel.ERROR,
                        )
            except Exception as exc:
                log(
                    f"[LLM] Sandbox unavailable for attachment upload: {exc}",
                    LogLevel.ERROR,
                )

            if uploaded:
                names = ", ".join(f"'{n}'" for n in uploaded)
                full_prompt = (
                    f"[System: The following files were uploaded to /workspace "
                    f"and are ready to use: {names}]\n\n{full_prompt}"
                )

        def on_tool_call(tool_name: str, args: dict, result: str) -> None:
            """Called from the worker thread each time the LLM uses a tool."""
            safe_args_for_log = _redact_tool_value(args)
            safe_result_for_log = _redact_tool_text(result)
            log(
                f"[LLM] Tool call: {tool_name}({safe_args_for_log}) → {safe_result_for_log!r}",
                LogLevel.DEBUG,
            )

            if tool_name == "gcal_add_event":
                conflict_payload = _extract_conflict_payload(result)
                if conflict_payload is not None:
                    state["handled_conflict_prompt"] = True
                    async def _send_gcal_conflict() -> None:
                        self._set_pending_conflict(message.author.id, conflict_payload, ttl_minutes=5)

                        conflicts = conflict_payload.get("conflicts") or []
                        suggestions = conflict_payload.get("suggestions") or []
                        if conflicts:
                            conflict_lines = "\n".join(
                                f"• **{c.get('title', 'Untitled')}** at `{_format_iso_brief(c.get('start'))}`"
                                for c in conflicts[:3]
                            )
                        else:
                            conflict_lines = "• Existing overlapping events detected."

                        if suggestions:
                            first = suggestions[0]
                            suggestion_line = (
                                f"Suggested move: `{_format_iso_brief(first.get('start_iso'))}` "
                                f"to `{_format_iso_brief(first.get('end_iso'))}`"
                            )
                        else:
                            suggestion_line = "No free suggestion found in the next 24 hours."

                        embed = discord.Embed(
                            title="Calendar Conflict Detected",
                            description=(
                                "I noticed this event overlaps with an existing event.\n\n"
                                f"{conflict_lines}\n\n"
                                f"{suggestion_line}\n\n"
                                "Choose what to do next:"
                            ),
                            color=discord.Color.gold(),
                        )
                        embed.add_field(
                            name="Choices",
                            value="`Create anyway`  •  `Move new event`  •  `Cancel`",
                            inline=False,
                        )
                        embed.set_footer(text="You can click a button or type: create anyway / move / cancel")

                        cog = self

                        class ConflictView(discord.ui.View):
                            def __init__(self, owner_id: int, payload: dict):
                                super().__init__(timeout=300)
                                self.owner_id = owner_id
                                self.payload = payload

                            async def _finish(self, interaction: discord.Interaction, status_text: str) -> None:
                                for item in self.children:
                                    if isinstance(item, discord.ui.Button):
                                        item.disabled = True
                                embed.set_footer(text=status_text)
                                if interaction.message:
                                    with suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                                        await interaction.message.edit(view=self, embed=embed)
                                self.stop()

                            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                                if interaction.user.id != self.owner_id:
                                    await interaction.response.send_message(
                                        "This conflict prompt is not for you.",
                                        ephemeral=True,
                                    )
                                    return False
                                return True

                            @discord.ui.button(label="Create anyway", style=discord.ButtonStyle.danger)
                            async def create_anyway(self, interaction: discord.Interaction, _button: discord.ui.Button):
                                await interaction.response.defer(ephemeral=True)
                                out, friendly = await cog._resolve_gcal_conflict_action(self.owner_id, self.payload, "create_anyway")
                                await interaction.followup.send(friendly, ephemeral=True)
                                await message.reply(out)
                                await self._finish(interaction, "Resolved: create anyway")

                            @discord.ui.button(label="Move new event", style=discord.ButtonStyle.primary)
                            async def move_event(self, interaction: discord.Interaction, _button: discord.ui.Button):
                                await interaction.response.defer(ephemeral=True)
                                out, friendly = await cog._resolve_gcal_conflict_action(self.owner_id, self.payload, "move")
                                await interaction.followup.send(friendly, ephemeral=True)
                                await message.reply(out)
                                await self._finish(interaction, "Resolved: moved new event")

                            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                            async def cancel_event(self, interaction: discord.Interaction, _button: discord.ui.Button):
                                await interaction.response.defer(ephemeral=True)
                                out, friendly = await cog._resolve_gcal_conflict_action(self.owner_id, self.payload, "cancel")
                                await interaction.followup.send(friendly, ephemeral=True)
                                await message.reply(out)
                                await self._finish(interaction, "Resolved: cancelled")

                        kwargs: dict = {"embed": embed, "view": ConflictView(message.author.id, conflict_payload)}
                        if _should_silent_all() or _should_silent_toolcall():
                            kwargs["silent"] = True
                        await message.channel.send(**kwargs)

                    asyncio.run_coroutine_threadsafe(_send_gcal_conflict(), loop)
                    return

            if tool_name == "gcal_add_event" and "Error:" not in result:
                async def _send_gcal_add_embed() -> None:
                    title = str(args.get("title", "Untitled event"))
                    start_iso = args.get("start_iso")
                    end_iso = args.get("end_iso")
                    reminder_vals = args.get("reminder_minutes") or []
                    attendee_vals = args.get("attendees") or []

                    if isinstance(reminder_vals, list) and reminder_vals:
                        reminder_text = ", ".join(str(v) for v in reminder_vals) + " minutes before"
                    else:
                        reminder_text = "Default / not set"
                    attendee_vals_safe = _redact_tool_value(attendee_vals, "attendees")
                    attendee_text = (
                        ", ".join(str(v) for v in attendee_vals_safe)
                        if isinstance(attendee_vals_safe, list) and attendee_vals_safe
                        else ""
                    )

                    embed = discord.Embed(
                        title="Calendar Update",
                        description=(
                            f"I've added your reminder for **{title}**. "
                            "Let me know if you want to edit anything.\n\n"
                            "```ansi\n\u001b[1;92m+ Event added to Google Calendar\u001b[0m\n```"
                        ),
                        color=discord.Color.from_rgb(78, 203, 113),
                    )
                    embed.add_field(name="Title", value=title, inline=False)
                    embed.add_field(name="Start", value=_format_iso_brief(start_iso), inline=True)
                    embed.add_field(name="End", value=_format_iso_brief(end_iso), inline=True)
                    embed.add_field(name="Reminder", value=reminder_text, inline=False)
                    if attendee_text:
                        embed.add_field(name="Attendees", value=attendee_text, inline=False)
                    embed.timestamp = datetime.now().astimezone()

                    kwargs: dict = {"embed": embed}
                    if _should_silent_all() or _should_silent_toolcall():
                        kwargs["silent"] = True
                    await message.channel.send(**kwargs)

                asyncio.run_coroutine_threadsafe(_send_gcal_add_embed(), loop)
                return

            # ── File download: detect [__discord_file__=<path>] tag ───────────
            # get_workspace_file embeds this tag so the cog can send the file
            # to Discord while the LLM sees a clean human-readable message.
            file_match = re.search(r"\[__discord_file__=([^\]]+)\]", result)
            if file_match:
                local_path   = file_match.group(1)
                display_name = args.get("filename", os.path.basename(local_path))
                clean_result = re.sub(
                    r"\s*\[__discord_file__=[^\]]+\]", "", result
                ).strip()

                async def _send_file() -> None:
                    try:
                        disc_file = discord.File(
                            local_path,
                            filename=os.path.basename(local_path),
                        )
                        kwargs: dict = {
                            "content": f"📁 `{display_name}`",
                            "file":    disc_file,
                        }
                        if _should_silent_all() or _should_silent_toolcall():
                            kwargs["silent"] = True
                        await message.channel.send(**kwargs)
                    except Exception as exc:
                        log(
                            f"[LLM] Failed to send file '{local_path}' "
                            f"to Discord: {exc}",
                            LogLevel.ERROR,
                        )
                    finally:
                        with suppress(OSError):
                            os.remove(local_path)

                asyncio.run_coroutine_threadsafe(_send_file(), loop)

                # Also show the human-readable confirmation as a tool notice.
                if _should_show_toolcall_notices():
                    args_safe = _redact_tool_value(args)
                    clean_result_safe = _redact_tool_text(clean_result)
                    args_str = ", ".join(f"{k}={v!r}" for k, v in args_safe.items())
                    notice = f"📁 **{tool_name}**({args_str}) → {clean_result_safe}"
                    asyncio.run_coroutine_threadsafe(
                        _send(
                            message.channel, notice,
                            force_silent=_should_silent_toolcall(),
                        ),
                        loop,
                    )
                return

            # ── Safety response: detect [__safety_response__=<type>] tag ─────
            # send_crisis_response / send_pr_deflection embed this tag so the
            # cog sends the correct pre-written message directly to Discord
            # without exposing the raw sentinel string as a tool notice.
            safety_match = re.search(
                rf"\[{re.escape(SAFETY_RESPONSE_TAG)}=([^\]]+)\]", result
            )
            if safety_match:
                response_type = safety_match.group(1)
                if response_type.startswith("crisis"):
                    safety_msg = _CRISIS_RESPONSE
                else:
                    safety_msg = _PR_DEFLECTION_RESPONSE
                asyncio.run_coroutine_threadsafe(
                    _send(message.channel, safety_msg),
                    loop,
                )
                return  # suppress normal tool notice

            # ── Normal tool-call notice ───────────────────────────────────────
            safe_args = {k: v for k, v in args.items() if k != "discord_user_id"}
            safe_args = cast(dict, _redact_tool_value(safe_args))
            safe_result = _redact_tool_text(result)
            if _should_show_toolcall_notices():
                args_str = ", ".join(f"{k}={v!r}" for k, v in safe_args.items())
                notice = f"🔧 **{tool_name}**({args_str}) → `{safe_result}`"
                asyncio.run_coroutine_threadsafe(
                    _send(
                        message.channel, notice,
                        force_silent=_should_silent_toolcall(),
                    ),
                    loop,
                )

        def tool_args_transform(tool_name: str, args: dict) -> dict:
            # Never trust model-supplied identity for calendar actions.
            if tool_name.startswith("gcal_"):
                updated = dict(args)
                updated["discord_user_id"] = user_id
                return updated
            if tool_name == "channel_history_lookup":
                updated = dict(args)
                updated["channel_id"] = int(getattr(message.channel, "id", 0) or 0)
                return updated
            return args

        async with message.channel.typing():
            try:
                log(f"[LLM] Sending request to API (tool calls enabled, max={MAX_TOOL_CALLS})…", LogLevel.DEBUG)
                reply = await loop.run_in_executor(
                    None,
                    lambda: chat(
                        full_prompt,
                        system_prompt=SYSTEM_PROMPT,
                        on_tool_call=on_tool_call,
                        tool_args_transform=tool_args_transform,
                    ),
                )
                log(
                    f"[LLM] Response received for {message.author} "
                    f"| {len(reply)} chars"
                )

                # Guard: block any reply that echoes the system prompt.
                if contains_prompt_leak(reply):
                    log(
                        f"[LLM] Prompt leak detected in response for "
                        f"{message.author} — reply blocked",
                        LogLevel.WARNING,
                    )
                    await message.reply("⚠️ I can't share that information.")
                    return

                # Guard: strip any safety sentinel tags the LLM may have
                # echoed verbatim in its text reply.  The tool call already
                # sent the correct safety message; echoing the raw sentinel
                # would expose internal tags to the Discord channel.
                reply = _SAFETY_SENTINEL_RE.sub("", reply).strip()
                reply = _GCAL_CONFLICT_RE.sub("", reply).strip()
                if _looks_like_internal_tool_inventory(reply):
                    log(
                        f"[LLM] Internal tool inventory leak blocked for {message.author}",
                        LogLevel.WARNING,
                    )
                    await message.reply(
                        "I can help with many tasks, but I can’t share internal command or tool details."
                    )
                    return
                if state["handled_conflict_prompt"]:
                    # Conflict embed/buttons already provided canonical choices.
                    # Suppress model prose to avoid contradictory guidance.
                    return
                if not reply:
                    # The tool call said everything that needed saying.
                    return

            except Exception as exc:
                log(
                    f"[LLM] API error for {message.author} "
                    f"| prompt: {prompt!r} | {type(exc).__name__}: {exc}",
                    LogLevel.ERROR,
                )
                # Truncate the exception message so it always fits in a Discord
                # message — raw API responses can be thousands of characters.
                err_str = str(exc)
                _ERR_LIMIT = _DISCORD_MAX - 40  # leave room for the prefix + backticks
                if len(err_str) > _ERR_LIMIT:
                    err_str = err_str[:_ERR_LIMIT] + "…"
                await message.reply(f"⚠️ The LLM returned an error: `{err_str}`")
                return

            # Send the reply inside the typing context so the indicator stays
            # active during the full reply delivery (including LaTeX rendering).
            # Text is split at natural boundaries; math is rendered inline.
            await _send_reply_with_math(message.channel, reply, reply_to=message)


async def setup(bot: commands.Bot) -> None:
    """Entry point called by Bot.load_extension."""
    await bot.add_cog(LLM(cast(Bot, bot)))
