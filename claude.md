# PRTS-BOT — AI Assistant Reference Guide

> Written for future AI assistants working on this codebase.
> Read this **before touching any file**. It will save you from breaking
> things that are deliberately designed a specific way.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Folder Structure](#2-folder-structure)
3. [How the Bot Works End-to-End](#3-how-the-bot-works-end-to-end)
4. [The Message Dispatch Model (Critical)](#4-the-message-dispatch-model-critical)
5. [Settings System](#5-settings-system)
6. [How to Add a New Command](#6-how-to-add-a-new-command)
7. [How to Add a New Tool (LLM callable)](#7-how-to-add-a-new-tool-llm-callable)
8. [The Admin System](#8-the-admin-system)
9. [The Docker Sandbox](#9-the-docker-sandbox)
10. [LLM Integration](#10-llm-integration)
11. [Testing Rules and Patterns](#11-testing-rules-and-patterns)
12. [Code Conventions](#12-code-conventions)
13. [What NOT to Do](#13-what-not-to-do)
14. [Quick Checklist for Any Change](#14-quick-checklist-for-any-change)
15. [Crisis / Distress Detection](#15-crisis--distress-detection)
16. [Rate Limiter](#16-rate-limiter)

---

## 1. Project Overview

This is a **public-facing Discord bot** running in a server watched by CEOs and
non-technical stakeholders. Quality, reliability, and security are paramount.
It is an engineering assistant that can:

- Answer freeform questions via an LLM (Groq API, OpenAI-compatible)
- Execute Python code in an isolated Docker sandbox (gVisor runtime)
- Run arbitrary shell commands in the same sandbox
- Perform unit conversions
- Evaluate mathematical expressions safely
- Render LaTeX/math to PNG images and send them inline
- Transfer files from the sandbox to Discord
- Operate in **admin-only mode** (restricting commands to a whitelist of user IDs)

**Python version:** 3.12 (venv at `.venv/`)  
**Run command:** `.venv/bin/python main.py`  
**Test command:** `.venv/bin/python -m pytest` (must always be 0 failures)

---

## 2. Folder Structure

```
main.py                  — Entry point. Creates Bot(), calls bot.run(token). 4 lines.
settings.py              — ALL env vars live here. Never call os.getenv elsewhere.
admin.txt                — Discord user IDs allowed in admin-only mode (one per line).
requirements.txt         — pip dependencies.

bot/
  __init__.py            — re-exports Bot so `from bot import Bot` works.
  client.py              — Bot subclass. Central on_message dispatcher. READ THIS FIRST.
  cogs/
    general.py           — hello, clear history commands.
    llm.py               — LLM chat handler. Agentic tool-call loop, LaTeX rendering.
    admin.py             — admin only / admin off commands.

utils/
  prefix_handler.py      — Prefix matching (get_command, has_prefix).
  command_registry.py    — Registry of known command names (used by LLM to avoid stealing).
  logger.py              — Structured logger (log(), LogLevel enum).
  prompts.py             — SYSTEM_PROMPT and prompt-leak guard (contains_prompt_leak).
  admin.py               — Admin-only mode state machine + admin.txt parser.
  crisis_detector.py     — Distress keyword detection + CRISIS_RESPONSE message.
  rate_limiter.py        — Per-user rate limiting with escalating stages.

tools/
  llm_api.py             — HTTP wrapper around OpenAI-compatible chat completions API.
  katex_formatter.py     — LaTeX → PNG renderer via matplotlib mathtext.
  toolcalls/
    calculator.py        — Safe AST-based arithmetic evaluator.
    code_runner.py       — run_python() — executes code in Docker sandbox.
    terminal_runner.py   — run_terminal() — executes shell commands in sandbox.
    unit_converter.py    — Engineering unit converter (SI-based).
    tool_registry.py     — Maps tool names → callables + OpenAI tool definitions.
    safety_responder.py  — LLM-callable tools: send_crisis_response, send_pr_deflection.
  docker/
    docker_manager.py    — DockerManager: starts/stops/executes in the sandbox container.
    Dockerfile           — Sandbox image definition. Python 3.13, Java JDK, gVisor.
    update_docker.py     — Script to rebuild the image when packages change.

sandbox_workspace/       — Host-side bind mount for /workspace inside the container.
                           Files here persist across container restarts.

tests/                   — Pytest tests. One file per module. Run before every commit.
```

---

## 3. How the Bot Works End-to-End

```
User types:  "gemma, hello"
                  │
                  ▼
          bot/client.py  on_message()
                  │
          [crisis gate] detect_crisis(message.content)?
                  │  YES → send CRISIS_RESPONSE (then CONTINUE — do not return)
                  │  NO  → continue
                  │
          prefix_handler.get_command()  →  strips prefix  →  "hello"
                  │  (None if no prefix → return)
                  │
          [admin gate] is_admin_only() and not is_allowed(author.id)?
                  │  YES → send "⛔ Admin-only mode is active." and return
                  │  NO  → continue
                  │
          [ban gate] is_banned(author.id) and not is_allowed(author.id)?
                  │  YES → send "⛔ You have been banned." and return
                  │  NO  → continue
                  │
          [rate-limit gate] (admins bypass)
                  │  COOLDOWN  → send cooldown message and return
                  │  RATE_LIMITED → send rejection message and return
                  │  WARNING   → send warning (then CONTINUE — do not return)
                  │  ALLOWED   → continue
                  │
          Walk _command_handlers (longest key first)
                  │
          "hello" matches → call General._hello(message, "hello")
                  │
          General._hello  →  message.channel.send("Hello!")
```

For unrecognised input (no registered command matches), `on_message` falls back
to `LLM._ask()`, which calls the Groq API with the full prompt and streams the
reply back. The LLM may call tools (calculator, run_python, etc.) in a loop
before producing its final text reply.

---

## 4. The Message Dispatch Model (Critical)

**Read this before adding any command or handler.**

### Single dispatcher in `bot/client.py`

All routing lives in `Bot.on_message()`. Cogs **never** listen to `on_message`
themselves. They only register handlers at `__init__` time:

```python
bot.register_command("my command", self._handler)   # exact / prefix match
bot.set_llm_handler(self._ask)                       # catch-all fallback (only one)
```

### Sequential LLM processing

`Bot` holds a single `asyncio.Lock` (`self._llm_lock`).  Every call to
`_llm_handler` is wrapped with `async with self._llm_lock:` so only one LLM
request runs at a time.  When multiple users send prompts concurrently each
request queues behind the current one — responses never interleave.  Registered
command handlers (non-LLM) are **not** serialised; they bypass the lock
entirely and remain concurrent.

### Longest-match wins

`register_command("clear")` and `register_command("clear history")` can
coexist. The dispatcher tries **longest key first**, so `"clear history all"`
correctly hits the `"clear history"` handler, not the `"clear"` handler.

### Prefix variants

`settings.BOT_PREFIX` is a list (currently `["gemma"]`).
`settings.PREFIX_SMART_CHARS` appends suffixes like `" "`, `", "`, `". "`.
`prefix_handler._VARIANTS` is built **once at import time** and sorted
longest-first.

If you need to test prefix matching, **monkeypatch `settings.BOT_PREFIX` and
then `importlib.reload(prefix_handler)`** — see `test_prefix_handler.py` for
the exact pattern.

### LLM is the fallback

`bot.set_llm_handler()` can only be called once (one fallback). The LLM cog
calls it in `LLM.__init__()`. Any message that matches a registered prefix
but has no matching command key falls through to the LLM.

### Crisis gate (runs before prefix check)

The very first check in `on_message`, before even stripping the prefix:

```python
if detect_crisis(message.content):
    await message.channel.send(CRISIS_RESPONSE)
# Does NOT return — processing continues normally.
```

Key properties:
- Fires on **every** non-bot message, regardless of prefix, admin mode, or ban status.
- Does **not** short-circuit the rest of `on_message` — if the message also has
  a valid prefix, the command is still dispatched after the crisis response.
- `detect_crisis` and `CRISIS_RESPONSE` are imported at module level from
  `utils.crisis_detector`. In tests, monkeypatch them at the import site:

```python
monkeypatch.setattr("bot.client.detect_crisis", lambda text: True)
```

### Admin gate

Immediately after prefix-stripping, before any command dispatch:

```python
if is_admin_only() and not is_allowed(message.author.id):
    await message.channel.send("⛔ Admin-only mode is active.")
    return
```

Both `is_admin_only` and `is_allowed` are **monkeypatched at the `bot.client`
module level** in tests (not at `utils.admin`). Always patch
`bot.client.is_admin_only` and `bot.client.is_allowed`.

### Rate-limit gate

After the admin and ban gates, before command dispatch:

```python
if not is_allowed(message.author.id):
    rl_result = check_rate_limit(message.author.id)
    if rl_result == RateLimitResult.COOLDOWN:
        await message.channel.send(COOLDOWN_MESSAGE)
        return
    if rl_result == RateLimitResult.RATE_LIMITED:
        await message.channel.send(RATE_LIMITED_MESSAGE)
        return
    if rl_result == RateLimitResult.WARNING:
        await message.channel.send(WARNING_MESSAGE)
        # Do NOT return — the message is still processed.
```

Key properties:
- **Admins bypass entirely.** If `is_allowed(user_id)` is `True`, the rate
  limiter is never consulted.
- Three escalating stages: WARNING (soft, message still processed),
  RATE_LIMITED (hard rejection), COOLDOWN (extended rejection after repeated
  violations).
- `check_rate_limit` is imported at module level from `utils.rate_limiter`.
  In tests, monkeypatch at the import site:

```python
monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.ALLOWED)
```

---

## 5. Settings System

**`settings.py` is the one and only place environment variables are read.**

```python
from settings import BOT_PREFIX, DISCORD_TOKEN, LLM_API_KEY  # correct
os.getenv("DISCORD_TOKEN")  # WRONG — never do this outside settings.py
```

### Key settings

| Variable | Type | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | str | Bot token (required) |
| `LLM_PROVIDER` | str | LLM backend selector (`groq` default, `ollama` optional) |
| `LLM_API_KEY` | str\|None | API key for hosted LLM providers; optional for Ollama |
| `LLM_BASE_URL` | str\|None | API endpoint override (default: Groq or Ollama local URL) |
| `LLM_MODEL` | str\|None | Model name override |
| `BOT_PREFIX` | list[str] | Trigger word(s) e.g. `["gemma"]` |
| `PREFIX_SMART_CHARS` | list[str] | Suffix variants e.g. `[" ", ", ", ". "]` |
| `PREFIX_CASE_SENSITIVE` | bool | Case sensitivity (default: False) |
| `REPLY_TRIGGER_ENABLED` | bool | Allow direct replies to bot messages without prefix |
| `RECENT_CONTEXT_ENABLED` | bool | Inject a small recent channel context window into every LLM prompt |
| `RECENT_CONTEXT_MESSAGE_COUNT` | int | Number of prior messages included in the default recent context window |
| `TEMPORARY_MEMORY_ENABLED` | bool | Enable deeper in-memory channel-history lookup |
| `TEMP_MEMORY_BUFFER_SIZE` | int | Max stored messages per channel for transient memory |
| `TEMP_MEMORY_MAX_LOOKBACK` | int | Max messages returned by transient history lookup |
| `TOOLCALL_SILENT` | bool | Silent notifications for tool calls |
| `GLOBAL_SILENT` | bool | Silent flag on every bot message |
| `SMART_CUTOFF` | bool | Smart vs. hard message splitting at 2000 chars |
| `KATEX_BG_COLOR` | str | LaTeX render background ("none" = transparent) |
| `KATEX_FG_COLOR` | str | LaTeX render text color |
| `KATEX_FONT_SIZE` | int | LaTeX render font size (pt) |
| `KATEX_DPI` | int | LaTeX render DPI |

### `get_env_var(name, required=True)`

Use the helper when adding new env vars to `settings.py`. It raises
`RuntimeError` on startup if a required var is missing — fail-fast behaviour
intended for production.

### Tests

`tests/conftest.py` sets fake env vars (`DISCORD_TOKEN=test-discord-token`,
`LLM_API_KEY=test-llm-key`) via `os.environ.setdefault` so importing
`settings` in tests never raises.

---

## 6. How to Add a New Command

Follow this exact pattern (copied from `general.py`):

### Step 1 — Create or edit a cog in `bot/cogs/`

```python
# bot/cogs/myfeature.py
from __future__ import annotations
from typing import cast
import discord
from discord.ext import commands
from bot.client import Bot
from utils.logger import log

class MyFeature(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        bot.register_command("my command", self._my_command)
        # Multi-word commands are supported: "my command sub" also works.

    async def _my_command(self, message: discord.Message, _command: str) -> None:
        await message.channel.send("Response here")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyFeature(cast(Bot, bot)))
```

### Step 2 — Nothing else needed for loading

`bot/client.py` auto-loads every `.py` file in `bot/cogs/` that has a `setup`
coroutine. Files starting with `_` are skipped. The load order is alphabetical.

### Step 3 — Write tests

Follow `tests/test_general_cog.py`. Use a `DummyBot` with a `.registered` dict,
a `DummyChannel` with a `.sent` list, and a `DummyMessage`. Run handlers with
`asyncio.run(cog._my_command(...))`.

### Important: do NOT use `command_registry.register()` for routing

`command_registry` is used only by the LLM cog to know what commands exist so
it doesn't accidentally handle them. The actual routing is done purely by
`bot.register_command()`. New cogs **do not need to call `command_registry`**
unless the LLM cog needs to be told about them explicitly (rare).

---

## 7. How to Add a New Tool (LLM callable)

Tools are Python functions the LLM can invoke during its reasoning loop.

### Step 1 — Create `tools/toolcalls/mytool.py`

```python
from __future__ import annotations

def my_tool(param: str) -> str:
    """Does something. Returns a plain string result."""
    # ... implementation ...
    return "result"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "One sentence description for the LLM.",
        "parameters": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "What this param does."},
            },
            "required": ["param"],
        },
    },
}
```

### Step 2 — Register in `tools/toolcalls/tool_registry.py`

```python
from tools.toolcalls.mytool import my_tool, TOOL_DEFINITION as _MY_DEF

TOOLS["my_tool"] = lambda args: my_tool(args["param"])
TOOL_DEFINITIONS.append(_MY_DEF)
```

### Step 3 — Document in the system prompt (`utils/prompts.py`)

Add a bullet point under the TOOLS section of `SYSTEM_PROMPT` so the LLM
knows the tool exists and when to use it.

### Step 4 — Write tests

Follow `tests/test_calculator.py` or `tests/test_unit_converter.py`. Test the
tool function directly — no mocking needed. The tool registry wiring can be
checked in `tests/test_tool_registry.py`.

---

## 8. The Admin System

### Files

| File | Purpose |
|---|---|
| `admin.txt` | Whitelist of Discord user IDs (snowflake integers). One per line. Lines starting with `#` and blank lines are ignored. |
| `utils/admin.py` | State machine. Single source of truth for `_admin_only` flag and `_allowed_ids` set. |
| `bot/cogs/admin.py` | Commands: `admin only`, `admin off`, `ban`, `unban`, `delete response`, `delete count`, `delete time`. All gated behind `is_allowed()`. |
| `bot/client.py` | Enforces the gate in `on_message()`. |

### Key functions in `utils/admin.py`

```python
load_admin_file(path)       # Parse a file, return set[int]. Does NOT update state.
reload_allowed_users(path)  # Parse and UPDATE _allowed_ids. Called before locking down.
is_allowed(user_id: int)    # Membership check against _allowed_ids.
set_admin_only(bool)        # Toggle the mode flag.
is_admin_only()             # Read the mode flag.
```

### State is module-level

`_admin_only` and `_allowed_ids` are module-level globals in `utils/admin.py`.
In tests, monkeypatch them directly:

```python
monkeypatch.setattr(admin_module, "_allowed_ids", {42})
monkeypatch.setattr(admin_module, "_admin_only", False)
```

### Patching in client-level tests

When testing `Bot.on_message` admin gate behaviour, patch at the **import
site** (where `bot/client.py` imported the names), not at the source:

```python
monkeypatch.setattr("bot.client.is_admin_only", lambda: True)
monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
```

### `reload_allowed_users` is called before enabling

When `admin only` is issued, the cog calls `reload_allowed_users()` **before**
setting the flag. This ensures any edits made to `admin.txt` since startup are
picked up immediately. If you add logic that depends on the allowed list at
lock-down time, call `reload_allowed_users()` first.

### Delete commands

Three message-deletion commands are registered by `AdminCog`.  All require the
caller to be listed in `admin.txt`.

**Critical rule: delete commands ONLY delete the bot's own messages.  User
messages are NEVER deleted.**  This is enforced by checking
`msg.author.id == self.bot.user.id` (for `delete response` and `delete count`)
or by passing a `check` filter to `channel.purge()` (for `delete time`).

| Command | Behaviour |
|---|---|
| `delete response` | Scans history backwards from the command message. Deletes every consecutive message **authored by this bot** until a non-bot message is reached, then stops. The user's command message is **not** deleted. If no bot messages are found, sends an info message. |
| `delete count <N>` | Scans history and deletes the previous N channel messages regardless of author, then also deletes the invoking command message. N must be a positive integer. |
| `delete time <duration>` | Purges up to 500 **bot-authored** messages sent within the last `<duration>` by passing `check=lambda msg: msg.author.id == bot_id` to `channel.purge()`. User messages are never touched. |

#### Duration format (`delete time`)

Parsed by `_parse_duration()` in `bot/cogs/admin.py`.  Accepts any combination
of `h` (hours), `m` (minutes), `s` (seconds) in **any order**.

```
1h        → 3 600 s
30m       → 1 800 s
1h30m     → 5 400 s
1m1h      → 3 660 s   (any order is fine)
2h1m30s   → 7 290 s
```

Returns `None` (rejected) if the string is empty, contains characters other
than digits + `h`/`m`/`s`, or resolves to zero seconds.  Colon-style formats
like `5:00` are explicitly rejected.

#### `_bulk_delete(channel, messages)`

Module-level async helper in `bot/cogs/admin.py`.  Handles Discord's
2–100-message requirement for `delete_messages`: single-item lists call
`message.delete()` directly; larger lists are sent in batches of 100.

---

## 9. The Docker Sandbox

### Architecture

```
DockerManager (tools/docker/docker_manager.py)
  │
  ├── Container name:  ai_sandbox_env
  ├── Image name:      ai_sandbox_image  (build from tools/docker/Dockerfile)
  ├── Runtime:         --runtime=runsc  (gVisor — syscall-level isolation)
  ├── Network:         none
  ├── Memory:          1 GB (swap disabled)
  ├── CPUs:            2
  ├── Capabilities:    ALL dropped
  ├── User:            sandboxuser (uid 1000, non-root)
  ├── /tmp:            ephemeral tmpfs (runner scripts land here, deleted after run)
  └── /workspace:      bind-mounted from sandbox_workspace/ (persistent)
```

### Singleton pattern

Both `code_runner.py` and `terminal_runner.py` keep a `_manager` module-level
singleton. `_get_manager()` lazily starts the container on first use.
`DockerManager.start_container()` is **idempotent** — safe to call multiple
times.

### /workspace vs /tmp

- `/tmp` — ephemeral. Runner scripts (`run_<uuid>.py`) are written here and
  deleted immediately after execution.
- `/workspace` — persistent bind-mount pointing to `sandbox_workspace/` on
  the host. Files the user's code writes here survive restarts and rebuilds.

### Rebuilding the image

Use `tools/docker/update_docker.py`. It handles backup of workspace files,
removes the old container, rebuilds the image, and restores files. Run it
whenever you change the `Dockerfile`.

```bash
cd tools/docker && python update_docker.py
```

### Adding packages to the sandbox

Edit `tools/docker/Dockerfile` (the `pip install` block) and run
`update_docker.py`. Do NOT pip-install inside a running container — it will
not persist across rebuilds.

---

## 10. LLM Integration

### Provider

Groq API by default (`https://api.groq.com/openai/v1`, model
`openai/gpt-oss-20b`). Local Ollama is also supported via
`LLM_PROVIDER=ollama` (default `http://localhost:11434/v1`, model
`llama3.1:8b`). Fully OpenAI-compatible — swap providers or override
`LLM_BASE_URL` and `LLM_MODEL` in `.env`.

### `tools/llm_api.py` — `chat()`

```python
chat(
    messages,           # str or list[Message dicts]
    system_prompt=...,  # prepended when messages is a str
    model=...,
    temperature=0.7,
    max_tokens=1024,
    timeout=30,
    enable_tools=True,
    on_tool_call=...,   # callback(tool_name, args_dict, result_str)
)  # → str (final reply)
```

The function runs an **agentic loop**: if the model returns `finish_reason =
"tool_calls"`, the requested tools are executed and results are injected back
as `tool` role messages. This repeats up to `MAX_TOOL_CALLS = 99` times.

### `on_tool_call` callback

Used by `LLM._ask()` to send Discord notifications from inside the worker
thread (which runs in a `ThreadPoolExecutor`). It uses
`asyncio.run_coroutine_threadsafe(coroutine, loop)` to post to the async
event loop. Do NOT `await` inside `on_tool_call` — it is synchronous.

### LaTeX rendering

The LLM reply is parsed by `katex_formatter.parse_math_segments()` into
alternating `{"type": "text", ...}` and `{"type": "math", ...}` segments.
Math segments are rendered to a PNG via `matplotlib.mathtext` (no TeX
installation required) and sent as Discord file attachments.

Render failures fall back gracefully to a fenced code block. Temp PNG files
are deleted by `katex_formatter.cleanup()` after sending.

### Reply threading

`_send_reply_with_math` accepts an optional `reply_to: discord.Message | None`
parameter.  When provided, the **first chunk only** (text or image) is sent
via `reply_to.reply()` so Discord shows the context link back to the user's
original message.  All subsequent chunks are sent with a plain `channel.send()`.
Error responses (`⚠️ prompt leak`, `⚠️ API error`) also use `message.reply()`
so every bot response is visually linked to the message that triggered it.

### Prompt leak guard

`utils/prompts.contains_prompt_leak(response)` uses a sliding window of 30
characters across the normalised system prompt. Any reply containing a 30-char
verbatim fragment from the prompt is blocked and replaced with
`"⚠️ I can't share that information."`.

### File attachments

If the user attaches files to a Discord message, `LLM._ask()` uploads them to
`/workspace` in the sandbox before calling the API. A `[System: files uploaded]`
prefix is prepended to the prompt so the LLM knows they are available.

---

## 11. Testing Rules and Patterns

### Run tests

```bash
.venv/bin/python -m pytest          # all tests
.venv/bin/python -m pytest tests/test_admin_cog.py -v  # one file
```

**All tests must pass before any commit. Currently: 409 tests, 0 failures.**

### Test file naming

One test file per module: `test_<module_name>.py`. Place in `tests/`.

For large modules with clearly distinct layers it is acceptable to split into
multiple files using a `test_<module>_<layer>.py` naming scheme. The current
example is the admin system:

| File | What it covers |
|---|---|
| `tests/test_admin_utils.py` | `utils/admin.py` pure-function layer: `load_admin_file`, `reload_allowed_users`, `is_allowed`, `set_admin_only`, `is_admin_only`, `_save_state`/`load_state`, `ban_user`/`unban_user`/`is_banned`, banned-IDs persistence |
| `tests/test_admin_cog.py` | `bot/cogs/admin.py` cog handlers + `Bot.on_message` integration: `_parse_user_id`, all command handlers, admin gate, ban gate |
| `tests/test_admin_delete.py` | Delete-message commands: `_parse_duration`, `_delete_response`, `_delete_count`, `_delete_time` |

### `conftest.py`

Sets `DISCORD_TOKEN` and `LLM_API_KEY` as fake env vars via
`os.environ.setdefault`. This means `settings.py` imports cleanly in tests.
If you add a new **required** env var to `settings.py`, add a matching
`setdefault` in `conftest.py`.

### DummyBot / DummyMessage / DummyChannel pattern

Do not import real `discord.py` objects in tests — they require an event loop
and token. Use simple classes:

```python
class DummyBot:
    def __init__(self):
        self.registered = {}
    def register_command(self, name, handler):
        self.registered[name] = handler

class DummyChannel:
    def __init__(self):
        self.sent = []
    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))

class DummyMessage:
    def __init__(self, user_id=0):
        self.author = DummyAuthor(user_id)
        self.channel = DummyChannel()
    async def reply(self, content=None, **kwargs):
        """Delegates to channel.send so msg.channel.sent captures replies too."""
        await self.channel.send(content, **kwargs)
```

### Running async handlers in tests

```python
asyncio.run(cog._my_handler(cast(Any, msg), "command"))
```

### Monkeypatching prefix_handler

Because `_VARIANTS` is built at import time, you must reload the module after
patching settings:

```python
monkeypatch.setattr(settings, "BOT_PREFIX", ["prts"])
ph = importlib.reload(prefix_handler)
assert ph.get_command("prts hello") == "hello"
```

### Monkeypatching admin state in client tests

Always patch at the `bot.client` import site:

```python
monkeypatch.setattr("bot.client.is_admin_only", lambda: True)
monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
```

### What to test for a new feature

Minimum coverage expected:
- Happy path
- Unhappy path / error branch
- Permission/guard rejection (if applicable)
- Registration (is the command/handler correctly registered?)
- State changes (do flags/state update correctly?)

---

## 12. Code Conventions

### Imports

- `from __future__ import annotations` at the top of every non-trivial file.
- All imports from `settings` directly: `from settings import FOO`.
- Relative imports are not used; everything is absolute.

### Type hints

Full type hints everywhere. Use `str | None` (PEP 604) not `Optional[str]`.
`cast(Any, ...)` is used in tests to silence type-checker complaints about
duck-typed dummies.

### File headers

Every Python file starts with a `# path/file.py — one-line description.` comment.

### Logging

Use `log(message, LogLevel.INFO)` from `utils/logger.py`. Never use `print()`
in production code (Docker manager uses `print()` as an exception — that's OK
for low-level infrastructure). Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

### Discord message sending

Always go through `_send()` in `bot/cogs/llm.py` when inside the LLM cog —
it applies `GLOBAL_SILENT` flags. In other cogs, use
`await message.channel.send(...)` directly.

For the **final LLM reply** and any error responses in `_ask`, use
`message.reply()` (or pass `reply_to=message` to `_send_reply_with_math`) so
Discord links the response back to the triggering message.  Tool-call notices
(`🔧 tool()`) and file-send notices are informational and use plain
`channel.send()`.

### 2000-character limit

Discord enforces a 2000-character message limit. The LLM cog handles splitting
via `_split_smart()` (paragraph/sentence/word boundaries) when
`settings.SMART_CUTOFF = True`, or `_split_hard()` as a fallback. If you send
a long message outside the LLM cog, you must handle splitting yourself.

### Error handling in cogs

Always catch exceptions and reply with a user-facing message rather than
letting an unhandled exception silently swallow the request. The LLM cog's
`_ask()` handler is a good reference for this pattern.

---

## 13. What NOT to Do

1. **Do NOT call `os.getenv()` outside `settings.py`.** All environment access
   must go through `settings.py` so there is one place to audit.

2. **Do NOT add `on_message` listeners in cogs.** The dispatcher in
   `bot/client.py` is the only place that handles messages. Adding `on_message`
   in a cog will create a parallel routing path that bypasses the admin gate,
   the prefix check, and the longest-match dispatch logic.

3. **Do NOT install packages into the running Docker container directly.**
   Add them to `Dockerfile` and rebuild with `update_docker.py`. Direct installs
   are lost on container restart.

4. **Do NOT use `bot.command()` / `bot.tree.command()` decorators.** The project
   uses its own `register_command()` dispatch system, not discord.py's built-in
   command framework. Mixing the two will cause duplicate or missed handling.

5. **Do NOT hardcode user IDs anywhere in Python code.** All admin user IDs must
   be in `admin.txt`. The file is designed to be edited without touching code.

6. **Do NOT add secrets or tokens to any file.** Use `.env` and `settings.py`.

7. **Do NOT skip tests.** Every new feature must have tests. Every change must
   leave the suite at 0 failures.

8. **Do NOT rely on `command_registry` for runtime dispatch.** Routing is
    owned by `bot.register_command(...)` in `bot/client.py`. Keep
    `command_registry` usage limited to explicit metadata/tests unless runtime
    integration is intentionally reintroduced.

9. **Do NOT modify `SYSTEM_PROMPT` casually.** The prompt-leak guard
   (`contains_prompt_leak`) uses a sliding window on the actual prompt text.
   Changing the prompt changes what counts as a leak. Test that the existing
   LLM cog prompt-leak tests still pass after any prompt change.

10. **Do NOT use `asyncio.run()` inside an already-running event loop.** The
    LLM worker runs in a thread executor — that's why it uses
    `asyncio.run_coroutine_threadsafe()` to post back to the event loop.

11. **Do NOT remove or weaken the crisis gate.** The `detect_crisis` check in
    `bot/client.py` must remain the first check in `on_message` (before admin
    gate, ban gate, and prefix check) and must never `return` early — the
    response should be sent AND normal processing should continue. Removing it
    silently is a serious PR and safety risk for a public-facing bot.

---

## 15. Crisis / Distress Detection & Safety Tool Calls

### Purpose

The bot is public-facing and watched by non-technical stakeholders. Two separate
layers handle safety signals:

| Layer | Where | Fires when | Action |
|---|---|---|---|
| **Keyword gate** | `bot/client.py` `on_message` | Message matches `_CRISIS_PHRASES` list | Sends `CRISIS_RESPONSE` immediately — no LLM involved |
| **LLM tool calls** | `bot/cogs/llm.py` `on_tool_call` | LLM calls `send_crisis_response()` or `send_pr_deflection()` | Sends appropriate pre-written message directly to Discord |

The keyword gate catches obvious distress signals before the LLM even sees the
message. The LLM tool calls catch subtler cases — nuanced phrasing, context-
dependent distress, and PR-risky questions that keyword matching would miss.

### Files

| File | Purpose |
|---|---|
| `utils/crisis_detector.py` | `detect_crisis(text)` keyword detector + `CRISIS_RESPONSE` string |
| `tools/toolcalls/safety_responder.py` | `send_crisis_response()`, `send_pr_deflection(topic)` tool functions + definitions + `PR_DEFLECTION_RESPONSE` |
| `bot/client.py` | Keyword gate in `on_message` (before prefix check) |
| `bot/cogs/llm.py` | `on_tool_call` sentinel handler sends safety messages to Discord |
| `tools/toolcalls/tool_registry.py` | Both tools registered |
| `utils/prompts.py` | `SYSTEM_PROMPT` entries instructing LLM when to call each tool |
| `tests/test_crisis_detector.py` | Tests for keyword detection |
| `tests/test_safety_responder.py` | Tests for the tool functions |
| `tests/test_tool_registry.py` | Registration checks |
| `tests/test_bot_client.py` | Keyword gate integration tests |

### How the sentinel tag works

The tool functions do **not** send to Discord directly (tools are pure functions
running in a thread executor). Instead they return a sentinel-tagged string:

```python
# send_crisis_response() returns:
"[__safety_response__=crisis] Crisis resources delivered to the user."

# send_pr_deflection(topic) returns:
"[__safety_response__=pr_deflection] PR deflection delivered for topic: 'topic'"
```

The `on_tool_call` callback in `bot/cogs/llm.py` matches the tag with a regex,
sends the correct pre-written message to Discord, and **returns early** so no
normal `🔧 tool() → result` notice is shown. The LLM also sees the tagged
result as a tool message and is instructed in `SYSTEM_PROMPT` to acknowledge
briefly without repeating the message.

This is architecturally identical to the `[__discord_file__=path]` mechanism
used by `get_workspace_file`.

### `utils/crisis_detector.py` — keyword gate

```python
detect_crisis(text: str) -> bool
CRISIS_RESPONSE: str   # the full emergency resources message
```

`_CRISIS_PHRASES` is a list of plain substrings and `\b`-anchored regex patterns.
To add a new phrase: add to the list, add a true-positive test in
`tests/test_crisis_detector.py`, and a false-positive test if needed.

### `tools/toolcalls/safety_responder.py` — LLM tool layer

```python
SAFETY_RESPONSE_TAG: str        # "__safety_response__" — do NOT rename
CRISIS_RESPONSE: str            # re-exported from utils.crisis_detector
PR_DEFLECTION_RESPONSE: str     # neutral professional deflection text
send_crisis_response() -> str
send_pr_deflection(topic: str) -> str
CRISIS_TOOL_DEFINITION: dict
PR_DEFLECTION_TOOL_DEFINITION: dict
```

### Adding a new response type

1. Define the message constant in `safety_responder.py`.
2. Write a new tool function returning `[{SAFETY_RESPONSE_TAG}=<new_type>] ...`.
3. Add a `TOOL_DEFINITION` dict with a clear `description` for the LLM.
4. Register in `tool_registry.py`.
5. Add an `elif response_type.startswith("<new_type>")` branch in the
   `on_tool_call` sentinel handler in `bot/cogs/llm.py`.
6. Add a bullet in `SYSTEM_PROMPT` (`utils/prompts.py`) describing when to call it.
7. Write tests in `tests/test_safety_responder.py`.

### Monkeypatching in tests

- Keyword gate: `monkeypatch.setattr("bot.client.detect_crisis", lambda text: True/False)`
- The tool functions themselves need no mocking — test them directly.

---

## 14. Quick Checklist for Any Change

- [ ] Read the relevant source files before editing.
- [ ] Follow the existing file header comment style.
- [ ] Use `from __future__ import annotations` at the top.
- [ ] Use `log()` not `print()` in production code.
- [ ] If adding a command: use `bot.register_command()` in the cog `__init__`.
- [ ] If adding a new cog: add a `setup(bot)` coroutine — auto-loading handles the rest.
- [ ] If adding a new tool: register in `tool_registry.py` AND document in `SYSTEM_PROMPT`.
- [ ] If adding a new required env var: add to `settings.py` AND add a fake default in `conftest.py`.
- [ ] If adding admin-related logic: patch `bot.client.is_admin_only` / `is_allowed` in tests, and `admin_module._allowed_ids` / `_admin_only` in utils-level tests.
- [ ] Write tests covering happy path, error path, and any permission gate.
- [ ] Run `.venv/bin/python -m pytest` — all tests must pass.
- [ ] Do not commit new markdown docs unless specifically asked.
- [ ] If editing `on_message` in `bot/client.py`: verify the crisis gate is still the first check and still does NOT return early.
- [ ] If adding a new LLM safety tool: follow the 7-step process in Section 15 (new response type).
- [ ] If editing rate-limiter logic in `on_message`: verify admins still bypass, and the WARNING stage does NOT return early.
---

## 16. Rate Limiter

### Purpose

Prevents users from spamming the bot with rapid-fire messages. Three
escalating stages apply increasing pressure to slow down:

| Stage | Trigger | Action |
|---|---|---|
| **WARNING** | 4th message in 60 s | Sends a soft warning — message is still processed |
| **RATE_LIMITED** | 6th+ message in 60 s | Message is rejected (not processed) |
| **COOLDOWN** | 3+ rate-limit rejections in 5 min | ALL messages rejected for 2 minutes |

Admins (`is_allowed(user_id) == True`) bypass the rate limiter entirely.

### Files

| File | Purpose |
|---|---|
| `utils/rate_limiter.py` | Core rate-limit logic, state, and configuration constants |
| `bot/client.py` | Gate in `on_message()` (after admin/ban gates, before command dispatch) |
| `tests/test_rate_limiter.py` | Unit tests for the rate limiter module |
| `tests/test_bot_client.py` | Integration tests for the rate-limit gate in `on_message` |
| `tests/conftest.py` | `_reset_rate_limiter` autouse fixture clears state between tests |

### Configuration constants (`utils/rate_limiter.py`)

| Constant | Default | Purpose |
|---|---|---|
| `RATE_LIMIT` | 5 | Max messages per window before hard rejection |
| `WARNING_THRESHOLD` | 4 | Messages before a soft warning (must be < `RATE_LIMIT`) |
| `WINDOW_SECONDS` | 60.0 | Sliding window size (seconds) |
| `COOLDOWN_STRIKES` | 3 | Rate-limit rejections in `COOLDOWN_WINDOW` to trigger cooldown |
| `COOLDOWN_WINDOW` | 300.0 | Window for counting strikes (5 minutes) |
| `COOLDOWN_DURATION` | 120.0 | How long the cooldown lasts (2 minutes) |

### Public API

```python
check_rate_limit(user_id: int) -> RateLimitResult
    # Returns ALLOWED, WARNING, RATE_LIMITED, or COOLDOWN.
    # Automatically records the timestamp — each call counts as a message.

reset_rate_limit(user_id: int) -> None
    # Clear all state for a single user.

reset_all() -> None
    # Clear all state for every user.

is_rate_limited(user_id: int) -> bool
    # True if the user is currently in cooldown.
```

### State is module-level

Three dicts hold per-user state:
- `_message_timestamps` — sliding window of message times
- `_strike_timestamps` — sliding window of rate-limit rejection times
- `_cooldown_until` — Unix timestamp when cooldown expires

State is **not persisted** — it resets on bot restart, which is intentional.

### Monkeypatching in client tests

Patch at the `bot.client` import site (same pattern as admin/crisis):

```python
from utils.rate_limiter import RateLimitResult
monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.ALLOWED)
```

### Monkeypatching time in unit tests

The rate limiter uses `time.monotonic()`. To test window expiry or cooldown
expiry, monkeypatch `rl.time` with a fake object:

```python
monkeypatch.setattr(rl, "time", type("FakeTime", (), {
    "monotonic": staticmethod(lambda: future_timestamp),
}))
```

### `conftest.py` autouse fixture

`tests/conftest.py` includes a `_reset_rate_limiter` autouse fixture that calls
`reset_all()` before every test. This prevents rate-limit state from leaking
between tests. If you add new module-level state to the rate limiter, ensure
`reset_all()` clears it.
