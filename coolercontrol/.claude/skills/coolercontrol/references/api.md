# CoolerControl 5.0.1 REST API (this machine)

Base `https://localhost:11987`, self-signed TLS, auth `Authorization: Bearer cc_…`. Use `scripts/cc.py api METHOD PATH [JSON|@file|-]`, which handles TLS, the token and JSON validation. `GET /handshake` and `GET /health` work without auth.

Derived from the web UI bundle the daemon ships (the UI is the reference client). The GET response shapes were verified against the live daemon on 2026-09-27; writes were verified with a POST + DELETE of a throwaway function: create/update/delete return **HTTP 200 with an empty body** (`null`), a client-generated UUID `uid` on POST is accepted, and the daemon persists to config.toml itself. Other write bodies come from the UI code. **GET responses omit unset fields**, so the JSON examples below list every possible field. A real object only carries the ones that apply to its type. Mirror what GET returns and don't add `null`s. After every write, GET again or run `cc.py live` to confirm.

## Contents
- Reading state
- Profiles
- Functions
- Custom sensors
- Assigning a profile / manual speed to a channel
- Modes
- Alerts
- Lighting (Aura / liquidctl)
- Device & channel settings, labels
- Stress tests, logs, misc

## Reading state

| Call | Returns |
|---|---|
| `GET /devices` | all devices with uid, name, type, channel capabilities (`speed_options`, `lighting_modes`, …) |
| `POST /status {}` | (verified) latest reading per device: `devices[].{uid,type,type_index,status_history[-1].{temps[].{name,temp}, channels[].{name,duty,rpm,…}}}` |
| `POST /status {"all": true}` | full history (large, slow) |
| `GET /devices/{uid}/settings` | per-channel settings (`profile_uid` / `speed_fixed` / `lighting` / `pwm_mode`) |
| `GET /devices/health`, `GET /health` | health checks |
| `GET /logs` | daemon log text |
| `GET /settings`, `GET /settings/devices`, `GET /settings/overrides` | global settings, per-device enable/disable, labels |

Sensor polling is 1 s. Don't poll `/status` faster than that.

## Profiles

`GET /profiles` → `{"profiles":[…]}` (verified). `POST /profiles` creates (send your own new UUID as `uid`). `PUT /profiles` updates by `uid` (send the **whole** object). `DELETE /profiles/{uid}`. `POST /profiles/order {"profiles":[…]}` sets the UI order. Profile `uid "0"` is the built-in "Unmanaged" (Default); don't touch it.

```json
{
  "uid": "3fe06857-54d1-4e2c-8001-cade3fd8322e",
  "name": "Radiators",
  "p_type": "Graph",                         // Default | Fixed | Graph | Mix | Overlay
  "speed_fixed": null,                       // Fixed: duty %
  "speed_profile": [[0.0,72],[50.0,72],[70.0,75],[78.0,100]],   // Graph: [temp °C (1 decimal), duty % (int)]
  "temp_source": {"temp_name": "sensor1", "device_uid": "19e098e3…"},  // Graph: what it reads
  "temp_min": 0.0, "temp_max": 78.0,
  "function_uid": "0ead43c6-…",              // "0" = Default (Identity) function
  "member_profile_uids": [],                 // Mix / Overlay: the profiles it's built from
  "mix_function_type": null,                 // Mix: Min | Max | Avg | Diff | Sum
  "offset_profile": []                       // Overlay: [[input duty %, offset %], …] (ints)
}
```

Overlay semantics, verified on this machine: "Fans" = Radiators with `offset_profile [[50,-15]]`. With Radiators at 72 % the Side fan runs 57 %, so a single point acts as a flat offset. With several points the offset is interpolated between them across the member's output duty.

`POST /profiles/generate` is the UI's "auto-create" wizard (assign channel kinds like `CaseIntake`/`AioPump`/`CpuCooler` + preset `Silent|Balanced|Performance`). It creates a whole set of new profiles, so only use it if the user asks for auto-generated profiles.

