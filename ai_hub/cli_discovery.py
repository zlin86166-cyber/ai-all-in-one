"""Read-only discovery of installed AI command-line tools on local drives."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable


CLI_COMMANDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("codex", "OpenAI Codex", ("codex",)),
    ("gemini", "Gemini CLI", ("gemini",)),
    ("claude", "Claude Code", ("claude",)),
    ("copilot", "GitHub Copilot CLI", ("copilot",)),
    ("cursor-agent", "Cursor Agent", ("cursor-agent",)),
    ("opencode", "OpenCode", ("opencode",)),
    ("aider", "Aider", ("aider",)),
    ("qwen-code", "Qwen Code", ("qwen", "qwen-code")),
    ("kimi", "Kimi CLI", ("kimi", "kimi-cli")),
    ("goose", "Goose", ("goose",)),
    ("ollama", "Ollama", ("ollama",)),
    ("amp", "Amp", ("amp",)),
)

_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1", ".py", "")
_COMMAND_LOOKUP = {
    f"{alias}{suffix}".casefold(): (cli_id, label, alias)
    for cli_id, label, aliases in CLI_COMMANDS
    for alias in aliases
    for suffix in _EXECUTABLE_SUFFIXES
}
_SKIP_DIRECTORY_NAMES = frozenset(
    {
        "$recycle.bin",
        "system volume information",
        "windows",
        "windows.old",
        "winsxs",
        "recovery",
        "perfLogs".casefold(),
        "windowsapps",
        ".git",
        ".npm",
        ".cache",
        "cache",
        "npm-cache",
        "pip-cache",
        "temp",
        "tmp",
        "__pycache__",
    }
)
_VIRTUAL_ENV_NAMES = frozenset({".venv", "venv", "virtualenv"})
_NODE_MODULES_NAME = "node_modules"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3


ProgressCallback = Callable[[dict[str, Any]], None]


def local_scan_roots() -> list[Path]:
    """Return accessible fixed and removable Windows drive roots, never network drives."""
    if os.name != "nt":
        home = Path.home()
        return [Path(home.anchor or str(home))]

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetLogicalDrives.restype = ctypes.c_uint32
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint
        drive_mask = int(kernel32.GetLogicalDrives())
    except (AttributeError, OSError):
        return []

    roots: list[Path] = []
    for index in range(26):
        if not drive_mask & (1 << index):
            continue
        root = Path(f"{chr(ord('A') + index)}:\\")
        if int(kernel32.GetDriveTypeW(str(root))) not in (_DRIVE_REMOVABLE, _DRIVE_FIXED):
            continue
        try:
            if root.is_dir():
                roots.append(root)
        except OSError:
            continue
    return roots


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _add_candidate(directory: Path, filename: str, found: dict[str, dict[str, str]]) -> None:
    definition = _COMMAND_LOOKUP.get(filename.casefold())
    if definition is None:
        return
    cli_id, label, alias = definition
    candidate_path = directory / filename
    try:
        if not candidate_path.is_file():
            return
        normalized_path = os.path.normcase(os.path.abspath(candidate_path))
    except OSError:
        return
    found.setdefault(
        normalized_path,
        {
            "id": cli_id,
            "label": label,
            "command": alias,
            "path": str(candidate_path),
        },
    )


def _scan_shim_directory(directory: Path, found: dict[str, dict[str, str]]) -> None:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                _add_candidate(directory, entry.name, found)
    except OSError:
        return


def scan_local_ai_clis(
    *,
    roots: Iterable[Path] | None = None,
    search_path: bool | None = None,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    progress_interval: float = 0.35,
) -> dict[str, Any]:
    """Walk local drives for known AI CLI command shims without executing them.

    ``node_modules/.bin`` and virtual-environment Scripts directories are inspected
    directly before their large dependency trees are pruned. Directory junctions,
    caches that contain operating-system files, and network drives are not followed.
    """
    if search_path is None:
        search_path = roots is None
    scan_roots = [Path(root) for root in (roots if roots is not None else local_scan_roots())]
    if not scan_roots:
        raise RuntimeError("找不到可掃描的本機磁碟。")

    cancel_event = cancel_event or threading.Event()
    found: dict[str, dict[str, str]] = {}
    directory_count = 0
    path_directory_count = 0
    inaccessible_count = 0
    started = time.monotonic()
    last_report = 0.0
    current_drive = ""

    def report(force: bool = False) -> None:
        nonlocal last_report
        now = time.monotonic()
        if progress and (force or now - last_report >= progress_interval):
            progress(
                {
                    "drive": current_drive,
                    "directories": directory_count,
                    "path_directories": path_directory_count,
                    "inaccessible": inaccessible_count,
                    "found": len(found),
                    "elapsed": now - started,
                }
            )
            last_report = now

    def on_walk_error(_error: OSError) -> None:
        nonlocal inaccessible_count
        inaccessible_count += 1
        report()

    if search_path and not cancel_event.is_set():
        current_drive = "PATH"
        allowed_drives = {os.path.normcase(root.drive) for root in scan_roots if root.drive}
        seen_path_directories: set[str] = set()
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if cancel_event.is_set():
                break
            raw_path = os.path.expandvars(entry.strip().strip('"'))
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                continue
            if os.name == "nt" and os.path.normcase(candidate.drive) not in allowed_drives:
                continue
            try:
                normalized = os.path.normcase(os.path.abspath(candidate))
                if normalized in seen_path_directories or not candidate.is_dir() or _is_link_or_reparse(candidate):
                    continue
            except OSError:
                continue
            seen_path_directories.add(normalized)
            path_directory_count += 1
            _scan_shim_directory(candidate, found)
            report()

    for root in scan_roots:
        if cancel_event.is_set():
            break
        current_drive = root.drive or str(root)
        report(force=True)

        for current, directory_names, filenames in os.walk(
            root,
            topdown=True,
            onerror=on_walk_error,
            followlinks=False,
        ):
            if cancel_event.is_set():
                break
            directory = Path(current)
            directory_count += 1
            for filename in filenames:
                _add_candidate(directory, filename, found)

            pruned: list[str] = []
            for dirname in directory_names:
                folded = dirname.casefold()
                child = directory / dirname
                if _is_link_or_reparse(child):
                    pruned.append(dirname)
                elif folded == _NODE_MODULES_NAME:
                    _scan_shim_directory(child / ".bin", found)
                    pruned.append(dirname)
                elif folded in _VIRTUAL_ENV_NAMES:
                    _scan_shim_directory(child / "Scripts", found)
                    pruned.append(dirname)
                elif folded in _SKIP_DIRECTORY_NAMES:
                    pruned.append(dirname)

            if pruned:
                pruned_names = set(pruned)
                directory_names[:] = [name for name in directory_names if name not in pruned_names]
            report()

    report(force=True)
    results = sorted(found.values(), key=lambda item: (item["label"].casefold(), item["path"].casefold()))
    return {
        "roots": [str(root) for root in scan_roots],
        "directories": directory_count,
        "path_directories": path_directory_count,
        "inaccessible": inaccessible_count,
        "results": results,
        "cancelled": cancel_event.is_set(),
        "elapsed": time.monotonic() - started,
    }
