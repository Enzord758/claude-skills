# claude-skills

Personal [Claude Code](https://claude.com/claude-code) skills for my CachyOS +
Hyprland machine, managed with [GNU Stow](https://www.gnu.org/software/stow/)
the same way as [Arch-dotfiles](https://github.com/Enzord758/Arch-dotfiles).

## Layout

Each top-level directory is a Stow package rooted at
`<package>/.claude/skills/<package>`. Stowing it symlinks the skill directory
into `~/.claude/skills/`, where Claude Code picks it up.

| Package | Covers |
| --- | --- |
| `arch-config` | General system config: packages/AUR, pacnew, kernel modules, sysctl, users, fstab/Btrfs, networking, audio, fonts |
| `coolercontrol` | Fans, pump and cooling via the CoolerControl daemon's REST API (RGB stays with OpenRGB) |
| `install-scripts` | Install scripts that rebuild the machine from the repo, kept in step with it by a drift check: structure, adopting drift, pitfalls |
| `hyprland` | `hyprland.lua` (Hyprland 0.55+ Lua API): binds, window rules, monitors, autostart, DMS boundary |
| `limine` | Limine bootloader, kernel cmdline, Snapper boot entries, Secure Boot signing |
| `nixos-migration` | Moving a desktop set up by install scripts and dotfiles to a NixOS flake: inventory, flake patterns, VM install-and-login test, pitfalls |
| `systemd` | Services, timers, user units, journald/logind, boot analysis |
| `vm-test-harness` | QEMU VM as a test harness for install scripts, Secure Boot, restores and SSH/network lockdown: setup, running, watching, pitfalls |

Not tracked here: `~/.claude/skills/*-workspace` (skill-creator eval
iterations and logs), `~/.claude/skills/synced` (managed by claude.ai) and
third-party skills.

## Install

```sh
git clone git@github.com:Enzord758/claude-skills.git ~/claude-skills
mkdir -p ~/.claude/skills
stow -d ~/claude-skills -t ~ arch-config coolercontrol install-scripts hyprland limine nixos-migration systemd vm-test-harness
```

Edits made through `~/.claude/skills/<name>` land in this repo, since the
skill directory is a symlink.
