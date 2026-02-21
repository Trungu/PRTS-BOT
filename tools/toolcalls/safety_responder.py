# tools/toolcalls/safety_responder.py — LLM-callable safety response tools.
#
# Design
# ------
# The LLM is instructed (via SYSTEM_PROMPT) to call these tools whenever it
# recognises a crisis signal or a PR-risky question.  Each tool function
# returns a string containing:
#
#   1. A sentinel tag  — [__safety_response__=<type>]
#      The on_tool_call handler in bot/cogs/llm.py detects this tag, sends
#      the correct pre-written message directly to Discord, and suppresses the
#      normal "🔧 tool() → result" notice so the channel stays clean.
#
#   2. A short human-readable confirmation — so the LLM knows the action
#      succeeded and can produce a brief, natural follow-up reply.
#
# Adding a new response type
# --------------------------
#   1. Define the message constant here.
#   2. Write a new tool function that returns [__safety_response__=<new_type>].
#   3. Add a TOOL_DEFINITION dict.
#   4. Register it in tool_registry.py.
#   5. Add an elif branch in the on_tool_call handler in bot/cogs/llm.py.
#   6. Update SYSTEM_PROMPT in utils/prompts.py.
#   7. Write tests in tests/test_safety_responder.py.

from __future__ import annotations

from utils.crisis_detector import CRISIS_RESPONSE

# ---------------------------------------------------------------------------
# Sentinel tag
# ---------------------------------------------------------------------------

# This exact string is matched by the on_tool_call regex in bot/cogs/llm.py.
# Do NOT rename it without updating that regex.
SAFETY_RESPONSE_TAG: str = "__safety_response__"

# ---------------------------------------------------------------------------
# Response messages
# ---------------------------------------------------------------------------

# Re-exported so bot/cogs/llm.py has a single import point for both messages.
# CRISIS_RESPONSE is defined in utils/crisis_detector.py to keep detection
# and response text co-located; we just re-export it here.
CRISIS_RESPONSE = CRISIS_RESPONSE  # noqa: PLW0127  (explicit re-export)

PR_DEFLECTION_RESPONSE: str = (
    "🤝 I'm a technical engineering assistant — I'm not set up to express "
    "opinions on political topics, geopolitical issues, national policies, "
    "religious stances, or anything that could be controversial on behalf "
    "of the organisation. For official positions or statements, please "
    "reach out to the team directly."
)

# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def send_crisis_response() -> str:
    """Send official mental-health emergency resources to the user.

    Called by the LLM when it detects genuine distress — suicidal ideation,
    self-harm, hopelessness, or any message where the user may be at risk.
    Returns a sentinel tag that bot/cogs/llm.py recognises to send the full
    crisis resources message directly to Discord.
    """
    return (
        f"[{SAFETY_RESPONSE_TAG}=crisis] "
        "Crisis resources delivered to the user."
    )


def send_pr_deflection(topic: str) -> str:
    """Send a neutral, professional deflection for a PR-sensitive question.

    Called by the LLM when the user asks for opinions on politically sensitive
    topics, geopolitical stances, religious views, company affiliations, or
    anything that could create negative publicity if answered directly.
    Returns a sentinel tag that bot/cogs/llm.py recognises to send the
    deflection message directly to Discord.

    Parameters
    ----------
    topic:
        Short description of the sensitive subject being deflected
        (e.g. ``"communist Russia"``).
    """
    return (
        f"[{SAFETY_RESPONSE_TAG}=pr_deflection] "
        f"PR deflection delivered for topic: {topic!r}"
    )


# ---------------------------------------------------------------------------
# OpenAI tool definitions
# ---------------------------------------------------------------------------

CRISIS_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "send_crisis_response",
        "description": (
            "Send official mental-health emergency resources to the user. "
            "Call this IMMEDIATELY — before any other response — if the user's "
            "message contains ANY sign of genuine distress: suicidal thoughts, "
            "self-harm, hopelessness, wanting to die or end their life, or any "
            "message where the user may be at risk, even if it seems like a joke "
            "or hyperbole. When in doubt, call this tool. "
            "Do NOT counsel, diagnose, or add commentary. After calling this tool, "
            "acknowledge very briefly that support has been shared."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

PR_DEFLECTION_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "send_pr_deflection",
        "description": (
            "Send a neutral, professional deflection when the user asks the bot "
            "to express opinions on politically sensitive topics, geopolitical "
            "issues, national or government policies, religious or ideological "
            "stances, company affiliations, or anything that could create negative "
            "publicity for the organisation if answered directly. "
            "Examples: 'do you support X country', 'what do you think of Y "
            "government', 'are you pro-X ideology', endorsement of parties or "
            "regimes. Do NOT engage with the topic at all — call this tool "
            "immediately and do not add your own opinion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Short description of the sensitive topic being deflected, "
                        "e.g. 'communist Russia' or 'political party endorsement'."
                    ),
                },
            },
            "required": ["topic"],
        },
    },
}
