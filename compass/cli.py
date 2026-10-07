from __future__ import annotations

import argparse
import curses
from concurrent.futures import Future
import json
import os
from pathlib import Path
import sys
import threading
import time
import textwrap

from . import __version__
from .core import Result, help_text, safe_text, suggest
from .completion import completion_choices, completion_scope, read_completions
from .session import LIMIT, load_session, save_session


def parser():
    p = argparse.ArgumentParser(description="Compass — find CLI commands with Jev, shell history, and local help.")
    p.add_argument("intent", nargs="?", help="What you want to do, in plain language")
    p.add_argument("--buffer", "-b", default="aws ec2", help="Current command line (default: aws ec2)")
    p.add_argument("--history", type=Path, help="History file; shell widgets supply current session history")
    p.add_argument("--offline", action="store_true", help="Use local keyword ranking without an API request")
    p.add_argument("--no-history", action="store_true", help="Exclude shell history")
    p.add_argument("--no-help", action="store_true", help="Skip invoking local CLI help")
    p.add_argument("--json", action="store_true", help="Return ranked candidates and status as JSON")
    p.add_argument("--pick", action="store_true", help="Open interactive picker; stdout receives only the selected command")
    p.add_argument("--browse", action="store_true", help="Show completion choices before entering a plain-language request")
    p.add_argument("--completions", type=Path, help="Native completion records supplied by the zsh widget")
    p.add_argument("--completion-scope", help="CLI scope before the word being completed (shell integration)")
    p.add_argument("--session", type=Path, help="Conversation state file (shell widgets manage this automatically)")
    p.add_argument("--resume", action="store_true", help="Continue the saved conversation instead of starting a new one")
    p.add_argument("--version", action="version", version="Compass " + __version__)
    return p


def interactive(args, search, state, browse=None) -> str | None:
    """Use the controlling terminal even when the shell captures stdout."""
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        raise ValueError("The picker needs an interactive terminal. Use --json or supply an intent.") from None
    saved_in, saved_out = os.dup(0), os.dup(1)
    try:
        sys.stdout.flush()
        os.dup2(tty_fd, 0)
        os.dup2(tty_fd, 1)
        return curses.wrapper(lambda screen: picker(screen, args.buffer if args.browse else state["buffer"],
                                                   args.intent or "", search, state,
                                                   lambda: save_session(args.session, state), browse))
    finally:
        os.dup2(saved_in, 0)
        os.dup2(saved_out, 1)
        os.close(saved_in)
        os.close(saved_out)
        os.close(tty_fd)


