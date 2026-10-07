# Tab stays with Readline completion. Ctrl-X then C starts Compass;
# Ctrl-X then R resumes the last conversation.

if (( BASH_VERSINFO[0] < 4 )); then
  printf '%s\n' 'Compass needs Bash 4+ for editable Readline buffers. On macOS, use the zsh integration.' >&2
  return 1
fi

COMPASS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPASS_BIN="${COMPASS_BIN:-$COMPASS_ROOT/bin/compass}"
_COMPASS_CONVERSATION="${_COMPASS_CONVERSATION:-}"

_compass_pick() {
  local selected tmpdir mode=${1:-new}
  tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/compass.XXXXXXXX") || return 1
  chmod 700 "$tmpdir"
  builtin history 200 | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//' > "$tmpdir/history"
  local -a opts=()
  [[ ${COMPASS_OFFLINE:-0} == 1 ]] && opts+=(--offline)
  [[ ${COMPASS_NO_HISTORY:-0} == 1 ]] && opts+=(--no-history)
  if [[ $mode == resume && -n $_COMPASS_CONVERSATION ]]; then
    printf '%s\n' "$_COMPASS_CONVERSATION" > "$tmpdir/session"
    opts+=(--resume)
  fi
  if "$COMPASS_BIN" --pick --buffer "$READLINE_LINE" --history "$tmpdir/history" --session "$tmpdir/session" "${opts[@]}" > "$tmpdir/selection"; then
    selected=$(cat "$tmpdir/selection")
    if [[ -n "$selected" ]]; then
      READLINE_LINE="$selected"
      READLINE_POINT=${#READLINE_LINE}
    fi
  fi
  [[ -f "$tmpdir/session" ]] && _COMPASS_CONVERSATION=$(cat "$tmpdir/session")
  rm -rf -- "$tmpdir"
}

bind -x '"\C-x\C-a":_compass_pick'
bind -x '"\C-x\C-r":_compass_pick resume'
bind -x '"\C-xc":_compass_pick'
bind -x '"\C-xr":_compass_pick resume'
