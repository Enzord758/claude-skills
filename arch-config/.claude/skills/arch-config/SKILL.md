---
name: arch-config
description: Use for general system configuration and maintenance on this CachyOS/Arch machine — installing/removing/updating packages (pacman, yay/AUR, CachyOS znver4 repos), mirrors and keyring errors, .pacnew/.pacsave merging, downgrades and rollback, cache/orphan cleanup, makepkg.conf, kernel modules and modprobe options, mkinitcpio, NVIDIA driver setup, sysctl tuning, locale/keymap/timezone, users/groups/sudoers, fstab/Btrfs/snapper/swap, NetworkManager and firewalld ports, PipeWire/WirePlumber audio, fonts/fontconfig, Flatpak, AppArmor denials, environment variables, udev rules and default apps. Use it even when the user doesn't name the tool — e.g. "installer X", "opdater systemet", "der er en .pacnew", "pakken er gået i stykker efter opdatering", "rul tilbage", "åbn en port", "Valent/KDE Connect finder ikke telefonen", "lyden virker ikke", "tilføj mig til en gruppe", "skift tidszone", "ryd op i pakker", "sæt en miljøvariabel", "controller bliver ikke genkendt" — because the session may run as root or as enzord without passwordless sudo, CachyOS repo order and the Limine/Secure-Boot initramfs chain make the generic Arch-wiki recipe wrong here, and several files (sysctl, modprobe, fstab, sudoers) can leave the machine unbootable or locked out if edited carelessly. Hands off to the hyprland, systemd, limine and coolercontrol skills for their areas.
---

# Arch/CachyOS configuration (this machine)

**Machine:** Arch base + CachyOS repos/kernel (`linux-cachyos`, prebuilt `linux-cachyos-nvidia-open`), Ryzen 7 7800X3D (→ `*-znver4` repos), RTX 4090, 31 GB RAM, Btrfs root with snapper + snap-pac, Limine with Secure Boot and an enrolled config hash, Hyprland via uwsm + DankMaterialShell. User `enzord` (UID 1000, home `/home/Enzord` — capital E; group `Enzord`). Danish user, `en_DK` locale, Europe/Copenhagen. Dotfiles in `~/dotfiles` (GNU stow).

This is a map, not the inventory. Live state wins: if the system contradicts something written here, trust the system and say so.

## Inspect efficiently

- **Targeted change** ("sæt X til Y", "åbn port Z"): go straight to the few live values and files involved (`sysctl <key>`, `cat` the file, `pacman -Qo`, `/sys/module/<m>/parameters/`, `firewall-cmd --list-all` …). No overview script needed.
- **Open-ended maintenance** ("opdater", "ryd op", "hvad er galt", "hvorfor er det langsomt"): start with `bash /home/Enzord/.claude/skills/arch-config/scripts/arch-check.sh` — it's read-only (no need to read it first) and prints identity, pending updates/reboot, .pacnew files, orphans, cache, failed units and disk in one go. Then **look around beyond it** the way you would without this skill: `ls` the directories involved, read the real hook/config files, review explicitly installed and AUR packages for forgotten ones. What a checklist misses (leftover dirs in the cache, a masked hook, an unused benchmark tool) is exactly what the user wants to hear about.
- **References**: read only the section you need — `grep -n '^## ' <file>` for the table of contents, then read that section. Don't load both files whole.

## Hand off to the specialised skills

| Topic | Skill |
|---|---|
| Keybinds, window rules, monitors, Hyprland env vars/autostart, desktop keyboard layout | `hyprland` |
| Services, timers, user units, journald/logind/sleep, boot time, `journalctl` | `systemd` |
| Kernel cmdline, boot menu, snapshot boot entries, Secure Boot, "won't boot" | `limine` |
| Fans, pump, temperatures, RGB | `coolercontrol` |

Many tasks span two (a modprobe option for `nvidia` lives here; the initramfs rebuild that makes it effective is limine territory). Do your part, then load the other skill for its part — but only if you actually need its details.

