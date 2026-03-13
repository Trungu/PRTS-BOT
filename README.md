# PRTS Discord Bot

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.0%2B-5865F2?logo=discord&logoColor=white)
![Status](https://img.shields.io/badge/status-work%20in%20progress-orange)
![Open Source](https://img.shields.io/badge/open%20source-yes-2ea44f)

PRTS is an AI-enabled Discord bot designed for technical communities. It provides conversational assistance, tool-driven workflows, and Google Calendar automation with a focus on safety, privacy, and operational control.

> NOTE: PRTS is actively evolving and remains a work in progress.

## Core Capabilities

- LLM chat fallback for natural conversation when no explicit command is matched.
- Tool-enabled responses for:
  - arithmetic and quick calculations
  - Python execution in an isolated sandbox
  - terminal command execution in an isolated sandbox
  - engineering/scientific unit conversion
- Google Calendar integration:
  - connect/disconnect flow via OAuth
  - create, find, remove events
  - set event reminders
  - support for natural-language scheduling via tool calls
- Safety responses for crisis content and politically sensitive requests.
- Message-level controls:
  - user rate limiting with warning, hard-limit, and cooldown stages
  - optional reply-trigger mode (process direct replies to bot messages without prefix)

## Architecture Overview

- `main.py`: application entrypoint.
- `bot/client.py`: central message router, command dispatch, gates (admin/ban/rate-limit), and fallback handling.
- `bot/cogs/llm.py`: LLM interaction, runtime context injection, tool-call handling, safety/leak guards.
- `tools/llm_api.py`: chat-completions wrapper with multi-step tool-call loop.
- `tools/toolcalls/tool_registry.py`: available tools and Google Calendar NL actions.
- `bot/cogs/gcal.py`: slash commands for calendar operations.
- `oauth_server.py`: OAuth callback/token handling.
- `settings.py`: centralized config loader for environment variables and runtime feature flags.

## Quick Start

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create environment file:

```bash
cp .env.example .env
```

4. Configure required values in `.env`:

- `DISCORD_TOKEN`
- `BOT_PREFIX`
- `LLM_API_KEY` (required for hosted LLM providers; not required when `LLM_PROVIDER=ollama`)
- Google OAuth settings (`CLIENT_ID`, `CLIENT_SECRET`, `OAUTH_BASE_URL`, `OAUTH_REDIRECT_URI`)
- Supabase settings (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`)

5. Run the bot:

```bash
python main.py
```

## Configuration Notes

- `settings.py` is the single source of truth for runtime configuration.
- Environment variables are loaded and parsed there (tokens, API keys, OAuth settings, prefixes).
- Feature flags (for example reply-trigger behavior and message silence modes) are also defined there.
- Recent prompt context is enabled by default and injects a small recent channel window into every LLM request.
- You can tune that default context size with `RECENT_CONTEXT_MESSAGE_COUNT` or disable it with `RECENT_CONTEXT_ENABLED=false`.
- LLM backend selection is opt-in via `LLM_PROVIDER`:
  - default: hosted Groq-compatible mode
  - optional: `ollama` for local OpenAI-compatible requests
- When `LLM_PROVIDER=ollama`, the default endpoint is `http://localhost:11434/v1` and the default model is `llama3.1:8b`.
- Existing hosted setups do not need any `.env` changes.

## Example Use Cases

- Ask technical questions and get concise engineering-focused answers.
- Solve quick calculations or unit conversions directly in chat.
- Run Python-based analysis and return results/files in Discord.
- Schedule reminders and calendar events using natural language.
- Update or remove calendar events without switching apps.
