#!/usr/bin/env bash
# Show a desktop notification to USER as soon as they have a session: run as
# its own transient unit (systemd-run --collect), so a test that starts or ends while nobody
# is logged in (03:00, or right after boot) still gets its message across.
# Gives up after 24 hours.
#
#   notify-wait.sh USER TITLE BODY [URGENCY]
set -uo pipefail

user=$1 title=$2 body=$3 urgency=${4:-normal}
bus=/run/user/$(id -u "$user")/bus
for _ in $(seq 2880); do
	[[ -S $bus ]] && break
	sleep 30
done
[[ -S $bus ]] || { echo "no session for $user within 24 h: $title"; exit 1; }
# a fresh login: give the notification daemon a moment to come up
sleep 20
runuser -u "$user" -- env DBUS_SESSION_BUS_ADDRESS="unix:path=$bus" \
	notify-send -u "$urgency" -a "vm test" -i system-run "$title" "$body"
