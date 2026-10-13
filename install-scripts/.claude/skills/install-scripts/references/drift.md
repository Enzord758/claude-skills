# Drift

Drift = anything a reinstall from the repo would produce differently from the
running machine. A drift check finds it; adopting it keeps the repo the truth.

Contents: what to compare · reading expectations from the scripts · the ignore
file · adopting each kind · running it on a schedule · root-owned copies

## What to compare

| Area | Expected (from the repo) | Actual (host) |
|---|---|---|
| packages | the lists (`repo.txt`, `aur.txt`), minus base/installer meta packages and `package NAME` lines in the ignore file | `pacman -Qqe` (explicit) and `pacman -Qq` (installed) |
| managed files | every `install`/`cp` of a repo file in `system/*/restore.sh` (and the final stage) | the target file, byte for byte |
| stage-written files | what the chroot stage writes from config (hostname, locale, vconsole, sudoers, kernel cmdline, one-line `echo "x" >/etc/y`) | the files |
| settings | values the stages set (timezone symlink, initramfs `MODULES/HOOKS` lines, snapshot config `set-config` keys) | the live config |
| units | `systemctl enable X` lines in the scripts, plus units their `[Install] Also=` pulls in | `systemctl list-unit-files --state=enabled` minus vendor-preset-enabled |
| firewall / network | the rules and connection settings the network script sets | `firewall-cmd --list-*`, `nmcli` |
| unowned files | — | files under `/etc` no package owns (`pacman -Qlq`) and no script accounts for |
| modified package files | `sed -i` targets in the scripts | `pacman -Qii` lines ending in `[modified]` |

Report both directions where it makes sense: installed-but-unlisted *and*
listed-but-missing; enabled-but-unscripted *and* scripted-but-not-enabled.

## Read expectations from the scripts, never run them

The checker parses the repo (regex/shlex over `install`, `cp`, `systemctl
enable`, `sed -i` lines; `config.sh` as plain values) so that:
- it follows the scripts automatically when they change,
- it never executes repo code (it typically runs as root, the repo is
  user-editable).
Skip lines whose paths contain `$` (can't be resolved without running).
Handle grouped flags (`-Dm 644`, `-t DIR`) and backslash continuations.
`scripts/drift.py` implements this for the layout in `structure.md`; extend it
with project-specific checks (bootloader header, snapper keys, network) rather
than special-casing in the generic part.

## The ignore file

`drift-ignore.txt`: one fnmatch glob per line (`*` matches `/` too), last match
wins, `!pattern` takes a path back in, `package NAME` exempts a hand-installed
package. **Every line or block has a comment saying why.** Typical content:
runtime state (`/etc/machine-id`, `/etc/adjtime`, `ld.so.cache`, pacman gnupg,
generated certificates), backups (`*.pacnew`, `*.pacsave`, `*.bak`, `/etc/*-`),
files package hooks generate, secrets restored from the backup (NetworkManager
connections, VPN keys, SSH host keys — not in the repo by design), and packages
built locally that no list can install. See `scripts/drift-ignore.example.txt`.

## Adopting, by kind

| Drift line | Investigate | Adopt as |
|---|---|---|
| package installed but in no list | `pacman -Qi` (reason, date), `pacman -Si` (which repo; AUR if not found), pacman.log for what came with it, ask if it was a one-off | a line in the right section of `repo.txt`/`aur.txt`, with a comment if not obvious (e.g. "service left disabled") — or `pacman -Rns` on the host if it was a trial (ask) |
| package listed but not installed | renamed/dropped upstream? replaced by a `-bin`? | fix the list; or install it |
| managed file differs | `diff` repo vs host: who changed which? | host is newer and intended → copy it into the repo; repo is newer → run that `restore.sh` |
| unowned file under `/etc` | `cat` it, `ls -l`, what created it (a tool's config, a hand edit, a leftover) | a new `system/<area>/` with the file and a `restore.sh`, or delete the leftover (ask), or ignore with a reason (runtime/secret) |
| modified package file | `pacman -Qii pkg` lists it; diff against the package's version (`pacman -Qkk`, or extract from the cache) | turn the change into a drop-in if the program supports `.d/`; else a `sed -i` of the exact line in a `restore.sh` |
| unit enabled but no script enables it | `systemctl cat`, who enabled it (pacman hook? user?) | `systemctl enable` in the stage or `restore.sh` that owns it, or disable it on the host |
| network/firewall differs | `nmcli`, `firewall-cmd --list-all` | change the network script (and expect a VM run), or revert the host |
| stale installed copy of the checker | the repo changed | re-run its `restore.sh` |

After adopting: apply on the host the way the scripts would (run the
`restore.sh`), re-run the check until it reports nothing, then report what was
adopted and where.

## Running it on a schedule

A systemd timer (daily, `Persistent=true`) runs the check as root with a
`--quiet` mode; when the report changes (not every night), notify the user's
desktop (`notify-send` as the user over `/run/user/<uid>/bus`, waiting for a
session if none). Keep the last report in `/var/lib/<name>/` and a `--show`
to print it.

## Root-owned copies

The scheduled job is root, the repo belongs to the user. So: the restore
script installs the checker to `/usr/local/lib/<name>/` (root-owned) and the
timer runs that copy with `--repo ~user/dotfiles` — it only *reads* the repo.
Because that copy is installed by an `install` line in a `restore.sh`, the
managed-files check compares it with the repo version like any other file: a
forgotten refresh shows up as drift.
