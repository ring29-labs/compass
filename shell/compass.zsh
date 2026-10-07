# First Tab uses your completion system; a consecutive second Tab opens Compass.
# Ctrl-X then C starts Compass; Ctrl-X then R resumes its last conversation.
typeset -g COMPASS_ROOT="${${(%):-%N}:A:h:h}"
typeset -g COMPASS_BIN="${COMPASS_BIN:-$COMPASS_ROOT/bin/compass}"
typeset -g _COMPASS_CONVERSATION="${_COMPASS_CONVERSATION:-}"
typeset -gA _COMPASS_NATIVE_TAB
typeset -ga _COMPASS_COMPLETIONS _COMPASS_DESCRIPTIONS
typeset -g _COMPASS_TAB_BUFFER _COMPASS_COMPLETION_SCOPE
typeset -gi _COMPASS_TAB_CURSOR

_compass_pick() {
  local selected tmpdir mode=${1:-new}
  tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/compass.XXXXXXXX") || return 1
  chmod 700 "$tmpdir"
  fc -ln -200 > "$tmpdir/history" 2>/dev/null
  local -a opts
  [[ ${COMPASS_OFFLINE:-0} == 1 ]] && opts+=(--offline)
  [[ ${COMPASS_NO_HISTORY:-0} == 1 ]] && opts+=(--no-history)
  if [[ $mode == browse ]]; then
    local i
    for (( i=1; i<=${#_COMPASS_COMPLETIONS}; i++ )); do
      print -rn -- "${_COMPASS_COMPLETIONS[i]}"$'\0'"${_COMPASS_DESCRIPTIONS[i]}"$'\0' >> "$tmpdir/completions"
    done
    opts+=(--browse --completions "$tmpdir/completions" --completion-scope "${_COMPASS_COMPLETION_SCOPE:-$BUFFER}")
  fi
  if [[ $mode == resume && -n $_COMPASS_CONVERSATION ]]; then
    print -r -- "$_COMPASS_CONVERSATION" > "$tmpdir/session"
    opts+=(--resume)
  fi
  zle -I
  if "$COMPASS_BIN" --pick --buffer "$BUFFER" --history "$tmpdir/history" --session "$tmpdir/session" "${opts[@]}" > "$tmpdir/selection"; then
    selected=$(<"$tmpdir/selection")
    if [[ -n "$selected" ]]; then
      BUFFER="$selected"
      CURSOR=${#BUFFER}
    fi
  fi
  [[ -f "$tmpdir/session" ]] && _COMPASS_CONVERSATION=$(<"$tmpdir/session")
  rm -rf -- "$tmpdir"
  zle reset-prompt
}

_compass_resume() { _compass_pick resume }

# This hook exists only while collecting choices on the second Tab. It leaves
# the native completion provider and its first-Tab insertion behavior intact.
_compass_capture_compadd() {
  local -A captured_opts
  local -a matches descriptions command_words
  local match description prefix suffix i
  zparseopts -E -A captured_opts P: p: S: s: i: I: d: A: O: D: W: F: M: \
    X: x: J: V: r: R: E: o:: a k q Q f e n U l 1 2 C
  if (( ${+captured_opts[-A]} || ${+captured_opts[-O]} || ${+captured_opts[-D]} )); then
    builtin compadd "$@"
    return
  fi
  if [[ -n ${captured_opts[-d]:-} ]]; then
    local description_array=${captured_opts[-d]}
    descriptions=( "${(@P)description_array}" )
  fi
  builtin compadd -A matches -D descriptions "$@"
  prefix="${IPREFIX}${captured_opts[-i]:-}${captured_opts[-P]:-}${captured_opts[-p]:-}"
  suffix="${captured_opts[-s]:-}${captured_opts[-S]:-}${captured_opts[-I]:-}${ISUFFIX}"
  for (( i=1; i<=${#matches}; i++ )); do
    match="$prefix${matches[i]}$suffix"
    # -Q providers have already shell-quoted their matches. Decode those before
    # quoting the full argv so filenames don't acquire literal backslashes.
    (( ${+captured_opts[-Q]} )) && match=${(Q)match}
    command_words=()
    (( CURRENT > 1 )) && command_words+=( "${(@Q)words[1,CURRENT-1]}" )
    command_words+=( "$match" )
    (( CURRENT < ${#words} )) && command_words+=( "${(@Q)words[CURRENT+1,-1]}" )
    _COMPASS_COMPLETIONS+=( "${(j: :)${(@q)command_words}}" )
    _COMPASS_DESCRIPTIONS+=( "${descriptions[i]:-$match}" )
  done
  builtin compadd "$@"
}

_compass_collect() {
  local saved_compadd=${functions[compadd]:-} had_compadd=${+functions[compadd]}
  local -a scope_words
  (( CURRENT > 1 )) && scope_words=( "${(@Q)words[1,CURRENT-1]}" )
  _COMPASS_COMPLETION_SCOPE="${(j: :)${(@q)scope_words}}"
  compstate[old_list]=''
  compstate[old_insert]=''
  functions[compadd]=$functions[_compass_capture_compadd]
  {
    _main_complete
  } always {
    if (( had_compadd )); then
      functions[compadd]=$saved_compadd
    else
      unfunction compadd
    fi
    compstate[insert]=''
    compstate[list]=''
    compstate[old_list]=''
  }
}

_compass_tab() {
  local native=${_COMPASS_NATIVE_TAB[$KEYMAP]:-${_COMPASS_NATIVE_TAB[emacs]:-expand-or-complete}}
  local -a buffer_words
  buffer_words=( ${(z)BUFFER} )
  if [[ ${COMPASS_DOUBLE_TAB:-1} != 0 && $LASTWIDGET == compass-tab &&
        $BUFFER == $_COMPASS_TAB_BUFFER && $CURSOR == $_COMPASS_TAB_CURSOR &&
        $CURSOR == ${#BUFFER} && ${buffer_words[1]:-} =~ '^[a-zA-Z0-9][a-zA-Z0-9_.-]*$' &&
        $BUFFER != *'|'* && $BUFFER != *';'* && $BUFFER != *'&'* &&
        $BUFFER != *'<'* && $BUFFER != *'>'* && $BUFFER != *'$'* && $BUFFER != *'`'* ]]; then
    _COMPASS_COMPLETIONS=()
    _COMPASS_DESCRIPTIONS=()
    _COMPASS_COMPLETION_SCOPE=$BUFFER
    if (( ${+functions[_main_complete]} )); then
      zle compass-collect
    fi
    _compass_pick browse
    _COMPASS_TAB_BUFFER=''
  else
    zle "$native"
    _COMPASS_TAB_BUFFER=$BUFFER
    _COMPASS_TAB_CURSOR=$CURSOR
  fi
}

zle -N compass-pick _compass_pick
zle -N compass-resume _compass_resume
zle -N compass-tab _compass_tab
zle -C compass-collect list-choices _compass_collect
for _compass_map in emacs viins; do
  _compass_binding=${${(z)$(bindkey -M "$_compass_map" '^I')}[-1]}
  if [[ $_compass_binding != compass-tab ]]; then
    _COMPASS_NATIVE_TAB[$_compass_map]=$_compass_binding
  fi
  if [[ ${COMPASS_DOUBLE_TAB:-1} == 0 ]]; then
    bindkey -M "$_compass_map" '^I' "${_COMPASS_NATIVE_TAB[$_compass_map]:-expand-or-complete}"
  else
    bindkey -M "$_compass_map" '^I' compass-tab
  fi
  bindkey -M "$_compass_map" '^X^A' compass-pick
  bindkey -M "$_compass_map" '^X^R' compass-resume
  bindkey -M "$_compass_map" '^Xc' compass-pick
  bindkey -M "$_compass_map" '^Xr' compass-resume
done
unset _compass_map _compass_binding
