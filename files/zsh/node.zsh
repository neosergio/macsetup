# Node — nvm, installed via Homebrew. HOMEBREW_PREFIX comes from
# 00-homebrew.zsh; the literal fallback keeps this fragment usable standalone.
export NVM_DIR="$HOME/.nvm"

_ms_nvm="${HOMEBREW_PREFIX:-/opt/homebrew}/opt/nvm"
[ -s "$_ms_nvm/nvm.sh" ] && \. "$_ms_nvm/nvm.sh"
[ -s "$_ms_nvm/etc/bash_completion.d/nvm" ] && \. "$_ms_nvm/etc/bash_completion.d/nvm"
unset _ms_nvm
