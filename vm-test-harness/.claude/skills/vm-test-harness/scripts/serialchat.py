#!/usr/bin/env python3
"""Talk to the VM's serial console (state/serial.sock) like a person at it:
wait for each regex in the output, then send the text after it.

  serialchat.py TIMEOUT REGEX SEND [REGEX SEND ...]

SEND may use \\r. Exits 1 if a REGEX doesn't show up within TIMEOUT seconds.
Everything read is echoed to stdout (the step log).
"""
import os, re, socket, sys, time

ROOT = os.environ.get("VMTEST_DIR", ".")  # runtime dir: state/, logs/, disks/
SOCK = os.path.join(ROOT, "state", "serial.sock")
ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Z0-9]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)")

timeout = float(sys.argv[1])
pairs = list(zip(sys.argv[2::2], sys.argv[3::2]))
s = socket.socket(socket.AF_UNIX)
s.connect(SOCK)
s.settimeout(0.5)
buf = b""
for regex, send in pairs:
    pat = re.compile(regex.encode(), re.M)
    end = time.time() + timeout
    while not pat.search(ANSI.sub(b"", buf)):
        if time.time() > end:
            sys.stdout.write(f"\n*** serialchat: no {regex!r} within {timeout:.0f} s\n")
            sys.exit(1)
        try:
            data = s.recv(4096)
        except socket.timeout:
            continue
        if not data:
            sys.exit(1)
        buf += data
        sys.stdout.write(ANSI.sub(b"", data).decode("utf-8", "replace").replace("\r", ""))
        sys.stdout.flush()
    buf = b""
    for b in send.encode().decode("unicode_escape").encode("latin-1"):
        s.send(bytes([b]))
        time.sleep(0.02)
s.close()
