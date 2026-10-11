#!/usr/bin/env python3
"""Read plain values from install/config.sh without running it, and print
them as shell assignments for run.sh to eval. Use it when the harness runs
as root but the config is editable by a normal user: never source it as root.

  config_vars.py CONFIG NAME...

Accepts NAME=value and NAME=(word word ...) with quotes and comments; refuses
anything with $ or ` (no expansion, no commands).
"""
import re, shlex, sys

path, names = sys.argv[1], sys.argv[2:]
found = {}
for line in open(path):
    m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
    if not m or m.group(1) not in names:
        continue
    value = m.group(2)
    if "$" in value or "`" in value:
        sys.exit(f"{path}: {m.group(1)} isn't a plain value")
    if value.startswith("("):
        inner = value[1:value.rindex(")")]
        found[m.group(1)] = "(" + " ".join(shlex.quote(w) for w in shlex.split(inner, comments=True)) + ")"
    else:
        words = shlex.split(value, comments=True)
        if len(words) != 1:
            sys.exit(f"{path}: {m.group(1)} isn't a single value")
        found[m.group(1)] = shlex.quote(words[0])
missing = [n for n in names if n not in found]
if missing:
    sys.exit(f"{path}: missing {', '.join(missing)}")
for n in names:
    print(f"{n}={found[n]}")
