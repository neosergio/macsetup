# HOMEBREW_PREFIX, without shelling out to `brew --prefix` on every startup.
# `brew shellenv` would set this, but it costs a subprocess and PATH is already
# handled by /etc/paths.d, so just resolve the two possible locations.
if [[ -z ${HOMEBREW_PREFIX} ]]; then
  if [[ -x /opt/homebrew/bin/brew ]]; then
    export HOMEBREW_PREFIX=/opt/homebrew      # Apple Silicon
  elif [[ -x /usr/local/bin/brew ]]; then
    export HOMEBREW_PREFIX=/usr/local         # Intel
  fi
fi
