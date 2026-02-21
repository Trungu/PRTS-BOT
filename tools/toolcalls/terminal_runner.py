# tools/toolcalls/terminal_runner.py — sandboxed shell command execution tool.
#
# Runs an arbitrary POSIX shell command inside the same Docker sandbox used by
# run_python.  The command is executed as sandboxuser (non-root) in /workspace,
# with no network access, all Linux capabilities dropped, and the gVisor (runsc)
# runtime providing OS-level syscall interception.
#
# The sandbox enforces (inherited from the shared container):
#   • No network access
#   • Read-only host filesystem (/tmp is tmpfs, /workspace is a persistent bind mount)
#   • All Linux capabilities dropped
#   • No privilege escalation (no-new-privileges)
#   • 1 GB RAM cap, 2 CPU cap
#   • 60-second execution timeout
#
# Useful for: C/C++ compilation (gcc/g++), Java (javac/java), shell pipelines,
# git operations, bc, gnuplot, graphviz, ImageMagick (convert/magick), and any
# other CLI tool installed in the sandbox image.

from __future__ import annotations

from tools.docker.docker_manager import DockerManager

# ---------------------------------------------------------------------------
# Module-level container singleton — shared across all tool calls in this
# process so we don't spin up a new container on every request.
# ---------------------------------------------------------------------------

_manager: DockerManager | None = None


def _get_manager() -> DockerManager:
    """Return the shared DockerManager, lazily starting the container."""
    global _manager
    if _manager is None:
        _manager = DockerManager()
    # start_container() is idempotent — returns immediately if already running,
    # restarts cleanly if the container stopped.
    _manager.start_container()
    return _manager


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def run_terminal(command: str) -> str:
    """Execute *command* inside the secure Docker sandbox and return the output.

    Parameters
    ----------
    command:
        A POSIX shell command string, e.g. ``"gcc -O2 -o solver solver.c && ./solver"``.
        The command runs in ``/workspace`` as ``sandboxuser`` (non-root), with
        no network access and all Linux capabilities dropped.
        Supports pipes (``|``), redirects (``>``, ``<``), and chaining
        (``&&``, ``||``, ``;``).

    Returns
    -------
    str
        Captured stdout + stderr from the command, or an ``"Error:"`` message
        if the sandbox could not be reached.
    """
    command = command.strip()
    if not command:
        return "Error: no command provided."

    try:
        mgr = _get_manager()
    except Exception as exc:
        return f"Error: could not start sandbox container: {exc}"

    return mgr.execute_command(command)


# ---------------------------------------------------------------------------
# OpenAI-style tool definition (read by llm_api agentic loop)
# ---------------------------------------------------------------------------

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "run_terminal",
        "description": (
            "Execute an arbitrary shell command inside the same fully isolated, "
            "network-free Docker sandbox used by run_python. "
            "The command runs in /workspace as a non-root user with all Linux "
            "capabilities dropped and the gVisor (runsc) runtime for OS-level isolation. "
            "Use this for: compiling and running C/C++ programs (gcc/g++), "
            "Java projects (javac/java), shell scripts, git operations, "
            "bc arithmetic, gnuplot / graphviz rendering, "
            "ImageMagick image manipulation (convert/magick), "
            "file management (cp, mv, mkdir, tar, zip/unzip), "
            "inspecting files (cat, head, tail, grep, wc, diff), "
            "and any other CLI tool available in the sandbox image. "
            "Prefer run_python for Python-specific tasks; use run_terminal "
            "when you need a shell pipeline, a non-Python language, or a CLI tool. "
            "Files written to /workspace persist between calls. "
            "Use get_workspace_file to deliver output files to Discord."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "A POSIX shell command string. Runs in /workspace as "
                        "sandboxuser (non-root). Supports pipes, redirects, and "
                        "command chaining (&&, ||, ;). "
                        "Examples: "
                        "'gcc -O2 -o solver solver.c && ./solver', "
                        "'javac Main.java && java Main', "
                        "'echo \"2^10\" | bc', "
                        "'dot -Tpng graph.dot -o graph.png', "
                        "'convert input.png -resize 800x600 output.png'."
                    ),
                },
            },
            "required": ["command"],
        },
    },
}
