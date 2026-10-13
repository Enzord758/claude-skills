#!/usr/bin/env python3
"""Compare this (Arch-based) machine with its install scripts and report drift:
anything a reinstall from the repo would get differently. Read-only. Run as
root (it reads all of /etc).

  drift.py                   full report, exit 1 when there is drift
  drift.py --quiet           only the drift lines
  drift.py --repo DIR        the repo to check against (default: the parent of
                             the directory this file is in, i.e. drop it in
                             install/)

It never runs code from the repo — a scheduled job may run it as root while
the repo is user-editable. What it expects is parsed from the repo, so it
follows the scripts. Layout it assumes (see the install-scripts skill):

  install/packages/*.txt       package lists: first word per line, # comments
  install/*.sh                 stage scripts
  system/*/restore.sh          root-owned config: `install`/`cp` of repo files
  install/drift-ignore.txt     what doesn't count (see the example file)

Checks:
  packages   explicitly installed but in no list / listed but not installed
  files      every repo file an `install`/`cp` line puts somewhere, byte for byte
  units      `systemctl enable X` in the scripts (+ their Also=) vs enabled units
  unowned    files under /etc no package owns and no script accounts for
  modified   package files pacman sees as [modified] that no script changes

Add project-specific checks (bootloader config, snapshot settings, network,
firewall) in the marked section rather than special-casing the generic ones.
"""
import fnmatch, glob, os, re, shlex, subprocess, sys

QUIET = "--quiet" in sys.argv
if "--repo" in sys.argv:
    REPO = os.path.abspath(sys.argv[sys.argv.index("--repo") + 1])
else:
    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install")
IGNORE = os.path.join(INSTALL, "drift-ignore.txt")
drift = []  # (area, message)


def sh(cmd):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True).stdout


def report(area, msg):
    drift.append((area, msg))


def read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def logical_lines(path):
    """Lines of a shell script with backslash continuations joined."""
    lines, cur = [], ""
    for line in open(path):
        line = line.rstrip("\n")
        if line.rstrip().endswith("\\"):
            cur += line.rstrip()[:-1] + " "
            continue
        lines.append(cur + line)
        cur = ""
    return lines


SCRIPTS = sorted(glob.glob(f"{INSTALL}/*.sh")) + sorted(glob.glob(f"{REPO}/system/*/restore.sh"))
ignore_lines = [l.strip() for l in open(IGNORE)] if os.path.exists(IGNORE) else []

# --- packages ---------------------------------------------------------------
wanted = set()
for f in glob.glob(f"{INSTALL}/packages/*.txt"):
    wanted |= {l.split()[0] for l in open(f) if l.strip() and not l.lstrip().startswith("#")}
explicit = set(sh("pacman -Qqe").split())
installed = set(sh("pacman -Qq").split())
# "package NAME-OR-GLOB" lines: installed by hand, or by pacstrap / a distro's
# installer (base, base-devel, …) on purpose
exempt = ["base", "base-devel"] + [l.split()[1] for l in ignore_lines
                                   if l.startswith("package ") and len(l.split()) > 1]
for p in sorted(explicit - wanted):
    if not any(fnmatch.fnmatch(p, e) for e in exempt):
        report("packages", f"{p} is installed explicitly but in no package list")
for p in sorted(wanted - installed):
    if p.endswith("-bin") and p[:-4] in installed:
        continue  # the plain package stands in for its -bin variant
    report("packages", f"{p} is in a package list but not installed")

# --- files the scripts install ----------------------------------------------
managed = {}  # target -> repo source


def parse_installs(script, base_dir):
    for line in logical_lines(script):
        line = line.split(" #", 1)[0].strip()
        if not (line.startswith("install ") or line.startswith("cp ")):
            continue
        line = line.replace('"$REPO_DIR', f'"{REPO}').replace("$REPO_DIR", REPO)
        try:
            words = shlex.split(line)
        except ValueError:
            continue
        args, pos, target_dir, i = words[1:], [], None, 0
        while i < len(args):
            a = args[i]
            # options taking a value, alone or ending a group (-Dm 644, -t DIR)
            if a.startswith("-") and not a.startswith("--") and a[-1] in "mogt":
                if a[-1] == "t":
                    target_dir = args[i + 1]
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            pos.append(a)
            i += 1
        if "$" in " ".join(pos):
            continue  # needs the script's variables: can't know without running it
        if target_dir is None:
            if len(pos) < 2:
                continue
            *srcs, dest = pos
        else:
            srcs, dest = pos, target_dir
        for src in srcs:
            if src.startswith("/") and not src.startswith(REPO):
                continue  # a copy between two places on the target, not a repo file
            src = src if os.path.isabs(src) else os.path.join(base_dir, src)
            if not os.path.isfile(src):
                continue
            t = dest
            if target_dir is not None or len(srcs) > 1 or dest.endswith("/"):
                t = os.path.join(dest, os.path.basename(src))
            managed[os.path.normpath(t)] = src


