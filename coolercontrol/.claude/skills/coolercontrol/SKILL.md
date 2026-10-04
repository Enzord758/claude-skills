---
name: coolercontrol
description: Use for anything about fans, pump, cooling or case/RGB lighting on this machine, which is controlled by CoolerControl 5 (coolercontrold). Covers fan curves and profiles (Graph/Fixed/Mix/Overlay), functions (hysteresis, delay, step size), custom sensors (mix/time-average), modes (Silent/Gaming presets), alerts, noise-vs-temperature tuning from live readings, the split with OpenRGB for RGB lighting, and troubleshooting ("fan doesn't react", "stuck at 100%", "pump", "0 rpm", "nct6799", "pwm_enable", "coolercontrold failed", "GPU fans"). Use it even when the user doesn't say "CoolerControl", e.g. "blæserne larmer", "gør den mere stille i idle", "lav en blæserkurve", "pumpen", "CPU'en bliver for varm", "radiatorblæserne", "fan curve", "RGB-lyset", because changes must go through the daemon's REST API with a token (hand edits to /etc/coolercontrol are overwritten while the daemon runs), one profile here drives several fans at once, the pump may only run at 44 % or 78 % (it whines in between), and RGB is owned by OpenRGB, not CoolerControl.
---

# CoolerControl (this machine)

CoolerControl **5.0.1** (`coolercontrold.service`, system unit, enabled). The daemon serves the web UI and REST API at **https://localhost:11987** (self-signed TLS). Its child process `coolercontrol-liqctld` (command line shows as `python3 -q`) is the embedded liquidctl bridge used for the ASUS Aura LED Controller.

Hardware: Ryzen 7 7800X3D (k10temp, Tjmax 89 °C, runs hot by design; 80-85 °C under all-core load is normal) and RTX 4090 (target temperature 84 °C per the driver, max 90 °C; above ~84 °C GPU Boost gives up clock bins). Water cooling (topology: see `$S topology`): the **pump is on a motherboard fan header** and radiator/case fans are on the **nct6799** Super-I/O chip (ASUS board, `nct6775` module).

## Get the real state first

The map below is a starting point, not the ground truth. Run this before reasoning about anything:

```bash
S=~/.claude/skills/coolercontrol/scripts/cc.py
$S show     # devices, which channel uses which profile, curves, functions, custom sensors, modes, alerts
$S live     # current temps + duty/RPM per channel (via API with token, else sysfs + nvidia-smi)
```

`show` parses `/etc/coolercontrol/config.toml` + `overrides.toml`. Both are world-readable, so it works without root or a token. It reflects what the daemon last saved.

Snapshot of the setup (2026-09-27):

| Channel (nct6799) | Label | Profile | Notes |
|---|---|---|---|
| fan2 | Top | Radiators | radiator fans |
| fan3 | **Pump** | Pump (Graph: 44 % below 60 °C, jumps to 78 % above, function "Pump: spring over 44-78 %") | ~2490 / ~3840 rpm; whines in between (see rules) |
| fan4 | Side | Fans (Overlay: Radiators −5 at 35 %, growing to −15 from 75 %) | |
| fan5 | Bottom | Radiators | |
| fan1/6/7 | — | disabled in CC | nothing connected (0 rpm), left to BIOS |

