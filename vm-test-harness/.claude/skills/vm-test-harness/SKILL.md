---
name: vm-test-harness
description: Build, run, watch and debug a QEMU/KVM virtual machine as a test harness for things that are too risky to try on the real machine — OS install scripts (partitioning, chroot, bootloader, Secure Boot key enrollment), reinstall/dual-boot flows, backup restores, network and SSH lockdown, firewall changes, dotfiles bootstrap. Covers making the VM look like the real host (disk serials, NIC name, a closed copy of the LAN), driving it the way a person would (console → password SSH → keys only), serial console and QMP control, OVMF Secure Boot vars, expect for interactive prompts, a resumable step runner with a status page and a watchdog, and the pitfalls hit along the way. Use it whenever someone wants to "test it in a VM first", test install/bootstrap scripts end to end, reproduce an install bug, automate an Arch/Linux install in QEMU, or has a VM test that hangs, stalls on a prompt or fails mysteriously — even if they never say "harness".
---

# VM test harness

A VM test harness installs or reconfigures a system inside QEMU exactly the way
it would happen on the real machine, step by step, and checks the result. It is
how you prove that destructive scripts (partitioning, bootloaders, Secure Boot,
network/SSH lockdown, restores) work before they ever touch real hardware — and
keep proving it as the scripts change.

If the project already has a harness (look for `test/vm`, `vmtest`, `run.sh` near the
install scripts, or a README mentioning QEMU), use and extend that one; read it first.
Otherwise build one along the lines below.

Reference files — read when relevant:
- `references/recipes.md` — concrete QEMU command lines, network shaping, Secure Boot
  vars, serial/QMP use, the step runner, resume, scheduled runs.
- `references/pitfalls.md` — symptom → cause → fix for everything that went wrong
  building one. Read it when something hangs or fails, and before building a new one.
- `scripts/` — generic helpers to copy into a harness (see the table at the end).

## Principles (and why)

**Make the VM indistinguishable to the scripts.** Scripts find disks by serial, NICs
by name, the LAN by subnet. Give the virtual disks the real serials, name the NIC like
the real one (`acpi-index=N` → `enoN`), shape QEMU's user-mode network like the real
LAN (same subnet, gateway, DNS address), give it the same hostname. Every difference is a
code path the test doesn't exercise.

**Drive it the way a person would.** If the real procedure is "boot the ISO, set root's
password on the console, then SSH in from another PC", the harness does exactly that —
types on the console over serial, then uses password SSH, and switches to keys only
after the step that disables passwords. A harness that takes shortcuts (cloud-init key
injection, root keys from the start) tests a procedure nobody runs.

**Keep the VM's network closed.** Use QEMU user-mode networking (NAT), not a bridge/tap:
the VM can then use the real LAN's addresses (even the host's own static IP) without ever
appearing on the real LAN. Reach specific real services through narrow forwards
(`guestfwd` relays), nothing else.

**Isolate the VM from real services it would otherwise touch.** A VM that is a copy of
the machine will happily run its scheduled backup against the real server, register the
same NFS client identity, etc. Mask such jobs inside the VM and give it distinct
identities where a server would confuse the two.

**Treat VM disks as sensitive once real data is restored into them.** A restore test
puts real secrets (SSH host keys, VPN configs, home directories) on the qcow2 files.
Copy decryption keys in only for that step and shred them after; delete the disks when
the run ends; never log key material.

**Test what persists, not just what's live.** Run re-runnable scripts twice (idempotency),
and reboot after any network/boot/SSH change and check again: a setting can be right
until the next boot (e.g. a restored network profile with higher priority winning over
the one the script configured).

**Make every step resumable and observable.** A full run takes the better part of an
hour; a failure at minute 40 must not cost another 40. Steps write their own log, a status
file drives a small progress page, and the runner can start at any step after preparing
the VM state that step needs.

**Silence means stuck.** Anything that waits (boot, SSH, poweroff) prints a heartbeat
line every ~10 s (VM running?, SSH banner, new serial output). Then a watchdog can tell a
slow step from a hung one by log age alone.

## Running a harness

- Start it as a transient unit so it survives your turn and can be watched:
  `systemd-run --unit=vmtest-run --description="VM test" /path/to/run.sh [FROM_STEP]`.
  Debug modes that leave a daemonized qemu behind need `systemd-run --scope …` — a
  service unit kills the daemonized child when the script exits.
