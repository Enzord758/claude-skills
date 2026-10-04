---
name: systemd
description: Use for configuring and troubleshooting systemd on this CachyOS machine — services, timers, sockets, mounts, targets, drop-in overrides, user units (systemctl --user), journald/logind/sleep/oomd config, boot-time analysis and anything read from journalctl. Covers "service won't start / keeps restarting / failed", "make X start at boot / at login", "write a timer instead of cron", "override a unit", "why is boot slow", "suspend/shutdown hangs", "journal is huge", "what's failing", and the user session (uwsm-managed Hyprland, DMS, pipewire, portals). Use it even when the user doesn't say "systemd" — e.g. "autostart", "daemon", "baggrundsservice", "kør hver nat", "hvorfor fejler X", "loggen", "boot tager lang tid", "lukker ikke ned" — because this session runs as root, so the obvious `systemctl --user` / `journalctl --user-unit` commands silently hit the wrong manager or return nothing.
---

# systemd (this machine)

CachyOS/Arch, **systemd 262**, Btrfs + snapper, NVIDIA. Login via SDDM → Hyprland launched through **uwsm** (`wayland-wm@hyprland.desktop.service` in the user manager). Human user: `enzord` (UID 1000, home `/home/Enzord` — capital E). Networking: NetworkManager + firewalld; also sshd, fail2ban, avahi, coolercontrold, nvidia-persistenced, smartd, apparmor. `acpid` is installed but deliberately disabled (2026-09-27: its handler only logged; logind handles the power button). Timers: snapper-timeline (hourly, triggers limine-snapper-sync), `btrfs-scrub@-.timer` (monthly scrub of root), fstrim, reflector, plus distro timers.

Read the live state rather than trusting this list — it's a starting map, not ground truth.

## You are root, the user's session is not

This Claude session runs as **root**. Every plain `systemctl`/`journalctl` talks to the *system* manager. The user's desktop (Hyprland, DMS, pipewire, portals, autostart apps) lives in *enzord's user manager*. The naive commands fail in quiet ways:

