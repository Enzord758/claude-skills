#!/usr/bin/env python3
"""Relay one guest TCP connection (stdin/stdout, from QEMU's guestfwd=cmd:) to
HOST:PORT. Lets a VM on QEMU user-net reach one real service (e.g. an NFS
server); the server sees the host, as with any NAT'ed client.

With --privileged the relay connects from a source port below 1024, like the
kernel's NFS client — needed for NFS exports without "insecure" (QEMU must run
as root then).

  guestfwd=tcp:IP:PORT-cmd:/usr/bin/python3 /path/tcprelay.py [--privileged] HOST PORT
"""
import errno, os, selectors, socket, sys

args = sys.argv[1:]
privileged = args[:1] == ["--privileged"]
if privileged:
    args = args[1:]
host, dport = args[0], int(args[1])

s = None
for port in (range(1023, 599, -1) if privileged else [0]):
    try:
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c.bind(("", port))
        c.connect((host, dport))
        s = c
        break
    except OSError as e:
        c.close()
        if e.errno not in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
            raise
if s is None:
    sys.exit("no free privileged source port")

sel = selectors.DefaultSelector()
sel.register(0, selectors.EVENT_READ)
sel.register(s, selectors.EVENT_READ)
while True:
    for key, _ in sel.select():
        if key.fileobj == 0:
            data = os.read(0, 65536)
            if not data:
                s.shutdown(socket.SHUT_WR)
                sel.unregister(0)
                continue
            s.sendall(data)
        else:
            data = s.recv(65536)
            if not data:
                sys.exit(0)
            view = memoryview(data)
            while view:
                n = os.write(1, view)
                view = view[n:]