## Who are you running as?

Run `id -u` first; it decides how changes are applied.

- **Root (uid 0):** apply after the user's OK. Files you create under `/home/Enzord` become root-owned — use `runuser -u enzord -- …` or `chown enzord:Enzord`. User-session commands: `systemctl --user -M enzord@ …`. Never run `yay`/`makepkg` as root (makepkg refuses; building AUR as root is unsafe) — `runuser -u enzord -- yay -Q…` for read-only queries, AUR installs go to the user.
- **enzord (uid 1000):** no passwordless sudo, and `sudo` can't prompt from your shell. Do the unprivileged parts yourself; hand the privileged part to the user:
  - One or two commands → one copy-paste block, each line starting with `sudo`.
  - Several files/steps → write the files plus an `apply.sh` in your scratchpad, show its full content, user runs `sudo bash <path>/apply.sh`. Idempotent, `set -euo pipefail`, back up overwritten files to `<file>.claude-bak`, end with verification commands. Ask them to paste the output.

Give exact commands for whoever runs them — not "run this as root" prose.

## Where configuration belongs

Package-owned files get overwritten or a `.pacnew` on upgrade; your changes go in a drop-in or a file no package owns (`pacman -Qo <file>`).

| What | Put it in | Takes effect with |
|---|---|---|
| Kernel tunables | `/etc/sysctl.d/NN-name.conf` | `sysctl --system`; verify `sysctl <key>` |
| Module options / blacklist | `/etc/modprobe.d/name.conf` | reload or reboot; module in initramfs (`nvidia*`) → `limine-mkinitcpio` + reboot |
| Initramfs modules/hooks | `/etc/mkinitcpio.conf` or `/etc/mkinitcpio.conf.d/` | `limine-mkinitcpio` (initramfs + boot entries/hash; `limine-update` also reinstalls Limine). Never bare `mkinitcpio -P` — it skips the boot entries |
| udev rules | `/etc/udev/rules.d/NN-name.rules` | `udevadm control --reload && udevadm trigger` |
| Mounts | `/etc/fstab` | `findmnt --verify`, `systemctl daemon-reload`, `mount -a` |
| Env vars | see `references/areas.md` §11 | re-login |
| makepkg flags | `/etc/makepkg.conf.d/*.conf` or `~/.config/pacman/makepkg.conf` | next build |
| Firewall | `firewall-cmd --permanent …` (not zone XML by hand) | `firewall-cmd --reload` |
| Audio | `~/.config/pipewire/*.conf.d/`, `~/.config/wireplumber/wireplumber.conf.d/` | restart user services |

Deliberate local files: `/etc/sysctl.d/99-security-hardening.conf`, `/etc/modprobe.d/nvidia.conf`, `/etc/mkinitcpio.conf` (nvidia in `MODULES`, `kms` hook removed on purpose), `/etc/makepkg.conf` (`-march=native -O3`, LTO), `/etc/xdg/reflector/reflector.conf`. Extend them rather than adding a competing file with the same keys — the lexically last sysctl/modprobe file silently wins.

## Workflow: inspect → propose → wait → apply → verify

Several mistakes here can't be fixed from the running system (bad fstab → emergency mode, bad sudoers → no sudo, wrong modprobe/initramfs → black screen, broken pacman.conf → no updates), so the pause has to come from you.

1. **Inspect** (above). For "broke after update": `grep -E 'upgraded|installed' /var/log/pacman.log | tail -40` + the journal.
2. **Propose**: explain each change (next section), then exact file contents or diff with full paths, then the commands in order. Pick the change by "Smallest footprint first" below.
3. **Wait for an explicit OK.** Never propose and apply in the same turn. Pure questions need no OK.
4. **Apply.** Back up (`cp -a f f.claude-bak`). snap-pac takes a *pre*-snapshot of every pacman transaction (its post hook is masked on purpose); for risky non-pacman changes offer `snapper -c root create -d "before <change>"`.
5. **Verify** the live value, not just the file. Report failures with the output.