## Functions

`GET /functions` → `{"functions":[…]}`, `POST /functions` (create), `PUT /functions` (update whole object), `DELETE /functions/{uid}`, `POST /functions/order`. Function `uid "0"` = built-in Identity.

```json
{
  "uid": "0ead43c6-2e8b-4292-a440-ea06c7e40bfe",
  "name": "Function for Radiators",
  "f_type": "Standard",               // Identity (step limits only) | Standard (step limits + hysteresis)
  "duty_minimum": 2,                  // smallest change applied (%); smaller changes are ignored
  "duty_maximum": 100,                // largest change per update (%)
  "step_size_min_decreasing": 2,      // asymmetric step sizes for ramping down (0 = same as up)
  "step_size_max_decreasing": 100,
  "response_delay": 10,               // seconds a change must persist before it's applied
  "deviance": 4.0,                    // hysteresis: °C the temperature must move before re-evaluating
  "only_downward": false,             // true = hysteresis/delay only when cooling down; ramp-up is immediate
  "threshold_hopping": true,          // after ~30 s unchanged, bypass limits so fans reach target
  "bypass_min_at_extremes": false     // always allow jumping to 0 % / 100 %
}
```

`duty_minimum`/`duty_maximum` are **step sizes**, not a fan speed floor/ceiling. A speed floor goes in the profile curve.

## Custom sensors

`GET /custom-sensors` → `{"custom_sensors":[…]}` (note the underscore), `POST` (create), `PUT` (update whole object), `DELETE /custom-sensors/{id}`. They appear as temps on the device "Custom Sensors" (uid `19e098e3…`), `temp_name` = the sensor `id`.

```json
{
  "id": "sensor1",
  "cs_type": "Mix",                   // Mix | TimeAverage | File | Offset (GET an existing one if unsure)
  "mix_function": "Max",              // Min | Max | Avg | Diff | Sum (Mix)
  "time_window_seconds": null,        // TimeAverage
  "offset": null,
  "file_path": null,                  // File: reads a temperature from a file
  "sources": [{"temp_source": {"temp_name": "sensor2", "device_uid": "19e098e3…"}, "weight": 1}],
  "children": [], "parents": []       // dependency info filled in by the daemon
}
```

## Assigning a profile / manual speed to a channel

```
PUT /devices/{device_uid}/settings/{channel}/profile   {"profile_uid": "<uid>"}
PUT /devices/{device_uid}/settings/{channel}/manual    {"speed_fixed": 60}
PUT /devices/{device_uid}/settings/{channel}/reset     (no body; back to unmanaged/hardware control)
PUT /devices/{device_uid}/settings/{channel}/pwm       {"pwm_mode": 0|1}   (DC vs PWM, hwmon)
```

nct6799 device uid: `00a4da18625f56275c89e2fcd25a83c08c5ad3326452fa7e252fcc8a89c92493`, channels `fan2`..`fan5`. Get uids from `cc.py show` or `GET /devices`. Don't copy them from memory.

## Modes

A mode stores all channels' settings under a name and restores them on activation.

| Call | Effect |
|---|---|
| `GET /modes` | `{"modes":[{uid,name,device_settings:[…]}]}` |
| `GET /modes-active` | `{"current_mode_uid": …, "previous_mode_uid": …}` |
| `POST /modes {"name":"Silent"}` | create a mode (from the current settings); check the result with GET |
| `PUT /modes {uid,name,…}` | rename/update |
| `PUT /modes/{uid}/settings` | overwrite the mode with the **current** live settings |
| `POST /modes/{uid}/duplicate`, `DELETE /modes/{uid}`, `POST /modes/order` | |
| `POST /modes-active/{uid}` | activate |

Workflow for a new mode: snapshot → set the channels the way the mode should be → `POST /modes` → switch back → verify both modes by activating them.

