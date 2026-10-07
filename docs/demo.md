# Record the terminal demo

The README animation comes from a real zsh session recorded as
[asciicast v2](demo.cast), then rendered as [a GIF](demo.gif).
It shows native first-Tab completion, the second-Tab Compass menu, local filtering,
a live Jev request for an EC2 table, insertion, and a tag-filter correction.
No proposed AWS command is executed.

## Record

Requires Python 3.10+, zsh, the AWS CLI (including `aws_completer` on PATH),
and a TypeSafe API key for the live demo:

```sh
export TYPESAFE_API_KEY='your-typesafe-api-key'
python3 scripts/record_demo.py
```

The script uses a fresh `zsh -f` session in the user's home directory with a
demo-only `~ >>` prompt. It initializes zsh completion with the AWS CLI's own
`aws_completer`, then sources Compass. Bootstrap happens before recording starts. It excludes
personal history, never records the environment or API key, and leaves your normal
prompt and shell configuration unchanged.
The demo shell disables automatic printing of the large native list before the
picker opens, keeping the recording readable; the completion choices are real.

Use `--offline` for a local demo. If you replace the published recording with an
offline one, update the README caption accordingly.

## Render

Rendering tools are development-only dependencies, available from PyPI:

```sh
uv run --no-project --with 'pyte==0.8.2' --with 'pillow==12.3.0' python scripts/render_demo.py
```

Or install `pyte` and `Pillow` into a development virtual environment and run the
script there. Menlo is used on macOS and DejaVu Sans Mono on Linux; `--font PATH`
selects another local monospace font. The GIF renders the recorded terminal output,
not a fabricated UI mockup.

Check `docs/demo.png` and play the animation before committing it. The cast can
also be replayed with `asciinema play docs/demo.cast` if asciinema is installed.
