"""Real terminal tests: native completion, Compass resume, no execution."""
import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import struct
import tempfile
import termios
import time
import unittest
import fcntl

ROOT = Path(__file__).resolve().parents[1]


class Terminal:
    def __init__(self, argv, env):
        self.pid, self.fd = os.forkpty()
        if self.pid == 0:
            os.execvpe(argv[0], argv, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 140, 0, 0))
        self.output = b""

    def send(self, text):
        os.write(self.fd, text.encode())

    def wait(self, text, timeout=8):
        expected, deadline = text.encode(), time.monotonic() + timeout
        while expected not in self.output:
            if time.monotonic() > deadline:
                raise AssertionError(f"Missing {text!r} in terminal:\n{self.output[-7000:]!r}")
            ready, _, _ = select.select([self.fd], [], [], 0.1)
            if ready:
                try:
                    self.output += os.read(self.fd, 65536)
                except OSError:
                    raise AssertionError(f"Shell exited:\n{self.output!r}") from None
        self.output = self.output.split(expected, 1)[1]

    def close(self):
        try:
            # Interactive shells may ignore SIGTERM. These are our test children.
            os.kill(self.pid, signal.SIGKILL)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    break
                time.sleep(0.02)
        except ProcessLookupError:
            pass
        os.close(self.fd)


