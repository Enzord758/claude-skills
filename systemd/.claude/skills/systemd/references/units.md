# Writing units — reference

Read this when creating a new service/timer/socket/path unit or a substantial drop-in. Everything here is valid for systemd 262; when in doubt check `man systemd.service`, `systemd.exec`, `systemd.timer`, `systemd.unit` locally rather than memory.

## Contents
1. System or user unit?
2. Service template
3. Choosing Type=
4. Restart behaviour
5. Timers (cron replacement)
6. Templates (`foo@.service`), sockets, path units
7. Hardening
8. Validate before enabling

## 1. System or user unit?

| Runs … | Put it in | Enable with |
|---|---|---|
| at boot, independent of login, needs root or a system user | `/etc/systemd/system/` | `systemctl enable --now x` |
| while enzord is logged into the desktop (needs Wayland, pipewire, dbus session, notifications) | `/home/enzord/.config/systemd/user/` (owned by enzord) | `systemctl --user -M enzord@ enable --now x` |
| as enzord but also without login | user unit + `loginctl enable-linger enzord` (ask first — keeps a user manager running permanently) | as above |

A system service with `User=enzord` does **not** get the user's session bus or `$WAYLAND_DISPLAY`. If the program touches the desktop, it's a user unit.

## 2. Service template

Comments must be on their own line starting with `#` or `;` — systemd has no inline comments, so `User=foo  # note` sets the user to `foo  # note`.

```ini
[Unit]
Description=Short human description
Documentation=man:foo(1)
# Only if it genuinely needs a working network (otherwise omit — it slows boot):
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
ExecStart=/usr/bin/foo --flag value
# Absolute paths only. No shell features (pipes, &&, ~, globs) — for those:
# ExecStart=/usr/bin/bash -c 'foo | bar'
# system units only; omit in user units
User=foo
Restart=on-failure
RestartSec=5s

[Install]
# user units: default.target or graphical-session.target
WantedBy=multi-user.target
```

Desktop-bound user service (this machine uses uwsm, which activates `graphical-session.target`):

```ini
[Unit]
Description=…
PartOf=graphical-session.target
After=graphical-session.target
Requisite=graphical-session.target

[Service]
ExecStart=/usr/bin/foo
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

Don't invent a compositor-specific target (an old hand-made `hyprland-session.target` was never started under uwsm and was removed 2026-09-27) — `graphical-session.target` is the one uwsm activates.

## 3. Choosing Type=

- `exec` (default choice): ready once the binary has been exec'd; failures to exec are reported. Prefer over `simple`.
- `simple`: like exec but reports success even if exec fails. Only for compatibility.
- `notify`/`notify-reload`: program calls `sd_notify(READY=1)`; use only if upstream documents it.
- `forking`: legacy daemons that double-fork; needs `PIDFile=`. Prefer running such daemons in foreground mode with `exec`.
- `oneshot`: runs to completion (scripts, timer jobs). Add `RemainAfterExit=yes` if it represents a state ("applied settings"). Can have multiple `ExecStart=`.
- `dbus`: ready once `BusName=` appears (e.g. dms.service).

## 4. Restart behaviour

`Restart=on-failure` for daemons; `always` only if clean exit also means "should come back". Default start-rate limit: 5 starts / 10 s → `start-limit-hit`. Tune in `[Unit]` with `StartLimitIntervalSec=` / `StartLimitBurst=`; after a hit, `systemctl reset-failed x`. `RestartSteps=` + `RestartMaxDelaySec=` give exponential back-off.

## 5. Timers (cron replacement)

Two files, same basename: `backup.service` (Type=oneshot, no `[Install]`) and `backup.timer`:

```ini
[Unit]
Description=Nightly backup

[Timer]
OnCalendar=*-*-* 03:00:00
# run at next boot if the machine was off at 03:00
Persistent=true
# optional jitter
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
```

Enable **the timer only**: `systemctl enable --now backup.timer`. Validate schedules with `systemd-analyze calendar 'Mon..Fri *-*-* 08:00' --iterations=3`. Monotonic alternatives: `OnBootSec=15min`, `OnUnitActiveSec=1h`. Test the job immediately with `systemctl start backup.service`.

Things that care about snapper/Btrfs: don't schedule heavy jobs at `:00` without jitter — `snapper-timeline.timer` fires hourly and triggers `limine-snapper-sync`, which rewrites `/boot/limine.conf`.

## 6. Templates, sockets, path units

- `foo@.service` + `%i` (instance, escaped) / `%I` (unescaped). Enable an instance: `systemctl enable foo@bar.service`. Paths as instance: `systemd-escape --path /dev/sdb`.
- Socket activation: `foo.socket` with `ListenStream=…`, service gets the fd; enable the socket, not the service.
- Path units: `foo.path` with `PathChanged=/some/file` triggers `foo.service` on change.

Useful specifiers: `%h` home dir, `%u` user, `%t` runtime dir (`/run` or `/run/user/1000`), `%S` state dir, `%C` cache dir.

## 7. Hardening (system services)

Start with a moderate set, then check with `systemd-analyze security x.service`. Each option can break a service that legitimately needs the access — add, restart, read the journal.

```ini
NoNewPrivileges=yes
# / read-only except:
ProtectSystem=strict
ReadWritePaths=/var/lib/foo
# or read-only; NB /home/enzord/games is under /home
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
# creates /var/lib/foo owned by User=
StateDirectory=foo
# throwaway UID, pairs well with StateDirectory=
DynamicUser=yes
```

A path listed in `ReadWritePaths=` that doesn't exist makes the service fail with `226/NAMESPACE`. AppArmor profiles apply on top of this.

## 8. Validate before enabling

```sh
systemd-analyze verify /etc/systemd/system/x.service      # syntax, missing binaries, bad deps
systemctl daemon-reload
systemctl cat x.service                                    # confirm systemd sees what you wrote
systemctl show x.service -p ExecStart,Type,Restart,WantedBy
systemctl start x.service && systemctl status x.service --no-pager
journalctl -u x.service -b --no-pager -n 50
```

For user units `systemd-analyze --user verify` needs to run as enzord (`runuser -u enzord -- env XDG_RUNTIME_DIR=/run/user/1000 systemd-analyze --user verify …`).
