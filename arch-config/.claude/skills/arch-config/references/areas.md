# System areas

## Contents
1. NVIDIA and kernel modules
2. sysctl
3. Locale, keymap, time
4. Users, groups, sudo
5. Storage: fstab, Btrfs, snapper, swap
6. Network and firewalld
7. Audio: PipeWire / WirePlumber
8. Fonts
9. Flatpak
10. AppArmor
11. Environment variables
12. udev and input devices
13. Default apps and theming

## 1. NVIDIA and kernel modules

RTX 4090 on `linux-cachyos-nvidia-open` (prebuilt open kernel modules matching the kernel) + `nvidia-utils`. No nouveau, no DKMS for the GPU.

- Early KMS: `nvidia nvidia_modeset nvidia_uvm nvidia_drm` in `MODULES=` of `/etc/mkinitcpio.conf`; the `kms` hook was removed on purpose (it pulled nouveau + ~100 MB firmware). `nvidia_drm.modeset=1` is set both on the kernel cmdline and in `/etc/modprobe.d/nvidia.conf` — redundant but harmless; don't remove either without a reason. With the current driver both `modeset` and `fbdev` already **default to 1** (`modinfo -p nvidia_drm`; live `Y` in `/sys/module/nvidia_drm/parameters/`), so old guides telling you to add them change nothing — check the live value first and tell the user.
- Suspend uses the driver's kernel suspend notifiers (`NVreg_UseKernelSuspendNotifiers=1`, shipped by nvidia-utils in `/usr/lib/modprobe.d/`), so `nvidia-suspend/resume/hibernate.service` are deliberately disabled. Old forum advice to enable them or set `NVreg_PreserveVideoMemoryAllocations` would double-handle suspend here (systemd skill has the details).
- Adding a module option: put it in `/etc/modprobe.d/<name>.conf`. Check the parameter exists first: `modinfo -p <module>` (or `/sys/module/<module>/parameters/`). Because the nvidia modules are in the initramfs, options for them only apply after an initramfs rebuild (`limine-mkinitcpio`; `limine-update` also works but additionally reinstalls Limine — limine skill) **and** a reboot. `/usr/local/bin/mkinitcpio` is a wrapper that warns on `-P` and offers `limine-mkinitcpio`; don't route around it. Verify after boot: `cat /sys/module/nvidia_drm/parameters/<param>` or `cat /proc/driver/nvidia/params`.
- Blacklisting a module: `blacklist <mod>` only stops autoloading by alias; to stop it completely also add `install <mod> /bin/false`. Never blacklist anything storage/USB/GPU-related without a rollback plan (snapshot boot entry).
- Loading a module at boot: `/etc/modules-load.d/<name>.conf` (one module per line).
- Kernel parameters go through `/etc/kernel/cmdline` + `limine-update` — limine skill. Don't edit `limine.conf` directly: Secure Boot + enrolled hash makes a hand edit unbootable.
- Useful reads: `lsmod`, `modinfo`, `nvidia-smi`, `lspci -k` (driver in use per device), `journalctl -b -k -g nvidia`.

## 2. sysctl

Local file `/etc/sysctl.d/99-security-hardening.conf` (not package-owned) sets, among others:
`kernel.kptr_restrict=2`, `kernel.dmesg_restrict=1` (non-root `dmesg` fails → use `journalctl -k`), `kernel.kexec_load_disabled=1`, `kernel.sysrq=4`, **`kernel.yama.ptrace_scope=2`**, `kernel.unprivileged_bpf_disabled=1`, `net.core.bpf_jit_harden=2`, redirects/source-route off, `rp_filter=1`, `log_martians=1`, `fs.suid_dumpable=0`.

Known side effects worth recognising:
- `ptrace_scope=2` → only root can attach: `gdb -p`, `strace -p`, some game tools/overlays/anti-cheat, `protonhax`-style injection and crash reporters fail with "Operation not permitted". If the user hits that, explain the cause and offer a choice: `1` (parent-only, the kernel default) or keep `2` and run the debugger as root. Don't silently weaken it.
- `kernel.sysrq=4` allows only keyboard-control SysRq; the full REISUB rescue needs `244` (or `1` = everything).
- `rp_filter=1` (strict) can break asymmetric routing (VPN split tunnels, multi-homed setups) — `2` (loose) is the fix there.

