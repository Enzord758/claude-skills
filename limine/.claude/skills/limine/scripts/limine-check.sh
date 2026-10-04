#!/usr/bin/env bash
# Read-only health check for the Limine setup. Changes nothing.
# Usage: limine-check.sh [ESP_PATH]   (default /boot)

ESP="${1:-/boot}"
CONF="$ESP/limine.conf"
EFI="$ESP/EFI/limine/limine_x64.efi"
fail=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; fail=1; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

hdr "Versions"
echo "  $(limine --version 2>/dev/null | head -1) | $(pacman -Q limine-mkinitcpio-hook limine-snapper-sync 2>/dev/null | tr '\n' ' ')"

hdr "Config enrollment (a mismatch here = unbootable under Secure Boot)"
if [[ ! -f $CONF || ! -f $EFI ]]; then
	bad "missing $CONF or $EFI"
else
	h=$(b2sum "$CONF" | awk '{print $1}')
	if grep -aqF "$h" "$EFI"; then ok "enrolled hash matches limine.conf (${h:0:16}…)"
	else bad "limine.conf hash ${h:0:16}… NOT enrolled in $EFI → run limine-enroll-config"; fi
	enroll=$(grep -hE '^\s*ENABLE_ENROLL_LIMINE_CONFIG=' /etc/limine-entry-tool.conf /etc/limine-entry-tool.d/*.conf /etc/default/limine 2>/dev/null | tail -1)
	echo "  setting: ${enroll:-ENABLE_ENROLL_LIMINE_CONFIG unset}"
fi

# Enrolled-hash slot of every Limine binary on the ESP (marker + 128 hex chars; all zeros = not enrolled)
for bin in "$ESP"/EFI/limine/*.efi "$ESP"/EFI/limine/*.EFI; do
	[[ -f $bin ]] || continue
	o=$(grep -aboF 'CONFIG_B2SUM_SIGNATURE++' "$bin" | head -1 | cut -d: -f1)
	[[ -n $o ]] || continue
	slot=$(dd if="$bin" bs=1 skip=$((o + 24)) count=16 2>/dev/null)
	ver=$(strings "$bin" | grep -m1 -oE 'Limine [0-9]+\.[0-9]+\.[0-9]+')
	[[ $slot == 0000000000000000 ]] && state="no enrolled hash (non-strict: boots any limine.conf)" || state="enrolled ${slot}…"
	echo "  $(basename "$bin") [$ver]: $state"
done

hdr "Secure Boot"
if command -v sbctl >/dev/null; then
	sbctl status 2>/dev/null | grep -E 'Setup Mode|Secure Boot' | sed 's/^/  /'
	if sbctl verify "$EFI" 2>/dev/null | grep -q 'is signed'; then ok "$EFI is signed"
	else bad "$EFI is NOT signed → sbctl sign $EFI"; fi
	unsigned=$(sbctl verify 2>/dev/null | grep 'not signed' | grep -v '/EFI/Microsoft/')
	[[ -n $unsigned ]] && { bad "unsigned files (excluding Microsoft's):"; echo "$unsigned" | sed 's/^/      /'; }
else
	warn "sbctl not installed"
fi

hdr "File hashes referenced in limine.conf"
# Unique boot():/path#hash references (kernels, initramfs, wallpaper, …)
mapfile -t refs < <(grep -oE 'boot\(\):/[^ ]+' "$CONF" | sort -u)
nok=0
for r in "${refs[@]}"; do
	p=${r#boot():}; p=${p#\$}
	file=${p%%#*}; want=${p#*#}
	[[ $p == *#* ]] || want=""
	path="$ESP$file"
	if [[ ! -f $path ]]; then bad "missing file: $path"; continue; fi
	# EFI chainloads are verified by firmware, no hash needed
	if [[ -z $want ]]; then
		[[ $file == *.efi || $file == *.EFI ]] && continue
		bad "no hash on $file (Limine panics on this under Secure Boot; wallpapers/fonts are just skipped)"; continue
	fi
	got=$(b2sum "$path" | awk '{print $1}')
	if [[ $got == "$want" ]]; then nok=$((nok+1)); else bad "hash mismatch: $file"; fi
done
ok "$nok hashed file references verified"

hdr "Global options (top of limine.conf)"
sed -n '1,/^\/[^\/]/p' "$CONF" | sed '$d' | grep -v '^\s*$' | cut -c1-110 | sed 's/^/  /'

hdr "Menu tree"
limine-entry-tool --no-hooks --tree 2 2>/dev/null | sed 's/^/  /' || grep -nE '^\s*/{1,2}[^/]' "$CONF" | sed 's/^/  /'
echo "  snapshot entries: $(grep -cE '^\s*///[^/]' "$CONF")"

hdr "Kernel cmdline"
src="/etc/kernel/cmdline"
grep -qE '^\s*KERNEL_CMDLINE\[' /etc/default/limine /etc/limine-entry-tool.d/*.conf 2>/dev/null && src="KERNEL_CMDLINE[...] in /etc/default/limine or drop-in"
echo "  source: $src"
entry=$(awk '/^  \/\/linux-cachyos/{f=1} f&&/cmdline:/{sub(/^ *cmdline: */,"");print;exit}' "$CONF")
running=$(cat /proc/cmdline)
echo "  in limine.conf: $entry" | sed -E 's/UUID=[0-9a-f-]+/UUID=…/'
[[ -f /etc/kernel/cmdline ]] && { [[ "$(tr -s ' ' </etc/kernel/cmdline | sed 's/ *$//')" == "$(echo "$entry" | tr -s ' ' | sed 's/ *$//')" ]] && ok "matches /etc/kernel/cmdline" || warn "differs from /etc/kernel/cmdline (limine-update not run since last edit?)"; }
[[ "$running" == *"$entry"* ]] && ok "running kernel booted with this cmdline" || warn "running cmdline differs (reboot pending, or booted a snapshot): $(echo "$running" | sed -E 's/UUID=[0-9a-f-]+/UUID=…/')"

