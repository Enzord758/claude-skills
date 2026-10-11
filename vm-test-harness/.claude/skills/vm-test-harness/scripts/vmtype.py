#!/usr/bin/env python3
"""Type text on the VM's keyboard through QMP (US layout, as on the Arch ISO).

  vmtype.py 'some command'      types it and presses Enter
"""
import json, os, socket, sys, time

ROOT = os.environ.get("VMTEST_DIR", ".")  # runtime dir: state/, logs/, disks/
QMP = os.path.join(ROOT, "state", "qmp.sock")
PLAIN = {" ": "spc", "-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right",
         ";": "semicolon", "'": "apostrophe", "`": "grave_accent", "\\": "backslash",
         ",": "comma", ".": "dot", "/": "slash", "\n": "ret"}
SHIFTED = {"_": "minus", "+": "equal", "{": "bracket_left", "}": "bracket_right", ":": "semicolon",
           '"': "apostrophe", "~": "grave_accent", "|": "backslash", "<": "comma", ">": "dot",
           "?": "slash", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
           "*": "8", "(": "9", ")": "0"}


def key(c):
    if c.isascii() and c.isalpha():
        return ([("shift")] if c.isupper() else []) + [c.lower()]
    if c.isdigit():
        return [c]
    if c in PLAIN:
        return [PLAIN[c]]
    if c in SHIFTED:
        return ["shift", SHIFTED[c]]
    sys.exit(f"can't type {c!r}")


def main():
    s = socket.socket(socket.AF_UNIX)
    s.connect(QMP)
    f = s.makefile("rw")
    f.readline()

    def cmd(c):
        f.write(json.dumps(c) + "\n")
        f.flush()
        while True:
            r = json.loads(f.readline())
            if "return" in r or "error" in r:
                return r

    cmd({"execute": "qmp_capabilities"})
    for c in sys.argv[1] + "\n":
        keys = [{"type": "qcode", "data": k} for k in key(c)]
        r = cmd({"execute": "send-key", "arguments": {"keys": keys}})
        if "error" in r:
            sys.exit(r["error"])
        time.sleep(0.02)


if __name__ == "__main__":
    main()