## Alerts

`GET /alerts` → `{"alerts":[…], "logs":[…]}` (logs = fired/recovered history), `POST /alerts` (create), `PUT /alerts` (update), `DELETE /alerts/{uid}`.

```json
{
  "uid": "<new uuid>", "name": "CPU hot",
  "channel_sources": [{"device_uid": "31afea3c…", "channel_name": "temp3", "channel_metric": "Temp"}],   // CPU temp3 = Tccd1
  "channel_source":  {"device_uid": "31afea3c…", "channel_name": "temp3", "channel_metric": "Temp"},
  "min": 0, "max": 90,                 // fires outside [min, max]; metric Temp|Duty|Load|RPM|Freq
  "warmup_duration": 5,                // seconds out of range before firing
  "cooldown_duration": 0, "repeat_interval": 0,
  "enabled": true, "desktop_notify": true, "desktop_notify_recovery": true,
  "desktop_notify_audio": false, "shutdown_on_activation": false
}
```

A pump-failure alert is a good use: metric `RPM` on nct6799 `fan3`, `min` ~2000. Never set `shutdown_on_activation` without the user's explicit consent.

## Lighting (Aura / liquidctl)

> Not used on this machine: OpenRGB owns the lighting (see SKILL.md). This is only for the case where the user explicitly moves lighting to CoolerControl.

ASUS Aura LED Controller: device uid `f226946857a3…` (type Liquidctl), channels `led1`..`ledN` (plus possibly `sync`). `GET /devices` → `devices[].info.channels.<ch>.lighting_modes[]` gives `{name, frontend_name, min_colors, max_colors, speed_enabled, backward_enabled}`. Verified Aura mode names: `off`, `static`, `breathing`, `flashing`, `spectrum_cycle`, `rainbow`, `spectrum_cycle_breathing`, `chase_fade`, … (list them for the channel you're changing). Apply with:

```
PUT /devices/{device_uid}/settings/{channel}/lighting
{"mode": "static", "colors": [[0,255,255]]}
```

Use `name` (not `frontend_name`), send between `min_colors` and `max_colors` colours as `[r,g,b]`, and include `speed`/`backward` only if that mode enables them.

## Device & channel settings, labels

- `PUT /settings/devices/{uid}` `{…"disable": true|false, "channel_settings": {"fan1": {"label":"fan1","disabled":true}}}`: enable/disable a whole device or channels (e.g. to let CC control the RTX 4090 fans again). GET first.
- `PUT /settings/devices/{uid}/channels/{channel}/overrides {"label":"Top"}`: rename a channel (stored in overrides.toml).
- `PUT /settings/devices/{uid}/overrides {"name":"…"}`: rename a device.
- `PATCH /settings {…}`: global settings (poll_rate, apply_on_boot, …); send only changed fields.

## Calibrations, stress tests, logs, misc

- Fan calibration (UI → channel → calibrate) sweeps one channel's duty to map RPM. `GET /calibrations/{device_uid}/channels/{ch}/status` → `{phase: in_progress|…, stage: up_sweep|…, percent, current_duty, current_rpm}`. `GET /calibrations` lists finished results. While one runs, that channel ignores its profile (the pump went down to ~7 % / 780 rpm during its sweep).

- Stress-test endpoints return **401 for API tokens** (verified 2026-09-27); they need the admin UI login. Use `cc.py stresstest` (stress-ng) or ask the user to start them in the UI.
- `POST /stress-test/cpu {"thread_count":16,"duration_secs":60,"backend":…}`, `/stress-test/gpu {"duration_secs":60,"backend":…,"gpu_id":…}`, `/stress-test/ram`, `/stress-test/drive`; `GET /stress-test` shows status/backends, `DELETE /stress-test` stops. Only run with the user's OK, and watch temps while it runs.
- `GET /logs`: the daemon log.
- `POST /shutdown`: stops the daemon (avoid; use systemctl).
