# Advanced usage

## Combined completion in zsh

Source `shell/compass.zsh` after your completion plugins. Single Tab delegates
to the widget that was already bound. A second consecutive Tab at the end of a
simple CLI command opens Compass with choices from zsh's completion system.
The temporary capture hook is restored before the picker opens; ordinary
completion functions and plugins remain available.

Type to filter the list locally. Enter with a typed request asks Compass to
interpret it. To insert a filtered completion directly, press Down or Tab to
focus the choices, then Enter. Enter with an empty input inserts the highlighted
choice. Escape returns to your original command line. The full completion list
is browsable; the eight-result limit applies only to semantic search results.

Opening and filtering the menu makes no TypeSafe request. If native choices
aren't available, local help supplies command paths; recipes and history are
the final fallback. Natural-language search includes native choices alongside
recipes, help and history.

Blank prompts, mid-line cursors, pipelines, and shell expressions use native Tab
behavior. Explicit request and resume shortcuts remain available.

To disable the combined menu and restore native double-Tab:

```sh
export COMPASS_DOUBLE_TAB=0
source ~/.local/share/compass/shell/compass.zsh
```

Set `COMPASS_DOUBLE_TAB=1` and re-source to enable it again. Re-sourcing doesn't
replace Compass's saved native widget with itself.

## Bash

Bash 4+ is required for editable Readline buffers. macOS's bundled Bash 3.2 is not
supported; use zsh there.

```sh
source ~/.local/share/compass/shell/compass.bash
```

Ctrl-X, then plain C starts a new conversation. Ctrl-X, then plain R resumes
the last one. Release Ctrl before pressing C or R. The original Ctrl-X, Ctrl-A
and Ctrl-X, Ctrl-R shortcuts also work. Ctrl-Space is left untouched.
Compass doesn't bind Tab. The Bash script is syntax-checked; the automated terminal
integration test targets zsh.

## Custom zsh shortcuts

The default shortcuts use Ctrl-X followed by plain C or R. To assign different
keys after sourcing Compass, bind its widgets, for example:

```sh
bindkey -M emacs '^Xf' compass-pick
bindkey -M emacs '^Xb' compass-resume
bindkey -M viins '^Xf' compass-pick
bindkey -M viins '^Xb' compass-resume
```

The widgets are installed in emacs and vi insert keymaps. The zsh Tab wrapper
saves your existing widget and invokes it on the first Tab. Disable the wrapper
with `COMPASS_DOUBLE_TAB=0` when using another double-Tab interface.

## CLI options

```sh
./bin/compass --help
./bin/compass --buffer 'aws ec2' --pick
./bin/compass --buffer 'aws ec2' --pick --browse
./bin/compass --buffer 'aws ec2' 'list instances with tags' --json
./bin/compass --no-history --no-help --buffer 'aws ec2' 'list instances'
```

The default buffer for standalone use is `aws ec2`. Supply `--buffer` for another
CLI. Shell widgets pass the current command line automatically.

Use `--history PATH` to supply a specific history file. Otherwise standalone use
reads `$HISTFILE` or `~/.zsh_history`; shell widgets include their current session.
Up to 100 recent distinct matching commands are considered. `--browse` starts
the picker with local choices. The zsh widget also supplies private native
completion records through `--completions` and the CLI scope through
`--completion-scope`; those are normally managed by the integration.

## Explicit context

| CLI | Preserved context flags |
| --- | --- |
| AWS | `--profile`, `--region`, `--output` |
| kubectl | `--context`, `--namespace`, `-n`, `--kubeconfig` |
| Azure | `--subscription`, `--resource-group`, `-g`, `--output`, `-o` |

Explicit flags override matching recipe defaults and saved history arguments.
An explicit Kubernetes namespace also removes all-namespace flags from recipes.
Other existing flags aren't accepted in a starting buffer yet. Begin with a
command path and describe the desired arguments.

Resume reuses the original scope rather than reparsing a previously inserted
command with generated filters. Start a new conversation to change scope.

AWS and Azure requests can name an output format, such as “in table format” or
“as JSON”. The last format mentioned across the conversation wins; an explicit
output flag in the starting buffer takes precedence. Compass applies context
and output flags before ranking so Jev sees the arguments that will be inserted.
EC2 table recipes project scalar ID, Name, State and Type fields. Requests for
all tags add a scalar `key=value` column, including an empty value for untagged
instances. This avoids a nested table for each instance's tags.

## Standalone conversations

```sh
./bin/compass --session /tmp/compass-conversation.json --buffer 'aws ec2' 'list instances with tags'
./bin/compass --session /tmp/compass-conversation.json --resume 'actually only with tag nitro'
```

Session files are atomically written with mode 0600 and retain six turns. Delete
an explicit session file when you're done. Widgets keep state in a non-exported
shell variable between invocations and remove their temporary files on return.
Completed searches can be resumed even if you cancel without accepting a command.
Cancelling a fresh conversation before searching retains the previous conversation.

## Ranking

Code reserves candidate slots for recipes, history, and the current conversation,
then prefilters up to 120 commands using overlap and synonyms. Jev gets a Choice
with a no-match option and a separate Noul fit question. Its latest correction
supersedes conflicting earlier requirements; other earlier requirements remain.

A fit below 0.5 or a winning no-match option yields no suggestions. Results with
choice probability below 0.01 are hidden. If a matching help command has children,
Compass expands it and reranks, up to four rounds. These gates are initial defaults,
not a measured guarantee of accuracy. Percentages compare candidates in the current
set; they aren't guarantees that a command is correct.

`COMPASS_MODEL` selects the TypeSafe model; the default is `jev-latest`.
The API uses the documented HTTPS endpoint and a six-second timeout. Errors fall
back to labeled local keyword ranking without printing API response bodies or keys.

## Local help

Compass executes argv such as `aws ec2 help` or `kubectl get --help` with a four-second
timeout and paging disabled. It never passes your buffer to a shell for execution.
Only use help discovery with CLIs you trust to implement help without side effects;
`--no-help` disables it.

Help is cached under `${XDG_CACHE_HOME:-~/.cache}/compass` for 24 hours, invalidated
when the executable changes. Recognized help layouts include AWS man pages,
Cobra/Click-style command sections, argparse subparsers, and Azure command groups.

## Optional package installation

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/compass --version
```

The package installs the standalone `compass` command. Source the shell widget from
the checkout separately. Standard-library `curses` is required for the picker.
No runtime Python packages are needed.