def picker(screen, buffer, query, search, state, checkpoint, browse=None) -> str | None:
    curses.curs_set(1)
    screen.keypad(True)
    screen.timeout(100)
    result, error, mode, selected, future = None, "", "edit", 0, None
    future_kind, browsing = "search", bool(browse)
    initial_choices = None

    def run_search(intent, conversation, target):
        try:
            target.set_result(search(intent, conversation))
        except Exception as exc:
            target.set_exception(exc)

    def run_browse(target):
        try:
            target.set_result(browse())
        except Exception as exc:
            target.set_exception(exc)

    if browse:
        mode, future_kind, future = "browse", "browse", Future()
        threading.Thread(target=run_browse, args=(future,), daemon=True).start()

    def line(row, text, attr=0):
        height, width = screen.getmaxyx()
        if 0 <= row < height - 1 and width > 2:
            try:
                screen.addnstr(row, 2, safe_text(text), width - 4, attr)
            except curses.error:
                pass

    # Search workers are daemon threads: Escape can return during a request.
    while True:
        if future and future.done():
            try:
                result = future.result()
                if future_kind == "browse":
                    initial_choices = result
                    error = "" if result.candidates else "No completion choices. Type a request and press Enter."
                else:
                    state["turns"].append({"intent": query,
                                           "suggested_command": result.candidates[0].command if result.candidates else ""})
                    state["turns"] = state["turns"][-LIMIT:]
                    checkpoint()
                    error = "" if result.candidates else "No matching command. Press / to refine your request."
            except Exception as exc:
                error = str(exc) if isinstance(exc, ValueError) else "Search failed. Press / to try again."
                result = None
            mode = "browse" if future_kind == "browse" else "select"
            future, selected = None, 0
        if browsing and initial_choices is not None:
            filtered = [c for c in initial_choices.candidates
                        if all(word in (c.description + " " + c.command).lower() for word in query.lower().split())]
            result = Result(filtered, initial_choices.engine, None, initial_choices.warnings)
            selected = min(selected, max(0, len(filtered) - 1))
        screen.erase()
        height, width = screen.getmaxyx()
        line(1, "COMPASS  /  find your next command", curses.A_BOLD)
        line(3, "$ " + buffer, curses.A_DIM)
        if state["turns"]:
            line(4, "Previous request: " + state["turns"][-1]["intent"], curses.A_DIM)
        title = "Type to filter completions, or ask in plain English" if browsing else (
            "Correction or follow-up?" if state["turns"] else "What do you want to do?")
        line(5, title, curses.A_BOLD)
        line(6, "> " + query)
        if future:
            line(8, ("Loading completion choices " if future_kind == "browse" else "Searching help, history, and Jev ")
                 + "." * (int(time.monotonic() * 3) % 4))
        elif result:
            label = {"jev": "Jev choice probabilities", "completion": "Shell completion choices",
                     "browse": "Local completion choices"}.get(result.engine, "Local keyword ranking")
            line(8, label + " · selection returns to your command line", curses.A_DIM)
            if browsing:
                count = len(result.candidates)
                line(9, f"{count} {'choice' if count == 1 else 'choices'} · Enter asks Compass when a request is typed", curses.A_DIM)
            if result.candidates:
                rows = max(1, (height - 15) // 4)
                start = min(max(0, selected - rows + 1), max(0, len(result.candidates) - rows))
                for i, candidate in enumerate(result.candidates[start:start + rows], start):
                    row = 10 + (i - start) * 4
                    marker = "›" if i == selected else " "
                    score = f"{candidate.score:.0%}" if result.engine == "jev" else ""
                    line(row, f"{marker} {i+1}. [{candidate.source}] {score} {candidate.description}",
                         curses.A_BOLD if i == selected else 0)
                    fragments = textwrap.wrap(candidate.command, width=max(1, width - 7),
                                              break_on_hyphens=False, replace_whitespace=False,
                                              drop_whitespace=False)
                    for offset, fragment in enumerate(fragments[:3], 1):
                        line(row + offset, "   " + fragment, curses.A_REVERSE if i == selected else curses.A_DIM)
                line(height - 5, result.candidates[selected].note, curses.A_DIM)
            if result.warnings:
                line(height - 4, result.warnings[0], curses.A_DIM)
        elif state["turns"]:
            previous = state["turns"][-1]
            line(8, "Previous command: " + (previous.get("selected_command") or previous.get("suggested_command", "")), curses.A_DIM)
        if error:
            line(height - 3, error, curses.A_BOLD)
        if mode == "browse":
            hint = "Type a request · Enter ask · ↓ or Tab choose · Esc cancel"
        else:
            hint = "Enter search · Esc cancel" if mode == "edit" else "↑↓ choose · Enter insert · / follow-up · e edit request · Esc cancel"
        line(height - 2, hint, curses.A_DIM)
        if height < 16 or width < 45:
            line(8, "Resize the terminal for the command list.")
        try:
            curses.curs_set(1 if mode in {"edit", "browse"} else 0)
            if mode in {"edit", "browse"} and height > 7:
                screen.move(6, min(width - 2, len(query) + 4))
        except curses.error:
            pass
        screen.refresh()
        try:
            key = screen.get_wch()
        except curses.error:
            continue
        if key in ("\x1b", "\x03"):
            return None
        if key == curses.KEY_RESIZE:
            continue
        if future and future_kind == "search":
            continue
        if mode == "browse" and key in (curses.KEY_DOWN, curses.KEY_UP, "\t", curses.KEY_BTAB) and result and result.candidates:
            selected = 0 if key in (curses.KEY_DOWN, "\t") else len(result.candidates) - 1
            mode = "select"
        elif mode == "browse" and key in ("\n", "\r", curses.KEY_ENTER) and not query.strip() and result and result.candidates:
            state["turns"].append({"intent": "Complete " + state["buffer"],
                                   "selected_command": result.candidates[selected].command})
            checkpoint()
            return result.candidates[selected].command
        elif mode in {"edit", "browse"}:
            if key in ("\n", "\r", curses.KEY_ENTER):
                if query.strip():
                    future = Future()
                    future_kind, browsing = "search", False
                    threading.Thread(target=run_search, args=(query, list(state["turns"]), future), daemon=True).start()
                    error = ""
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                query = query[:-1]
            elif key == "\x15":
                query = ""
            elif isinstance(key, str) and key.isprintable() and len(query) < 2000:
                query += key
        else:
            count = len(result.candidates) if result else 0
            if key in ("/", "\x15"):
                mode = "browse" if browsing else "edit"
                query = ""
            elif key == "e" and state["turns"]:
                query = state["turns"].pop()["intent"]
                mode = "edit"
            elif key in (curses.KEY_DOWN, "j", "\t") and count:
                selected = (selected + 1) % count
            elif key in (curses.KEY_UP, "k", curses.KEY_BTAB) and count:
                selected = (selected - 1) % count
            elif isinstance(key, str) and key in "12345678" and int(key) <= count:
                selected = int(key) - 1
            elif key in ("\n", "\r", curses.KEY_ENTER) and count:
                if browsing:
                    state["turns"].append({"intent": query or "Complete " + state["buffer"]})
                state["turns"][-1]["selected_command"] = result.candidates[selected].command
                checkpoint()
                return result.candidates[selected].command
            elif browsing and isinstance(key, str) and key.isprintable():
                query += key
                mode = "browse"


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)

    try:
        if args.resume and args.session is None:
            raise ValueError("--resume needs --session; shell shortcuts supply it automatically.")
        state = load_session(args.session) if args.resume else None
        if args.resume and state is None:
            raise ValueError("No previous Compass conversation. Start one first.")
        buffer = completion_scope(args.completion_scope) if args.completion_scope else args.buffer
        state = state or {"buffer": buffer, "turns": []}
        native = read_completions(args.completions)

        def search(intent, conversation=None):
            return suggest(state["buffer"], intent, history=args.history, offline=args.offline,
                           no_history=args.no_history, no_help=args.no_help, conversation=conversation,
                           extra_candidates=native)

        def browse():
            return completion_choices(state["buffer"], native, args.history, args.no_history, args.no_help, help_text)

        if args.pick:
            command = interactive(args, search, state, browse if args.browse else None)
            if command is None:
                return 130
            print(command)
        else:
            if not args.intent:
                p.error("supply an intent or use --pick")
            result: Result = search(args.intent, state["turns"])
            state["turns"].append({"intent": args.intent,
                                   "suggested_command": result.candidates[0].command if result.candidates else ""})
            save_session(args.session, state)
            if args.json:
                print(json.dumps(result.json(), indent=2))
            else:
                print(f"Compass · {result.engine} ranking\n")
                for i, c in enumerate(result.candidates, 1):
                    probability = f" · {c.score:.0%}" if result.engine == "jev" else ""
                    print(f"{i}. {c.description} [{c.source}{probability}]\n   {c.command}")
                    if c.note:
                        print(f"   {c.note}")
                if not result.candidates:
                    print("No matching commands. Try a more specific request.")
                for warning in result.warnings:
                    print(warning, file=sys.stderr)
        return 0
    except (ValueError, OSError, curses.error) as exc:
        print(f"Compass: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