Changing: edit that file for hardening keys; put unrelated tuning (e.g. `vm.swappiness`, `vm.max_map_count` for games, `fs.inotify.max_user_watches`) in a new `/etc/sysctl.d/90-<topic>.conf` so the hardening file stays focused. Check what wins without applying anything: `systemd-analyze cat-config sysctl.d` (read-only; later files override earlier). `sysctl --system` *applies* all files — it's the apply step, not an inspection tool. Apply: `sudo sysctl --system`, verify: `sysctl <key>`. `/usr/lib/sysctl.d/10-arch.conf` already sets `vm.max_map_count=1048576` (games) and raised inotify limits — check the live value before "fixing" those.

## 3. Locale, keymap, time

- `/etc/locale.conf`: `LANG=en_DK.UTF-8` (English text, Danish formats). `/etc/locale.gen` enables `en_DK.UTF-8` and `en_US.UTF-8`. Adding e.g. `da_DK.UTF-8`: uncomment in locale.gen → `sudo locale-gen` → set the specific `LC_*` in `/etc/locale.conf` (or `localectl set-locale`) → re-login. Per-user override: `~/.config/locale.conf`.
- Console keymap: `/etc/vconsole.conf` `KEYMAP=dk-latin1`, `FONT=Lat2-Terminus16` (in initramfs via `sd-vconsole` → change needs `limine-mkinitcpio`). The **desktop** keyboard layout is set in Hyprland (`hyprland` skill), and SDDM's login-screen layout via `localectl set-x11-keymap dk` — three separate places.
- Time: `Europe/Copenhagen`, `systemd-timesyncd` with NTP on. Change zone: `sudo timedatectl set-timezone <Zone>`. Dual-boot with Windows: Linux keeps RTC in UTC (correct); if Windows shows the wrong time, fix it on the Windows side (`RealTimeIsUniversal` registry key), don't switch Linux to local time.

## 4. Users, groups, sudo

`enzord`: groups `enzord wheel audio input storage video`; shell `/bin/zsh`. `wheel` gives sudo (password required).

- Adding to a group: `sudo usermod -aG <group> enzord` (**`-a`** — without it, `-G` replaces all supplementary groups and can drop `wheel` = losing sudo). Takes effect at next login (`newgrp` / re-login); verify with `id enzord` (shows the DB) vs `id` (current session).
- With systemd-logind + PipeWire, device access is granted by uaccess ACLs to the active seat — `audio`/`video`/`input`/`storage` groups are mostly not needed and `input` lets any process read keystrokes. Don't add more of these as a fix; find out why uaccess didn't apply (usually a udev rule missing `TAG+="uaccess"`). Common legit additions: `docker`/`libvirt`, `uucp` (serial devices), `gamemode` isn't a group.
- **Starting/stopping/restarting a system service without a password** → prefer a polkit rule over sudoers: the user then runs plain `systemctl restart <unit>` (no `sudo` at all), it's scoped to one unit + verb + user, and a syntax error in it can't lock anyone out of sudo. `/etc/polkit-1/rules.d/50-<name>.rules` (root:root 0644, takes effect immediately; check with `journalctl -u polkit` for parse errors):
  ```js
  polkit.addRule(function(action, subject) {
      if (action.id == "org.freedesktop.systemd1.manage-units" &&
          action.lookup("unit") == "<unit>.service" &&
          action.lookup("verb") == "restart" &&   // or "start" / "stop" / "reload"
          subject.user == "enzord") {
          return polkit.Result.YES;
      }
  });
  ```
  Undo: delete the file. Use sudoers NOPASSWD only when the command isn't a systemd unit action.
