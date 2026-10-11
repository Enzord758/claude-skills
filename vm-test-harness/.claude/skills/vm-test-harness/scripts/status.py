#!/usr/bin/env python3
"""Keep state/status.json for the test run. Called by the runner, read by the progress page and watch.sh.

  status.py init                 (re)create from STEPS below, all pending
  status.py start ID             mark running
  status.py pass ID [NOTE]       mark passed
  status.py fail ID [NOTE]       mark failed
  status.py skip ID [NOTE]       mark skipped
  status.py note ID NOTE         set the note, keep the state
  status.py run STATE [NOTE]     overall state: running | passed | failed | stopped
"""
import json, os, sys, tempfile, time

ROOT = os.environ.get("VMTEST_DIR", ".")  # runtime dir: state/, logs/, disks/
PATH = os.path.join(ROOT, "state", "status.json")

# (id, group, title)
STEPS = [  # replace with the harness's steps, in run order
    ("lint", "Prep", "shellcheck on the scripts under test"),
    ("iso", "Prep", "Download and verify the installer ISO"),
    ("disks", "Prep", "Create VM disks and empty firmware vars (Setup Mode)"),
    ("r1-boot-iso", "Round 1 · fresh", "Boot the ISO, set root's password on its console"),
    ("r1-install", "Round 1 · fresh", "Run the install scripts over password SSH"),
    ("r1-reboot", "Round 1 · fresh", "Secure Boot on, boot the installed system"),
    ("r1-verify-boot", "Round 1 · fresh", "Check boot, Secure Boot, mounts"),
    ("r1-desktop", "Round 1 · fresh", "Desktop/bootstrap script"),
    ("r1-desktop-again", "Round 1 · fresh", "Same script again (idempotent)"),
    ("r1-lockdown", "Round 1 · fresh", "Final script: keys-only SSH, network"),
    ("r1-reboot-check", "Round 1 · fresh", "Reboot: settings still in effect"),
    ("r1-verify", "Round 1 · fresh", "Full checks"),
]


def now():
    return time.time()


def load():
    with open(PATH) as f:
        return json.load(f)


def save(s):
    s["run"]["updated"] = now()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH))
    with os.fdopen(fd, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, PATH)


def step(s, sid):
    for st in s["steps"]:
        if st["id"] == sid:
            return st
    sys.exit(f"unknown step {sid}")


def main(argv):
    cmd = argv[1]
    if cmd == "init":
        save({
            "run": {"state": "running", "started": now(), "updated": now(), "note": ""},
            "steps": [{"id": i, "group": g, "title": t, "status": "pending",
                       "started": None, "ended": None, "note": ""} for i, g, t in STEPS],
        })
        return
    s = load()
    if cmd == "run":
        s["run"]["state"] = argv[2]
        s["run"]["note"] = argv[3] if len(argv) > 3 else ""
        if argv[2] != "running":
            s["run"]["ended"] = now()
    elif cmd == "start":
        st = step(s, argv[2])
        st.update(status="running", started=now(), ended=None, note="")
        s["run"]["current"] = argv[2]
    elif cmd in ("pass", "fail", "skip"):
        st = step(s, argv[2])
        st["status"] = {"pass": "passed", "fail": "failed", "skip": "skipped"}[cmd]
        st["ended"] = now()
        if st["started"] is None:
            st["started"] = st["ended"]
        if len(argv) > 3:
            st["note"] = argv[3]
    elif cmd == "note":
        step(s, argv[2])["note"] = argv[3]
    else:
        sys.exit(f"unknown command {cmd}")
    save(s)


if __name__ == "__main__":
    main(sys.argv)
