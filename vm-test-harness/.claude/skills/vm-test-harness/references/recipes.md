# Recipes

Contents: layout · starting the VM · network shaped like the LAN · Secure Boot vars ·
console and serial · access phases · step runner · resume · stopping cleanly ·
progress page · scheduled runs · host packages

Placeholders: `<lan>` = the real LAN subnet (e.g. 10.0.0.0/24), `<gw>`, `<dns>`,
`<server>` = a real server the VM must reach, `<SERIAL…>` = real disk serials read from
the project's config.

## Layout

Keep the harness code in the repo next to what it tests (`test/vm/`), and runtime data
outside it on a disk with room (`VMTEST_DIR`): `disks/`, `iso/`, `logs/<step>.log`,
`logs/serial-*.log`, `state/` (status.json, qmp.sock, serial.sock, qemu.pid, run.lock),
`ssh/id` (the harness's own key). A real install + desktop needs 100+ GB of qcow2
(sparse) and 16 GB RAM if anything compiles (8 GB ran out during Rust builds).

## Starting the VM

```bash
qemu-system-x86_64 -name vmtest -enable-kvm -machine q35,smm=on -cpu host -smp 12 -m 16384 \
  -global driver=cfi.pflash01,property=secure,value=on \
  -drive if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd \
  -drive if=pflash,format=raw,unit=1,file=$D/vars.fd \
  -device ahci,id=ahci \
  -drive id=sys,if=none,format=qcow2,discard=unmap,file=$D/sda.qcow2 \
  -device ide-hd,bus=ahci.0,drive=sys,serial=<SERIAL_SYS> \
  -drive id=n1,if=none,format=qcow2,file=$D/nvme1.qcow2 -device nvme,drive=n1,serial=<SERIAL_NVME1> \
  -netdev "user,id=n0,net=<lan>,host=<gw>,dhcpstart=<.100>,dns=<dns>,hostfwd=tcp:127.0.0.1:2222-<.100>:22" \
  -device virtio-net-pci,netdev=n0,acpi-index=1 \
  -device VGA -display none \
  -chardev socket,id=ser0,path=$S/serial.sock,server=on,wait=off,logfile=$L/serial-$(date +%H%M%S).log \
  -serial chardev:ser0 \
  -qmp unix:$S/qmp.sock,server=on,wait=off \
  -pidfile $S/qemu.pid -daemonize \
  [-drive id=cd,if=none,media=cdrom,readonly=on,file=$ISO -device ide-cd,bus=ahci.4,drive=cd,bootindex=0]
```

- `serial=` on `ide-hd`/`nvme` makes `/dev/disk/by-id/*<serial>` match the real machine.
- `acpi-index=1` → predictable name `eno1`.
- `-device VGA`: some QEMU builds lack virtio-vga; VGA always works with screendump.
- Create disks with `qemu-img create -f qcow2`; a fresh run deletes and recreates them.
  If the scripts expect an existing filesystem with a fixed UUID (e.g. a data RAID), create
  it in a prep step with `mkfs … -U <uuid>` after `wipefs -a` (a rerun finds the old one).

## Network shaped like the LAN

QEMU user-net with `net=`, `host=` (gateway), `dns=` and `dhcpstart=` set to the real
LAN's values: scripts that configure DHCP, a fixed DNS server or LAN-only firewall rules
run unchanged. The guest can't be reached from the LAN and doesn't send from its own
address, so reusing real addresses is safe.

Reaching one real service (e.g. NFS) from inside:

```
guestfwd=tcp:<server-ip>:2049-cmd:/usr/bin/python3 /path/tcprelay.py --privileged <server-ip> 2049
```

QEMU spawns the relay per connection with the guest's stream on stdin/stdout. The server
sees the host. NFS exports without `insecure` require a source port < 1024: the relay
binds one (QEMU must run as root). If the server identifies clients (NFSv4 client id
derived from the hostname), give the VM its own:
`echo vmtest-<hostname> > /sys/module/nfs/parameters/nfs4_unique_id` (after `modprobe nfs`,
before mounting) — otherwise the server rejects the VM or confuses it with the host.

If the scripts later switch the VM to another address, the hostfwd breaks; add one live
(see QMP below) or design the forward around the final address.

## Secure Boot firmware vars

- Empty vars (`cp /usr/share/edk2/x64/OVMF_VARS.4m.fd $D/vars.fd`) = no PK = Setup Mode:
  what a script that enrolls its own keys (sbctl) needs. Reset them at the start of every
  fresh round, or a rerun finds the last attempt's keys and Secure Boot rejects the ISO.
- `virt-fw-vars` (pip `virt-firmware`, in a venv) edits vars offline:
  `virt-fw-vars --inplace vars.fd --sb` (Secure Boot on — what the user does in the
  firmware after first boot), `--set-false SecureBootEnable` (off, to boot the unsigned
  ISO again for a reinstall while keeping enrolled keys).
- With enrolled custom keys the firmware may lack `dbDefault`; `sbctl enroll-keys -m -f`
  fails then — use `-f` only when the dbDefault efivar exists.

## Console and serial

- The serial chardev on a socket is bidirectional and also logged. It works from the
  first firmware line, needs no network, and shows panics/stuck boots that SSH can't.
- Linux only logs to serial with `console=ttyS0` on its command line. For the ISO: when
  the boot menu appears on serial (systemd-boot prints `Boot in`), send `e`, then
  ` console=tty0 console=ttyS0,115200\r` to append to the entry. Last `console=` gets
  systemd's status lines. Leave the installed system's command line untouched so it
  matches the real one.
- Log into the ISO console and set root's password like a person:
  `serialchat.py 60 '' '\r' 'login: ?$' 'root\r' '# $' 'passwd\r' 'New password: ?$' 'PW\r'
  'Retype new password: ?$' 'PW\r' 'updated successfully' ''` (send `\r` first: the login
  prompt may already have scrolled by).
- Type one byte at a time with small delays; firmware serial input is slow.

## QMP

Connect with `socat - UNIX-CONNECT:$S/qmp.sock` (or a few lines of Python, see
`scripts/vmtype.py`), send `{"execute":"qmp_capabilities"}`, then e.g.:
- `{"execute":"screendump","arguments":{"filename":"/tmp/s.png","format":"png"}}`
- `{"execute":"human-monitor-command","arguments":{"command-line":"hostfwd_add tcp:127.0.0.1:2223-<ip>:22"}}`
- `{"execute":"send-key","arguments":{"keys":[{"type":"qcode","data":"ret"}]}}`

## Access phases

Track who the harness logs in as with one function, e.g. `access USER PORT password|key`,
and derive ssh options from it:
- password mode: `sshpass -p PW ssh -o PubkeyAuthentication=no
  -o PreferredAuthentications=password,keyboard-interactive …` (no key even tried, so
  you really test password login);
- key mode: `ssh -i $T/ssh/id -o IdentitiesOnly=yes …`.
Always `-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
-o ConnectTimeout=5 -o ServerAliveInterval=15`.

If a restore step brings back the real `authorized_keys`, append the harness's own public
key afterwards (and say so — it's the one deliberate difference from a real install), or
you lose access once passwords are disabled.

Helpers worth having: `vssh CMD`, `vscp FILE DEST`, `vsudo 'script'` (password piped to
`sudo -S -p ''`), `vscript FILE` (pipe a local script to root bash), `vint TIMEOUT STEP CMD`
(interactive through `interact.exp` with `ssh -tt`), `wait_ssh SECONDS` (loop with
heartbeat), `pw_ssh` (does a password login work? — for negative tests).

Long interactive commands that drop the connection on purpose (a script reapplying the
network profile) should run their network part in their own unit
(`systemd-run --wait --collect …`) inside the guest so the drop doesn't kill them; the
harness then reconnects (exit 255 from ssh = connection dropped).

## Step runner

```bash
FROM=${1:-}
step() { # ID FUNCTION ARGS…
  local id=$1 rc; shift
  if [[ -n $FROM ]]; then [[ $id == "$FROM" ]] || return 0; FROM=; fi
  st start "$id"; NOTE=
  "$@" >>"$L/$id.log" 2>&1; rc=$?
  if ((rc == 0)); then st pass "$id" "$NOTE"
  else st fail "$id" "${NOTE:-exit $rc} — see the log"; st run failed "Stopped at: $id"
       poweroff_vm >>"$L/$id.log" 2>&1; exit 1; fi
}
CUR=r1-01 step r1-01 s_01 fresh
```
`st` = `scripts/status.py`. Steps set `NOTE` to a one-line human result.

Typical install sequence: lint → fetch+verify ISO (sha256 + signature) → disks → boot
ISO + console password → prep + copy the working tree in (`tar | ssh tar -x`) → each install
script → (firmware change, e.g. Secure Boot on) → reboot to disk → boot checks → desktop
script twice → restore → lockdown script → negative checks (passwords refused) →
reboot → same checks → full checks. A second round for "reinstall over an existing
system" (fake Windows boot manager on the ESP, reuse enrolled keys) catches cleanup bugs.

## Resume

`run.sh STEP` skips earlier steps but first rebuilds the context STEP needs:
- chroot steps: boot the ISO, copy the repo, mount the installed system (the install
  scripts should have a `mount` mode for exactly this), refresh the scripts inside;
- steps on the installed system: boot the disk, pick password or key access depending
  on whether the lockdown step already ran, refresh the scripts inside, and remove a
  stale package-manager lock left by an earlier hard stop.

## Stopping cleanly

`sync` in the guest before any hard stop, and prefer `systemctl poweroff` + wait (up to
~3 min, with heartbeats) over killing qemu. A hard kill right after writing leaves files
empty (seen: a kernel command line file and a key GUID file at 0 bytes, which made the
next boot menu empty) and package-manager locks behind.

## Progress page

A ~100-line `http.server` on 127.0.0.1: `/` (static HTML polling), `/status.json`,
`/log/<step>?n=400` (tail, with an `X-Log-Age` header), `/screen.png` (QMP screendump on
request). Run it as its own transient unit, started by the runner if not active.

## Scheduled runs

A systemd timer (`OnCalendar=…`, `Persistent=true` so a missed run catches up after boot)
→ service with `ExecCondition=` skipping when a manual run is active,
`ExecStartPre=/bin/sleep 600` so a catch-up doesn't compete with login, a long
`TimeoutStartSec`. Notify the desktop at start, failure and success; if nobody is logged
in, a transient unit waits for `/run/user/<uid>/bus` (up to a day) and then calls
`notify-send` as the user. Delete restored-data disks at exit (trap).
A scheduled job running as root must run a root-owned copy of the harness and must not
source user-editable config.

## Host packages (Arch names)

qemu-base (or qemu-full), edk2-ovmf, expect, sshpass, socat, python, shellcheck;
virt-firmware via pip in a venv.
