#!/usr/bin/env bash
# Read-only overview of package/config health. Works as root or as enzord
# (sections that need root say so instead of failing).
set -u
hdr() { printf '\n== %s ==\n' "$1"; }
isroot=0; [ "$(id -u)" -eq 0 ] && isroot=1

hdr "identity"
echo "running as: $(id -un) (uid $(id -u))$([ $isroot -eq 1 ] && echo ' — root: can apply after OK' || echo ' — not root: privileged steps go to the user')"
echo "kernel running: $(uname -r)"
echo "kernel installed: $(pacman -Q linux-cachyos 2>/dev/null)"
if [ ! -d "/usr/lib/modules/$(uname -r)" ]; then
  echo "!! modules dir for running kernel is gone -> kernel was upgraded, REBOOT pending"
fi

hdr "last sync / upgrade"
grep -E '\[PACMAN\] (starting full system upgrade|synchronizing)' /var/log/pacman.log | tail -n 2
grep -E 'upgraded|installed|removed' /var/log/pacman.log | tail -n 1

hdr "pending updates (repo, fresh db in tmp — no partial-upgrade risk)"
if command -v checkupdates >/dev/null; then
  out=$(checkupdates 2>/dev/null); n=$(printf '%s' "$out" | grep -c . )
  echo "$n repo updates pending"; printf '%s\n' "$out" | grep -E '^(linux|nvidia|mesa|systemd|glibc|hyprland|pacman|limine|mkinitcpio)' 
fi
if command -v yay >/dev/null && [ $isroot -eq 0 ]; then
  echo "AUR updates: $(yay -Qua 2>/dev/null | grep -c .)"
fi

hdr ".pacnew / .pacsave"
find /etc /boot -xdev \( -name '*.pacnew' -o -name '*.pacsave' \) 2>/dev/null | head -n 30 || true
[ $isroot -eq 0 ] && echo "(as non-root some /etc dirs are unreadable; list may be incomplete)"

hdr "orphans (installed as deps, nothing needs them)"
pacman -Qdtq 2>/dev/null | head -n 30 | tr '\n' ' '; echo

hdr "foreign packages (AUR/local) count"
pacman -Qqm | wc -l

hdr "package cache"
du -sh /var/cache/pacman/pkg 2>/dev/null
echo "paccache.timer: $(systemctl is-enabled paccache.timer 2>/dev/null)"
echo "interrupted-download leftovers (download-*): $(ls -d /var/cache/pacman/pkg/download-* 2>/dev/null | wc -l)"
[ -d /home/Enzord/.cache/yay ] && echo "yay build cache: $(du -sh /home/Enzord/.cache/yay 2>/dev/null | cut -f1)"
echo "explicit leaf packages to review: $(pacman -Qetq | wc -l) (pacman -Qetq; AUR: pacman -Qmq)"

hdr "failed units"
systemctl --failed --no-legend --plain 2>/dev/null || true

hdr "local /etc config not owned by any package (selected dirs)"
for d in /etc/sysctl.d /etc/modprobe.d /etc/udev/rules.d /etc/mkinitcpio.conf.d /etc/environment.d /etc/pacman.d/hooks /etc/NetworkManager/conf.d /etc/pipewire/pipewire.conf.d /etc/X11/xorg.conf.d; do
  [ -d "$d" ] || continue
  for f in "$d"/*; do [ -e "$f" ] || continue; pacman -Qoq "$f" >/dev/null 2>&1 && continue
    if [ "$(readlink "$f")" = /dev/null ]; then echo "masked: $f -> /dev/null"; else echo "local: $f"; fi; done
done

hdr "disk"
df -h / /home /boot 2>/dev/null | sed 1d
if [ $isroot -eq 1 ]; then btrfs filesystem usage -T / 2>/dev/null | sed -n '1,8p'; fi

hdr "snapper (root)"
snaps=$(snapper -c root list --columns number,date,description 2>/dev/null) && printf '%s\n' "$snaps" | tail -n 3 || echo "(snapper list needs root)"
