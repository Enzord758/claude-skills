#!/usr/bin/env bash
# Watchdog for a VM test run. Run it in the background; it exits (waking whoever
# waits on it) with one line saying why:
#   ENDED    the run unit is no longer active (final state from status.json)
#   FAILED   a step failed (the runner may still be powering the VM off)
#   PROMPT   the current step's log ends in what looks like an unanswered prompt
#   STALL    the current step's log hasn't grown for STALL seconds
#   VM DIED  the qemu pid is gone (seen twice: a poweroff removes it a moment later)
#   CHECKIN  every CHECKIN seconds regardless — a reminder to look at the log and
#            the screen and judge whether the step is working or stuck
# The runner should print a heartbeat every ~10 s while it waits, so a quiet log
# really means the VM side went quiet. Restart the watchdog after each exit while
# the run is active.
#
#   VMTEST_DIR=… [UNIT=vmtest-run] watch.sh [STALL_SECONDS] [PROMPT_SECONDS] [CHECKIN_SECONDS]
# Expects $VMTEST_DIR/state/status.json (status.py), logs/<step>.log, state/qemu.pid.
T=${VMTEST_DIR:?set VMTEST_DIR}
UNIT=${UNIT:-vmtest-run}
STALL=${1:-150}
PROMPT=${2:-120}
CHECKIN=${3:-300}
gone=0

field() { python3 -c "import json,sys; s=json.load(open('$T/state/status.json')); print(eval(sys.argv[1]))" "$1" 2>/dev/null; }

while :; do
	sleep 20
	if ! systemctl is-active -q "$UNIT"; then
		echo "ENDED: run $(field "s['run']['state']") — $(field "s['run'].get('note','')")"
		exit 0
	fi
	failed=$(field "' '.join(x['id'] for x in s['steps'] if x['status'] == 'failed')")
	if [[ -n $failed ]]; then
		echo "FAILED: $failed — $(field "[x['note'] for x in s['steps'] if x['status'] == 'failed'][0]")"
		exit 0
	fi
	cur=$(field "s['run'].get('current','')")
	log=$T/logs/$cur.log
	[[ -n $cur && -f $log ]] || continue
	age=$(($(date +%s) - $(stat -c %Y "$log")))
	last=$(tail -c 400 "$log" | sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' | tr '\r' '\n' | grep -v '^\s*$' | tail -1)
	if ((age > PROMPT)) && grep -qiE '\[[yY]/[nN]\]|password|YES|\?\s*$|:\s*$' <<<"$last"; then
		echo "PROMPT: step $cur has waited ${age}s on: $last"
		exit 0
	fi
	if ((SECONDS > CHECKIN)); then
		echo "CHECKIN: step $cur, log age ${age}s, last line: $last"
		exit 0
	fi
	if ((age > STALL)); then
		echo "STALL: step $cur log unchanged for ${age}s; last line: $last"
		exit 0
	fi
	if [[ -f $T/state/qemu.pid ]] && ! kill -0 "$(cat "$T/state/qemu.pid")" 2>/dev/null; then
		((gone++)) && { echo "VM DIED: qemu is gone during step $cur"; exit 0; }
	else
		gone=0
	fi
done
