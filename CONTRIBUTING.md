# Contributing

Small, focused improvements are welcome: CLI recipes, help-layout support,
conversation behavior, and terminal usability.

## Run the checks

Python 3.10+ and zsh are required for the full suite.

```sh
python3 -m unittest discover -s tests -v
zsh -n shell/compass.zsh
bash -n shell/compass.bash
```

Tests use synthetic history and mocked TypeSafe responses. The terminal test drives
an isolated zsh with a fake CLI. A real API key is not needed for the suite.

## Add a recipe or help parser

Recipes live in `templates` in `compass/core.py`. Copy literal values from the
request, construct argv, then quote with `shlex.join`. Don't build shell expressions
or execute a proposed command. Include a concise description and a note when scope
or required arguments matter.

Extend `parse_help` for a new help layout. Add representative help text as a test
fixture, including section boundaries and nested groups. Help discovery should use
argv and bounded timeouts; avoid shell invocation and network resource discovery.

Test behavior that matters to users: correct filters, retained context flags,
no-match handling, no command execution, native first-Tab behavior, double-Tab
menu filtering, and restoration of completion hooks. Browsing must never call
Jev; only a submitted request does.

## Keep the published demo reproducible

See [docs/demo.md](docs/demo.md). Use a clean prompt and synthetic or excluded
history. Check both the recording and rendered animation before publishing.

## Pull requests

Explain the concrete problem, the resulting behavior, and the checks you ran.
If a change uses a live API, distinguish mocked coverage from live validation.
Don't commit credentials, personal shell history, environment files, or recordings
that show private account details.