- sudoers: drop-in in `/etc/sudoers.d/<name>` (no dot in the name), mode `0440`, validate with `visudo -cf` **before** installing. As enzord, a broken sudoers file means no sudo and no way to fix it without root (live USB / snapshot boot) — the apply script must validate first and abort on failure. `NOPASSWD` for specific commands only, never `ALL`.
- Passwords: `passwd` is interactive — leave to the user.

## 5. Storage: fstab, Btrfs, snapper, swap

Layout on `sda3` (one Btrfs, `compress=zstd:1,noatime,ssd,discard=async,space_cache=v2`): `@`→`/`, `@home`→`/home`, `@cache`→`/var/cache`, `@log`→`/var/log`, `@snapshots`→`/.snapshots`. ESP `sda1`→`/boot` (vfat, 1.5 GB, holds kernels + snapshot initramfs history). Swap partition `sda2` (8 GB, zswap enabled, no zram). Games: separate Btrfs RAID0 at `/home/enzord/games` with `nofail,x-systemd.device-timeout=10` (keep — boot survives a missing disk).

- **fstab edits**: identify by `UUID=` (from `lsblk -f` / `blkid`), never `/dev/sdX` for new entries. Validate (`findmnt --verify --tab-file new.fstab`), install, `sudo systemctl daemon-reload`, `sudo mount -a`, `findmnt <target>`. Any non-root disk gets `nofail` — without it a missing/broken disk drops boot into emergency mode. New Btrfs subvolume entries copy the existing option set and add `subvol=/@name`.
- Subvolumes keep data out of root snapshots: new `@name` for things like VM images, large downloads, or databases (also `chattr +C` on the empty dir for VM images/DBs to disable CoW). Creating one: mount the top level (`subvolid=5`) somewhere temporary, `btrfs subvolume create`, add fstab line.
- **snapper**: config `root` only (`/etc/snapper/configs/root`, readable as root). snap-pac makes a pre-snapshot per pacman transaction (post hook masked on purpose); `snapper-timeline.timer` hourly; `snapper-cleanup.timer` prunes per the config's `NUMBER_*`/`TIMELINE_*` limits. Snapshot boot entries are limine's (limine skill). To keep fewer/more: change the limits in the config (`snapper -c root set-config TIMELINE_LIMIT_DAILY=5`) instead of deleting snapshots by hand, and never delete `limine_history` files on the ESP. `/home` has no snapper config — mention it if the user asks about protecting their files; snapshots aren't backups anyway (same disk).
- Maintenance in place: `fstrim.timer` (weekly) + `discard=async`, `btrfs-scrub@-.timer` (monthly, root). Health: `btrfs device stats /`, `btrfs filesystem usage -T /`, `smartctl -a /dev/sda` (systemd skill has the sda/ata10 history).
- Swap/zswap: `swappiness=100` (kernel default). Hibernation would need swap ≥ RAM and a `resume=` param (limine) — 8 GB is too small; say so before anyone tries.

## 6. Network and firewalld

NetworkManager (`nmcli`) manages `eno1` (Intel I225-V, the active link) and the MediaTek MT7922 Wi-Fi. `nm-applet` runs in the session.

- Connections: `nmcli con show`, `nmcli dev status`. Static IP/DNS: `nmcli con mod <name> ipv4.method manual ipv4.addresses … ipv4.gateway … ipv4.dns …` then `nmcli con up <name>` (drops the link briefly — say so). Global NM options in `/etc/NetworkManager/conf.d/*.conf`.
- I225-V is known for occasional link drops at 2.5 GbE with some switches; EEE off (`ethtool --set-eee eno1 eee off`, persisted via an NM dispatcher or udev rule) is the usual fix if the user reports random disconnects.

