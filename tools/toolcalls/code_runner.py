# tools/toolcalls/code_runner.py — sandboxed Python code execution tool for the LLM agent.
#
# Code is uploaded into the running Docker sandbox as a uniquely named script
# in /tmp (ephemeral), executed as a non-root user, then deleted.  Any files
# the code itself writes to /workspace are kept — /workspace is a persistent
# bind mount that survives container restarts.
#
# The sandbox enforces:
#   • No network access
#   • Read-only host filesystem (/tmp is tmpfs, /workspace is a persistent bind mount)
#   • All Linux capabilities dropped
#   • No privilege escalation (no-new-privileges)
#   • 1 GB RAM cap, 2 CPU cap
#   • 60-second execution timeout
#
# See tools/docker/Dockerfile and tools/docker/docker_manager.py for the full
# sandbox specification.

from __future__ import annotations

import os
import re
import uuid

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
    # start_container() is idempotent — it returns immediately if the
    # container is already running, and restarts it cleanly if it stopped.
    _manager.start_container()
    return _manager


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def run_python(code: str) -> str:
    """Execute *code* inside the secure Docker sandbox and return the output.

    Parameters
    ----------
    code:
        Complete, self-contained Python 3 source code.  Use ``print()`` to
        produce visible output — the tool captures and returns stdout and
        stderr.  Runtime errors (tracebacks) are returned as normal output
        so the model can diagnose and retry.

    Returns
    -------
    str
        Captured stdout + stderr from the execution, or an error message
        prefixed with ``"Error:"`` if the sandbox could not be reached or
        the script could not be uploaded.
    """
    code = code.strip()
    if not code:
        return "Error: no code provided."

    # Fast syntax pre-check — gives a clean error before touching Docker.
    try:
        compile(code, "<run_python>", "exec")
    except SyntaxError as exc:
        return f"Error: syntax error — {exc}"

    # Obtain (or start) the sandbox container.
    try:
        mgr = _get_manager()
    except Exception as exc:
        return f"Error: could not start sandbox container: {exc}"

    # Write the runner script to /tmp (ephemeral) so /workspace stays clean
    # for files the user's code intentionally creates.
    script_name    = f"run_{uuid.uuid4().hex[:16]}.py"
    container_path = f"/tmp/{script_name}"

    ok = mgr.copy_to_container(code.encode("utf-8"), container_path)
    if not ok:
        return "Error: failed to upload script to sandbox."

    # Execute and capture output.
    output = mgr.execute_command(f"python3 {container_path}")

    # Clean up the runner script from /tmp.  Any files the code wrote to
    # /workspace are intentionally left in place (persistent workspace).
    mgr.execute_command(f"rm -f {container_path}")

    return output


# ---------------------------------------------------------------------------
# OpenAI-style tool definition (read by llm_api agentic loop)
# ---------------------------------------------------------------------------

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Execute arbitrary Python 3 code in a fully isolated, network-free "
            "sandbox with no root access and all Linux capabilities dropped. "
            "Files saved to /workspace persist between sessions — use this to "
            "store results, generated plots, or intermediate data. "
            "Use this for: precise multi-step numerical calculations, matrix / "
            "linear algebra (numpy), symbolic math and calculus (sympy), "
            "signal processing and differential equations (scipy), "
            "ML and data analysis (scikit-learn, statsmodels), "
            "image processing (scikit-image, pillow), "
            "unit-aware calculations (pint), graph algorithms (networkx), "
            "convex optimisation (cvxpy), control systems (control), "
            "error propagation (uncertainties), data manipulation (pandas, pyarrow), "
            "Excel / Word / PDF I/O (openpyxl, python-docx, pypdf, h5py), "
            "geometric calculations (shapely), and anything needing real code. "
            "Prefer this over the calculator for anything multi-step or iterative. "
            "Available packages: numpy, scipy, sympy, matplotlib, seaborn, pandas, "
            "openpyxl, xlrd, pyarrow, statsmodels, scikit-learn, scikit-image, "
            "pint, control, cvxpy, uncertainties, networkx, pygraphviz, "
            "pypdf, pillow, python-docx, h5py, beautifulsoup4, lxml, "
            "tqdm, joblib, tabulate, shapely, requests. "
            "Java (javac / java), gcc/g++, bc, gnuplot, graphviz, "
            "ImageMagick (convert), and git are also available via subprocess."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Complete, self-contained Python 3 source code. "
                        "Use print() to produce visible output — the tool returns "
                        "captured stdout and stderr. Runtime errors are returned as "
                        "output (the interpreter traceback) so you can diagnose and "
                        "retry. "
                        "Example: "
                        "'import numpy as np\\n"
                        "A = np.array([[4, 2], [1, 3]])\\n"
                        "vals, vecs = np.linalg.eig(A)\\n"
                        "print(\"eigenvalues:\", vals)'."
                    ),
                },
            },
            "required": ["code"],
        },
    },
}

