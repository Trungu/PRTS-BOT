# utils/admin.py — Admin-only mode: allowed-user list and mode state.
#
# State machine
# -------------
# When admin-only mode is ON, the bot's on_message dispatcher will reject
# any command from a user whose Discord ID is not listed in admin.txt.
# The mode can be toggled with the "admin only" / "admin on" / "admin off"
# commands, all of which are gated behind the same allowed-user check.
#
# Persistence
# -----------
# The admin-only flag is written to STATE_FILE (admin_state.json) every time
# it changes, and restored from that file at startup.  This means the mode
# survives unexpected bot crashes or reboots automatically.

from __future__ import annotations

import json
import os

from utils.logger import log, LogLevel

# Absolute path to admin.txt, resolved relative to the project root.
ADMIN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin.txt")

# Absolute path to the state file that persists the admin-only flag across
# restarts.  Lives next to admin.txt in the project root.
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin_state.json")

# ---------------------------------------------------------------------------
# Module-level state — single source of truth
# ---------------------------------------------------------------------------

_admin_only: bool = False
_allowed_ids: set[int] = set()
_banned_ids: set[int] = set()


# ---------------------------------------------------------------------------
# Admin file helpers
# ---------------------------------------------------------------------------

def load_admin_file(path: str = ADMIN_FILE) -> set[int]:
    """Parse *path* and return the set of Discord user IDs it contains.

    Rules:
    - One entry per line.
    - Entries must be plain integers (Discord snowflake IDs).
    - Lines starting with ``#`` and blank lines are silently skipped.
    - Invalid (non-integer) entries are skipped with a WARNING log.
    - A missing file is handled gracefully (returns an empty set).
    """
    ids: set[int] = set()
    try:
        with open(path) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    ids.add(int(line))
                except ValueError:
                    log(
                        f"[Admin] Skipping non-integer entry in admin file: {line!r}",
                        LogLevel.WARNING,
                    )
    except FileNotFoundError:
        log(
            f"[Admin] Admin file not found at {path!r}. "
            "No users will be permitted in admin-only mode.",
            LogLevel.WARNING,
        )
    return ids


def reload_allowed_users(path: str = ADMIN_FILE) -> None:
    """Reload the in-memory allowed-user set from *path*.

    Call this before enabling admin-only mode so the latest version of the
    file is always active.
    """
    global _allowed_ids
    _allowed_ids = load_admin_file(path)
    log(f"[Admin] Loaded {len(_allowed_ids)} allowed user(s) from admin file.")


def is_allowed(user_id: int) -> bool:
    """Return ``True`` if *user_id* is in the current allowed-user set."""
    return user_id in _allowed_ids


# ---------------------------------------------------------------------------
# Ban helpers
# ---------------------------------------------------------------------------

def ban_user(user_id: int) -> None:
    """Add *user_id* to the banned-users set and persist state."""
    global _banned_ids
    _banned_ids.add(user_id)
    _save_state()
    log(f"[Admin] User {user_id} added to ban list.", LogLevel.INFO)


def unban_user(user_id: int) -> None:
    """Remove *user_id* from the banned-users set and persist state."""
    global _banned_ids
    _banned_ids.discard(user_id)
    _save_state()
    log(f"[Admin] User {user_id} removed from ban list.", LogLevel.INFO)


def is_banned(user_id: int) -> bool:
    """Return ``True`` if *user_id* has been banned from using the bot."""
    return user_id in _banned_ids


# ---------------------------------------------------------------------------
# Mode flag
# ---------------------------------------------------------------------------

def set_admin_only(enabled: bool) -> None:
    """Enable (``True``) or disable (``False``) admin-only mode.

    Persists the new flag to STATE_FILE so the mode survives restarts.
    """
    global _admin_only
    _admin_only = enabled
    _save_state()


def is_admin_only() -> bool:
    """Return ``True`` if admin-only mode is currently active."""
    return _admin_only


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _save_state() -> None:
    """Write the current ``_admin_only`` flag to ``STATE_FILE``.

    Failures are logged as warnings but never raised — a write error must
    never crash the bot.
    """
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump({"admin_only": _admin_only, "banned_ids": sorted(_banned_ids)}, fh)
    except OSError as exc:
        log(
            f"[Admin] Failed to persist state to {STATE_FILE!r}: {exc}",
            LogLevel.WARNING,
        )


def load_state() -> None:
    """Restore ``_admin_only`` from ``STATE_FILE``.

    Called once at startup.  If the file is missing the flag defaults to
    ``False`` (normal operation).  If the file is unreadable or malformed,
    a warning is logged and the flag defaults to ``False``.
    """
    global _admin_only, _banned_ids
    try:
        with open(STATE_FILE) as fh:
            data = json.load(fh)
        _admin_only = bool(data.get("admin_only", False))
        _banned_ids = set(int(x) for x in data.get("banned_ids", []))
        log(
            f"[Admin] Restored state: admin_only={_admin_only}, "
            f"banned={len(_banned_ids)} user(s)"
        )
    except FileNotFoundError:
        _admin_only = False
        _banned_ids = set()
    except (OSError, json.JSONDecodeError) as exc:
        log(
            f"[Admin] Could not read state file {STATE_FILE!r}: {exc} "
            "— defaulting to False",
            LogLevel.WARNING,
        )
        _admin_only = False
        _banned_ids = set()


# ---------------------------------------------------------------------------
# Initialisation — runs once at import time
# ---------------------------------------------------------------------------

# 1. Load the allowed-user set so is_allowed() works immediately.
reload_allowed_users()
# 2. Restore the persisted admin-only flag so the mode survives restarts.
load_state()
