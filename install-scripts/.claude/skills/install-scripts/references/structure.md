# Structure and patterns

Contents: repo layout · stages · config · helpers · package lists · AUR ·
system/<area> restore scripts · users and passwords · secrets and restore ·
SSH-first install and the final stage · idempotency checklist · docs

## Repo layout

```
dotfiles/
├── <stow packages>/            user config, symlinked into ~ (zsh/, nvim/, hypr/, …)
├── install.sh                  stows the user packages (excludes install/, system/, test/)
├── install/
│   ├── config.sh               plain NAME=value settings, no logic
│   ├── lib.sh                  helpers, sourced by every stage
│   ├── 01-live.sh              on the live ISO: disks, pacstrap, fstab, copy repo
│   ├── 02-chroot.sh            in arch-chroot: base config, users, repos, packages, initramfs, services
│   ├── 03-boot.sh              in arch-chroot: bootloader, Secure Boot keys, boot entries
│   ├── 04-desktop.sh           first login, as the user: dotfiles, AUR, system/* restores
│   ├── 05-finish.sh            last, as root: lock down SSH, final network config
│   ├── restore-backup.sh       restore secrets/home from the (encrypted) backup
│   ├── packages/repo.txt       repo packages, sectioned, commented
│   ├── packages/aur.txt        AUR packages, in dependency order
│   ├── drift.py                drift check (read-only)
│   └── drift-ignore.txt        what the drift check doesn't count, each with a reason
├── system/<area>/              root-owned config the stow can't handle
│   ├── <files for /etc>        e.g. 10-size.conf, sudo.conf, a hook
│   └── restore.sh              installs them, enables/restarts what needs it
└── test/vm/                    VM harness for the whole install (see vm-test-harness)
```

Stow must not pick up `install/`, `system/`, `test/` (they go to `/etc` via
scripts, or nowhere).

## Stages

Split by *where and as whom* a stage runs, because that's what changes
between them (live ISO vs chroot vs booted system; root vs user):

| Stage | Runs | Does | Notes |
|---|---|---|---|
| 01 live | ISO, root | find disks by serial, partition (modes!), mkfs, subvolumes, mount, pacstrap, genfstab, copy repo into the target | modes `fresh` (wipe disk), `reinstall` (keep ESP/other OSes, reformat root), `mount` (only mount, to re-enter the chroot) |
| 02 chroot | chroot, root | timezone, locale, keymap, hostname, users, extra repos, packages from the lists, remove what the lists replace, initramfs, snapshot config, enable services, move the repo to the user | must not depend on a running system (no `systemctl start`, no DBus) |
| 03 boot | chroot, root | bootloader install + config, kernel cmdline, Secure Boot (create/enroll keys, sign), boot order | fail loudly if the config has no kernel entry |
| 04 desktop | booted, user (sudo where needed) | stow dotfiles, AUR packages, shell framework, themes, every `system/<area>/restore.sh` | re-runnable; exit with a distinct code if only AUR builds failed |
| restore | booted, root | secrets and home from the backup | needs the backup key, which never lives in the repo |
| 05 finish | booted, root, **last** | keys-only SSH, LAN-only firewall, final network config | after it, reconnect with a key / at the new address |

Re-entering: document "boot the ISO, `01-live.sh mount`, `arch-chroot /mnt`,
re-run 02/03" — and make 02/03 safe for that.

## config.sh

Only plain assignments and arrays: hostname, timezone, locale, keymap, user
name/uid/home/group, disk serials, filesystem UUIDs that must stay, kernel
cmdline extras, LAN subnet/DNS/interface, repo URL. No `$(...)`, no
expansion. Then other tools (a drift check, a VM harness running as root) can
*parse* it safely instead of sourcing it (`scripts/drift.py` shows how: regex
+ `shlex.split`, refuse `$` and backticks).

## Helpers (lib.sh)

See `scripts/lib.sh`: `info/ok/warn/die`, `confirm` ([y/N]),
`confirm_destructive` (type YES), `require_root`, `require_user`, `in_chroot`,
`disk_by_serial SERIAL`, `partition DISK N` (sda3 vs nvme0n1p3), `read_list FILE`
(lines minus comments/blanks, first word). Every stage starts with
`set -euo pipefail` and `source "$(dirname "$0")/lib.sh"`.

## Package lists

- One package per line, first word counts; `#` comments explain non-obvious
  ones ("needed by X", "replaces Y", "kept although Z").
