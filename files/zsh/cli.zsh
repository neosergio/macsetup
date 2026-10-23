# The two `cli` tools that need shell wiring rather than just a binary on PATH.
#
# Installed as 90-cli.zsh so zoxide initialises after every other fragment:
# zoxide's own doctor check wants its init at the end of the shell config, and
# it says so on stderr when it is not. The gap to 40-p10k leaves room for
# fragments that have to load earlier.

# `always` rather than the default `auto`, which drops the icons as soon as the
# output is not a terminal -- `ls | less` should still show them. The glyphs come
# from the Nerd Font, which is why the cli module requires the fonts module.
alias ls="eza --icons=always"

# zoxide tracks visited directories and jumps to a match on a partial name.
# Aliasing cd to z keeps `cd some/real/path` working, since z falls back to a
# plain cd when the argument resolves to a real directory. `zi` still opens the
# interactive picker.
eval "$(zoxide init zsh)"
alias cd="z"
