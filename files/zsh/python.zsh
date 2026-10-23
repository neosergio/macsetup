# Python — uv only. pyenv and poetry were dropped on 2026-07-26.
#
# No completion setup here: Homebrew already installs _uv and _uvx into
# site-functions, which 10-completion.zsh puts on fpath. Calling
# `uv generate-shell-completion` at startup would duplicate that and cost two
# subprocesses per shell.

# `uv tool install` puts shims here.
export PATH="$HOME/.local/bin:$PATH"

# Prefer uv's managed interpreters over whatever the system ships.
export UV_PYTHON_PREFERENCE=managed
