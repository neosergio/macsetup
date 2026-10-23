# zsh completion. Must run before any fragment that calls compdef -- tool
# completion scripts fail with "command not found: compdef" otherwise.
#
# Homebrew drops completions in share/zsh/site-functions (_brew, _git, _gh,
# _docker, _uv, _uvx, _wezterm, _zed, _aws), so adding it to fpath is all that
# is needed; no per-tool `eval` at startup.
if [[ -n ${HOMEBREW_PREFIX} && -d ${HOMEBREW_PREFIX}/share/zsh/site-functions ]]; then
  fpath=("${HOMEBREW_PREFIX}/share/zsh/site-functions" $fpath)
fi

autoload -Uz compinit

# compinit's security audit is slow, so run it in full at most once a day and
# use the cached dump otherwise. -i skips the prompt about Homebrew's
# group-writable directories, which are expected rather than suspicious.
_ms_zcompdump="${ZDOTDIR:-$HOME}/.zcompdump"
if [[ -n ${_ms_zcompdump}(#qN.mh+24) ]]; then
  compinit -i -d "${_ms_zcompdump}"
else
  compinit -C -i -d "${_ms_zcompdump}"
fi
unset _ms_zcompdump
