# CoolerControl troubleshooting (this machine)

Start every diagnosis with measurements:

```bash
systemctl status coolercontrold --no-pager
journalctl -u coolercontrold -b --no-pager | tail -50     # readable as enzord
~/.claude/skills/coolercontrol/scripts/cc.py live
~/.claude/skills/coolercontrol/scripts/cc.py show
```

## Reading the nct6799 sysfs values

hwmon numbers (`hwmon4` …) **change between boots**, so find the chip by `name` (cc.py does this). Don't hard-code `hwmonN` anywhere.

`pwmN_enable` on nct6775-family chips:

| value | meaning |
|---|---|
| 0 | full speed (no control) |
| 1 | manual: CoolerControl is writing `pwmN` |
| 2 | thermal cruise (BIOS) |
| 3 | fan speed cruise (BIOS) |
| 5 | SmartFan IV: the BIOS curve is in control |

A channel CC controls should show `pwm_enable=1`. `5` on fan2-5 means CC isn't controlling it: the channel is disabled or unmanaged, the daemon is down, or it failed to apply at startup (look for "Successfully applied" / errors in the journal). fan1/6/7 show 5 and 0 rpm because nothing is connected and they're disabled in CC. That's expected.

`pwmN` is 0-255. duty % = pwm × 100 / 255.

## "The fan doesn't react to temperature"

1. Is the channel assigned the profile you think it is? `cc.py show` → Channel assignments.
2. What does the profile read? Radiators reads **cpu-gpu-mix**, a 5 s time average of max(CPU, GPU). Short spikes are smoothed away by design.
3. The function: `deviance 4.0` means the temperature must move 4 °C before re-evaluating, `response_delay 4` s, and `only_downward` means ramp-up is immediate. A slowly rising temperature within the hysteresis band looks like "nothing happens".
4. The curve: Radiators is flat 35 % up to 55 °C on the mix sensor (Side follows at ~30 %). Below that nothing changes by design.
5. Is the daemon applying at all? `pwm_enable` should be 1 (see above).

## "Fans stuck at 100 % / full speed"

- Daemon down or crashed: the BIOS/SmartFan or the chip's failsafe takes over. `systemctl status`, journal.
- The temp source reads garbage (e.g. a sensor that disappeared makes a Mix sensor fail). Check `live` for missing or absurd temps.
- The curve reaches 100 % at 78 °C on the mix sensor. A GPU at 78 °C+ in a game is normal, so all radiator fans at 100 % while gaming is *intended* unless the user wants a different curve.

## Daemon won't start / keeps restarting

- `journalctl -u coolercontrold -b` → often a config parse error after a hand edit. As root: `coolercontrold check`, then fix or `coolercontrold restore` (daemon stopped). As enzord: hand the user these commands.
- `coolercontrold detect` (root) shows which hardware it finds. Missing nct6799 → `lsmod | grep nct6775`. The daemon's `sensors_auto_detect` loads Super-I/O modules at startup.
- Port 11987 busy: `ss -ltnp | grep 11987`.
- For more detail, set `CC_LOG=DEBUG` in a drop-in (`systemctl edit coolercontrold` → `[Service]` `Environment=CC_LOG=DEBUG`), restart, and remove it afterwards. Use the systemd skill for drop-in conventions.

## After suspend/resume

The daemon reapplies settings on resume. If fans stay wrong after resume: journal around the resume time (`journalctl -u coolercontrold --since "-10 min"`), then `systemctl restart coolercontrold` (root) as a workaround. Report it; don't just paper over it.

## GPU (RTX 4090) fans

The 4090 is **water-blocked in the CPU loop** (topology recorded 2026-09-27). Its fan headers are unused, which is why its fan channels are **disabled in CC** and `nvidia-smi` reports 0 %. That's expected, not a fault. The radiator fans cool the GPU, so "the GPU is hot" means looking at the radiator curve (`cpu-gpu-mix`), the pump and the loop, not at GPU fans. "Make the GPU fans follow the radiators" has nothing to act on here. Say so.

On a machine where the GPU is air cooled (check `cc.py topology`), its own firmware curve runs the fans. To let CC control them, re-enable the channels (`PUT /settings/devices/{gpu uid}`, see api.md), assign a profile, and warn that CC then owns the card's fan curve, including at idle. The daemon uses NVML (`--nvidia-cli` forces the CLI fallback).

## liquidctl / RGB (ASUS Aura LED Controller)

- The `coolercontrol-liqctld` child of coolercontrold (command line `python3 -q`) is the liquidctl bridge. If it's missing, lighting control is gone. Check the journal for liquidctl errors.
- `liquidctl_integration = true` in config.toml. Disabling it removes Aura control.
- Modes available per channel: `GET /devices` → `lighting_modes`.
- Lighting is owned by OpenRGB, not CoolerControl. For colour problems read "RGB lighting belongs to OpenRGB" in SKILL.md first.
- The Aura controller is USB HID. If it disappears after a firmware/BIOS update or resume, replug/reboot before debugging the software.

## Resetting

Destructive, and only if the user wants to start over: stop the daemon, `coolercontrold backup` first, then remove `/etc/coolercontrol/` and `/var/lib/coolercontrol/`. Always offer a targeted fix before this.
