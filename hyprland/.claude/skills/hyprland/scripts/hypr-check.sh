#!/usr/bin/env bash
# hypr-check.sh — validate the Hyprland Lua config and inspect the live session.
# Works whether run as root (some Claude sessions) or as the desktop user.
#
#   hypr-check.sh                 verify live config + show live config errors + ownership check
#   hypr-check.sh <file.lua>      verify a candidate hyprland.lua (copied next to the live dms/ dir) without touching the live one
#   hypr-check.sh clients         list open windows: class | title | floating | workspace | monitor, plus initial class/title when they differ
#   hypr-check.sh binds           list active binds as "SUPER+SHIFT + key [flags]" (raw hyprctl only shows dispatcher "__lua")
#   hypr-check.sh -- <hyprctl args>   run any hyprctl command against the running session (e.g. -- getoption general:gaps_in, -- reload config-only)

set -u
HUSER=enzord
HHOME=~enzord
LIVE_DIR="$HHOME/.config/hypr"
LIVE="$LIVE_DIR/hyprland.lua"
HUID=$(id -u "$HUSER")
RUNDIR="/run/user/$HUID"
SIG=$(ls -t "$RUNDIR/hypr" 2>/dev/null | head -1)

as_user() {
  if [ "$(id -u)" = 0 ]; then
    (cd /tmp && runuser -u "$HUSER" -- env HOME="$HHOME" XDG_RUNTIME_DIR="$RUNDIR" HYPRLAND_INSTANCE_SIGNATURE="$SIG" "$@")
  else
    (cd /tmp && env XDG_RUNTIME_DIR="$RUNDIR" HYPRLAND_INSTANCE_SIGNATURE="$SIG" "$@")
  fi
}

hc() {
  if [ -z "$SIG" ]; then echo "(Hyprland not running — no live session to query)"; return 1; fi
  as_user hyprctl "$@"
}

PY_CLIENTS=$(cat <<'PY'
import json, sys
for c in json.load(sys.stdin):
    cls, title = c["class"], c["title"][:45]
    fl = str(c["floating"]).lower()
    ws = c.get("workspace", {}).get("name", "?")
    extra = ""
    if c.get("initialClass") != cls:
        extra += "  initial_class=%r" % c.get("initialClass")
    if c.get("initialTitle") != c["title"]:
        extra += "  initial_title=%r" % (c.get("initialTitle") or "")[:45]
    print(f"{cls:28} | {title:45} | float={fl:5} | ws={ws:4} | mon={c.get('monitor')}{extra}")
PY
)
PY_MONITORS=$(cat <<'PY'
import json, sys
print("monitors: " + ", ".join(f"{m['id']}={m['name']}" for m in json.load(sys.stdin)))
PY
)
PY_BINDS=$(cat <<'PY'
import json, sys
MODS = [(64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT"), (2, "CAPS"), (16, "MOD2"), (32, "MOD3"), (128, "MOD5")]
rows = []
for b in json.load(sys.stdin):
    mods = "+".join(n for bit, n in MODS if b.get("modmask", 0) & bit)
    key = b.get("key") or "code:%s" % b.get("keycode")
    combo = f"{mods} + {key}" if mods else key
    flags = " ".join(f"[{f}]" for f in ("locked", "repeat", "release", "longPress", "non_consuming") if b.get(f))
    sub = " submap=%s" % b["submap"] if b.get("submap") else ""
    desc = "  # %s" % b["description"] if b.get("description") else ""
    rows.append(f"{combo:32} {flags}{sub}{desc}".rstrip())
print("\n".join(sorted(rows, key=str.lower)))
PY
)

verify() { # $1 = path to a hyprland.lua whose dms/ sits next to it
  echo "== Hyprland --verify-config ($1)"
  local out rc
  out=$(as_user timeout 30 Hyprland --verify-config -c "$1" 2>&1); rc=$?
  if [ "$rc" -ge 124 ] || ! grep -q 'Config parsing result' <<<"$out"; then
    # A crash/timeout prints no verdict at all — say so loudly instead of printing nothing.
    echo "VERIFY DID NOT FINISH (exit $rc$([ "$rc" -gt 128 ] && echo ", signal $((rc - 128))")) — the config was NOT checked."
    echo "Known cause: a top-level hl.exec_cmd(cmd, { rules }) segfaults --verify-config on 0.56.2. Last output:"
    tail -5 <<<"$out" | sed 's/\x1b\[[0-9;]*m//g; s/^/  /'
    return 3
  fi
  sed -n '/Config parsing result/,$p' <<<"$out" | sed '/^=*.*Config parsing result/d;/^$/d'
  return "$rc"
}

case "${1:-}" in
  clients)
    hc clients -j | python3 -c "$PY_CLIENTS"
    hc monitors -j | python3 -c "$PY_MONITORS"
    ;;
  binds)
    hc binds -j | python3 -c "$PY_BINDS"
    ;;
  --)
    shift; hc "$@"
    ;;
  "")
    verify "$LIVE"; rc=$?
    echo
    echo "== hyprctl configerrors (what the running session actually loaded — autoreload is on)"
    errs=$(hc configerrors 2>&1)
    if [ -z "$(echo "$errs" | tr -d '[:space:]')" ]; then echo "none"; else echo "$errs"; fi
    echo
    echo "== ownership (files under the user's config must stay $HUSER-owned)"
    bad=$(find -L "$LIVE_DIR" "$HHOME/.local/share/applications" "$HHOME/.local/share/icons/hicolor" \
            ! -user "$HUSER" 2>/dev/null)
    if [ -n "$bad" ]; then echo "NOT owned by $HUSER (fix as root: chown $HUSER:enzord <file>):"; echo "$bad"; else echo "ok"; fi
    exit $rc
    ;;
  *)
    cand=$(readlink -f "$1")
    [ -f "$cand" ] || { echo "no such file: $1"; exit 2; }
    tmp=$(mktemp -d /tmp/hypr-verify.XXXXXX)
    cp -r "$LIVE_DIR"/. "$tmp"/
    cp "$cand" "$tmp/hyprland.lua"
    chown -R "$HUSER" "$tmp" 2>/dev/null
    verify "$tmp/hyprland.lua"; rc=$?
    rm -rf "$tmp"
    exit $rc
    ;;
esac
