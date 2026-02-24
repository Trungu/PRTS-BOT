from __future__ import annotations

import tools.toolcalls.code_runner as code_runner


class _DummyManager:
    def __init__(self, *, stat_result: str = "1024", file_path: str | None = "/tmp/file.bin") -> None:
        self._stat_result = stat_result
        self._file_path = file_path

    def execute_command(self, command: str) -> str:
        return self._stat_result

    def get_file_path(self, container_path: str):
        return self._file_path


def test_get_workspace_file_rejects_path_traversal(monkeypatch) -> None:
    monkeypatch.setattr(code_runner, "_get_manager", lambda: _DummyManager())

    result = code_runner.get_workspace_file("../etc/passwd")

    assert result.startswith("Error:")
    assert "path traversal" in result


def test_get_workspace_file_rejects_workspace_prefix_bypass(monkeypatch) -> None:
    """Regression test: '/workspaceevil' must not pass workspace-root validation."""
    monkeypatch.setattr(code_runner, "_get_manager", lambda: _DummyManager())

    result = code_runner.get_workspace_file("../workspaceevil/secret.txt")

    assert result.startswith("Error:")
    assert "path traversal" in result


def test_get_workspace_file_accepts_valid_relative_path(monkeypatch) -> None:
    monkeypatch.setattr(
        code_runner,
        "_get_manager",
        lambda: _DummyManager(stat_result="2048", file_path="/tmp/download.bin"),
    )

    result = code_runner.get_workspace_file("reports/output.csv")

    assert "__discord_file__=/tmp/download.bin" in result
    assert "output.csv" in result
