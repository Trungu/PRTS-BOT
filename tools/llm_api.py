# tools/llm_api.py — thin wrapper around an OpenAI-compatible chat completions API.
#
# Supports:
#   • Simple string input  → chat("Say hello")
#   • Structured history   → chat([{"role": "user", "content": "..."}, ...])
#
# Agentic tool-call loop:
#   The model may call any registered tool up to MAX_TOOL_CALLS (99) times
#   before returning a final text reply.  Tool results are injected back into
#   the conversation as "tool" role messages so the model can chain calls.
#
# Valid message roles:
#   "system"    — sets the model's behaviour / persona
#   "user"      — a message from the human
#   "assistant" — a previous reply from the model
#   "tool"      — the result returned by a tool call

from __future__ import annotations

import json
import requests
from typing import Callable, Literal, TypedDict

import settings
from tools.toolcalls.tool_registry import TOOLS, TOOL_DEFINITIONS

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Role = Literal["system", "user", "assistant", "tool"]


class Message(TypedDict):
    """A single turn in a conversation."""
    role: Role
    content: str


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL  = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL     = "llama-3.1-8b-instant"
MAX_TOOL_CALLS     = 99   # hard ceiling on agentic iterations

# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def chat(
    messages: str | list[Message],
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: int = 30,
    enable_tools: bool = True,
    on_tool_call: Callable[[str, dict, str], None] | None = None,
) -> str:
    """Send a chat request and handle agentic tool-call loops automatically.

    Parameters
    ----------
    messages:
        Either a plain string (treated as a single ``user`` message) or a list
        of ``Message`` dicts with ``role`` and ``content`` keys.
    system_prompt:
        Convenience shortcut — prepended as a ``system`` message when
        *messages* is a plain string.  Ignored when *messages* is a list.
    model:
        Model identifier.  Falls back to ``LLM_MODEL`` env var, then the
        built-in default.
    temperature:
        Sampling temperature (0 = deterministic, 2 = very random).
    max_tokens:
        Upper limit on reply length in tokens per request.
    timeout:
        HTTP request timeout in seconds.
    enable_tools:
        Set to ``False`` to skip tool definitions entirely (plain chat mode).
    on_tool_call:
        Optional callable invoked synchronously after each tool executes.
        Receives ``(tool_name: str, args: dict, result: str)``.
        Use this to send Discord notifications from the calling coroutine via
        ``asyncio.run_coroutine_threadsafe``.

    Returns
    -------
    str
        The model's final text reply, stripped of leading/trailing whitespace.

    Raises
    ------
    requests.HTTPError
        When the API returns a non-2xx status code.
    ValueError
        When the response JSON is missing expected fields.
    """
    # --- Build the message list ------------------------------------------------
    if isinstance(messages, str):
        payload_messages: list[dict] = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.append({"role": "user", "content": messages})
    else:
        payload_messages = [dict(m) for m in messages]

    # --- Resolve configuration ------------------------------------------------
    base_url   = (settings.LLM_BASE_URL or _DEFAULT_BASE_URL).rstrip("/")
    model_name = model or settings.LLM_MODEL or _DEFAULT_MODEL
    url        = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type":  "application/json",
    }

    # --- Agentic loop ---------------------------------------------------------
    tool_calls_made = 0

    while True:
        body: dict = {
            "model":       model_name,
            "messages":    payload_messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }

        # Attach tool definitions while we're still under the cap.
        if enable_tools and TOOL_DEFINITIONS and tool_calls_made < MAX_TOOL_CALLS:
            body["tools"]       = TOOL_DEFINITIONS
            body["tool_choice"] = "auto"

        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        try:
            choice  = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected API response shape: {data}") from exc

        finish_reason = choice.get("finish_reason", "stop")

        # --- Tool call branch -------------------------------------------------
        if finish_reason == "tool_calls" and tool_calls_made < MAX_TOOL_CALLS:
            raw_calls = message.get("tool_calls", [])

            # Add the assistant's tool-call message to history.
            payload_messages.append({
                "role":       "assistant",
                "content":    message.get("content") or "",
                "tool_calls": raw_calls,
            })

            # Execute each tool and append results.
            for tc in raw_calls:
                tool_call_id = tc["id"]
                fn_name      = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"].get("arguments", "{}"))
                except json.JSONDecodeError:
                    fn_args = {}

                if fn_name in TOOLS:
                    try:
                        result = TOOLS[fn_name](fn_args)
                    except Exception as exc:
                        result = f"Error: tool raised {type(exc).__name__}: {exc}"
                else:
                    result = f"Error: unknown tool '{fn_name}'"

                payload_messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call_id,
                    "name":         fn_name,
                    "content":      str(result),
                })

                if on_tool_call is not None:
                    on_tool_call(fn_name, fn_args, str(result))

                tool_calls_made += 1

            # Loop: send results back to the model.
            continue

        # --- Final text reply -------------------------------------------------
        content = message.get("content") or ""
        if not content and finish_reason != "tool_calls":
            raise ValueError(f"Unexpected API response shape: {data}")

        return content.strip()
