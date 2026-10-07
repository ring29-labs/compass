#!/usr/bin/env python3
"""Record a real zsh/Compass session as asciicast v2. No cloud command is run."""
import argparse
import codecs
import fcntl
import json
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

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Record local keyword ranking instead of Jev')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/demo.cast')
    args = parser.parse_args()
    if not args.offline and not os.getenv('TYPESAFE_API_KEY'):
        parser.error('Set TYPESAFE_API_KEY for the live demo, or use --offline.')
    completer = shutil.which('aws_completer')
    if not completer:
        parser.error('Install the AWS CLI so aws_completer is available for the native completion demo.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='compass-demo-') as temporary:
        env = {**os.environ, 'TERM': 'xterm-256color', 'COMPASS_NO_HISTORY': '1',
               'COMPASS_OFFLINE': '1' if args.offline else '0', 'COMPASS_DOUBLE_TAB': '1',
               'XDG_CACHE_HOME': temporary}
        # Actual working directory is the user's home; it is never listed or recorded.
        pid, fd = os.forkpty()
        if pid == 0:
            os.chdir(Path.home())
            os.execvpe('zsh', ['zsh', '-f'], env)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 132, 0, 0))
        started, recording, output, events = time.monotonic(), False, '', []
        decoder = codecs.getincrementaldecoder('utf-8')('replace')

        def read_for(seconds):
            nonlocal output
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], min(0.1, max(0, deadline - time.monotonic())))
                if ready:
                    data = os.read(fd, 65536)
                    if not data:
                        raise RuntimeError('The demo shell exited unexpectedly.')
                    chunk = decoder.decode(data)
                    output += chunk
                    if recording:
                        events.append([round(time.monotonic() - started, 3), 'o', chunk])

        def wait_for(text, timeout=40):
            nonlocal output
            deadline = time.monotonic() + timeout
            while text not in output:
                if time.monotonic() > deadline:
                    raise RuntimeError(f'Demo did not reach {text!r}.')
                read_for(0.1)
            output = output.split(text, 1)[1]

        def send(text, typing=False):
            nonlocal output
            output = ''
            if typing:
                for character in text:
                    os.write(fd, character.encode())
                    read_for(0.045)
            else:
                os.write(fd, text.encode())
                read_for(0.1)

        try:
            # Bootstrap before recording: no personal filesystem paths in the cast.
            send(f"autoload -Uz compinit; compinit -i -d {shlex.quote(temporary + '/zcompdump')}; "
                 f"autoload -Uz bashcompinit; bashcompinit; complete -C {shlex.quote(completer)} aws; "
                 f"source {shlex.quote(str(ROOT / 'shell/compass.zsh'))}; "
                 "PS1='~ >> '; HISTFILE=/dev/null; unsetopt AUTO_LIST; clear\n")
            wait_for('~ >> ')
            read_for(0.25)
            started, recording, output = time.monotonic(), True, ''
            events.append([0, 'o', '\x1b[2J\x1b[H~ >> '])
            read_for(1)
            send('aws ec2 ', typing=True)
            read_for(1)
            send('\t')
            read_for(0.6)
            send('\t')
            wait_for('Shell completion choices')
            read_for(1.5)
            send('describe-instances', typing=True)
            read_for(1.5)
            send('\x15')
            send('list all instances in table format', typing=True)
            send('\n')
            ranking = 'Local keyword ranking' if args.offline else 'Jev choice probabilities'
            wait_for(ranking)
            read_for(2.5)
            send('\n')  # Accept into BUFFER only. Never press Enter on the shell buffer.
            wait_for('~ >> ')
            read_for(2)
            send('\x18r')
            wait_for('Previous request: list all instances in table format')
            read_for(1)
            send('only with tag Environment=prod', typing=True)
            send('\n')
            wait_for(ranking)
            wait_for('Environment=prod')
            read_for(2.5)
            send('\n')
            wait_for('~ >> ')
            read_for(2.5)
            # Clear the edited buffer and show a short note; this command is local.
            send('\x01\x0bprint -r -- "Selection inserted. Review it before pressing Enter."\n')
            wait_for('~ >> ')
            read_for(2)
            header = {'version': 2, 'width': 132, 'height': 28,
                      'title': 'Compass: double-Tab, browse completions, ask Jev, then refine',
                      'env': {'TERM': 'xterm-256color'},
                      'theme': {'fg': '#d9e2f2', 'bg': '#0d1117'}}
            with args.output.open('w') as stream:
                stream.write(json.dumps(header) + '\n')
                for event in events:
                    stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            print(f'Recorded {events[-1][0]:.1f}s to {args.output}')
        finally:
            os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if os.waitpid(pid, os.WNOHANG)[0]:
                    break
                time.sleep(0.02)
            os.close(fd)


if __name__ == '__main__':
    main()