- Take a lock (`flock`) so two runs never share disks.
- If there's a progress page, start it with every run (users follow along in the
  browser and shouldn't have to ask).
- Never edit the runner script while it runs: bash reads scripts incrementally, and an
  edit mid-run makes it skip or repeat lines. Stop, edit, resume.
- Run as root only code root owns. If a scheduled job runs the harness as root, install a
  root-owned copy and parse config files instead of sourcing user-editable shell.

## Watching a run — check in and judge

Run a watchdog in the background (`scripts/watch.sh`), restart it each time it returns
while the run is active. It exits on: run ended, step failed, log stalled (~150 s), the
log ending in an unanswered prompt (~120 s), the VM process gone, or a periodic CHECKIN
(~5 min). A CHECKIN is a prompt to look, not an alarm: read the last lines of the
current step's log and the serial log, take a screenshot if needed, and decide whether
the step is progressing (downloads advancing, compiler output, heartbeats with changing
state) or stuck (same line, prompt at the end, VM down). Tell the user briefly; don't let
them be the one to discover a hang.

On failure: read the step log from the bottom up, decide whether the bug is in the
scripts under test or in the harness, fix it, and resume at the failed step. Harness
bugs are common (false positives/negatives in checks) — fix the check, don't paper over
it.

## Getting into the VM to debug

- SSH via a host forward (`hostfwd=tcp:127.0.0.1:2222-<vm-dhcp-ip>:22`).
- If the VM ended up on another address, add a forward live through QMP:
  `human-monitor-command` → `hostfwd_add tcp:127.0.0.1:2223-<other-ip>:22`.
- Serial console on a unix socket: works from firmware onwards, needs no network, shows
  panics and stuck boots. Use it to type into the bootloader and the ISO console
  (`scripts/serialchat.py`, `scripts/serialtype.py`).
- QMP `screendump` for a screenshot, `send-key` to type on the graphical console
  (`scripts/vmtype.py`).

## Writing checks

- Run checks inside the VM as small `set -e` blocks or a pushed script printing
  `PASS/WARN/FAIL` lines; exit non-zero on any FAIL.
- Make markers unforgeable: if you grep a log for proof that a remote command ran, have
  the remote side compute it (`echo OK-$((40+2))` → grep `OK-42`), otherwise the echoed
  command line itself matches.
- Compare case-insensitively where tools changed their output format (e.g. `sshd -T`
  prints CamelCase keys in newer OpenSSH).
- Separate "external flake" from "script bug": e.g. an AUR/upstream download failing
  with 502 is recorded and tolerated, a script error is not.

## Editing safely

Write multi-line edit scripts to a file and run that file. Feeding them through a bash
heredoc breaks when the edited content contains the heredoc terminator — the rest then
runs as shell commands (as root, on the host). If anything like that happens: stop,
work out exactly what ran, tell the user, and ask before cleaning up.

## Finishing a run

1. Check the status: every step passed; note tolerated failures and why.
2. Delete disks and firmware vars that hold restored data; keep logs and the ISO.
3. Stop the progress page if nobody needs it.
4. Report what passed, what was fixed (scripts vs harness), and what's uncommitted.

## Bundled scripts

| Script | Use |
|---|---|
| `scripts/interact.exp` | Run a command (usually `ssh -tt`) and answer prompts like a person: passwords, sudo, `[y/N]`, `Type YES`, pacman selections. ANSI-tolerant, inactivity timeout (every output line resets it). Add project-specific prompts at the top. |
| `scripts/watch.sh` | Watchdog: ENDED / FAILED / PROMPT / STALL / VM DIED / CHECKIN. |
| `scripts/serialchat.py` | Wait for regex on the serial socket, send a reply; repeat. |
| `scripts/serialtype.py` | Type bytes on the serial socket (reaches firmware and bootloader). |
| `scripts/vmtype.py` | Type via QMP `send-key` (US layout). |
| `scripts/tcprelay.py` | `guestfwd=…-cmd:` relay to a real host:port; `--privileged` connects from a port < 1024 (NFS without `insecure`). |
| `scripts/status.py` | Step list + `status.json` for a progress page. |
| `scripts/config_vars.py` | Read plain `NAME=value` / arrays from a shell config without sourcing it. |
| `scripts/notify-wait.sh` | Desktop notification to a user as soon as they have a session (for scheduled runs at night). |

Copy them into the project's harness and adapt; they read `VMTEST_DIR` for state and
logs.
