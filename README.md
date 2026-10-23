# macsetup

Declarative provisioning for macOS. Describe what a machine should have in
YAML; `macsetup plan` shows you the difference against reality, and
`macsetup apply` closes it.

```
$ macsetup plan
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Module       ┃ Package                      ┃ State     ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ core         │ git, gh                      │ satisfied │
│ cli          │ ripgrep                      │ install   │
│ cli          │ ~/.config/macsetup/zsh/90-…  │ update    │
│ lang-python  │ uv                           │ satisfied │
└──────────────┴──────────────────────────────┴───────────┘
1 to install, 1 file to update, 6 satisfied
```

Adding software is a YAML edit, never a code change. Re-running on a converged
machine is a no-op, and `plan` and `apply` share the same planner, so the
preview is exactly what apply acts on.

Built for the case where you have **several** Macs that should share an
environment without every machine getting every package.

## Install

```sh
brew install uv
uv tool install macsetup
macsetup init
```

`init` runs a wizard (machine name → profile → per-module choices), saves the
result to `~/.config/macsetup/machine.toml`, and applies it. After that no
flags are needed.

```sh
macsetup plan        # what apply would do; changes nothing
macsetup apply       # do it
macsetup status      # drift: manifest vs this machine
macsetup untracked   # installed packages no selected module accounts for
macsetup modules     # the whole catalog and its profiles
```

Every wizard answer has a flag equivalent, so a machine can be provisioned
unattended: `macsetup apply --profile work --yes`.

## Your own catalog

macsetup ships a small example catalog so a fresh install has something to run
against. It is an example — replace it with yours:

```sh
export MACSETUP_MANIFESTS=~/dotfiles/manifests
export MACSETUP_FILES=~/dotfiles/files
```

Both are resolved in that order: the environment variable, then a `manifests/`
or `files/` directory in the current working directory, then the copy baked
into the wheel. Keeping your catalog in a private repo and the engine public
is the intended arrangement.

### Modules

One file per module in `manifests/modules/`, where `id` matches the filename
stem:

```yaml
id: cli
name: CLI tools
requires: [fonts]          # dependency-closed at resolve time
packages:
  - ripgrep                          # formula
  - {name: ghostty, cask: true}      # cask
files:
  - copy: zsh/cli.zsh
    to: ~/.config/macsetup/zsh/90-cli.zsh
```

**Casks must be marked explicitly.** Several names exist in both namespaces —
`docker` is the CLI formula *and* Docker Desktop the cask — and a bare
`brew install docker` silently picks the formula. Marking casks is the single
biggest class of bug the manifest format exists to prevent.

`always: true` puts a module on every machine regardless of profile.
`select: pick` turns a module into a per-package menu in the wizard, with
`default:` pre-ticked. Pydantic forbids unknown keys, so a typo fails at load
rather than halfway through an install.

### Profiles

`manifests/profiles.yaml` bundles modules into named sets; `"*"` means
everything.

```yaml
profiles:
  work: [cli, lang-python, editors]
  minimal: [cli]
  full: ["*"]
```

`machine.toml` stores the **resolved module list**, not just the profile name,
so a module added to a profile upstream cannot silently install itself on
every machine the next time they sync. `status` reports unadopted modules;
`configure` adopts them.

### Files

Three actions:

```yaml
files:
  - copy: zsh/python.zsh                        # verbatim
    to: ~/.config/macsetup/zsh/20-python.zsh
  - render: git/gitconfig.j2                    # Jinja2 + machine vars
    to: ~/.gitconfig
    mode: "600"
  - block: shell/zshrc-block.zsh                # region in a file you don't own
    into: ~/.zshrc
    position: top                               # default bottom
```

`block:` maintains a marker-delimited region. Lines outside the markers are
preserved; re-applying rewrites only what's between them. `position: top`
exists because some formats are order-sensitive — an `Include` in `ssh_config`
is ignored if it lands after a matching block.

`render:` substitutes variables from `manifests/vars.yaml`, overridden per
machine by the `[vars]` table in `machine.toml`, plus `machine` and `home`
which are always supplied. Rendering uses `StrictUndefined`: a template
referencing a variable with no value is a hard error, not a silently empty
setting.

Before overwriting a file it did not create, `copy`/`render` leave a
`.macsetup-bak` copy alongside it.

**Nothing is symlinked.** A symlink would point into the installed wheel and
break on the next upgrade, so files are copied and you re-run `apply` after
editing a fragment.

## Design notes

A few decisions that are load-bearing, in case you're reading the source:

**Data is separate from code.** `manifests/` says what to install;
`src/macsetup/` only knows how. If adding software requires touching Python,
something is wrong.

**`brew list` runs exactly twice per invocation**, cached in `detect.py` —
never once per package. Checking 60 packages costs two subprocess calls, so a
converged machine plans in well under a second regardless of catalog size.
There is a test asserting the call count.

**Installs delegate to `brew bundle`** against a generated Brewfile rather than
shelling out per package. Homebrew already knows about retries, cask
quarantine and sudo prompts. Generated Brewfiles stay in
`~/.cache/macsetup/brewfiles/` so a failure can be inspected.

**`apply` never upgrades.** `brew bundle install` upgrades by default; macsetup
passes `--no-upgrade` so converging a machine cannot turn into a 40-minute
upgrade run. `--upgrade` is opt-in.

**Subprocess calls go through `runner.py`.** That protocol is the test seam —
the suite runs without touching the machine.

## Development

```sh
uv sync
uv run macsetup plan -p work
uv run pytest                 # no machine access required
uv run ruff check . && uv run ruff format .
uv tool install -e .          # put `macsetup` on PATH, tracking this checkout
```

Tests never mutate the machine: `FakeRunner` stands in for subprocesses, and
file steps run against a sandboxed `HOME`. To try the file actions safely:

```sh
SB=/tmp/ms-try; mkdir -p $SB
HOME=$SB MACSETUP_CONFIG=$SB/.config uv run macsetup apply --only shell --yes
```

`shell` has no packages, so that never invokes brew.

## Not built yet

- `sync` (git pull + apply), `add`, `prune`, `upgrade`, `doctor`
- macOS `defaults write` tweaks as a step type
- Mac App Store apps (`brew bundle` handles `mas` entries natively; no manifest
  uses them yet)
- CI

## Prior art

[chezmoi](https://www.chezmoi.io/) does dotfiles thoroughly but not packages.
`brew bundle` does packages but has no preview, no drift report and no notion
of per-machine subsets. [nix-darwin](https://github.com/LnL7/nix-darwin) does
all of it and more, if you want to learn Nix. macsetup is the middle: plain
YAML, Homebrew underneath, a plan you read before anything happens.

## License

MIT
