"""Bounded conversation state. Shell integrations keep it in shell memory."""
import json
import os
from pathlib import Path
import tempfile

from .core import CONTROL, SECRET, split_buffer

LIMIT = 6


def load_session(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        if path.stat().st_size > 100_000:
            raise ValueError()
        state = json.loads(path.read_text())
        split_buffer(state["buffer"])
        turns = state["turns"]
        if not isinstance(turns, list) or len(turns) > LIMIT:
            raise ValueError()
        for turn in turns:
            if not isinstance(turn, dict) or not isinstance(turn.get("intent"), str):
                raise ValueError()
            for key, value in turn.items():
                if key not in {"intent", "suggested_command", "selected_command"} or not isinstance(value, str):
                    raise ValueError()
                if len(value) > 8000 or CONTROL.search(value) or SECRET.search(value):
                    raise ValueError()
        if SECRET.search(state["buffer"]):
            raise ValueError()
        return {"buffer": state["buffer"], "turns": turns}
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("The saved Compass conversation is invalid. Start a new conversation.") from None


def save_session(path: Path | None, state: dict):
    if path is None:
        return
    fd, temp = tempfile.mkstemp(prefix=".compass-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"buffer": state["buffer"], "turns": state["turns"][-LIMIT:]}, stream)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