hdr "Snapshots"
snaps=$(ls /.snapshots 2>/dev/null | wc -l)
echo "  snapper snapshots on disk: $snaps  | entries in boot menu: $(grep -cE '^\s*///[^/]' "$CONF")"
if [[ -f /etc/snapper/configs/root ]]; then
	lim=$(grep -E '^(NUMBER_LIMIT|TIMELINE_LIMIT_(HOURLY|DAILY|WEEKLY|MONTHLY|YEARLY))=' /etc/snapper/configs/root | tr -d '"' | tr '\n' ' ')
	echo "  limits: $lim"
fi
for t in snapper-timeline.timer snapper-cleanup.timer; do
	st=$(systemctl is-enabled "$t" 2>/dev/null)
	[[ $t == snapper-cleanup.timer && $st != enabled ]] && warn "$t is $st — snapshots are never pruned, so they (and limine_history on the ESP) keep growing" || echo "  $t: $st"
done
M=$(cat /etc/machine-id 2>/dev/null)
[[ -d $ESP/$M/limine_history ]] && echo "  limine_history: $(du -sh "$ESP/$M/limine_history" | cut -f1) in $(ls "$ESP/$M/limine_history" | wc -l) files (kernels/initramfs kept for snapshot entries)"

hdr "ESP"
df -h --output=used,size,pcent "$ESP" | tail -1 | awk '{print "  used " $1 " / " $2 " (" $3 ")"}'
ls -l --time-style=+'%F %T' "$CONF" "$CONF.old" 2>/dev/null | awk '{print "  " $6 " " $7 "  " $8}'

hdr "Firmware boot order"
efibootmgr 2>/dev/null | grep -E '^(BootCurrent|BootOrder|Boot[0-9A-F]{4})' | cut -c1-90 | sed 's/^/  /'

echo
((fail)) && { printf '\033[31mProblems found — see ✗ above.\033[0m\n'; exit 1; }
printf '\033[32mAll critical checks passed.\033[0m\n'
