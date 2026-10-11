#!/usr/bin/env python3
"""Type on the VM's serial console (state/serial.sock). Unlike vmtype.py this
reaches the firmware and bootloader too, before any keyboard driver runs.

  serialtype.py TEXT [TEXT...]   each argument is sent as is; \\r and \\e work
"""
import os, socket, sys, time

ROOT = os.environ.get("VMTEST_DIR", ".")  # runtime dir: state/, logs/, disks/
SOCK = os.path.join(ROOT, "state", "serial.sock")

s = socket.socket(socket.AF_UNIX)
s.connect(SOCK)
for arg in sys.argv[1:]:
    data = arg.encode().decode("unicode_escape").encode("latin-1")
    for b in data:
        s.send(bytes([b]))  # one byte at a time: the firmware's serial input is slow
        time.sleep(0.02)
    time.sleep(0.5)
s.close()