Validate before it lands: sudoers → `visudo -cf <file>`, install `0440 root:root` in `/etc/sudoers.d/` (name without `.` or `~`); fstab → `findmnt --verify --tab-file <new>`, non-root disks get `nofail`; udev → `udevadm verify`.

## Smallest footprint first

Every package, running service, privileged group or opened port you add is something the user has to maintain, update and trust — and more attack surface. So when choosing a solution, work down this ladder and stop at the first rung that solves the user's actual goal:

1. **Nothing** — the value is already in effect, or the problem isn't where the user thought.
2. **A setting or drop-in** in something already installed (a config file, a systemd override, a firewall rule, a polkit rule).
3. **A built-in mechanism the system already has** (polkit instead of sudoers, logind/uaccess instead of a group, a systemd timer instead of a cron daemon).
4. **New software, services, groups or privileges** — only when nothing above works, and then say explicitly why the lower rungs don't, and what it costs (disk, a daemon running, privileges it grants).

This applies to what the user asked for *and* to anything you volunteer. If the goal can be reached on rungs 1–3, don't propose, offer or advertise new software the user didn't ask for — not as an option, not as an "alternativ", not as a closing "sig til hvis du vil have X". There is simply no reason to.

Requests often name a means ("tilføj mig til gruppen X", "installer Y så Z virker") — look at the goal behind it and solve that with the smallest change. If the user explicitly asked for something that isn't there (e.g. a group whose package isn't installed), that part of the request is still theirs: state the fact in one sentence and ask one short question — "X er ikke installeret, så gruppen findes ikke. Skal jeg installere X, eller var det ikke meningen?" No sales pitch, no list of install variants and warnings until they say yes. Things the user didn't ask for, you don't offer.

When you get stuck, don't reach for installing new software as the way out — say what blocked you.

## Explaining changes — the user must understand what they approve

The user reviews every change before it lands and has said this matters a lot to them: an OK is only worth something if they understand what they say yes to. For **each** setting, file line and state-changing command, say in plain Danish:

- **What it is** — what it actually controls, in a sentence or two a non-kernel-developer gets. Not just its name.
- **What changes for them** — what they'll notice (or that nothing changes because it's already in effect), and the trade-off.
- **Why this way** — why this file/method, if it differs from what they'd find online.
- **Risk and undo** — what could go wrong and the exact way back.

The bar, by example — `kernel.sysrq=244` isn't "sætter sysrq til 244" but: "Magic SysRq er tastekombinationer (Alt+PrtSc+bogstav) som kernen reagerer på selv når skrivebordet er frosset. Din hardening-fil tillader i dag kun tastaturstyring (4); 244 tilføjer sync, remount read-only, kill og genstart — så du kan lukke sikkert ned med REISUB i stedet for at holde tænd-knappen inde. Ulempen er at alle med fysisk adgang til tastaturet kan dræbe processer. Fortrydes ved at sætte værdien tilbage til 4 og køre `sysctl --system`."

Lead with the conclusion, then per-change explanations, then commands. Explaining is not dumping internals — skip mechanics that don't change what the user should do. One recommendation; mention an alternative only when it's a real choice for the user.

After a successful /etc change, ask once whether to save a copy in `~/dotfiles/system/<area>/` with a short restore note (like `system/limine/`). Don't stow `system/` — those files belong in `/etc`.

## References

- `references/packages.md` — repos/mirrors, updating, install/remove, keyring, .pacnew merging, downgrade/rollback, cleanup, makepkg, queries.
- `references/areas.md` — NVIDIA & modules, sysctl, locale/time, users/groups/sudo, storage/snapper/swap, network/firewalld, PipeWire/WirePlumber, fonts, Flatpak, AppArmor, env vars, udev/input, default apps.