- **Radiators** (Graph) reads custom sensor **sensor1 "cpu-gpu-mix"** = Max(5 s time average of CPU `temp1`/**Tctl**, 5 s time average of GPU temp). The user switched sensor2 from Tccd1 to Tctl on 2026-09-27; Tctl reads ~5-8 °C higher, so sensor values in reports from before 19:05 that day aren't comparable. Curve (since 2026-09-27 19:24, shifted +5 °C for Tctl) `[[0,35],[55,35],[65,45],[73,60],[79,80],[82,100]]`. Measured in `gamelike`: idle 35 % / game 62 %, CPU 72.6 °C with 13 °C margin; the old one was a flat 72 % up to 50 °C (undo files in `~/.local/state/coolercontrol-skill/proposals/20260927-quiet/`). Function "Function for Radiators" (Standard, hysteresis 4 °C, 10 s response delay in both directions (`only_downward: false`), threshold hopping on; checked 2026-10-03).
- **The chain matters:** Radiators drives Top and Bottom directly and **Side through the Fans overlay**. Editing Radiators moves three fans. To change one fan alone, give it its own profile and don't edit the shared one. Say this out loud when you propose a change.
- **Custom loop with CPU and GPU (4090 water block):** recorded 2026-09-27, `topology.json`. Every radiator fan cools both, which is why Radiators follows `cpu-gpu-mix`.
- RTX 4090 fan channels are **disabled in CC** on purpose. The card is water-blocked, so its fan headers are unused and it reports 0 %. The NVMe drives are disabled as devices too.
- No modes and no alerts exist yet.
- Temperature names are what the API and profiles use, not the sysfs labels. CPU device: `temp1` = Tctl, `temp3` = Tccd1. GPU: `GPU Temp`, `GPU Temp Hotspot`. The nct6799 temps (`temp1`..`temp13`) are motherboard sensors. Several read nonsense (0 °C, 14 °C, 18 °C), so don't build curves on them.

## Cooling topology: ask once, before advising on curves

What a fan should follow depends on what it cools, and that can't be seen from sensors. Run `$S topology`. If it says "not recorded yet", **ask the user** before proposing curves, sensors or stress tests:

1. Is the machine air cooled or water cooled?
2. If water cooled: is the GPU in the loop with the CPU, or is only the CPU water cooled?

Store the answer with `$S topology water --gpu-in-loop`, `$S topology water --gpu-air` or `$S topology air`. It lives in `~/.config/coolercontrol-skill/topology.json`, so the question is asked only once per machine. The reports print the matching advice. What follows from it:

- **CPU and GPU in one loop:** it's safe to assume that every radiator fan cools both. The radiator curves should follow the hotter of the two, like the existing `cpu-gpu-mix` sensor (max of the 5 s averages). Testing needs CPU **and** GPU load: `stresstest` only loads the CPU, so also `record` during a game or GPU benchmark.
- **Only the CPU water cooled:** the radiator fans follow the CPU. The GPU runs on its own fans (firmware curve), and case fans help it only indirectly. A mix sensor that includes the GPU would spin the radiators up for heat they don't carry.
- **Air cooled:** the CPU cooler fan follows the CPU. Case fans follow the hotter of CPU and GPU.

If the recorded answer contradicts the setup (e.g. "CPU only" but the radiators follow `cpu-gpu-mix`), point it out and suggest the fitting sensor instead of silently changing it.

## Access: who am I, and what can I do?

Check `id -u` first. Sessions run either as **enzord** (UID 1000, no passwordless sudo) or as **root**.

| Action | enzord | root |
|---|---|---|
| `cc.py show`, read config.toml, sysfs, `journalctl -u coolercontrold` | yes | yes |
| REST API changes | with token | with token |
| `coolercontrold check / backup / restore / detect` | no ("must be run with root") → give the user the `sudo` line | yes |
| Hand-edit `/etc/coolercontrol/*` | no | only with the daemon stopped (see below) |
| Write to `/sys/class/hwmon/*/pwm*` | no | **don't**: the daemon overwrites it every poll, and fighting it is confusing |

**Changes go through the REST API.** The daemon owns its config files and rewrites them. An edit made while it runs is silently lost, and a UI change can also overwrite your hand edit. The API applies changes live and persists them.

### The token

`cc.py` reads a bearer token from `$CC_TOKEN` or `/home/Enzord/.config/coolercontrol-skill/token` (the same path for root). Run `cc.py token` to see whether one exists and works.

If none exists, stop and ask the user to create one. Instructions to give the user:

1. Open the CoolerControl UI → **Access Protection** → *Create Token*. Label it `claude`, turn **Write Access** on (off = read-only, enough for `live`/`snapshot`), optionally set an expiry.
2. Copy the token (it's shown once), then in your own terminal: `mkdir -p ~/.config/coolercontrol-skill && (umask 077; wl-paste > ~/.config/coolercontrol-skill/token)`

Suggest the terminal route rather than asking for the token in chat: anything pasted into the conversation stays in the session log. If the user pastes it anyway, save it with `umask 077` to the path above, don't repeat it back, and carry on.

Until a token exists you can still analyse (`show`, `live` via sysfs) and prepare the exact JSON you'd send, so the user only has to approve.

**Never open the desktop app's settings, not even with grep or a filter:** `~/.config/org.coolercontrol.CoolerControl/CoolerControl.conf` and `~/.local/share/org.coolercontrol.CoolerControl/`. They hold the app's own API token and session cookie in plain text, and any read prints them into the session log (this happened in testing). The same goes for `/etc/coolercontrol/.passwd` and `.tokens`. Everything you'd want from that file is known already:
- The desktop app `coolercontrol` is **not autostarted**. It isn't in `~/.config/hypr/` or any XDG autostart; the user opens it by hand. Check with `pgrep -x coolercontrol`.
- That app config lives in `~/dotfiles` via a stow symlink and is tracked, but a **git clean filter** (`.githooks/strip-coolercontrol-secrets`, set up via `.gitattributes` + `install.sh`) strips `networkCookies` and the `[daemonAccessTokens]`/`[daemonAccessTokenIds]` sections on stage. A pre-commit hook blocks any `cc_…` token or cookie that slips through. Committing it is safe; don't bypass the filter or the hook (`--no-verify`).
- Alert **desktop notifications are shown by that app**, so they only appear while it runs. The daemon still evaluates alerts, and `shutdown_on_activation` works without the app. If the user wants reliable notifications, offer to autostart it in the tray. Wire it into Hyprland via the hyprland skill (`hl.exec_cmd`), and let the user toggle "start in tray" in the app's own settings dialog rather than editing its config file.

## Making a change: the workflow

1. **`cc.py show` + `cc.py live`.** Know which channels the target profile/function feeds, and the current temps/duties.
2. **`cc.py snapshot <short-label>`** before any write. It saves the API objects and config files to `~/.local/state/coolercontrol-skill/snapshots/<time>-<label>/`, so you can undo.
3. **GET, modify, send back the whole object.** `PUT /profiles`, `PUT /functions` and `PUT /custom-sensors` replace the object with the same `uid`/`id`, so send every field, not a diff. Start from the object exactly as `GET` returns it. The API **omits unset fields** (an Overlay has no `temp_source`, a Fixed has no `speed_profile`), so don't add `null`s or fields copied from config.toml or from another profile type. Change only what the task needs. Build the JSON in a file and pass it as `@file.json`. `cc.py api` validates the JSON locally before sending.
   ```bash
   $S api GET /profiles > /tmp/p.json      # pick out the one profile, edit it
   $S api PUT /profiles @radiators.json
   ```
4. **Verify.** Wait roughly 20 s: the 5 s time average plus the Radiators function's 10 s response delay mean the effect isn't instant (the pump function waits 15 s). Then run `cc.py live` again and show before/after duty and RPM for every affected channel. Check that the pump RPM is unchanged unless the pump was the target.
5. **Report** what changed, which fans it affects, and how to undo (the snapshot path + the PUT that restores it). For curve changes, show the `cc.py plot` chart (see Tuning) in the proposal.

Full endpoint list and JSON shapes: **`references/api.md`**. Read it before your first write in a session.

## Rules that protect the hardware

- **The pump has two quiet points, 44 % and 78 %. Everything in between whines.** The user reported on 2026-09-27 that the pump is high-pitched from 44 % to 78 %. 44 % is also the lowest acceptable flow, since at 44 % it already moves little water. So:
  - never set the pump below 44 %, and never leave it anywhere in 44-78 %;
  - a pump curve must **jump** between 44 and 78. The profile curve alone would interpolate through the band. Pair it with a Standard function whose `duty_minimum` (smallest change applied) is 30, so targets in 45-74 % are ignored, with `threshold_hopping: false` (otherwise CoolerControl forces the in-between value after ~30 s) and a response delay so short spikes don't toggle it;
  - above 78 % is untested for noise, so ask before using it;
  - never "Unmanaged", 0 %, or a function that can reach below 44. "Quieter" means the fans, or the 44 % state at idle, never a value inside the band.
- **Pump RPM:** after its calibration CoolerControl's pump duty isn't raw PWM ("44 %" = 54 % raw ≈ 2490 rpm, "78 %" = 81 % raw ≈ 3800-3850 rpm). `cc.py plot` estimates RPM from duty→rpm pairs measured in earlier test runs.
- **Curves must end at 100 %** at a temperature below the components' danger zone (the current Radiators curve hits 100 % at 82 °C on the mix sensor). Don't flatten the top end to cut noise. Take noise out of the idle and mid range instead, where it's actually heard.
- **Duty floors on radiator fans.** Many fans stall below 20-30 % duty. After you lower a floor, check `live`: RPM must not be 0.
- A **Graph** curve is `[[temp °C, duty %], …]`, ascending in temperature. Keep `temp_min`/`temp_max` consistent with the first and last point.
- Before changing any sensor source, confirm with the user whether a component is known to run hot (the 7800X3D does).

## Tuning for noise vs. temperature

Work from measurements, not guesses. The daemon keeps about an hour of 1 s history: `POST /status {"all": true}` (read-only) shows where the sensors actually sit during normal use, not just this second. Replay a proposed curve against it ("average duty would drop from 72 % to about 42 %"). If the hour holds no gaming, say so, and ask the user to run a typical load (a game, a compile) while you sample, or use CoolerControl's built-in stress tests (`/stress-test/cpu|gpu`, see api.md) with their OK. Useful levers, roughly from least to most invasive:

- Lower the flat idle plateau (currently 35 % up to 55 °C on Radiators; Side runs ~30 %) toward the lowest level that doesn't stall.
- Raise the function's `deviance` (hysteresis) or `response_delay` to stop audible up/down "breathing".
- Adjust the Side overlay offset (currently −5 → −15) to rebalance side vs. radiator fans without touching the curve.
- Modes (e.g. "Silent" / "Gaming") let the user switch whole setups with one click: a mode stores every channel's current setting.

Explain the trade-off in °C and in noise (duty/RPM) terms, propose concrete points, and apply only after the user agrees.

**Show curves as a chart, not a table.** The user asked for this, and has said text/ASCII charts are useless. Write the proposed profile object(s) to JSON files (start from `GET /profiles`, change only the points; keep `-undo.json` copies of the originals), then run:

```bash
$S plot Radiators Fans --new radiators.json --new fans.json --mark 42.5:Tomgang --mark 67:Spil --mark 75:"Tung last"
```

It writes an HTML page (`~/.local/state/coolercontrol-skill/plots/`) and opens it. For each profile it shows duty against the profile's sensor, now (dashed) vs. proposed, the channels it drives (overlays included), and the measured operating points (`--mark TEMP:label`, taken from test reports) as vertical guides with the duty at each. The hover tooltip and a table give duty plus RPM estimated from the fan calibration. Use real measured sensor values for the marks. In your reply, give the path and a short summary (idle / game / heavy load: now → proposed, and what stays the same at the top).

## Verifying curves under load (stress tests)

Don't guess whether a curve works under load. Measure it:

```bash
$S limits                                   # safe limits for this CPU/GPU and where they come from
$S stresstest                               # CPU step test with stress-ng: idle → 25/50/75/100 % → cooldown (~8 min)
$S stresstest --steps 50,100 --step-secs 120 --cooldown 90
$S record 10m                               # just watch; the user creates the load (game, benchmark, CoolerControl's GPU test)
$S scenario                                 # list realistic scenarios: encode, nvenc, heatsoak
$S scenario heatsoak --yes                  # CPU 100 % + GPU render: 10 min, extended while still warming
$S scenario game --yes                      # real game engine: Superposition 4K fullscreen, 15 min (takes over the screen)
```

**`stresstest` and `scenario` only print the plan unless `--yes` is given.** Add `--yes` only after the user has said yes to that specific test and its length. A test once ran by accident when a GPU tool had been installed in the meantime. Every load program runs under `timeout`, so it stops on its own even if `cc.py` is killed. The whole process tree is killed at the end of each phase.

Scenarios (idle 1 min → load 10 min → cooldown 2 min). **The load extends itself** a minute at a time while the curve's sensor still rises more than 0.3 °C/min over the last 2 min, up to `--max-minutes` (20). So a run ends when the loop has settled, not after a guessed time. The user judged 10 min enough. In the first heat-soak the sensor still rose ~1.3 °C/min at minute 4, so let the extension decide rather than hard-coding longer runs:
- `encode`: SVT-AV1 4K software export via ffmpeg (~13 of 16 threads), GPU idle. CPU-heavy video work.
- `nvenc`: NVENC + CUDA scaling export (~80 W GPU, a few cores). Realistic GPU export, but light on heat.
- `render`: Blender Cycles on OptiX with a procedural scene (`scripts/blender_load.py`; ~99 % GPU, ~260 W, one CPU core). A realistic 3D render.
- `heatsoak`: stress-ng on all cores plus the Blender GPU render (~260 W). The heaviest *realistic* mix (render while encoding).
- `burn`: stress-ng plus `gpu_burn` (FP32, ~445 W; `-d` doubles only reach ~125 W on GeForce). An extreme synthetic torture test, far denser than games or renders. Only run it when the user asks for it by name, and don't draw conclusions about real use from it (the user considers it too aggressive to be representative).
- `game`: Unigine Superposition, 4K Optimized preset, fullscreen 3840×2160 on the 4K screen (default 15 min). A real game engine, ~370-390 W GPU, light CPU. **It takes over the screen for the whole run, so say so when asking.** It needs the user's graphical session (run as enzord, not root). `superposition_cli` is Pro-only, but the engine binary `/opt/unigine-superposition/bin/superposition` accepts the launcher's arguments directly, even in the free Basic edition (`superposition_cmd()` in cc.py). `-mode 0` runs the ~3 min benchmark sequence and then keeps rendering the last scene at the same power until killed, which makes it a steady load. The interactive Game modes (`-mode 1`/`3`) idle at ~70 W without input, so they're useless unattended. The engine logs to `~/.Superposition/log.html` ("Benchmark running" / "Benchmark stopped"). (Its AUR package installed `/opt/unigine-superposition` root-only. The user fixed that with `chmod -R a+rX` on 2026-09-27.)
  First run, 2026-10-03, 15 min at 365-387 W: GPU core max 64 °C, hotspot max 102 °C (Δ ~36 °C, 0.099 °C/W, on the known line), CPU Tctl 62-67 °C (it, not the GPU, drives `cpu-gpu-mix` in games), mix sensor 66-67 °C and still rising ~0.3 °C/min at the end. Radiators 47 % / ~1110 rpm, Side 39 %, pump 78 % from minute 5½ with 0 samples in 45-77 %. A 16 s pump blip 44→78→44 at load start came from a CPU spike while the scene loaded. Report: `runs/20261003-104935/`.
- `gamelike`: Blender OptiX render + stress-ng on 6 threads at 50 %. A synthetic game profile (GPU high, CPU mid). Prefer `game` when the screen can be taken over.
- Other real games: the user starts them (a game's built-in benchmark) and you run `record 20m` alongside.

Both commands save every second's readings as `samples.csv` (+ `meta.json`) in `~/.local/state/coolercontrol-skill/runs/<time>/`. At the end they build **`graph.html`** and open it in the browser. The page has:
- tiles for CPU/GPU max against their limits, pump RPM stability, and how many fans followed their curve,
- three time charts on a shared time axis with a crosshair tooltip: temperatures with the stop limits, fan duty with the curve's expected value dashed, and RPM,
- a table per phase with the steady-state values (the last 30 s, so hysteresis and the 5 s average have settled) and ✓/✕ per fan.

**Live status:** the report opens in the browser a few seconds after a test starts and reloads every 5 s, with a status bar showing phase, time, progress, the current temperature rise and whether the load will extend. When the run ends, the same page turns into the final report. `$S graph [run dir]` rebuilds and reopens a report (default: the latest). In your reply, give the path to `graph.html` and the verdicts. Don't paste charts as text: the user has said ASCII charts are useless.

- **Limits** (`scripts/limits.py`) come from the hardware/driver first: Intel `coretemp` TjMax, `amdgpu` crit, NVIDIA's HW thermal-slowdown flag. Then vendor spec tables: AMD Ryzen 7000 X3D 89 °C (this 7800X3D), Ryzen 9000/7000/8000G 95, Ryzen 5000 90, Intel 100/105, RTX 40 90 °C. Then conservative defaults. The stress test **stops itself** at limit − 3 °C, on NVIDIA HW thermal slowdown (the card's emergency throttle), when the pump drops below 1000 rpm, when a driven fan reads 0 rpm, or when a CoolerControl fan calibration starts. It won't start during a calibration either: a calibration sweeps the fans and runs the pump low on purpose, so curve checks would be meaningless and full load would be unsafe.
- **NVIDIA "thermal" flags:** on RTX cards, SW thermal slowdown (T.Limit headroom ≈ 0) only means GPU Boost can't clock higher because of temperature. That doesn't have to mean the card is throttling or losing performance: it's normal boost behaviour, not a danger signal (the user pointed this out after the first heat-soak stopped on it at a 66 °C core). It's logged and shown as "boost limited by heat". The card's real protection is HW thermal slowdown and then shutdown, and only HW slowdown and the temperature limits stop a test. Don't read a SW-slowdown blip as "the GPU is too hot". Look at core temperature, T.Limit headroom and whether clocks and power sag over time.
- **GPU hotspot:** CoolerControl exposes `GPU Temp Hotspot` (nvidia-smi doesn't on Linux). The reports log it and show the typical hotspot−core difference under load, plus °C per watt. Observed on 2026-09-27: idle Δ 8 °C, `gamelike` at ~257 W Δ ~24 °C, `gpu_burn` at ~445 W Δ ~44 °C (hotspot 110 °C). On 2026-10-03, `game` at ~367 W: Δ ~36 °C (hotspot max 102 °C). The Δ scales roughly linearly with power (~0.09-0.10 °C/W). The user doesn't think it's the GPU or the water block. The earlier "bad contact" read came from the synthetic burn, which they consider too aggressive. Treat the Δ as an observation to track over time, not a diagnosis. Don't push repasting, and don't try to fix it with fan curves (radiator airflow doesn't change die-to-block Δ).
- **Ask before running `stresstest` or a `scenario`.** They load the machine for many minutes, so it's the user's call (see `--yes` above). `record` only watches, but it can't stop a load it didn't start. It prints a loud warning instead.
- **GPU load:** `stress-ng` can't load a 4090 meaningfully. CoolerControl's own GPU stress test (`/stress-test/gpu`) rejects API tokens (401): it needs the admin login in the UI. So for the GPU side use `scenario game` (Superposition, with the user's OK), `render`/`gamelike` (Blender), or ask the user to start a game or the UI's GPU stress test and run `record` alongside.
- The step test is what catches mid-range noise problems. Full load jumps straight past the 50-70 °C part of the curve where noise is heard. Use partial loads (`--steps`) to land on the part of the curve you changed.

## RGB lighting belongs to OpenRGB

**The general rule (from the user):** if another program already controls the LEDs and CoolerControl can't take over *all* of the lighting devices, stay with that program. That way lighting is set in exactly one place. Splitting it (some devices in CoolerControl, the rest elsewhere) means two places to configure and two programs fighting over shared controllers. Only suggest moving lighting to CoolerControl if it can drive every lit device (check `GET /devices` for which ones have `lighting_modes`) *and* the user asks for it.

**OpenRGB controls the lighting on this machine, deliberately.** It drives the motherboard (ASUS Aura), RAM and GPU from one profile. Don't move lighting to CoolerControl, even though CoolerControl also sees the Aura controller (liquidctl, channels `led1`..`led4` + `sync`) and could set it. Two programs writing to one HID controller fight, and the user wants OpenRGB in charge. Leave CoolerControl's Aura lighting settings empty (`GET /devices/<aura uid>/settings` → `[]`, as today).

What that means in practice:
- OpenRGB 1.0 is autostarted from `hyprland.lua` (~line 29): `openrgb --startminimized --profile default`. The profile lives in `~/.config/OpenRGB/profiles/default.json` (under `~/dotfiles` via stow).
- **Colour changes go through the OpenRGB GUI.** The instance running in the tray has no SDK server (port 6742 closed), so `openrgb --client …` can't reach it. A second `openrgb --device … --mode …` would start its own detection next to the running instance and fight it. Open the window, set mode/colour, and **Save Profile → `default`** so it survives a reboot. If the user wants CLI/scripted control, they can enable the SDK server in OpenRGB's settings. After that, `openrgb --client --device … --mode static --color FF0000` talks to the running instance (check the device index with `--client -l`).
- **"The lights keep cycling colours"**: the `default` profile addresses the board by hidraw path (`/dev/hidraw15` when saved). The Aura controller has since moved (`/dev/hidraw17` on 2026-09-27), so the profile doesn't reach the board and it falls back to its firmware rainbow. The profile also still lists the old RAM (Dominator; now Vengeance RGB DDR5). The fix is to re-save the profile from the GUI while the current devices are detected. That refreshes the stored locations. Back up `default.json` first. It isn't a CoolerControl change.
- Only suggest CoolerControl lighting if the user explicitly wants to drop OpenRGB. Then OpenRGB's autostart has to go too (hyprland skill), otherwise they fight. The API details are in api.md.

## Hand-editing config (root only, last resort)

For cases the API can't cover, or a broken config that stops the daemon from starting:

```bash
coolercontrold backup                       # rotated backup, keeps 10
systemctl stop coolercontrold
$EDITOR /etc/coolercontrol/config.toml       # overrides.toml (labels) is meant for hand edits
coolercontrold check                        # validate before starting
systemctl start coolercontrold && journalctl -u coolercontrold -b -n 30 --no-pager
```

As enzord, give the user these lines to run in their own terminal (or with the `! ` prefix in this prompt).

## Troubleshooting

See **`references/troubleshooting.md`** for daemon failures, fans that don't react, pwm_enable values, hwmon renumbering, suspend/resume, GPU fan control and liquidctl/RGB issues. The first three commands for almost any problem:

```bash
systemctl status coolercontrold --no-pager
journalctl -u coolercontrold -b --no-pager | tail -50
$S live
```