for script in SCRIPTS:
    parse_installs(script, os.path.dirname(script))
for target, src in sorted(managed.items()):
    have = read(target)
    if have is None:
        report("files", f"{target} is missing (from {os.path.relpath(src, REPO)})")
    elif have != read(src):
        report("files", f"{target} differs from {os.path.relpath(src, REPO)}")

# --- enabled units ----------------------------------------------------------
expect_units = set()
for script in SCRIPTS:
    for line in logical_lines(script):
        m = re.match(r"\s*(?:sudo\s+)?systemctl enable (.*)", line)
        if m:
            expect_units |= {w for w in m.group(1).split("#")[0].split()
                             if not w.startswith("-") and "$" not in w}
# Units an enabled unit pulls in through [Install] Also= come with it
for u in list(expect_units):
    for line in sh(["systemctl", "cat", u if "." in u else u + ".service"]).splitlines():
        if line.startswith("Also="):
            expect_units |= set(line[5:].split())
for u in sorted(expect_units):
    unit = u if "." in u else u + ".service"
    if sh(["systemctl", "is-enabled", unit]).strip() != "enabled":
        report("units", f"{unit} isn't enabled (the scripts enable it)")
for line in sh("systemctl list-unit-files --state=enabled --no-legend --plain").splitlines():
    parts = line.split()
    if len(parts) < 3 or parts[2] == "enabled":
        continue  # enabled by the vendor preset: no script needed
    unit = parts[0]
    if unit in expect_units or unit.removesuffix(".service") in expect_units:
        continue
    if "@." in unit and any(u.startswith(unit.split("@")[0] + "@") for u in expect_units):
        continue  # template instances show up as their template
    report("units", f"{unit} is enabled, but no script enables it")

# --- project-specific checks --------------------------------------------------
# e.g. the bootloader config's header, snapshot config keys the chroot stage
# sets, the network profile and firewall rules the network script sets. Add
# any file such a check covers to `accounted` below.
accounted = set(managed)

# --- files under /etc nobody accounts for --------------------------------------
rules = [l for l in ignore_lines if l and not l.startswith(("#", "package "))]


def ignored(path):
    hit = False
    for r in rules:  # last match wins; !pattern takes a path back in
        neg = r.startswith("!")
        pat = r[1:] if neg else r
        if fnmatch.fnmatch(path, pat) or ("/" not in pat and fnmatch.fnmatch(os.path.basename(path), pat)):
            hit = not neg
    return hit


owned = set(sh("pacman -Qlq").splitlines())
# package files a script edits in place (sed -i … /etc/x), and files a script
# writes with a redirect (… > /etc/x)
for script in SCRIPTS:
    for line in logical_lines(script):
        line = line.split(" #")[0]
        if re.match(r"\s*(?:sudo\s+)?sed -i", line):
            accounted |= set(re.findall(r"(/etc/[^\s'\"]+)\s*$", line))
        accounted |= {p for p in re.findall(r">>?\s*(/etc/[^\s'\";)]+)", line) if "$" not in p}
for dirpath, dirs, files in os.walk("/etc"):
    for name in files:
        p = os.path.join(dirpath, name)
        if p in owned or p in accounted or ignored(p):
            continue
        report("unowned", f"{p} isn't from a package or the scripts")

for line in sh("pacman -Qii").splitlines():
    m = re.search(r"(/\S+) \[modified\]$", line)
    if m and m.group(1) not in accounted and not ignored(m.group(1)):
        report("modified", f"{m.group(1)} is changed from the package's version, and no script changes it")

# --- report -------------------------------------------------------------------
if not QUIET:
    print(f"Checked against {REPO}: {len(wanted)} listed packages, "
          f"{len(managed)} script-installed files, {len(expect_units)} units")
for area, msg in drift:
    print(f"{area:9} {msg}")
if not QUIET:
    print(f"\n{len(drift)} difference(s)" if drift else "\nNo drift: a reinstall from the repo gives this machine.")
sys.exit(1 if drift else 0)