| Want | Works as root | Trap |
|---|---|---|
| status/list/start/stop/enable/daemon-reload of a user unit | `systemctl --user -M enzord@ <verb> <unit>` | plain `systemctl --user` → root's own (empty) user manager |
| `cat`/`edit` a user unit | `runuser -u enzord -- env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user cat <unit>` | `-M enzord@ cat` → "Cannot remotely cat units" |
| logs of a user unit | `journalctl -b _SYSTEMD_USER_UNIT=<unit>` | `journalctl --user-unit=X` adds `_UID=0` (root's UID) → **silently empty output**, looks like "no logs" |
| all of the user's logs | `journalctl -b _UID=1000` | `journalctl --user` → root's user journal |

Creating files under `/home/Enzord/.config/systemd/user/` as root leaves them root-owned. Either write them via `runuser -u enzord -- …` or `chown -R enzord:Enzord` the new files afterwards — a root-owned unit in the user's home is a mess the user can't edit.

`/run/user/1000/systemd/user/*.d/` holds runtime drop-ins that uwsm generates at every login (e.g. `50_custom.conf` for the compositor). Don't edit those; they vanish on logout.

## Where configuration belongs

Precedence (highest wins): `/etc/systemd/system` > `/run/systemd/system` > `/usr/lib/systemd/system` (user units: `~/.config/systemd/user` > `/etc/systemd/user` > `/usr/lib/systemd/user`). `/usr/lib` is package-owned and gets overwritten on upgrade — never edit it.

- **Change part of a packaged unit** → drop-in `/etc/systemd/system/<unit>.d/<NN>-<name>.conf` containing only the changed keys. Non-interactive way: `systemctl edit --stdin --drop-in=<name> <unit> <<'EOF' … EOF` (does the daemon-reload for you). Don't run bare `systemctl edit` — it opens an editor and hangs this shell.
- **List-type keys** (`ExecStart=`, `ExecStartPre=`, `After=`, `Wants=`, `Environment=`…): in a drop-in, assigning *appends* to the original. To *replace* `ExecStart=` you must first clear it with an empty `ExecStart=` line, otherwise a non-oneshot service refuses to load ("has more than one ExecStart=").
- **Replace a unit wholesale** → full copy in `/etc/systemd/system/<unit>` (`systemctl edit --full`), but that stops tracking upstream changes; prefer drop-ins.
- **Daemon config** (journald, logind, sleep, oomd, resolved, timesyncd, coredump, system.conf) → `/etc/systemd/<daemon>.conf.d/<NN>-<name>.conf`, not the main `.conf` (those are all-defaults here; keeping them pristine avoids `.pacnew` churn). Existing local config (added 2026-09-27): `/etc/systemd/journald.conf.d/10-size.conf` (`SystemMaxUse=500M`); outside systemd, `/etc/apparmor.d/local/fail2ban-server` and `write-cache` enabled in `/etc/apparmor/parser.conf` (backup `.claude-bak`).
- **Revert** → `systemctl revert <unit>` removes all /etc overrides and drop-ins for it.
- See what's overriding what: `systemd-delta --no-pager`, `systemctl cat <unit>`, `systemd-analyze cat-config systemd/journald.conf`.

Vendor drop-ins that are intentional — leave alone, and don't "fix" them:
- `nvidia-utils`: `systemd-{suspend,hibernate,hybrid-sleep,suspend-then-hibernate,homed}.service.d/10-nvidia-no-freeze-session.conf` sets `SYSTEMD_SLEEP_FREEZE_USER_SESSIONS=false` (NVIDIA breaks with session freezing).
- `snapper`/limine: `snapper-timeline.timer.d`/`snapper-boot.timer.d` order after `snapper-sync.service`; `snapper-cleanup.service.d/limine-snapper-override.conf` runs `limine-snapper-sync` after cleanup. Anything that touches snapper/limine boot entries → use the `limine` skill too.

**Before writing a new unit, check whether a package already ships one** — e.g. `btrfs-progs` has `btrfs-scrub@.timer`, `cliphist` has a user `cliphist.service`. `systemctl list-unit-files '*name*'` and `systemctl --user -M enzord@ list-unit-files '*name*'` (and `pacman -Ql <pkg> | grep systemd`). Enabling the packaged unit plus a small drop-in beats a hand-written copy: it keeps getting upstream fixes. Template instances take an escaped path: `systemd-escape --path /home/Enzord/games` → `home-Enzord-games`.

For writing new units, timers, sockets, templates, hardening and choosing `Type=`/`Restart=`, read `references/units.md` in this skill directory.

## Workflow: inspect → propose → wait → apply → verify

Being root means nothing stops a `systemctl stop NetworkManager` or `mask sddm` from running — the pause has to come from you. Several units here would cut the user off if touched carelessly: `sddm`/`display-manager`, `NetworkManager`, `sshd` (if they're remote), `firewalld`, `dbus-broker`, the user manager (`user@1000.service`), `wayland-wm@…` (kills the running desktop).

1. **Inspect** with read-only commands. Start broad with `bash ~/.claude/skills/systemd/scripts/systemd-check.sh` (failed units system+user, degraded state, recent errors, boot time, local overrides, timers, journal size) when the problem is vague; go straight to `systemctl status`/`journalctl -u` when it's specific.
2. **Propose**: write commands as they'll actually be run — by *you, as root* — so user-manager commands carry `-M enzord@`/`runuser`, not a note saying "run this as enzord". Exact file contents / diffs with full paths, then the exact commands in order. Say which command makes it take effect, whether a daemon-reload, restart, re-login or reboot is needed, and what could go wrong (e.g. "restarting NetworkManager drops your connection for a few seconds").
3. **Wait for an explicit OK** before any state-changing command. Don't propose and apply in the same turn.
4. **Apply**: back up any existing file you overwrite (`cp -a f f.claude-bak`), write files, `systemctl daemon-reload` (or `--user -M enzord@ daemon-reload`), then enable/restart.
5. **Verify**: `systemctl status`, `systemctl is-enabled/is-active`, journal since the change (`journalctl -u X --since "-5min"`), `systemctl list-timers` for timers, `systemd-analyze verify <file>` for new units. Report failures honestly.

Pure questions ("what failed?", "why is boot slow?", "when does reflector run?") → just inspect and answer. Troubleshooting that ends in a fix → diagnose first, show the evidence (the actual log lines), then propose.

## Troubleshooting playbook

**Unit failed / won't start / restart loop**
- `systemctl status <u> -l --no-pager` (exit code, `Result=`), then `journalctl -u <u> -b --no-pager -n 100`. `status=203/EXEC` = binary missing/not executable/wrong path; `217/USER` = bad `User=`; `226/NAMESPACE` = a hardening path doesn't exist; `start-limit-hit` = restarting too fast → fix the cause, then `systemctl reset-failed <u>`.
- `systemctl show <u> -p ExecStart,Environment,User,WorkingDirectory,FragmentPath,DropInPaths` to see what systemd actually uses after drop-ins.
- Reproduce the ExecStart by hand only if it's harmless; for user units run it as enzord (`runuser -u enzord -- …`).
- AppArmor is enforced here — if a service gets EACCES on paths that look fine, check `journalctl -b -k -g apparmor` for `DENIED`.

**Boot is slow** — `systemd-analyze` (firmware ~40 s here is the motherboard, not Linux), `systemd-analyze critical-chain`, `systemd-analyze blame | head`. After the AppArmor fix the critical path is `coolercontrold.service` (~3–6 s, it waits for the cooling hardware). Known: `apparmor.service` took ~10 s compiling ~660 profiles every boot because the parser cache was off; `write-cache` was enabled 2026-09-27 and boot time dropped to ~0.3 s (userspace 16.3 s → 9.5 s). If apparmor is still slow in `blame`, check the cache is being hit (`show-cache` in parser.conf) before anything else. `NetworkManager-wait-online.service` is enabled; it only delays units that pull in `network-online.target` (here just reflector and archlinux-keyring-wkd-sync), so it doesn't slow boot. Device units in `blame` (`dev-disk-…`) are just udev settling, not a problem.

**Shutdown/reboot hangs** ("A stop job is running…") — previous boot's log: `journalctl -b -1 -n 200 --no-pager`, look for the unit that hit its timeout. Fix with a drop-in `TimeoutStopSec=` on *that* unit rather than lowering `DefaultTimeoutStopSec` globally.

**Suspend/resume** — `journalctl -b -g 'PM:|suspend|nvidia' --no-pager`. This machine uses the newer NVIDIA scheme: `options nvidia NVreg_UseKernelSuspendNotifiers=1 NVreg_TemporaryFilePath=/var/tmp` (in modprobe.d), so the driver hooks suspend itself and `nvidia-suspend/resume/hibernate.service` are **deliberately disabled**. Old forum advice says to enable them — on this setup that would double-handle suspend. Also don't touch the no-freeze drop-in. Sleep settings via `/etc/systemd/sleep.conf.d/`, lid/power-button via `/etc/systemd/logind.conf.d/` (then `systemctl kill -s HUP systemd-logind`, not restart — restarting logind kills the session).

**Timer didn't fire** — `systemctl list-timers --all`, `systemctl status <t>.timer <t>.service`. `Persistent=true` catches up after downtime; check with `systemd-analyze calendar '<OnCalendar>'`. A timer only needs to be enabled, not its service.

**Disk health** — `smartd` monitors all disks (DEVICESCAN) and logs to the journal: `journalctl -u smartd`. The root SSD `sda` is on `ata10`; one link reset (`PHYRdyChg`, CRC count 3) happened 2026-09-27 with SMART otherwise clean — if `ata10` errors recur, suspect cable / SATA link power management (`med_power_with_dipm`), not the flash.

**System-wide hangs / journald watchdog crashes** — symptom: `systemd-journald.service: Watchdog timeout`, journald core dumps in `ftruncate`, kernel `INFO: task … blocked for more than 122 seconds` with stacks in `wait_current_trans`/`start_transaction`. That's a stalled btrfs transaction, not a journald bug. Check `ps -eo pid,stat,etime,comm | awk '$2 ~ /D/'` for `btrfs-transaction` and `btrfs-qgroup-rescan`. Seen 2026-09-27: btrfs quotas are on because snapper uses them (`QGROUP="1/0"` in `/etc/snapper/configs/root`); `snapper-cleanup` ran `btrfs qgroup clear-stale`, which triggered a ~30 min qgroup rescan that froze writes to `/`. It finished on its own; no stalls in the following week. **The user chose to keep qgroups** (snapshot churn is low now that the snapper limits are tuned) — don't propose `btrfs quota disable` again unless stalls recur. Wrap any `btrfs qgroup`/`snapper` inspection in `timeout`, since they block during a stall, and tell the user not to reboot mid-rescan (it resumes at mount).

**Mounts** — fstab is turned into `.mount` units by a generator; after editing fstab run `systemctl daemon-reload` before `mount -a`. `/home/Enzord/games` is a separate Btrfs (RAID0) with `nofail,x-systemd.device-timeout=10` on purpose so boot survives a missing member — keep those options. A broken fstab line without `nofail` drops boot into emergency mode.

**Journal** — capped at 500 MB via `journald.conf.d/10-size.conf`. If it grows fast or is noisy, first find out *what* fills it: `journalctl --since -7d -o json --output-fields=SYSLOG_IDENTIFIER,_COMM -q | jq -r '.SYSLOG_IDENTIFIER // ._COMM' | sort | uniq -c | sort -rn | head`. On this machine the bulk is kernel `apparmor="ALLOWED"` lines from apparmor.d profiles in complain mode — mainly `fail2ban-server` (its systemd backend reads all journal files but the profile only allows `system.journal`, so every read is logged back into the journal) and sddm/discord `ptrace`. Fixing the noise source (a rule in `/etc/apparmor.d/local/<profile>` + `apparmor_parser -r`) matters more than the cap. The fail2ban rule is in place (2026-09-27); sddm/discord `ptrace` is the remaining big source. To change the cap, edit that drop-in, then `systemctl restart systemd-journald`. One-off cleanup: `journalctl --vacuum-size=…` (irreversible — say so). Useful reads: `journalctl -b -p err`, `-b -1` (previous boot), `--list-boots`, `-g <regex>`, `-k` (kernel), `--since "1 hour ago"`, `-o cat` (message only).

## The desktop session (user manager) on this machine

- Hyprland is `wayland-wm@hyprland.desktop.service`, started by uwsm; `graphical-session.target` and `wayland-session@hyprland.desktop.target` are active. User services meant to run with the desktop should be `WantedBy=graphical-session.target` + `PartOf=`/`After=graphical-session.target` — that's the target uwsm activates.
- **DMS is launched by Hyprland, not systemd**: `hl.exec_cmd("dms run")` in `~/.config/hypr/hyprland.lua`. `dms.service` is packaged but not enabled. (Until 2026-09-27 it looked "enabled" via a hand-made `hyprland-session.target` that uwsm never starts; that target and a no-op `app-@autostart` override were moved to `~/.config/systemd/claude-bak-20260927/`.) So:
  - `~/.config/hypr/hyprland.lua` is **hard-linked** to `~/dotfiles/hypr/.config/hypr/hyprland.lua`. `sed -i`, `cp` over it or an editor that saves via rename replaces the inode and silently breaks the link. Edit it in place (`sed … f > tmp && cat tmp > f`, or the Edit tool) and confirm with `stat -c '%i %h' <both paths>`. Follow the `hyprland` skill for anything in that file.
  - `dms.service` being inactive is **expected**, not a fault. Check `pgrep -a dms` instead.
  - Don't just `enable --now dms.service` or add it to graphical-session.target — you'd get two DMS instances (two bars, notification-bus clash on `org.freedesktop.Notifications`). Switching DMS to systemd means removing the `exec_cmd` line too (use the `hyprland` skill for that edit) and asking the user first.
- Other exec_cmd-started things (cliphist, polkit-gnome, gnome-keyring, openrgb, discord) also aren't systemd units; XDG-autostart apps (nm-applet, Valent, limine-snapper-notify) are, as `app-…@autostart.service`.
- Session environment problems (portals, GTK apps, `$DISPLAY`/`$WAYLAND_DISPLAY` missing in a user service): `systemctl --user -M enzord@ show-environment`; uwsm exports the compositor env into the user manager.

## Safe vs. state-changing commands

Read-only anytime: `systemctl status|cat|show|list-units|list-unit-files|list-timers|list-dependencies|is-*|--failed`, `journalctl …` (except `--vacuum-*`, `--rotate`, `--flush`), `systemd-analyze` (all subcommands incl. `verify`, `security`, `calendar`), `systemd-delta`, `loginctl list-sessions/show-session`, `busctl list`, the check script.

State-changing, only after OK: `start|stop|restart|reload|enable|disable|mask|unmask|revert|edit|daemon-reload|reset-failed|kill|set-property|isolate`, `journalctl --vacuum-*`, writing anything under `/etc/systemd` or `~/.config/systemd`, `reboot|poweroff|soft-reboot|suspend`. `daemon-reload` and `reset-failed` are low-risk but still changes — bundle them into the proposal.

Never run `systemctl isolate`, `switch-root`, `stop user@1000.service`, `stop display-manager` or `restart systemd-logind` casually: each ends the user's desktop session.
