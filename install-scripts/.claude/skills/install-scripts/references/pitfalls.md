# Pitfalls: symptom → cause → fix

Found while building and testing install scripts for an Arch-based desktop
(btrfs + snapper, Limine with sbctl Secure Boot, a third-party optimised repo,
NetworkManager, firewalld, AppArmor, fail2ban, an encrypted backup restore).

## Disks and filesystems

| Symptom | Cause | Fix |
|---|---|---|
| Wrong disk partitioned / script refuses on a rerun | `/dev/sdX` order isn't stable | find disks by serial (`lsblk -dno NAME,SERIAL`) |
| `mkfs.btrfs -U <uuid>` fails on a rerun | the old filesystem with that UUID still there | `wipefs -a` the members and `btrfs device scan --forget` first |
| Reinstall: pacstrap "file exists" for microcode/kernel images | the old install's files on the ESP | reinstall mode deletes the old Linux files on the ESP (images, bootloader dir, machine-id dirs) and keeps other OSes' (`EFI/Microsoft`, `EFI/BOOT`) |
| Snapper `create-config` fails ("subvolume exists") | `/.snapshots` already a mounted subvolume | the usual dance: umount, remove the dir, create-config, delete its subvolume, recreate the dir, mount again |
| Snapper qgroup errors | quotas not set up | `snapper setup-quota` after `create-config` |
| Files written right before a hard power-off are empty | page cache not flushed | `sync` before power-off in any automation; prefer a clean shutdown |

## Boot and Secure Boot

| Symptom | Cause | Fix |
|---|---|---|
| Boot menu empty ("no valid entries") | `/etc/kernel/cmdline` empty, so the entry tool generated nothing | the boot stage dies if the cmdline file is empty, and checks the generated config has a kernel entry after the update |
| `sbctl enroll-keys -m -f` fails | firmware has no `dbDefault` (`-f` = firmware builtin keys) | use `-f` only if the `dbDefault` efivar exists, else `-m` (Microsoft keys only) |
| sbctl confused on a rerun | half-created `/var/lib/sbctl` from an aborted run | move an incomplete key dir aside before creating keys |
| "Setup Mode" check unreliable | parsing human output | read `sbctl status --json`; compare the enrolled PK with your cert via efivars to know it's yours |
| Kernel package can't be removed later | stock kernel pulled in by pacstrap | install the replacement kernel from the lists, then remove the stock one explicitly |
| Bootloader enrolled config hash mismatch after edits | config edited by hand after enrollment | change the bootloader's config only through its update tool, which re-enrolls |

## Packages and builds

| Symptom | Cause | Fix |
|---|---|---|
| A listed package disappeared from the repos | upstream dropped it | switch to the `-bin`/AUR variant in the list; the AUR loop skips a `-bin` whose plain name is installed |
| Rust AUR builds fail / `rustc` broken | distro `rust` vs the toolchain a third-party repo's LLVM expects | `rustup` (as dependency) with `rustup default stable`, minimal profile |
| One AUR failure aborts the whole stage | `set -e` on the loop | build one at a time, collect failures, exit 2 at the end |
| stow refuses to link a config | a package's post-install created the file first | stow before AUR installs |
| `git` "dubious ownership" in the chroot | repo copied as root, used as the user | `chown -R user: repo`, run git as the user |
| The modified-config list in a backup/drift tool is always empty | wrong parse of `pacman -Qii` | modified files appear as `/path [modified]` in the backup-files section |
| Package needs a confirm in an unattended run | `[Y/n]`, provider selections | `--noconfirm` in scripts that are never interactive; interactive stages answer prompts themselves |

## Services, security

| Symptom | Cause | Fix |
|---|---|---|
| fail2ban's sshd jail not active after install | start/stop race at first enable | `enable` then `restart`, then wait for `fail2ban-client status sshd` |
| `systemctl mask` fails | unit file lives in `/etc/systemd/system` | move it aside, then mask |
| AppArmor denies a service's new path | enforced profile | a rule in `/etc/apparmor.d/local/<profile>` + `apparmor_parser -r` (managed by a restore script) |
| A drop-in `sshd -T` check fails although set | newer OpenSSH prints CamelCase keys | compare case-insensitively |
| Journal grows to GBs | default cap is 10 % of the filesystem | `journald.conf.d/10-size.conf` with `SystemMaxUse=` |

## Network and SSH

| Symptom | Cause | Fix |
|---|---|---|
| Network config right after the final stage, back to old after reboot | a restored NetworkManager profile with higher autoconnect-priority wins at boot | the network script keeps exactly one wired profile for the interface (highest priority), deletes the others, configures that one; a reboot check proves it |
| The install over SSH dies at the network step | the connection reapply drops the session and kills the script | run the network part in its own transient unit (`systemd-run --wait --collect`) and reconnect |
| Locked out after keys-only | `authorized_keys` missing or wrong | the final stage refuses unless `ssh-keygen -lf ~/.ssh/authorized_keys` works; `sshd -t` before reload |
| SSH open to the world after hardening | the default `ssh` service still in the zone | remove the service, add rich rules for the LAN subnet only |
| NFS export by hostname refuses the client | the server resolves the client by mDNS | `nss-mdns` in `nsswitch.conf` (`mdns_minimal [NOTFOUND=return]` before `resolve`), avahi running, mDNS allowed in the firewall |
| Console font/keymap commands fail over SSH | no real console | warn, don't die |

## Process

| Symptom | Cause | Fix |
|---|---|---|
| A script edited mid-run skipped/repeated lines | bash reads scripts incrementally | never edit a running script |
| A multi-line edit through a heredoc ran half as shell commands | the content contained the terminator | write edit scripts to a file and run the file |
| "Works on my machine" after adopting drift | the change was applied by hand, not via the script | apply on the host by running the same `restore.sh`, then re-run the drift check |
