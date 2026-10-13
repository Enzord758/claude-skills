# shellcheck shell=bash disable=SC2034
# Helpers shared by the install stages. Sourced, not run:
#   set -euo pipefail
#   source "$(dirname "$0")/lib.sh"
# config.sh next to it holds the plain settings (USER_NAME, disk serials, …).

INSTALL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(dirname "$INSTALL_DIR")
# shellcheck source=/dev/null
source "$INSTALL_DIR/config.sh"

info() { printf '\e[36m::\e[0m %s\n' "$*"; }
ok() { printf '\e[32m::\e[0m %s\n' "$*"; }
warn() { printf '\e[33m:: %s\e[0m\n' "$*" >&2; }
die() {
	printf '\e[31merror:\e[0m %s\n' "$*" >&2
	exit 1
}

# confirm "question" -> 0 on y/yes
confirm() {
	local ans
	read -rp "$1 [y/N] " ans
	[[ $ans == [yY] || $ans == [yY][eE][sS] ]]
}

# confirm_destructive "what will be destroyed" -> exits unless the user types YES
confirm_destructive() {
	local ans
	printf '\n\e[31m%s\e[0m\n' "$1"
	read -rp "Type YES to continue: " ans
	[[ $ans == YES ]] || die "aborted"
}

require_root() { [[ $EUID -eq 0 ]] || die "run as root"; }
require_user() { [[ $EUID -ne 0 ]] || die "run as ${USER_NAME:-the user}, not root (sudo is used where needed)"; }
in_chroot() { systemd-detect-virt --chroot; }

# disk_by_serial SERIAL -> /dev/sdX or /dev/nvmeXnY (device order isn't stable)
disk_by_serial() {
	local name
	name=$(lsblk -dno NAME,SERIAL | awk -v s="$1" '$2 == s {print $1; exit}')
	[[ -n $name ]] || die "no disk with serial $1"
	printf '/dev/%s\n' "$name"
}

# partition DISK N -> /dev/sda3 or /dev/nvme0n1p3
partition() {
	if [[ $1 == *[0-9] ]]; then printf '%sp%s\n' "$1" "$2"; else printf '%s%s\n' "$1" "$2"; fi
}

# read_list FILE -> names, comments and blank lines dropped (first word per line)
read_list() { grep -vE '^[[:space:]]*(#|$)' "$1" | awk '{print $1}'; }
