"""Completion choices supplied by the shell; browsing never calls Jev."""
from pathlib import Path
import shlex

from .core import (CONTROL, SECRET, Candidate, Result, apply_context, parse_help,
                   read_history, split_buffer, templates)


def completion_scope(buffer: str) -> str:
    """Drop an incomplete option/value until the CLI scope can be searched."""
    words = shlex.split(buffer)
    while words:
        scope = shlex.join(words)
        try:
            split_buffer(scope)
            return scope
        except ValueError:
            words.pop()
    raise ValueError("Type a CLI name first, then press Tab twice.")


def read_completions(path: Path | None) -> list[Candidate]:
    if path is None:
        return []
    try:
        if path.stat().st_size > 2_000_000:
            return []
        fields = path.read_text().split("\0")
    except (OSError, UnicodeError):
        return []
    candidates, seen = [], set()
    for index in range(0, len(fields) - 1, 2):
        command, description = fields[index:index + 2]
        if not command or CONTROL.search(command) or SECRET.search(command):
            continue
        try:
            # Requote the words so a completion is always inserted as literals.
            command = shlex.join(shlex.split(command))
        except ValueError:
            continue
        if command and command not in seen:
            seen.add(command)
            candidates.append(Candidate(command, description or command, "completion",
                                        note="From your shell completion provider; review arguments before running."))
    return candidates


def completion_choices(buffer: str, native: list[Candidate], history, no_history, no_help, discover) -> Result:
    if native:
        return Result(native, "completion", None, [])
    path, flags = split_buffer(buffer)
    items = [] if no_help else parse_help(path, discover(path))
    if not items:
        items = templates(path, "list")
        if not no_history:
            items += read_history(history, path.split()[0])
    unique = {}
    for item in items:
        if item.command == path or item.command.startswith(path + " "):
            if not SECRET.search(item.command) and not CONTROL.search(item.command):
                item = apply_context(item, flags)
                unique.setdefault(item.command, item)
    return Result(list(unique.values()), "browse", None, [])
