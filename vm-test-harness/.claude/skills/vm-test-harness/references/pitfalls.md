# Pitfalls: symptom → cause → fix

Every entry here actually happened while building and running a harness for an
Arch/CachyOS install (Limine, sbctl Secure Boot, btrfs + snapper, NetworkManager,
firewalld, NFS backup restore). Grouped by area.

## Harness control

| Symptom | Cause | Fix |
|---|---|---|
| A step was silently skipped after editing the runner | bash reads scripts incrementally; the file changed under it | never edit the runner while it runs; stop → edit → resume |
| `pkill -f pattern` killed your own shell | the pattern appears in your own command line | match `/proc/*/comm` / `pgrep -x NAME`, or kill by pid file |
| A heredoc edit ran half the edit script as shell commands (as root, on the host) | the edited text contained the heredoc terminator (`EOF`) | write edit scripts to a file and run the file |
| qemu disappears right after a debug mode "started" it | `systemd-run` service unit killed the daemonized child when the script exited | `systemd-run --scope` for modes that leave qemu running |
| Monthly/manual runs clobber each other | shared disks | `flock` on a lock file; `ExecCondition` in the timer's service |
| Run looks fine but nobody noticed it hung for an hour | no watchdog / no output while waiting | heartbeat every 10 s in every wait loop; watchdog with stall + prompt + check-in exits |
| Banner probe in the heartbeat hung or printed garbage | read a fixed byte count from the SSH port | `exec 3<>/dev/tcp/127.0.0.1/PORT; head -n 1 <&3` with a `timeout` |
| Serial lines flood the log (boot menu countdown) | redraws without newline | strip ANSI, split on `\r`, keep last 3 lines with letters, cut to 160 chars |

## Prompts and expect

| Symptom | Cause | Fix |
|---|---|---|
| Hung at pacman `[Y/n]` | prompt followed by an ANSI escape, regex anchored on `$` didn't match | allow `(?:\x1b\[[0-9;?]*[A-Za-z])*` before `$` in every prompt regex |
| expect timeout killed a 20-minute compile | absolute timeout | inactivity timeout: a `-re {[^\n]*\n} { exp_continue }` branch resets it on each line |
| Password-login check "passed" although logins were disabled | grepped the log for a marker that is also in the logged command | have the remote compute it: `echo OK-$((40+2))`, grep `OK-42` |
| `pacman` "enter a selection" / "enter a number" prompts hang | provider/group questions | answer with `\r` (default) in interact.exp |
| Script asked for a path (key file) and waited | project-specific prompt not in the expect table | add it at the top of interact.exp; the watchdog's PROMPT exit finds these quickly |

## Boot, firmware, Secure Boot

| Symptom | Cause | Fix |
|---|---|---|
| Rerun: Secure Boot rejects the ISO | firmware vars from the last attempt already had keys | fresh copy of empty OVMF vars at the start of each fresh round |
| `sbctl enroll-keys -m -f` fails | no `dbDefault` efivar in OVMF | use `-f` only if the dbDefault efivar exists |
| Boot stops in the bootloader menu, which is empty ("no valid entries") | kernel cmdline file was 0 bytes: VM hard-stopped before it hit disk | `sync` before stopping; graceful poweroff; make the boot script fail if the cmdline is empty or the generated config has no kernel entry |
| Second install: half-written keys dir broke enrollment | earlier hard stop left an incomplete `/var/lib/sbctl` | detect incomplete key dirs and move them aside before creating keys |
| ISO not booting at all | ISO path missing / not attached | check the ISO step result before boot; `-drive media=cdrom … bootindex=0` |
| Reinstall: package conflict on microcode/kernel images | old files left on the ESP | reinstall mode removes the old Linux files from the ESP but keeps other OSes' (test with a fake Windows boot manager) |
| QEMU refused `-device virtio-vga` | not built in | `-device VGA` |

## Install scripts (things the VM caught)

| Symptom | Cause | Fix |
|---|---|---|
| Rerun of the prep step fails creating a filesystem with a fixed UUID | old filesystem with that UUID still there | `wipefs -a` + `btrfs device scan --forget` first |
| `git` in the chroot: "dubious ownership" | repo owned by another uid than the one running git | `chown` to the user, run git as the user (`runuser -u USER -- git …`) |
| AUR package unavailable (removed from repos) | upstream dropped a dependency version | switch to the `-bin` variant; build AUR packages one at a time and collect failures instead of aborting |
| Rust packages fail to build / `rust` conflicts | distro `rust` vs the toolchain the third-party repo's LLVM wants | `rustup` (install `--asdeps`, `rustup default stable`) |
| Package post-install wrote files that later conflicted with dotfile symlinks | dotfiles stowed after package installs | stow dotfiles first, then install AUR packages |
| fail2ban jail not active after install | start/stop transaction conflict at first enable | `systemctl enable` + `restart`, then wait for the jail |
| `40G` disk too small | CUDA/large packages | 160G sparse qcow2 |
| Masking a unit failed | unit file lives in `/etc/systemd/system` | move it aside, then `systemctl mask` |
| Network config right after the script, wrong after reboot | a restored NetworkManager profile with higher autoconnect-priority (e.g. static IP) beat the profile the script changed | script keeps exactly one wired profile for the interface (highest priority), deletes duplicates, configures that one; reboot step in the harness checks it |
| `sshd -T | grep -x 'passwordauthentication no'` fails although set | newer OpenSSH prints CamelCase keys | `grep -ix` |
| Backup's list of modified config files always empty | parsed `pacman -Qii` output wrongly | files are listed as `/path [modified]` — test the parser against real output |

## Network, NFS, mDNS

| Symptom | Cause | Fix |
|---|---|---|
| NFS mount in the VM: EPERM | export without `insecure`, relay connected from a high port | relay binds a source port < 1024 (QEMU as root) |
| NFS mount EPERM / weird state only while the host also has it mounted | same NFSv4 client id (same hostname) through the same source address | set `nfs4_unique_id` in the VM before mounting |
| Stale NFS file handles during long copies | server moved files between cache and array tiers mid-transfer | export from a share that doesn't move files (array-only), or no cache tier |
| Export by hostname doesn't match | the server resolves the client by mDNS | run avahi during restore so `<host>.local` answers; check firewall allows mDNS |
| Temporary avahi denied reading its config in /tmp on the installed system | AppArmor profile enforces avahi's paths | only use the temporary avahi where there's no AppArmor (chroot from the ISO); on the installed system use the normal service |
| The VM must not take the host's real static IP on the LAN | bridged networking would put it on the wire | QEMU user-net only |

## Data hygiene

- Restore tests put real secrets on the VM disks. Delete disks and vars after; a
  scheduled run does it in an EXIT trap.
- Copy decryption keys in for one step and `shred -u` them right after, inside the VM.
- Never write passwords/keys into the repo, logs or status notes. A test-only password
  for the VM is fine and should obviously be one, so nobody mistakes it for a real secret.
