# Sources every fragment macsetup has installed. Add a fragment by adding it to
# a module manifest -- this block never needs to change.
for _f in "$HOME"/.config/macsetup/zsh/*.zsh(N); do
  [ -r "$_f" ] && source "$_f"
done
unset _f