@unittest.skipUnless(shutil.which("zsh"), "zsh is required")
class ShellTests(unittest.TestCase):
    def _combined_terminal(self, temp, disabled=False):
        marker = temp / "executed"
        fake = temp / "aws"
        fake.write_text("#!/bin/sh\nif [ \"$2\" = help ]; then\n"
                        "  printf 'AVAILABLE COMMANDS\\n  + describe-instances\\n  + terminate-instances\\n'\n"
                        f"else\n  touch {shlex.quote(str(marker))}\nfi\n")
        fake.chmod(0o755)
        env = {**os.environ, "PATH": str(temp) + ":" + os.environ["PATH"], "TERM": "xterm-256color",
               "COMPASS_OFFLINE": "1", "COMPASS_NO_HISTORY": "1", "XDG_CACHE_HOME": str(temp / "cache")}
        if disabled:
            env["COMPASS_DOUBLE_TAB"] = "0"
        terminal = Terminal(["zsh", "-f"], env)
        # CI images can include untrusted completion directories. Ignore those
        # directories rather than prompting in the isolated test terminal.
        setup = "autoload -Uz compinit; compinit -i -d " + shlex.quote(str(temp / "dump")) + "; "
        setup += "_custom_aws() { local -a candidates; candidates=('describe-instances:List instances' 'native-only-command:Only from shell provider'); _describe 'EC2 commands' candidates; }; compdef _custom_aws aws; "
        setup += "compadd() { builtin compadd \"$@\"; }; _saved_compadd=$functions[compadd]; "
        setup += f"source {shlex.quote(str(ROOT / 'shell/compass.zsh'))}; " * 2
        setup += "_inspect() { print -r -- \"CHECK_BUFFER=$BUFFER\"; [[ $functions[compadd] == $_saved_compadd ]] && print HOOK_RESTORED; zle reset-prompt; }; "
        setup += "zle -N inspect-buffer _inspect; bindkey '^X^P' inspect-buffer; PS1='READY> '; print SETUP_DONE\n"
        terminal.send(setup)
        terminal.wait("SETUP_DONE\r\n")
        terminal.wait("READY> ")
        terminal.output = b""
        return terminal, marker

    def test_double_tab_native_choices_filter_insert_resume_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            terminal, marker = self._combined_terminal(Path(d))
            try:
                terminal.send("aws ec2 \t")
                terminal.wait("Only from shell provider")
                terminal.send("\t")
                terminal.wait("Shell completion choices")
                terminal.wait("native-only-command")
                terminal.send("native-only\t\n")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 native-only-command")
                terminal.wait("HOOK_RESTORED")
                self.assertFalse(marker.exists())
                terminal.send("\x18r")
                terminal.wait("Previous request: native-only")
                terminal.send("\x1b")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 native-only-command")
                self.assertFalse(marker.exists())
            finally:
                terminal.close()

    def test_double_tab_accepts_plain_language_without_a_mode_shortcut(self):
        with tempfile.TemporaryDirectory() as d:
            terminal, marker = self._combined_terminal(Path(d))
            try:
                terminal.send("aws ec2 \t")
                terminal.wait("Only from shell provider")
                terminal.send("\t")
                terminal.wait("Shell completion choices")
                terminal.send("list all instance in table format\n")
                terminal.wait("Local keyword ranking")
                terminal.wait("--output table")
                terminal.send("\n")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 describe-instances --query")
                self.assertFalse(marker.exists())
            finally:
                terminal.close()

    def test_double_tab_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            terminal, marker = self._combined_terminal(Path(d), disabled=True)
            try:
                terminal.send("aws ec2 \t")
                terminal.wait("Only from shell provider")
                terminal.send("\t\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2")
                self.assertNotIn(b"COMPASS  /", terminal.output)
                self.assertFalse(marker.exists())
            finally:
                terminal.close()

    def test_native_file_completion_preserves_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            folder = temp / "some-dir"
            folder.mkdir()
            (folder / "file one.txt").write_text("")
            (folder / "file two.txt").write_text("")
            terminal, marker = self._combined_terminal(temp)
            try:
                terminal.send("cd " + shlex.quote(str(temp)) + "; print DIRECTORY_READY\n")
                terminal.wait("DIRECTORY_READY\r\n")
                terminal.wait("READY> ")
                terminal.send("cat some-dir/\t")
                terminal.wait("file\\ ")
                terminal.send("\t")
                terminal.wait("Shell completion choices")
                terminal.wait("some-dir/file one.txt")
                terminal.send("\n")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=cat 'some-dir/file one.txt'")
                self.assertFalse(marker.exists())
            finally:
                terminal.close()

    def test_native_tab_and_shortcut_resume_with_correction(self):
        self._check_shortcuts("\x18\x01", "\x18\x12")

    def test_plain_letter_shortcuts_preserve_tab_and_control_space(self):
        self._check_shortcuts("\x18c", "\x18r")

    def _check_shortcuts(self, open_keys, resume_keys):
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            marker = temp / "executed"
            fake = temp / "aws"
            fake.write_text("#!/bin/sh\nif [ \"$2\" = help ]; then\n"
                            "  printf 'AVAILABLE COMMANDS\\n  + describe-instances\\n  + terminate-instances\\n'\n"
                            f"else\n  touch {shlex.quote(str(marker))}\nfi\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": str(temp) + ":" + os.environ["PATH"], "TERM": "xterm-256color",
                   "COMPASS_OFFLINE": "1", "XDG_CACHE_HOME": str(temp / "cache"), "TYPESAFE_API_KEY": ""}
            terminal = Terminal(["zsh", "-f"], env)
            try:
                setup = "_native_tab() { zle -M 'NATIVE_TAB_PRESERVED'; }; zle -N native-tab _native_tab; "
                setup += "bindkey -M emacs '^I' native-tab; bindkey -M viins '^I' native-tab; "
                setup += "_native_space() { zle -M 'NATIVE_SPACE_PRESERVED'; }; zle -N native-space _native_space; "
                setup += "bindkey -M emacs '^@' native-space; bindkey -M viins '^@' native-space; "
                setup += f"source {shlex.quote(str(ROOT / 'shell/compass.zsh'))}; PS1='READY> '; "
                setup += "_inspect() { print -r -- \"CHECK_BUFFER=$BUFFER\"; zle reset-prompt; }; "
                setup += "zle -N inspect-buffer _inspect; bindkey '^X^P' inspect-buffer\n"
                terminal.send(setup)
                terminal.wait("READY> ")
                terminal.output = b""
                terminal.send("aws ec2\x00")
                terminal.wait("NATIVE_SPACE_PRESERVED")
                terminal.send("\t")
                terminal.wait("NATIVE_TAB_PRESERVED")
                terminal.send(open_keys)
                terminal.wait("What do you want to do?")
                terminal.send("list all ec2 with their tags\n")
                terminal.wait("Local keyword ranking")
                terminal.send("\n")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 describe-instances --query")
                self.assertFalse(marker.exists(), "Accepting a suggestion must never execute it")
                # Resume from a full generated command with flags. The original
                # command scope must be reused, not reparsed from that buffer.
                terminal.send(resume_keys)
                terminal.wait("Previous request: list all ec2 with their tags")
                terminal.send("actually only with tag nitro\n")
                terminal.wait("Local keyword ranking")
                terminal.send("\n")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 describe-instances --filters Name=tag-key,Values=nitro")
                self.assertFalse(marker.exists())
                # Searches survive Escape, and cancellation keeps the buffer.
                terminal.send(resume_keys)
                terminal.wait("Previous request: actually only with tag nitro")
                terminal.send("\x1b")
                terminal.wait("READY> ")
                terminal.send("\x18\x10")
                terminal.wait("CHECK_BUFFER=aws ec2 describe-instances --filters Name=tag-key,Values=nitro")
                self.assertFalse(marker.exists())
            finally:
                terminal.close()


if __name__ == "__main__":
    unittest.main()
