#!/usr/bin/env bash
# Read-only systemd health overview for this machine (system + enzord's user manager).
# Safe to run anytime: only status/list/journal reads, nothing is started, stopped or written.
# Usage: systemd-check.sh [boot-offset]   e.g. -1 for the previous boot's errors

B="${1:-0}"
USER_NAME=enzord
USER_UID=$(id -u "$USER_NAME" 2>/dev/null || echo 1000)
U=(systemctl --user -M "$USER_NAME@" --no-pager)
bold() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

bold "State"
printf 'system: %s\n' "$(systemctl is-system-running 2>&1)"
printf 'user (%s): %s\n' "$USER_NAME" "$("${U[@]}" is-system-running 2>&1)"
systemctl --version | head -1

bold "Failed units (system)"
systemctl --failed --no-legend --no-pager || true
bold "Failed units (user $USER_NAME)"
"${U[@]}" --failed --no-legend 2>&1 || true

bold "Errors this boot ($B), priority err and worse, last 30 (system + user)"
journalctl -b "$B" -p err --no-pager -q -n 30 2>&1 || true

bold "Recently restarting / start-limit units (system)"
systemctl list-units --type=service --all --no-legend --no-pager \
  | awk '$3=="activating" || $4=="auto-restart" {print}' || true
journalctl -b "$B" --no-pager -q -g 'start-limit-hit|Start request repeated too quickly|Scheduled restart job' -n 10 2>/dev/null || true

bold "Boot time"
systemd-analyze 2>&1 | head -2
systemd-analyze blame --no-pager 2>/dev/null | grep -v '\.device$' | head -8

bold "Local overrides (/etc, ~/.config) — vendor /usr/lib drop-ins omitted"
systemd-delta --no-pager 2>/dev/null | grep -E '^\[' | grep -E '/etc/|/home/' || echo "(none in /etc)"
ls -1 /etc/systemd/*.conf.d/ 2>/dev/null || echo "(no /etc/systemd/*.conf.d drop-ins)"
echo "user units in ~/.config/systemd/user:"
find ~enzord/.config/systemd/user -mindepth 1 \( -type f -o -type l \) -printf '  %P%l\n' 2>/dev/null | sed 's#\([^ ]\)/usr#\1 -> /usr#'
find ~enzord/.config/systemd -user root 2>/dev/null | sed 's/^/  ROOT-OWNED: /'

bold "Enabled-but-inactive user units (may be intentional: oneshots like xdg-user-dirs)"
"${U[@]}" list-unit-files --state=enabled --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -v '@\.service$' \
  | while read -r u; do s=$("${U[@]}" is-active "$u" 2>/dev/null); [ "$s" != active ] && echo "  $u: $s"; done

bold "Timers"
systemctl list-timers --no-pager 2>/dev/null | head -12
"${U[@]}" list-timers --no-legend 2>/dev/null | sed 's/^/  user: /'

bold "Journal"
journalctl --disk-usage
grep -hE '^\s*SystemMaxUse' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf 2>/dev/null || echo "SystemMaxUse: not set (default 10% of fs, max 4G)"