- Sections by purpose (kernel, system, security, network, audio, GPU, desktop,
  fonts, CLI/dev, apps, gaming, …). Adopting drift = putting the package in the
  right section, not appending at the end.
- The list holds **explicitly installed** packages only; dependencies come by
  themselves. The drift check compares `pacman -Qqe` with the lists.
- Packages the base install brings (`base`, `base-devel`, a distro's installer
  meta packages) are exempt in the checker, not listed.
- Install with `pacman -S --needed $(read_list repo.txt)`; remove what the
  lists replace (e.g. a stock kernel) explicitly, after.

## AUR

- Install the helper (yay/paru) from a repo if one ships it, else bootstrap it.
- Build **as the user**, never as root.
- One package at a time in list order (earlier ones satisfy later ones'
  dependencies); collect failures, keep going, print them at the end and exit
  with a distinct code (e.g. 2) so a caller can tell "AUR build broke upstream"
  from "script error".
- A `-bin` variant whose plain name is already installed is skipped (they
  conflict).
- Stow dotfiles **before** AUR packages: some packages' post-install copy
  default configs into `~/.config`, and stow then refuses to replace them.

## system/<area>/restore.sh

```bash
#!/usr/bin/env bash
# What this restores and why (one or two lines). Run as root.
set -euo pipefail
cd "$(dirname "$0")"

install -Dm 644 10-size.conf /etc/systemd/journald.conf.d/10-size.conf
systemctl restart systemd-journald
journalctl --disk-usage   # show the effect
```

- `install -Dm MODE src dest` (idempotent, creates dirs, sets mode) instead of
  `cp`/`cat >>`. A drift check can parse these lines to know which files the
  repo manages and compare them byte for byte.
- Prefer drop-ins (`/etc/<x>.d/NN-name.conf`) over editing package files; if a
  package file must change, `sed -i` one exact line (and the checker treats
  `sed -i` targets as accounted for).
- Enable with `systemctl enable` (explicit unit names, no variables) so the
  checker can read the expected units; `--now` only where the booted stage runs it.
- End with a verification line that shows the result.
- The desktop stage runs them in a fixed order (`for part in a b c; do sudo bash
  system/$part/restore.sh; done`); network/SSH changes are not in that loop.

## Users and passwords

- Create users with fixed uid/gid/home from config (`useradd -m -u … -g …`), so
  restored files keep their ownership.
- Ask for passwords interactively only when not set yet
  (`passwd -S user | awk '{print $2}'` ≠ `P` → `until passwd user; do :; done`);
  never take them from the repo or the command line.
- sudoers via a file in `/etc/sudoers.d/` (validate with `visudo -cf`).

## Secrets and restore

- Back up secrets encrypted (e.g. `age` to a recipient public key); the private
  key stays offline with the owner. The restore script asks for its path.
- Restore into a staging dir (`/root/restore-<stamp>`), then copy the parts in
  (NetworkManager connections, VPN configs, SSH host keys, app tokens, the
  user's home), with the right owners; stop services whose state you replace,
  start them after.
- Restored config can override what the scripts set (a restored network
  profile with a higher priority) — the final stage must reconcile, and a
  reboot check must prove it.

## SSH-first install and the final stage

- Everything up to the final stage works over a password SSH session from
  another machine on the LAN: no step may need the physical console after the
  ISO's root password is set (console font/keymap failures only warn).
- The final stage, as root: verify the user has a working `authorized_keys`
  (`ssh-keygen -lf`), install the keys-only sshd drop-in, `sshd -t`, reload;
  firewall rules limited to the LAN subnet; then the network change last, in
  its own unit (`systemd-run --wait --collect bash restore.sh`) so the SSH
  session dropping doesn't kill it; print where to reconnect.

## Idempotency checklist

- `--needed` on every pacman/yay install; `[[ -d x ]] || git clone …`.
- `install -D` / drop-in files instead of appending; `sed -i 's/^KEY=.*/KEY=v/'`
  instead of `echo >> file`.
- Create only if missing (users, snapper configs, subvolumes in reinstall mode),
  or recreate deliberately (a half-created key dir moved aside first).
- `systemctl enable` is idempotent; `restart` where config changed.
- Tools that must be re-run after a change (initramfs, bootloader update) run
  every time — they're cheap.
- Test: run the stage twice; the second run must change nothing and succeed.

## Docs

A README in `install/` (or the repo root) with: the stages in order with the
exact commands, what each mode does to which disk, what needs the owner (the
backup key, firmware settings like Secure Boot / Setup Mode), how to re-enter
the chroot, how the drift check and VM test keep it honest.