# ---------------------------------------------------------------------------
# Public manager accessor (used by llm.py for attachment uploads)
# ---------------------------------------------------------------------------

def get_manager() -> DockerManager:
    """Return the shared DockerManager, starting the container if needed."""
    return _get_manager()


# ---------------------------------------------------------------------------
# list_workspace tool
# ---------------------------------------------------------------------------

def list_workspace() -> str:
    """List all files in the persistent ``/workspace`` directory.

    Returns
    -------
    str
        A human-readable directory listing, or an error message prefixed
        with ``"Error:"``.
    """
    try:
        mgr = _get_manager()
    except Exception as exc:
        return f"Error: could not reach sandbox: {exc}"
    return mgr.execute_command(
        "ls -lAh --group-directories-first "
        "--time-style='+%Y-%m-%d %H:%M' /workspace 2>&1"
    )


LIST_WORKSPACE_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "list_workspace",
        "description": (
            "List all files and directories in the persistent sandbox /workspace. "
            "Call this before running code to see what data files are already "
            "available, or after running code to confirm output files were created. "
            "Files in /workspace survive container restarts and image rebuilds."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


# ---------------------------------------------------------------------------
# get_workspace_file tool
# ---------------------------------------------------------------------------

def get_workspace_file(filename: str) -> str:
    """Retrieve a file from ``/workspace`` and queue it for Discord delivery.

    Parameters
    ----------
    filename:
        Filename or relative path within ``/workspace``, e.g. ``'plot.png'``
        or ``'results/data.csv'``.

    Returns
    -------
    str
        A human-readable confirmation string that embeds a hidden
        ``[__discord_file__=<local_temp_path>]`` tag for the bot cog to
        parse and deliver as a Discord attachment.  Returns an ``"Error:"``
        string on failure.
    """
    clean = filename.strip().lstrip("/")
    if not clean:
        return "Error: filename must not be empty."

    # Prevent path traversal outside /workspace.
    workspace_root = "/workspace"
    container_path = os.path.normpath(f"{workspace_root}/{clean}")
    if container_path != workspace_root and not container_path.startswith(f"{workspace_root}/"):
        return "Error: path traversal outside /workspace is not allowed."

    try:
        mgr = _get_manager()
    except Exception as exc:
        return f"Error: could not reach sandbox: {exc}"

    # Get human-readable file size for the confirmation message.
    stat_out = mgr.execute_command(
        f"stat -c '%s' '{container_path}' 2>/dev/null"
    )
    try:
        size_bytes = int(stat_out.strip())
        size_kb = size_bytes / 1024
        size_str = (
            f"{size_kb:.1f} KB" if size_kb < 1024
            else f"{size_kb / 1024:.2f} MB"
        )
    except (ValueError, AttributeError):
        size_str = "unknown size"

    local_path = mgr.get_file_path(container_path)
    if local_path is None:
        return f"Error: '{clean}' not found or unreadable in /workspace."
    if local_path == "TOO_LARGE":
        return f"Error: '{clean}' exceeds the 8 MB Discord transfer limit."

    display_name = os.path.basename(clean)
    # The [__discord_file__=...] tag is parsed by the cog to trigger the
    # actual Discord attachment send.  The LLM sees the human-readable part.
    return (
        f"✅ '{display_name}' ({size_str}) is being sent to Discord as an attachment. "
        f"[__discord_file__={local_path}]"
    )


GET_WORKSPACE_FILE_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_workspace_file",
        "description": (
            "Send a file from the sandbox /workspace to Discord as an attachment. "
            "Use list_workspace first to confirm the exact filename. "
            "Supports any file type: PNG/JPEG images (matplotlib / seaborn plots), "
            "CSV / Excel data files, PDFs, text files, NumPy .npz, HDF5 .h5, "
            "compiled binaries, and more. Maximum file size: 8 MB (Discord limit). "
            "Example workflow: run_python saves 'output.png' → "
            "get_workspace_file('output.png') delivers it in chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Filename or relative path within /workspace. "
                        "Examples: 'plot.png', 'results.csv', 'report.pdf', "
                        "'subdir/data.npz'."
                    ),
                },
            },
            "required": ["filename"],
        },
    },
}