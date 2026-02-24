# tests/test_admin_utils.py — Unit tests for utils/admin.py (pure-function layer).
#
# Coverage
# --------
#   load_admin_file         — valid IDs, comments/blanks, bad entries, missing file
#   reload_allowed_users    — updates module-level state
#   is_allowed              — membership checks
#   set_admin_only /        — toggle behaviour + persistence
#     is_admin_only
#   _save_state / load_state — JSON persistence across restarts
#   ban_user / unban_user /  — user ban state management
#     is_banned
#   banned_ids round-trip   — persistence of the banned-IDs set

from __future__ import annotations

import json

import utils.admin as admin_module
from utils.admin import (
    ban_user,
    is_admin_only,
    is_allowed,
    is_banned,
    load_admin_file,
    load_state,
    reload_allowed_users,
    set_admin_only,
    unban_user,
)


# ---------------------------------------------------------------------------
# load_admin_file
# ---------------------------------------------------------------------------

def test_load_admin_file_valid_ids(tmp_path) -> None:
    f = tmp_path / "admin.txt"
    f.write_text("111111111111111111\n222222222222222222\n")

    result = load_admin_file(str(f))

    assert result == {111111111111111111, 222222222222222222}


def test_load_admin_file_ignores_comments_and_blanks(tmp_path) -> None:
    f = tmp_path / "admin.txt"
    f.write_text("# admin list\n\n123456789\n\n# trailing comment\n")

    result = load_admin_file(str(f))

    assert result == {123456789}


def test_load_admin_file_skips_invalid_entries(tmp_path) -> None:
    f = tmp_path / "admin.txt"
    f.write_text("not_an_id\n999\n\nalso-bad\n")

    result = load_admin_file(str(f))

    assert result == {999}


def test_load_admin_file_missing_file_returns_empty_set(tmp_path) -> None:
    result = load_admin_file(str(tmp_path / "nonexistent.txt"))

    assert result == set()


def test_load_admin_file_empty_file_returns_empty_set(tmp_path) -> None:
    f = tmp_path / "admin.txt"
    f.write_text("")

    result = load_admin_file(str(f))

    assert result == set()


# ---------------------------------------------------------------------------
# reload_allowed_users / is_allowed
# ---------------------------------------------------------------------------

def test_reload_allowed_users_updates_state(tmp_path, monkeypatch) -> None:
    f = tmp_path / "admin.txt"
    f.write_text("42\n")
    monkeypatch.setattr(admin_module, "_allowed_ids", set())

    reload_allowed_users(str(f))

    assert is_allowed(42)
    assert not is_allowed(99)


def test_is_allowed_false_when_set_empty(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", set())

    assert not is_allowed(12345)


# ---------------------------------------------------------------------------
# set_admin_only / is_admin_only
# ---------------------------------------------------------------------------

def test_admin_only_starts_disabled(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_admin_only", False)

    assert not is_admin_only()


def test_set_admin_only_enable(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    set_admin_only(True)

    assert is_admin_only()


def test_set_admin_only_disable(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_admin_only", True)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    set_admin_only(False)

    assert not is_admin_only()


def test_admin_only_toggle_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    assert not is_admin_only()
    set_admin_only(True)
    assert is_admin_only()
    set_admin_only(False)
    assert not is_admin_only()


# ---------------------------------------------------------------------------
# Persistence — _save_state / load_state
# ---------------------------------------------------------------------------

def test_save_state_writes_enabled(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", True)
    monkeypatch.setattr(admin_module, "_banned_ids", set())

    admin_module._save_state()

    with open(state_file) as fh:
        data = json.load(fh)
    assert data["admin_only"] is True
    assert data["banned_ids"] == []


def test_save_state_writes_disabled(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_banned_ids", set())

    admin_module._save_state()

    with open(state_file) as fh:
        data = json.load(fh)
    assert data["admin_only"] is False
    assert data["banned_ids"] == []


def test_load_state_restores_enabled(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    (tmp_path / "state.json").write_text(json.dumps({"admin_only": True}))
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)  # start opposite

    load_state()

    assert is_admin_only() is True


def test_load_state_restores_disabled(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    (tmp_path / "state.json").write_text(json.dumps({"admin_only": False}))
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", True)  # start opposite

    load_state()

    assert is_admin_only() is False


def test_load_state_missing_file_defaults_false(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "nonexistent.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", True)  # would be wrong if kept

    load_state()

    assert is_admin_only() is False


def test_load_state_corrupt_file_defaults_false(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    (tmp_path / "state.json").write_text("not valid json{{")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", True)

    load_state()

    assert is_admin_only() is False


def test_set_admin_only_persists_to_state_file(monkeypatch, tmp_path) -> None:
    """End-to-end: setting mode writes to file; loading restores it."""
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)

    set_admin_only(True)

    with open(state_file) as fh:
        data = json.load(fh)
    assert data["admin_only"] is True

    # Simulated restart: reset in-memory flag, then load from file.
    monkeypatch.setattr(admin_module, "_admin_only", False)
    load_state()
    assert is_admin_only() is True


# ---------------------------------------------------------------------------
# ban_user / unban_user / is_banned
# ---------------------------------------------------------------------------

def test_is_banned_false_initially(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    assert not is_banned(12345)


def test_ban_user_adds_to_banned_set(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    ban_user(42)

    assert is_banned(42)


def test_ban_user_does_not_affect_others(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    ban_user(42)

    assert not is_banned(99)


def test_unban_user_removes_from_banned_set(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_banned_ids", {42})
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    unban_user(42)

    assert not is_banned(42)


def test_unban_user_is_idempotent(monkeypatch) -> None:
    """Unbanning a user who is not banned must not raise."""
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    unban_user(99)  # 99 was never banned — must be silent

    assert not is_banned(99)


def test_ban_user_persists_state(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_banned_ids", set())

    ban_user(777)

    with open(state_file) as fh:
        data = json.load(fh)
    assert 777 in data["banned_ids"]


def test_unban_user_persists_state(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_banned_ids", {777})

    unban_user(777)

    with open(state_file) as fh:
        data = json.load(fh)
    assert 777 not in data["banned_ids"]


# ---------------------------------------------------------------------------
# Persistence — banned_ids round-trip
# ---------------------------------------------------------------------------

def test_save_state_includes_banned_ids(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_banned_ids", {10, 20, 30})

    admin_module._save_state()

    with open(state_file) as fh:
        data = json.load(fh)
    assert set(data["banned_ids"]) == {10, 20, 30}


def test_load_state_restores_banned_ids(monkeypatch, tmp_path) -> None:
    state_file = str(tmp_path / "state.json")
    (tmp_path / "state.json").write_text(
        json.dumps({"admin_only": False, "banned_ids": [10, 20, 30]})
    )
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_banned_ids", set())

    load_state()

    assert is_banned(10)
    assert is_banned(20)
    assert is_banned(30)
    assert not is_banned(99)


def test_load_state_missing_banned_ids_key_defaults_empty(
    monkeypatch, tmp_path
) -> None:
    state_file = str(tmp_path / "state.json")
    (tmp_path / "state.json").write_text(json.dumps({"admin_only": False}))
    monkeypatch.setattr(admin_module, "STATE_FILE", state_file)
    monkeypatch.setattr(admin_module, "_banned_ids", {99})  # would be wrong if kept

    load_state()

    assert not is_banned(99)
