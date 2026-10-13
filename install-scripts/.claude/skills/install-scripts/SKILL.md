---
name: install-scripts
description: Build and maintain install scripts that rebuild a Linux machine (Arch-based especially) from a dotfiles/config repo — partitioning, pacstrap/chroot setup, bootloader and Secure Boot, desktop and AUR packages, /etc config, restore from backup, final SSH/network lockdown — and keep them in step with the live machine through a drift check ("scripts are the source of truth"). Use it whenever someone wants to write, refactor or extend their install/bootstrap/reinstall scripts, asks "would a reinstall give me this machine?", wants to adopt changes made on the host (new packages, edited /etc files, enabled services, firewall rules) into the repo, runs or interprets a drift check, adds a package or config "to the install script", or wants a reinstall to be safe to run over SSH and to re-run — even if they only say "update drift", "add X to the install", or "keep my setup reproducible".
---

# Install scripts as the source of truth

The goal: a repo from which the machine can be rebuilt exactly — and a routine
that keeps it that way. Two halves: **building** the scripts (structure, safety,
idempotency) and **maintaining** them (drift: every change on the host lands in
the repo, or is consciously ignored).

If the project already has such scripts (look for `install/`, `bootstrap/`,
`setup.sh`, numbered stage scripts, package lists, a `drift`/`check` script,
a README describing a reinstall), read them and their README first and follow
their conventions; this skill describes the pattern, the repo is the authority.

References — read the one you need:
- `references/structure.md` — stages, repo layout, script patterns (helpers,
  idempotency, restore scripts, package lists, AUR, secrets/restore, SSH-first
  install), with snippets.
- `references/drift.md` — how a drift check works, how to adopt or ignore each
  kind of drift, scheduling it, the root-owned-copy rule.
- `references/pitfalls.md` — things that broke in practice (boot, Secure Boot,
  NetworkManager, packages, services) and the fix.
- `scripts/` — `drift.py` (generic drift checker for the layout below),
  `lib.sh` (helpers), `drift-ignore.example.txt`.

## Principles (and why)

- **The scripts are the truth, not the machine.** A change made by hand on the
  host is unfinished until a script makes it. Otherwise the next reinstall
  silently loses it, and nobody remembers why it was there.
- **Every change gets a reason in a comment.** Six months later "why is this
  sysctl here?" must be answerable from the repo.
- **Re-runnable.** Every stage can run again on a system where it already ran
  (re-install after a partial failure, adding one package). Check before
  creating, use `--needed`, `install -D` instead of append, set values instead
  of toggling. Test it by running the stage twice.
- **Destructive steps ask, by typing.** Partitioning/formatting needs
  `Type YES to continue`, and disks are found by serial, never by `/dev/sdX`
  order (which changes between boots and with USB sticks).
- **Install the way it will really happen.** If the real reinstall is done
  over SSH from another PC, the scripts must work over password SSH until the
  very last step, and only the last step turns on keys-only SSH / LAN-only
  firewall / final network — then reconnect.
- **No secrets in the repo.** Passwords are prompted, keys and tokens come from
  the backup (encrypted) at a restore step. Restore helpers write to a staging
  dir and copy from there.
- **Root never executes what a normal user can edit.** A scheduled root job
  (drift check, VM test) runs a root-owned installed copy, and parses config
  files instead of sourcing them.
- **Small footprint.** Prefer a drop-in file in a `.d/` directory over editing a
  package's file; prefer an existing mechanism over a new package or daemon.

## Workflows

### Adopting drift ("update drift", "is the install script up to date?")

1. Run the drift check (project's own, else `scripts/drift.py --repo <repo>`) as
   root. Read every line.
2. For each difference decide, and say which:
   - **adopt**: add the package to the right list section, copy the `/etc` file
     into `system/<area>/` with a `restore.sh` that installs it, add the
     `systemctl enable`, the firewall rule, the setting in the stage script;
   - **ignore**: runtime state or deliberate hand-install → a line in
     `drift-ignore.txt` with a comment saying why;
   - **revert on the host**: the change was a mistake — ask the user first.
   Look at the item before deciding: `pacman -Qi`/`-Si` (repo? explicitly
   installed? when — `/var/log/pacman.log`), `pacman -Qo`, `systemctl cat`,
   the file's content. Ask the user only when intent is unclear (a package
   tried once vs. kept).
3. Refresh installed copies the check itself uses (e.g. a root-owned copy of the
   checker) if the repo version changed.
4. Re-run until it reports no drift. Report what was adopted where, and what was
   ignored and why. Commit/push only when the user asks.

### Adding something new "to the install"

Put it where the stage that owns it would do it (see `structure.md` → stages):
packages in the lists, system config in `system/<area>/` + `restore.sh` called
from the desktop stage, user dotfiles in the stow packages, boot/kernel in the
boot stage, network/SSH lockdown only in the final stage. Apply it on the host
the same way (run that `restore.sh`), then run the drift check.

### Building or refactoring the scripts

Follow `structure.md`. Keep stages small and named after when they run (live
ISO, chroot, boot, first login, finish). Lint with `shellcheck -x`. Then test in
a VM before trusting it — see the `vm-test-harness` skill if available — and run
re-runnable stages twice there.

### Changes that need a VM run

Anything in partitioning, chroot setup, bootloader/Secure Boot, initramfs,
fstab, network/SSH/firewall, the restore step, or the order of stages. A new
package, a new drop-in or a new enabled unit usually only needs the drift check
(and a VM run at the next scheduled one).

## Safety

- Read-only first: the drift check changes nothing. Applying a `restore.sh` on
  the host changes `/etc`: say what it does and get an OK, like any system change.
- Never run partitioning/formatting/bootloader stages on the live machine to
  "test" them.
- Never write secrets (passwords, keys, tokens, backup keys) into the repo,
  logs or commit messages. If one was pasted in chat, don't store it anywhere.
- Before deleting something created by accident, say what it is.