**firewalld** — zone `public` on `eno1`, default target (reject). Currently allowed: `dhcpv6-client`; ports `27036/udp 27036/tcp 27040/tcp` (Steam Remote Play / LAN transfer); a rich rule allowing `ssh` only from `192.168.1.0/24`.
- Read: `firewall-cmd --list-all` works as enzord; changes need root.
- Prefer named services over raw ports: `firewall-cmd --get-services` has `kdeconnect`, `steam-streaming`, `steam-lan-transfer`, `ssh`, … Add: `sudo firewall-cmd --permanent --zone=public --add-service=<svc>` then `sudo firewall-cmd --reload`. Raw ports only when no service exists (`--add-port=1234/tcp`). For LAN-only exposure, a rich rule like the ssh one: `--add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" service name="<svc>" accept'`.
- **Valent** (installed, KDE Connect protocol, autostarts) needs the `kdeconnect` service (1714–1764 tcp+udp) — it's not open, so phone discovery fails unless the phone connects outward. Opening it LAN-only via rich rule is the tidy fix.
- Never remove the ssh rule or switch the zone without asking whether the user is connected remotely. Changing the Steam port list to the named services is a nice cleanup but not necessary.

## 7. Audio: PipeWire / WirePlumber

PipeWire 1.6 + WirePlumber 0.5 + pipewire-pulse, all user services. No user config yet (`~/.config/pipewire`, `~/.config/wireplumber` don't exist). Devices: NVIDIA HDMI audio (monitors) plus whatever USB/onboard devices — read `wpctl status` live.

- Inspect: `wpctl status`, `wpctl inspect <id>`, `pw-top`, `pactl list short sinks`. Default sink: `wpctl set-default <id>` (persists in WirePlumber state).
- **WirePlumber 0.5 uses SPA-JSON `.conf` files** in `~/.config/wireplumber/wireplumber.conf.d/*.conf`; the Lua snippets (`~/.config/wireplumber/main.lua.d/*.lua`, `alsa_monitor.rules = …`) found in most forum posts are 0.4 syntax and are **silently ignored** here. Typical 0.5 rule (disable a device / rename / set priority):
  ```
  monitor.alsa.rules = [
    { matches = [ { node.name = "~alsa_output.pci-0000_01_00.1.*" } ]
      actions = { update-props = { node.disabled = true } } }
  ]
  ```
  Match names come from `wpctl inspect` / `pw-cli ls Node`.
- PipeWire tunables (quantum, sample rate) in `~/.config/pipewire/pipewire.conf.d/*.conf` (`context.properties = { default.clock.allowed-rates = [ 44100 48000 ] }`). Pulse-specific in `pipewire-pulse.conf.d`.
- Apply: `systemctl --user restart wireplumber pipewire pipewire-pulse` (as root: `systemctl --user -M enzord@ restart …`). Audio cuts out for a second; apps usually reconnect.
- Crackling under load → raise quantum (`default.clock.min-quantum = 1024`) before anything else. HDMI audio disappearing after monitor sleep is an NVIDIA/ELD quirk — re-plug or `wpctl` re-select, not a config fault.

## 8. Fonts

Installed: noto-fonts (+cjk, emoji), ttf-jetbrains-mono-nerd, MesloLGS Nerd (p10k). ~1000 font files.
- Install from repos/AUR; user-only fonts can go in `~/.local/share/fonts/`. Then `fc-cache -f`.
- Defaults/substitution: `~/.config/fontconfig/fonts.conf` (doesn't exist yet) or `~/.config/fontconfig/conf.d/NN-name.conf`. Check result with `fc-match sans-serif`, `fc-match monospace`, `fc-match emoji`.
- Terminal font is in kitty.conf (dotfiles); GTK/Qt app fonts via nwg-look / qt6ct — not fontconfig. Ask which surface the user means if it's unclear.

## 9. Flatpak

Remote `flathub` (system-wide). No apps installed currently.
- Install user-level without root: `flatpak install --user flathub <id>` (needs `flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo` once) — useful when running as enzord. System-wide installs need root/polkit.
- Permissions: `flatpak override --user --filesystem=/home/enzord/games <id>`, inspect with `flatpak info --show-permissions <id>`. Flatseal is the GUI.
- Theming: GTK theme inside flatpaks needs the matching `org.gtk.Gtk3theme.*` or `--env=GTK_THEME=…` override; cursor via `--filesystem=~/.icons:ro` / `xdg-data/icons:ro`.

## 10. AppArmor

Enabled (`lsm=…apparmor…` on cmdline), with the `apparmor.d` package (~690 profiles, many in complain mode) and parser cache on.
- Denials: `journalctl -b -k -g 'apparmor="DENIED"'` (enforced) and `apparmor="ALLOWED"` (complain-mode noise). The profile name in the log line is what to fix.
- Fix by adding rules to `/etc/apparmor.d/local/<profile>` (included by the apparmor.d profile; not overwritten on upgrade), then `sudo apparmor_parser -r /etc/apparmor.d/<profile>`. Don't edit the profile file itself (package-owned).
- Last resort for one app: `sudo aa-complain /etc/apparmor.d/<profile>` (logs instead of blocks) — never disable AppArmor globally as a fix.
- Journal noise from complain-mode profiles is a systemd-skill topic (it has the current fail2ban/sddm/discord findings).

## 11. Environment variables

Pick the narrowest place that reaches the processes that need it:

| Scope | Where | Notes |
|---|---|---|
| Hyprland and everything it launches | `hyprland.lua` (`hl.env(...)`) | hyprland skill; uwsm forwards the compositor env to the user manager |
| systemd user services + session | `~/.config/environment.d/NN-name.conf` (`KEY=value`) | exists: `90-dms.conf` (`ELECTRON_OZONE_PLATFORM_HINT=auto`, `TERMINAL=kitty`); re-login |
| One app | its `.desktop` `Exec=env KEY=val app` in `~/.local/share/applications/`, or flatpak override | most targeted |
| Shell only | `~/.zshrc` / `~/.zshenv` | doesn't reach GUI apps |
| Every user incl. root, all PAM logins | `/etc/environment` | blunt; avoid for desktop stuff |

Verify in the right context: `systemctl --user show-environment` (as root: `-M enzord@`), `cat /proc/<pid>/environ | tr '\0' '\n'` for a running app. NVIDIA/Wayland vars (`LIBVA_DRIVER_NAME`, `__GLX_VENDOR_LIBRARY_NAME`, `NVD_BACKEND`, …) belong in Hyprland's env, not here — check what hyprland.lua already sets first.

## 12. udev and input devices

- Rules: `/etc/udev/rules.d/NN-name.rules`. Find match keys with `udevadm info -a /dev/<node>` or `udevadm info -q property -n /dev/<node>`; for USB, `lsusb` gives `idVendor:idProduct`. Validate `udevadm verify <file>`, test `udevadm test $(udevadm info -q path -n /dev/<node>)`, apply `sudo udevadm control --reload && sudo udevadm trigger` (or replug).
- Device access for the desktop user: `TAG+="uaccess"` (logind ACL for the active seat) instead of `MODE="0666"` or adding groups. Number the file below `73` (`70-…`) so uaccess processing sees the tag.
- Xbox controller: `xone-dkms-git` (+ `xone-dongle-firmware`) for the wireless dongle. If it stops working after a kernel update: `dkms status`, `journalctl -b -k -g xone`; reinstall/rebuild with yay. Wired controllers use the in-kernel `xpad`. Steam Input may grab controllers — test outside Steam with `evtest` / `jstest`.
- Keyboard/mouse settings (sensitivity, accel, layout) are Hyprland's `input` block, not udev — hyprland skill.

## 13. Default apps and theming

- `~/.config/mimeapps.list` is a symlink into `~/dotfiles/mimeapps/` — edit through the symlink (or `xdg-mime default <app>.desktop <mime/type>`, which writes to the same file; check afterwards that it's still a symlink and not replaced by a regular file). Query: `xdg-mime query default <type>`, `xdg-mime query filetype <file>`.
- GTK theme/icons/cursor via nwg-look (config in dotfiles); colours come from DMS's matugen templates — don't hand-edit generated `dank-*` files. Qt apps follow GTK (`QT_QPA_PLATFORMTHEME=gtk3` set in hyprland.lua); qt6ct is installed but not active. Icon theme: Papirus (catppuccin folders), cursor Bibata.
