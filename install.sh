#!/bin/bash
# Bootstrap macsetup on a Mac, fresh or not: Homebrew, uv, macsetup, wizard.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/neosergio/macsetup/main/install.sh)"
#
# With no arguments it ends in the `macsetup init` wizard. Arguments replace
# that and are passed to macsetup, for unattended provisioning:
#
#   curl -fsSL .../install.sh | bash -s -- apply --profile work --yes
#
# Every step checks before it acts, so re-running it is safe.
#
# Written for the /bin/bash that ships with macOS (3.2): no bash 4 features.

set -euo pipefail

# Where `uv tool install` gets macsetup from: PyPI by default. CI points it at
# the checkout to test this script; a git URL works too, for unreleased code.
MACSETUP_SOURCE="${MACSETUP_SOURCE:-macsetup}"

if [[ -t 1 ]]; then
  say() { printf '\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
  die() {
    printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
    exit 1
  }
else
  say() { printf '==> %s\n' "$*"; }
  die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
  }
fi

# `curl | bash` feeds the script itself on stdin, so anything that prompts has
# to read the terminal explicitly -- otherwise it would swallow the rest of
# this file as its answers. That means the terminal's real device, not
# /dev/tty: macOS kqueue rejects /dev/tty with EINVAL, and the wizard's event
# loop (prompt_toolkit on asyncio) dies on it before asking anything.
tty_dev=""
if [[ ! -t 0 ]]; then
  tty_dev="/dev/$(ps -o tty= -p $$ | tr -d ' ')"
  { : <"$tty_dev"; } 2>/dev/null || tty_dev=""
fi
if [[ -t 0 || -n $tty_dev ]]; then have_tty=1; else have_tty=0; fi
interactive() {
  if [[ -t 0 ]]; then
    "$@"
  elif [[ -n $tty_dev ]]; then
    "$@" <"$tty_dev"
  else
    "$@" </dev/null
  fi
}

find_brew() {
  local candidate
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x $candidate ]]; then
      echo "$candidate"
      return
    fi
  done
  command -v brew || true
}

# Everything lives in main so bash has read the whole file before running any
# of it: a download cut off halfway fails to parse instead of half-running.
main() {
  [[ $(uname -s) == Darwin ]] || die "macsetup only supports macOS."
  [[ $EUID -ne 0 ]] || die "run this as your normal user, not with sudo."

  local brew_bin
  brew_bin=$(find_brew)
  if [[ -z $brew_bin ]]; then
    say "Installing Homebrew (it will ask for your password)"
    ((have_tty)) || export NONINTERACTIVE=1
    interactive /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew_bin=$(find_brew)
    [[ -n $brew_bin ]] || die "Homebrew did not install; see its output above."
  else
    say "Homebrew already installed"
  fi
  eval "$("$brew_bin" shellenv)"

  # On Apple Silicon /opt/homebrew/bin is not on the default PATH, and the
  # Homebrew installer only prints the fix. Apply it so `brew` works in the
  # next terminal too.
  local line="eval \"\$($brew_bin shellenv)\""
  if [[ $brew_bin == /opt/homebrew/* ]] && ! grep -qsF "$line" "$HOME/.zprofile"; then
    printf '\n%s\n' "$line" >>"$HOME/.zprofile"
  fi

  # Through brew rather than astral's installer: the catalog's lang-python
  # module also asks brew for uv, and two copies would be one too many.
  if command -v uv >/dev/null; then
    say "uv already installed"
  else
    say "Installing uv"
    brew install uv
  fi

  # Persist uv's bin dir for future shells, then add it to this one -- in that
  # order: update-shell does nothing when the dir is already on PATH, which
  # left `macsetup: command not found` in every new terminal.
  uv tool update-shell >/dev/null 2>&1 || true
  PATH="$(uv tool dir --bin):$PATH"
  say "Installing macsetup"
  uv tool install --upgrade "$MACSETUP_SOURCE"

  if (($#)); then
    say "Running: macsetup $*"
    interactive macsetup "$@"
  elif ((have_tty)); then
    say "Starting the setup wizard"
    interactive macsetup init
  else
    say "macsetup is installed. In a new terminal, run: macsetup init"
    return
  fi

  say "Done. Open a new terminal so PATH picks up brew and macsetup."
}

main "$@"
