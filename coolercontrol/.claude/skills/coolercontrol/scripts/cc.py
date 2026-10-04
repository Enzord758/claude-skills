#!/usr/bin/env python3
"""CoolerControl helper for this machine.

  cc.py show                 config overview: devices, channel -> profile, profiles, functions, sensors
  cc.py live                 current temps / duty / RPM (API if a token works, else sysfs + nvidia-smi)
  cc.py snapshot [label]     save profiles/functions/sensors/modes/alerts/device settings (+ config.toml) for undo
  cc.py api METHOD PATH [JSON | @file.json | -]
                             authenticated REST call, prints the response body
  cc.py token                is a token configured, and does it work (read / write)?
  cc.py topology [water|air] [--gpu-in-loop|--gpu-air]
                             show or record how the machine is cooled (asked once, stored per machine)
  cc.py limits               safe CPU/GPU temperature limits for this hardware and where they come from
  cc.py record DURATION      sample temps/duty/rpm every second (you create the load: game, benchmark,
                             CoolerControl UI stress test), then report how the fan curves responded
  cc.py stresstest [--steps 25,50,75,100] [--step-secs 90] [--cooldown 60] [--method matrixprod] [--yes]
                             CPU step test with stress-ng + the same report; stops itself at the safe limits
  cc.py graph [RUN_DIR|samples.csv]
                             (re)build the HTML report for a run (default: the latest) and open it
  cc.py scenario [NAME] [--minutes N] [--yes]
                             realistic load: encode (CPU video export), nvenc (GPU export), render (Blender GPU),
                             gamelike (GPU high + CPU mid), heatsoak (CPU max + GPU render), burn (synthetic extreme);
                             no NAME lists them. Games/benchmarks you start yourself: use `record`.
                             stresstest/scenario only print the plan unless --yes is given
  cc.py plot PROFILE [PROFILE…] [--new file.json …] [--mark TEMP:label …]
                             HTML chart of each profile's duty vs. its sensor: now vs. proposed (profile objects
                             in the files, matched by uid/name), measured operating points, RPM from calibration

`show` needs no root and no token: /etc/coolercontrol/config.toml is world-readable.
The token is read from $CC_TOKEN or ~/.config/coolercontrol-skill/token and is never printed.
"""
import csv
import json
import os
import ssl
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("CC_URL", "https://localhost:11987")
CONF = Path("/etc/coolercontrol")
# Always the desktop user's home, also when this runs as root (root's $HOME is /root).
USER_HOME = Path("/home/Enzord")
TOKEN_FILE = USER_HOME / ".config/coolercontrol-skill/token"
SNAP_DIR = USER_HOME / ".local/state/coolercontrol-skill/snapshots"
HWMON = Path("/sys/class/hwmon")


# ---------- auth / http ----------

def token():
    t = os.environ.get("CC_TOKEN", "").strip()
    if not t and TOKEN_FILE.is_file():
        t = TOKEN_FILE.read_text().strip()
    return t or None


def request(method, path, body=None, auth=True):
    """Returns (status, parsed-json-or-text). Never raises on HTTP errors."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # daemon uses a self-signed cert on localhost
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode() if not isinstance(body, (bytes, str)) else (
            body.encode() if isinstance(body, str) else body)
        headers["Content-Type"] = "application/json"
    if auth:
        t = token()
        if t:
            headers["Authorization"] = f"Bearer {t}"
    req = urllib.request.Request(BASE + path, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except urllib.error.URLError as e:
        return 0, f"connection failed: {e.reason} (is coolercontrold running?)"
    txt = raw.decode(errors="replace")
    try:
        return status, json.loads(txt) if txt else None
    except json.JSONDecodeError:
        return status, txt


# ---------- config parsing ----------

def load_config():
    cfg = tomllib.loads((CONF / "config.toml").read_text())
    try:
        ov = tomllib.loads((CONF / "overrides.toml").read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        ov = {}
    return cfg, ov


def labels(ov):
    """{device_uid: {channel: label}} from overrides.toml."""
    out = {}
    for duid, d in (ov.get("devices") or {}).items():
        out[duid] = {ch: v.get("label") for ch, v in (d.get("channels") or {}).items()}
    return out


def src_str(ts, devnames, lab):
    if not ts:
        return "-"
    dn = devnames.get(ts["device_uid"], ts["device_uid"][:8])
    l = lab.get(ts["device_uid"], {}).get(ts["temp_name"])
    return f"{dn}:{ts['temp_name']}" + (f" ({l})" if l else "")


def cmd_show(_args):
    cfg, ov = load_config()
    devnames = cfg.get("devices", {})
    lab = labels(ov)
    profiles = {p["uid"]: p for p in cfg.get("profiles", [])}
    functions = {f["uid"]: f for f in cfg.get("functions", [])}
    settings = cfg.get("settings", {})

    print("== Devices (uid prefix  name  [disabled channels])")
    for uid, name in devnames.items():
        s = settings.get(uid, {}) if isinstance(settings.get(uid), dict) else {}
        dis = [ch for ch, v in (s.get("channel_settings") or {}).items() if v.get("disabled")]
        flag = " DISABLED" if s.get("disable") else ""
        print(f"  {uid[:12]}  {s.get('name', name)}{flag}" + (f"  [off: {', '.join(sorted(dis))}]" if dis else ""))

    print("\n== Channel assignments")
    for duid, chans in (cfg.get("device-settings") or {}).items():
        for ch, st in sorted(chans.items()):
            l = lab.get(duid, {}).get(ch)
            what = ("profile " + profiles.get(st["profile_uid"], {}).get("name", st["profile_uid"])) if "profile_uid" in st \
                else f"manual {st['speed_fixed']}%" if "speed_fixed" in st else json.dumps(st)
            print(f"  {devnames.get(duid, duid[:8])}:{ch}" + (f" ({l})" if l else "") + f" -> {what}")

    print("\n== Profiles")
    for p in profiles.values():
        t = p.get("p_type")
        line = f"  [{t}] {p['name']}  uid={p['uid']}"
        if t == "Fixed":
            line += f"  {p.get('speed_fixed')}%"
        elif t == "Graph":
            line += f"\n      source: {src_str(p.get('temp_source'), devnames, lab)}"
            line += f"\n      curve (temp C -> duty %): {p.get('speed_profile')}  range {p.get('temp_min')}..{p.get('temp_max')}"
            line += f"\n      function: {functions.get(p.get('function_uid'), {}).get('name', p.get('function_uid'))}"
        elif t in ("Mix", "Overlay"):
            mem = [profiles.get(u, {}).get("name", u) for u in p.get("member_profile_uids", [])]
            line += f"\n      members: {mem}"
            if t == "Mix":
                line += f"  mix: {p.get('mix_function_type')}"
            else:
                line += f"  offsets (input duty %, offset %): {p.get('offset_profile')}"
        print(line)

    print("\n== Functions")
    for f in functions.values():
        extra = {k: v for k, v in f.items() if k not in ("uid", "name", "f_type")}
        print(f"  [{f.get('f_type')}] {f['name']}  uid={f['uid']}" + (f"\n      {extra}" if extra else ""))

    print("\n== Custom sensors (device 'Custom Sensors')")
    for cs in cfg.get("custom_sensors", []):
        l = next((ls.get(cs["id"]) for ls in lab.values() if cs["id"] in ls), None)
        srcs = [f"{src_str(s['temp_source'], devnames, lab)} w={s.get('weight', 1)}" for s in cs.get("sources", [])]
        extra = f" window={cs['time_window_seconds']}s" if cs.get("cs_type") == "TimeAverage" else ""
        extra += f" file={cs['file_path']}" if cs.get("file_path") else ""
        print(f"  {cs['id']}" + (f" ({l})" if l else "") + f": {cs.get('cs_type')} {cs.get('mix_function')}{extra}")
        for s in srcs:
            print(f"      <- {s}")

    for fname in ("modes.json", "alerts.json"):
        try:
            data = json.loads((CONF / fname).read_text())
            key = fname.split(".")[0]
            items = data.get(key, [])
            print(f"\n== {key}: " + (", ".join(i.get("name", "?") for i in items) or "none")
                  + (f"  (active: {data.get('current_active_mode')})" if key == "modes" else ""))
        except (OSError, json.JSONDecodeError):
            pass


# ---------- live ----------

def hwmon_by_name(name):
    for h in sorted(HWMON.iterdir()):
        try:
            if (h / "name").read_text().strip() == name:
                return h
        except OSError:
            continue
    return None


def rd(p):
    try:
        return p.read_text().strip()
    except OSError:
        return None


def live_api():
    st, data = request("POST", "/status", {})
    if st != 200 or not isinstance(data, dict):
        return False
    cfg, ov = load_config()
    lab = labels(ov)
    names = cfg.get("devices", {})
    # The API exposes hwmon temps by input name; add the k10temp labels for readability.
    k = hwmon_by_name("k10temp")
    if k:
        cpu_uid = next((u for u, n in names.items() if "Ryzen" in n or "CPU" in n), None)
        if cpu_uid:
            for f in k.glob("temp*_label"):
                lab.setdefault(cpu_uid, {}).setdefault(f.stem.split("_")[0], rd(f))
    for d in data.get("devices", []):
        hist = d.get("status_history") or []
        if not hist:
            continue
        last = hist[-1]
        uid = d.get("uid")
        temps = [f"{t['name']}{'(' + lab.get(uid, {}).get(t['name']) + ')' if lab.get(uid, {}).get(t['name']) else ''}={t['temp']:.1f}C"
                 for t in last.get("temps", [])]
        chans = []
        for c in last.get("channels", []):
            bits = [x for x in (f"{c['duty']:.0f}%" if c.get("duty") is not None else None,
                                f"{c['rpm']}rpm" if c.get("rpm") is not None else None) if x]
            if bits:
                l = lab.get(uid, {}).get(c["name"])
                chans.append(f"{c['name']}{'(' + l + ')' if l else ''} " + " ".join(bits))
        if temps or chans:
            print(f"{names.get(uid, uid[:8])}:")
            if temps:
                print("   temps: " + "  ".join(temps))
            if chans:
                print("   chans: " + "  ".join(chans))
    return True


def live_sysfs():
    print("(no working token: reading sysfs/nvidia-smi directly; values are raw hardware, not CoolerControl's view)")
    cfg, ov = load_config()
    lab = labels(ov)
    k = hwmon_by_name("k10temp")
    if k:
        t = {rd(k / f"{f.stem.split('_')[0]}_label"): int(rd(f)) / 1000 for f in k.glob("temp*_input")}
        print("CPU k10temp: " + "  ".join(f"{n}={v:.1f}C" for n, v in t.items()))
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,fan.speed,power.draw",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=5).stdout.strip()
        print(f"GPU nvidia-smi (temp, own fan, power): {g}")
    except (OSError, subprocess.TimeoutExpired):
        pass
    for chip in ("nct6799",):
        h = hwmon_by_name(chip)
        if not h:
            print(f"{chip}: not found (nct6775 module loaded?)")
            continue
        duid = next((u for u, n in cfg.get("devices", {}).items() if n == chip), None)
        print(f"{chip} ({h.name}):  pwm_enable 1=manual(CC controls) 5=SmartFan IV(BIOS) 0=full")
        for f in sorted(h.glob("fan*_input"), key=lambda p: int(p.stem[3:].split("_")[0])):
            n = f.stem.split("_")[0]
            i = n[3:]
            pwm = rd(h / f"pwm{i}")
            l = lab.get(duid, {}).get(n, "")
            duty = f"{int(pwm) * 100 / 255:.0f}%" if pwm is not None else "?"
            print(f"   {n:<5}{('(' + l + ')') if l else '':<9} {rd(f):>5} rpm  duty {duty:>4}  pwm_enable={rd(h / f'pwm{i}_enable')}")


def cmd_live(_args):
    if token() and live_api():
        return
    live_sysfs()


# ---------- snapshot / api / token ----------

def cmd_snapshot(args):
    label = args[0] if args else "manual"
    d = SNAP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    if token():
        for name, path in [("profiles", "/profiles"), ("functions", "/functions"),
                           ("custom-sensors", "/custom-sensors"), ("modes", "/modes"),
                           ("alerts", "/alerts"), ("settings", "/settings")]:
            st, data = request("GET", path)
            if st == 200:
                (d / f"{name}.json").write_text(json.dumps(data, indent=2))
                saved.append(name)
        cfg, _ = load_config()
        for duid in (cfg.get("device-settings") or {}):
            st, data = request("GET", f"/devices/{duid}/settings")
            if st == 200:
                (d / f"device-settings-{duid[:12]}.json").write_text(json.dumps(data, indent=2))
                saved.append(f"device-settings-{duid[:12]}")
    for f in ("config.toml", "overrides.toml", "modes.json", "alerts.json"):
        try:
            (d / f).write_text((CONF / f).read_text())
            saved.append(f)
        except OSError:
            pass
    if os.geteuid() == 0:  # keep the user's state dir user-owned
        subprocess.run(["chown", "-R", "enzord:Enzord", str(SNAP_DIR.parent)], check=False)
    print(f"snapshot: {d}\n  saved: {', '.join(saved)}")
    if not token():
        print("  (no token: only the on-disk config files were saved)")


def cmd_api(args):
    if len(args) < 2:
        sys.exit("usage: cc.py api METHOD PATH [JSON | @file.json | -]")
    method, path = args[0], args[1]
    body = None
    if len(args) > 2:
        a = args[2]
        raw = sys.stdin.read() if a == "-" else Path(a[1:]).read_text() if a.startswith("@") else a
        body = json.loads(raw)  # validate locally before sending
    if not token():
        sys.exit(f"no token: create one in the CoolerControl UI (Access Protection -> Create Token) "
                 f"and save it to {TOKEN_FILE} (chmod 600), or export CC_TOKEN")
    st, data = request(method, path, body)
    print(json.dumps(data, indent=2) if not isinstance(data, str) else data)
    print(f"[HTTP {st}]", file=sys.stderr)
    sys.exit(0 if 200 <= st < 300 else 1)


def cmd_token(_args):
    src = "CC_TOKEN" if os.environ.get("CC_TOKEN") else str(TOKEN_FILE) if TOKEN_FILE.is_file() else None
    if not src:
        print(f"no token configured ({TOKEN_FILE} missing, CC_TOKEN unset)")
        sys.exit(1)
    if TOKEN_FILE.is_file() and TOKEN_FILE.stat().st_mode & 0o077:
        print(f"warning: {TOKEN_FILE} is readable by others; chmod 600 it")
    st, _ = request("GET", "/profiles")
    print(f"token from {src}: read -> HTTP {st}")
    if st != 200:
        sys.exit(1)
    print("(write access isn't probed; a read-only token fails the first PUT/POST with 401/403)")


# ---------- plot ----------

def interp(points, x):
    pts = sorted(points)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y1
    return pts[-1][1]


def duty_at(profile, temp, by_uid, depth=0):
    """Duty % a profile outputs at a given temperature of its (graph member's) sensor."""
    if depth > 5:
        return None
    t = profile.get("p_type")
    if t == "Fixed":
        return profile.get("speed_fixed")
    if t == "Graph":
        return interp(profile.get("speed_profile") or [], temp)
    members = [by_uid[u] for u in profile.get("member_profile_uids", []) if u in by_uid]
    vals = [v for v in (duty_at(m, temp, by_uid, depth + 1) for m in members) if v is not None]
    if not vals:
        return None
    if t == "Overlay":
        base = vals[0]
        return max(0, min(100, base + (interp(profile.get("offset_profile") or [], base) or 0)))
    if t == "Mix":
        f = profile.get("mix_function_type") or "Max"
        return {"Min": min(vals), "Max": max(vals), "Avg": sum(vals) / len(vals),
                "Sum": min(100, sum(vals)), "Diff": max(vals) - min(vals)}.get(f, max(vals))
    return None


def graph_source(profile, by_uid, depth=0):
    if profile.get("p_type") == "Graph" or depth > 5:
        return profile.get("temp_source")
    for u in profile.get("member_profile_uids", []):
        if u in by_uid:
            ts = graph_source(by_uid[u], by_uid, depth + 1)
            if ts:
                return ts
    return None


def sensor_stats(ts, history):
    """(current, lo, hi) for a temp source from the API, or Nones."""
    if not ts or not token():
        return None, None, None
    st, data = request("POST", "/status", {"all": True} if history else {})
    if st != 200 or not isinstance(data, dict):
        return None, None, None
    for d in data.get("devices", []):
        if d.get("uid") != ts["device_uid"]:
            continue
        vals = [t["temp"] for h in d.get("status_history", []) for t in h.get("temps", [])
                if t.get("name") == ts["temp_name"]]
        if vals:
            return vals[-1], (min(vals) if history else None), (max(vals) if history else None)
    return None, None, None


def cmd_plot(args):
    """HTML chart of each profile's duty against its sensor: now vs. proposed, with measured operating points."""
    names, new_files, marks = [], [], []
    it = iter(args)
    for a in it:
        if a == "--new":
            new_files.append(next(it))
        elif a == "--mark":
            t, _, lab = next(it).partition(":")
            marks.append({"t": float(t), "label": lab or ""})
        elif a == "--no-history":
            pass
        else:
            names.append(a)
    if not names:
        sys.exit("usage: cc.py plot PROFILE [PROFILE…] [--new file.json …] [--mark TEMP:label …]")
    st, data = request("GET", "/profiles") if token() else (0, None)
    profiles = data["profiles"] if st == 200 else load_config()[0].get("profiles", [])
    now = {p["uid"]: p for p in profiles}
    new = dict(now)
    for f in new_files:
        obj = json.loads(Path(f).read_text())
        for p in obj.get("profiles", [obj]) if isinstance(obj, dict) else obj:
            uid = p.get("uid") or next((u for u, q in now.items() if q["name"] == p.get("name")), None)
            new[uid or p.get("name")] = {**p, "uid": uid or p.get("name")}
    cfg, ov = load_config()
    devnames, lab = cfg.get("devices", {}), labels(ov)
    # which channels use which profile (directly, or through an overlay/mix built on it)
    users = {}
    for duid, chans in (cfg.get("device-settings") or {}).items():
        for ch, stt in chans.items():
            if "profile_uid" in stt:
                users.setdefault(stt["profile_uid"], []).append((duid, ch))
    # RPM estimates from fan calibrations, per channel
    calibs = {}
    if token():
        st, cal = request("GET", "/calibrations")
        for c in (cal.get("calibrations", []) if st == 200 and isinstance(cal, dict) else []):
            up = (c.get("calibration") or {}).get("up_curve") or []
            if up:
                calibs[(c.get("device_uid"), c.get("channel_name"))] = [[pt["duty"], pt["rpm"]] for pt in up]
    calib = None

    def measured_curve(label, since):
        """duty → rpm pairs this channel actually showed in recorded runs (CoolerControl's duty is not raw PWM
        after a calibration, so these beat the raw calibration curve). Median rpm per whole-percent duty."""
        by = {}
        for f in sorted(RUNS_DIR.glob("*/samples.csv")):
            try:
                if since and time.mktime(time.strptime(f.parent.name, "%Y%m%d-%H%M%S")) < since:
                    continue
            except ValueError:
                continue
            for r in csv.DictReader(open(f, newline="")):
                du, rp = r.get(f"{label}_duty"), r.get(f"{label}_rpm")
                if du and rp:
                    by.setdefault(round(float(du)), []).append(float(rp))
        pts = [[d, sorted(v)[len(v) // 2]] for d, v in sorted(by.items()) if len(v) >= 5]
        return pts if len(pts) >= 2 else None

    cal_time = {}
    if token():
        st, cal = request("GET", "/calibrations")
        for c in (cal.get("calibrations", []) if st == 200 and isinstance(cal, dict) else []):
            ts_ = (c.get("calibration") or {}).get("timestamp", "")[:19]
            try:
                cal_time[(c.get("device_uid"), c.get("channel_name"))] = time.mktime(time.strptime(ts_, "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                pass
    cur = None
    tmin, tmax, step = 20.0, 90.0, 0.5
    grid = [tmin + i * step for i in range(int((tmax - tmin) / step) + 1)]
    out_profiles = []
    for name in names:
        prof = next((p for p in new.values() if p["name"].lower() == name.lower()), None)
        if not prof:
            print(f"no profile named {name!r}")
            continue
        old = now.get(prof["uid"])
        ts = graph_source(prof, new) or (graph_source(old, now) if old else None)
        if cur is None:
            c, _, _ = sensor_stats(ts, False)
            if c is not None and all(abs(mk["t"] - c) > 3 for mk in marks):
                marks.insert(0, {"t": round(c, 1), "label": "Nu"})
            cur = c
        who = [f"{lab.get(d, {}).get(ch) or ch}" for d, ch in users.get(prof["uid"], [])]
        member_of = [q["name"] for q in now.values() if prof["uid"] in (q.get("member_profile_uids") or [])]
        for q in now.values():
            if prof["uid"] in (q.get("member_profile_uids") or []):
                who += [f"{lab.get(d, {}).get(ch) or ch} (via {q['name']})" for d, ch in users.get(q["uid"], [])]
        # calibration of a channel this profile drives (directly or via an overlay), else any non-pump one
        chans_of = users.get(prof["uid"], []) + [k for q in now.values() if prof["uid"] in (q.get("member_profile_uids") or [])
                                                 for k in users.get(q["uid"], [])]
        calib = next((m for k in chans_of if (m := measured_curve(lab.get(k[0], {}).get(k[1]) or k[1], cal_time.get(k)))), None) \
            or next((calibs[k] for k in chans_of if k in calibs), None)
        pn = [round(duty_at(old, t, now) or 0, 2) for t in grid] if old else None
        pp = [round(duty_at(prof, t, new) or 0, 2) for t in grid] if new_files and prof is not old else None
        rows = []
        for mk in marks:
            i = min(len(grid) - 1, max(0, round((mk["t"] - tmin) / step)))
            cell = lambda arr: "–" if arr is None else (f"{arr[i]:.0f} %" + (f" · ~{interp(calib, arr[i]):.0f} rpm" if calib else ""))
            rows.append([f"{mk['label']} ({mk['t']} °C)", cell(pn), cell(pp)])
        out_profiles.append({"name": prof["name"], "calibration": calib,
                             "who": f"Styrer: {', '.join(who) or 'ingen kanaler'} · x-akse: {src_str(ts, devnames, lab)}"
                                    + (f" · indgår i {', '.join(member_of)}" if member_of else ""),
                             "now": pn if pn else pp, "new": pp if pn else None,
                             "table": {"head": ["Driftspunkt", "Nu", "Forslag" if pp else ""], "rows": rows} if marks else None})
    data = {"title": "Blæserkurver: nu og forslag" if new_files else "Blæserkurver",
            "subtitle": "Driftspunkterne er målte sensorværdier; rpm er anslået ud fra kanalens målte duty→rpm i tidligere tests" if calibs
                        else "Driftspunkterne er målte sensorværdier",
            "tmin": tmin, "tmax": tmax, "step": step, "marks": marks, "calibration": calib, "profiles": out_profiles}
    d = USER_HOME / ".local/state/coolercontrol-skill/plots"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"curves-{time.strftime('%Y%m%d-%H%M%S')}.html"
    out.write_text((ASSET.parent / "curves.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    print(out)
    open_file(out)


# ---------- cooling topology ----------

TOPOLOGY_FILE = USER_HOME / ".config/coolercontrol-skill/topology.json"


def load_topology():
    try:
        return json.loads(TOPOLOGY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def topology_advice(t):
    if not t:
        return ("cooling topology unknown: ask the user (air or water? if water: is the GPU in the loop "
                "with the CPU?) and store it with `cc.py topology`")
    if t["cooling"] == "air":
        return ("air cooled: the CPU cooler fan should follow the CPU; case fans should follow the hotter "
                "of CPU and GPU; the GPU's own fans stay on its firmware curve")
    if t.get("gpu_in_loop"):
        return ("custom loop with CPU + GPU: every radiator fan cools both, so radiator curves should follow "
                "the hotter of the two (a max-mix sensor). Verify with CPU AND GPU load: the stress test only "
                "loads the CPU, so also run `record` during a game or GPU benchmark")
    return ("water-cooled CPU only: radiator fans should follow the CPU; the GPU is cooled by its own fans, "
            "and case fans help it only indirectly")


def cmd_topology(args):
    if not args:
        t = load_topology()
        print(json.dumps(t, indent=2) if t else "not recorded yet")
        print(topology_advice(t))
        return
    if args[0] not in ("water", "air"):
        sys.exit("usage: cc.py topology [water|air] [--gpu-in-loop|--gpu-air]")
    t = {"cooling": args[0], "cpu_in_loop": args[0] == "water",
         "gpu_in_loop": args[0] == "water" and "--gpu-in-loop" in args,
         "recorded": time.strftime("%Y-%m-%d")}
    if args[0] == "water" and not ({"--gpu-in-loop", "--gpu-air"} & set(args)):
        sys.exit("water cooling: say whether the GPU is in the loop (--gpu-in-loop) or air cooled (--gpu-air)")
    TOPOLOGY_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOPOLOGY_FILE.write_text(json.dumps(t, indent=2) + "\n")
    if os.geteuid() == 0:
        subprocess.run(["chown", "enzord:Enzord", str(TOPOLOGY_FILE)], check=False)
    print(f"saved {TOPOLOGY_FILE}\n" + topology_advice(t))


# ---------- HTML graph from a run's CSV ----------

ASSET = Path(__file__).resolve().parent.parent / "assets/report.html"


def open_file(path):
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_graph(run_dir):
    """Reads samples.csv (+ meta.json) in run_dir, writes graph.html next to them, returns its path."""
    run_dir = Path(run_dir)
    rows = list(csv.DictReader(open(run_dir / "samples.csv", newline="")))
    try:
        meta = json.loads((run_dir / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        import limits  # run recorded before meta.json existed: use today's limits
        c = limits.cpu_limit()
        meta = {"title": "Tidligere kørsel", "date": run_dir.name, "abort_margin": limits.ABORT_MARGIN,
                "cpu": {"name": c["name"], "limit": c["limit"], "source": c["source"]},
                "gpus": [{"name": g["name"], "limit": g["limit"], "source": g["source"]} for g in limits.gpu_limits()],
                "warn_margin": limits.WARN_MARGIN, "sensor": None, "channels": [], "cooling": "", "aborted": None}
    num = lambda v: float(v) if v not in ("", None) else None
    cols = rows[0].keys() if rows else []
    gcol = next((c for c in cols if c.startswith("gpu:")), None)
    chans = meta["channels"] or [{"label": c[:-5], "pump": "pump" in c.lower()} for c in cols if c.endswith("_duty")]
    D = {"t": [num(r["t"]) for r in rows], "phase": [r["phase"] for r in rows],
         "cpu": [num(r["cpu"]) for r in rows], "gpu": [num(r[gcol]) if gcol else None for r in rows],
         "sensor": [num(r.get("sensor")) for r in rows],
         "tlimit": [num(r.get("gpu_tlimit")) for r in rows], "gpupower": [num(r.get("gpu_power")) for r in rows],
         "hotspot": [num(r.get("gpu_hotspot")) for r in rows]}
    slow = [r.get("gpu_slowdown", "") for r in rows]
    for i, c in enumerate(chans):
        for kind in ("duty", "rpm", "expected"):
            D[f"c{i}_{kind}"] = [num(r.get(f"{c['label']}_{kind}")) for r in rows]
    # phases = contiguous runs of the same phase name
    phases, start = [], 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i]["phase"] != rows[start]["phase"]:
            phases.append({"name": phase_da(rows[start]["phase"]),
                           "start": D["t"][start], "end": D["t"][i - 1], "i0": start, "i1": i - 1})
            start = i
    D["phase"] = [phase_da(p) for p in D["phase"]]
    cpu, gpus, am, wm = meta["cpu"], meta["gpus"], meta["abort_margin"], meta["warn_margin"]
    # colour slots: temps 1-3 (+5 hotspot), channels 4-7 (non-pump first, pump last); fixed per entity across charts
    order = sorted(range(len(chans)), key=lambda i: chans[i]["pump"])
    slot = {i: f"--s{4 + n}" for n, i in enumerate(order[:4])}
    radiator = next((i for i in order if not chans[i]["pump"]), None)
    refs = []
    if cpu:
        refs.append({"y": cpu["limit"] - am, "label": f"CPU-stop {cpu['limit'] - am:.0f} °C", "short": f"CPU-stop {cpu['limit'] - am:.0f}"})
    if gpus:
        refs.append({"y": gpus[0]["limit"] - am, "label": f"GPU-stop {gpus[0]['limit'] - am:.0f} °C (kerne)", "short": f"GPU-stop {gpus[0]['limit'] - am:.0f}"})
    temp_series = [{"name": "CPU", "key": "cpu", "color": "--s1"}]
    if gcol:
        temp_series.append({"name": "GPU", "key": "gpu", "color": "--s2"})
    if any(v is not None for v in D["sensor"]):
        temp_series.append({"name": "Kurvens sensor", "key": "sensor", "color": "--s3"})
    if any(v is not None for v in D["hotspot"]):
        temp_series.append({"name": "GPU hotspot", "key": "hotspot", "color": "--s5"})
    duty_series = [{"name": chans[i]["label"], "key": f"c{i}_duty", "color": slot[i]} for i in order if i in slot]
    if radiator is not None and any(v is not None for v in D[f"c{radiator}_expected"]):
        duty_series.append({"name": f"Kurven siger ({chans[radiator]['label']})", "key": f"c{radiator}_expected",
                            "color": "--text-muted", "dashed": True})
    rpm_series = [{"name": chans[i]["label"], "key": f"c{i}_rpm", "color": slot[i]} for i in order if i in slot]
    charts = [{"title": "Temperaturer", "unit": "°C", "series": temp_series, "refs": refs}]
    if any(v is not None for v in D["tlimit"]):
        charts.append({"title": "GPU: termisk margen (T.Limit, fra driveren)", "unit": "°C",
                       "series": [{"name": "T.Limit-margen", "key": "tlimit", "color": "--s2"}],
                       "refs": [{"y": 0, "label": "0 °C margen: boost begrænses af varme", "short": "boost-grænse"}], "min": -5})
    if any(v is not None for v in D["gpupower"]):
        charts.append({"title": "GPU-effekt", "unit": "W", "series": [{"name": "GPU", "key": "gpupower", "color": "--s2"}], "min": 0})
    if duty_series:
        charts.append({"title": "Blæserhastighed (duty)", "unit": "%", "series": duty_series, "min": 0, "max": 100})
    if rpm_series:
        charts.append({"title": "Omdrejninger", "unit": "rpm", "series": rpm_series, "min": 0})

    def level(mx, lim):
        return "good" if mx < lim - wm else ("warning" if mx < lim - am else "critical")
    tiles = []
    cv = [v for v in D["cpu"] if v is not None]
    if cv and cpu:
        mx = max(cv)
        tiles.append({"label": "CPU maks", "value": f"{mx:.1f} °C", "meter": mx / cpu["limit"] * 100,
                      "status": level(mx, cpu["limit"]), "detail": f"{cpu['limit'] - mx:.1f} °C margen til {cpu['limit']:.0f} °C"})
    gv = [v for v in D["gpu"] if v is not None]
    if gv and gpus:
        mx = max(gv)
        tiles.append({"label": "GPU maks", "value": f"{mx:.0f} °C", "meter": mx / gpus[0]["limit"] * 100,
                      "status": level(mx, gpus[0]["limit"]), "detail": f"{gpus[0]['limit'] - mx:.0f} °C margen til {gpus[0]['limit']:.0f} °C"})
    for i, c in enumerate(chans):
        if c["pump"]:
            r = [v for v in D[f"c{i}_rpm"] if v is not None]
            if r:
                stable = max(r) - min(r) < 0.1 * max(r)
                tiles.append({"label": "Pumpe", "value": f"{min(r):.0f}–{max(r):.0f} rpm",
                              "status": "good" if stable and min(r) >= 1000 else "critical",
                              "detail": "stabil" if stable else "svinger mere end 10 %"})
    # per phase: steady state = last 30 s
    head = ["Fase", "CPU maks", "GPU maks", "Sensor snit"] + [chans[i]["label"] for i in order]
    trows, ok, total = [], 0, 0
    for ph in phases:
        idx = [i for i in range(ph["i0"], ph["i1"] + 1) if D["t"][i] >= D["t"][ph["i1"]] - 30]
        pick = lambda key: [D[key][i] for i in idx if D[key][i] is not None]
        row = [ph["name"]]
        for key, unit, f in (("cpu", "°C", max), ("gpu", "°C", max)):
            v = pick(key)
            row.append(f"{f(v):.1f} {unit}" if v else "–")
        v = pick("sensor")
        row.append(f"{sum(v) / len(v):.1f} °C" if v else "–")
        for i in order:
            du, rp, ex = pick(f"c{i}_duty"), pick(f"c{i}_rpm"), pick(f"c{i}_expected")
            if not du:
                row.append("–")
                continue
            ad = sum(du) / len(du)
            txt = f"{ad:.0f} % · {sum(rp) / len(rp):.0f} rpm" if rp else f"{ad:.0f} %"
            if ex:
                ed = sum(ex) / len(ex)
                good = abs(ad - ed) <= 5
                ok += good
                total += 1
                row.append({"text": txt + (" ✓" if good else f" ✕ kurven: {ed:.0f} %"), "cls": "ok" if good else "bad"})
            else:
                row.append(txt)
        trows.append(row)
    if total:
        tiles.append({"label": "Blæsere fulgte kurven", "value": f"{ok}/{total}", "status": "good" if ok == total else "warning",
                      "detail": "i alle faser" if ok == total else "se tabellen"})
    # "under load" = GPU drawing > 150 W (or, without power data, a core above 55 °C)
    loaded = [(pw_ is not None and pw_ > 150) or (pw_ is None and g is not None and g >= 55)
              for pw_, g in zip(D["gpupower"], D["gpu"])]
    pairs = [(g, h) for g, h, on in zip(D["gpu"], D["hotspot"], loaded) if on and g is not None and h is not None]
    if len(pairs) >= 30:
        deltas = sorted(h - g for g, h in pairs)
        pws = sorted(v for v, on in zip(D["gpupower"], loaded) if on and v is not None)
        pw = pws[len(pws) // 2] if pws else None
        typ = deltas[len(deltas) // 2]
        tiles.append({"label": "GPU hotspot − kerne (under last)", "value": f"{typ:.0f} °C",
                      "status": "good" if typ <= 20 else ("warning" if typ <= 30 else "critical"),
                      "detail": (f"hotspot maks {max(h for _, h in pairs):.0f} °C"
                                 + ("" if typ <= 20 else ". Højere end typisk: sammenlign med en realistisk last, før du konkluderer noget")
                                 + (f" · ≈{typ / pw:.2f} °C pr. W ved ~{pw:.0f} W" if pw else ""))})
    n_sw, n_hw = sum(1 for v in slow if v == "sw"), sum(1 for v in slow if v == "hw")
    if n_hw:
        tiles.append({"label": "GPU-nødbremse (HW)", "value": f"{n_hw} s", "status": "critical",
                      "detail": "hardwarens egen termiske nødbremse greb ind"})
    if n_sw:
        tiles.append({"label": "GPU-boost begrænset af varme", "value": f"{n_sw} s",
                      "detail": "normal GPU Boost-opførsel: kortet kunne ikke klokke højere pga. temperatur"})
    if meta.get("aborted"):
        tiles.insert(0, {"label": "Stoppet tidligt", "value": "Stop", "status": "critical", "detail": meta["aborted"], "wide": True})
    sub = " · ".join(x for x in [meta.get("date"), cpu["name"] if cpu else None,
                                  ", ".join(g["name"] for g in gpus) or None] if x)
    data = {"title": f"Køletest · {meta['title']}", "subtitle": sub, "tiles": tiles, "charts": charts, "live": meta.get("live"),
            "phases": phases, "table": {"head": head, "rows": trows}, **D}
    out = run_dir / "graph.html"
    out.write_text(ASSET.read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    return out


PHASE_DA = {"idle": "Tomgang", "cooldown": "Nedkøling", "recovery": "Genopretning", "record": "Måling",
            "encode": "CPU-eksport", "nvenc": "NVENC-eksport", "heatsoak": "CPU + GPU-render", "burn": "Syntetisk burn",
            "gaming": "Gaming", "game": "Spil (Superposition)", "render": "3D-render", "gamelike": "Spil-lignende"}


def phase_da(name):
    if name.startswith("load "):
        return "Last " + name[5:].replace("%", " %")
    return PHASE_DA.get(name, name)


def cmd_graph(args):
    if not args:
        runs = sorted(RUNS_DIR.glob("*/samples.csv"))
        if not runs:
            sys.exit("no runs yet")
        args = [str(runs[-1].parent)]
    d = Path(args[0])
    d = d.parent if d.suffix == ".csv" else d
    html = build_graph(d)
    print(html)
    open_file(html)


# ---------- limits / record / stresstest ----------

RUNS_DIR = USER_HOME / ".local/state/coolercontrol-skill/runs"


def parse_duration(txt):
    txt = txt.strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600}.get(txt[-1], 1)
    return int(float(txt[:-1] if txt[-1] in "smh" else txt) * mult)


class Monitor:
    """Samples CPU/GPU temps (sysfs / nvidia-smi) plus CoolerControl's sensors and channels (API)."""

    def __init__(self):
        import limits
        self.L = limits
        self.cpu = limits.cpu_limit()
        self.gpus = limits.gpu_limits()
        cfg, ov = load_config()
        self.devnames, self.lab = cfg.get("devices", {}), labels(ov)
        self.api = bool(token()) and request("GET", "/profiles")[0] == 200
        self.profiles, self.assign = {}, {}
        if self.api:
            self.profiles = {p["uid"]: p for p in request("GET", "/profiles")[1]["profiles"]}
            for duid in (cfg.get("device-settings") or {}):
                st, d = request("GET", f"/devices/{duid}/settings")
                for c in (d.get("settings", []) if st == 200 else []):
                    if c.get("profile_uid") and c["profile_uid"] != "0":
                        self.assign[(duid, c["channel_name"])] = c["profile_uid"]
        self.samples = []
        self.run_dir, self.opened = None, False
        self.hotspot_key = None
        if self.api:
            st, data = request("POST", "/status", {})
            for d in (data.get("devices", []) if st == 200 else []):
                for t in ((d.get("status_history") or [{}])[-1].get("temps", [])):
                    if "hotspot" in t["name"].lower() and self.hotspot_key is None:
                        self.hotspot_key = (d["uid"], t["name"])

    def slope(self, ss, window):
        """Rise in °C/min of the radiator curve's sensor (or the CPU) over the last `window` seconds."""
        radiator = next((k for k in self.assign if self.profiles.get(self.assign[k], {}).get("p_type") == "Graph"), None)
        ts = graph_source(self.profiles[self.assign[radiator]], self.profiles) if radiator else None
        key = (ts["device_uid"], ts["temp_name"]) if ts else None
        pts = [(x["t"], x["temps"].get(key) if key else x["cpu"]) for x in ss if x["t"] >= ss[-1]["t"] - window]
        pts = [(t, v) for t, v in pts if v is not None]
        if len(pts) < window * 0.8:
            return None
        n = len(pts)
        mt, mv = sum(t for t, _ in pts) / n, sum(v for _, v in pts) / n
        den = sum((t - mt) ** 2 for t, _ in pts)
        return sum((t - mt) * (v - mv) for t, v in pts) / den * 60 if den else None

    def calibrating(self):
        """Labels of assigned channels with a CoolerControl fan calibration in progress."""
        busy = []
        for duid, ch in self.assign:
            st, d = request("GET", f"/calibrations/{duid}/channels/{ch}/status")
            if st == 200 and isinstance(d, dict) and d.get("phase") == "in_progress":
                busy.append(f"{self.label((duid, ch))} ({d.get('stage')}, {d.get('percent')} %)")
        return busy

    def label(self, key):
        duid, ch = key
        return self.lab.get(duid, {}).get(ch) or ch

    def sample(self, phase=""):
        s = {"t": time.time(), "phase": phase, "cpu": self.L.cpu_temp(), "gpu": {}, "temps": {}, "chans": {}}
        for name, r in self.L.gpu_readings(self.gpus).items():
            s["gpu"][name] = (r["temp"], r["sw_slow"] or r["hw_slow"])
            s.setdefault("gpux", {})[name] = r
        if self.api:
            st, data = request("POST", "/status", {})
            if st == 200:
                for d in data.get("devices", []):
                    last = (d.get("status_history") or [{}])[-1]
                    for t in last.get("temps", []):
                        s["temps"][(d["uid"], t["name"])] = t["temp"]
                    for c in last.get("channels", []):
                        if c.get("rpm") is not None or c.get("duty") is not None:
                            s["chans"][(d["uid"], c["name"])] = (c.get("duty"), c.get("rpm"))
        s["expected"] = {}
        for key, puid in self.assign.items():
            prof = self.profiles.get(puid)
            ts = graph_source(prof, self.profiles) if prof else None
            src = s["temps"].get((ts["device_uid"], ts["temp_name"])) if ts else None
            if prof and (src is not None or prof.get("p_type") == "Fixed"):
                s["expected"][key] = duty_at(prof, src or 0, self.profiles)
        self.samples.append(s)
        return s

    def check(self, s, stall_count):
        """Returns (abort_reason or None, warnings list). stall_count is a dict kept by the caller."""
        warn, cpu_lim = [], self.cpu["limit"]
        if self.api and len(self.samples) % 5 == 1:
            busy = self.calibrating()
            if busy:
                return "fan calibration started: " + ", ".join(busy) + " (it overrides the curves and runs the pump low)", warn
        if s["cpu"] is not None and s["cpu"] >= cpu_lim - self.L.ABORT_MARGIN:
            return f"CPU {s['cpu']:.1f} °C reached the stop limit ({cpu_lim - self.L.ABORT_MARGIN:.0f} °C)", warn
        for g in self.gpus:
            temp, _ = s["gpu"].get(g["name"], (None, False))
            x = s.get("gpux", {}).get(g["name"], {})
            if x.get("hw_slow"):
                return f"{g['name']}: HW thermal slowdown (the hardware's own emergency throttle)", warn
            # SW thermal slowdown is GPU Boost dropping bins because of temperature: normal, only logged
            if temp is not None and temp >= g["limit"] - self.L.ABORT_MARGIN:
                return f"{g['name']} {temp:.0f} °C reached the stop limit ({g['limit'] - self.L.ABORT_MARGIN:.0f} °C)", warn
        for key in self.assign:
            duty, rpm = s["chans"].get(key, (None, None))
            is_pump = "pump" in self.label(key).lower()
            bad = rpm is not None and ((is_pump and rpm < 1000) or (duty or 0) >= 20 and rpm == 0)
            stall_count[key] = stall_count.get(key, 0) + 1 if bad else 0
            if stall_count[key] >= (3 if is_pump else 5):
                what = "pump below 1000 rpm" if is_pump else "fan at 0 rpm while driven"
                return f"{self.label(key)}: {what} for {stall_count[key]} s", warn
        return None, warn


def save_run(mon, title, aborted=None, live=None):
    """Writes samples.csv + meta.json + graph.html for the run so far. With `live` (a status dict) the
    page reloads itself every few seconds, so it doubles as the status view while a test runs."""
    S, L = mon.samples, mon.L
    if mon.run_dir is None:
        mon.run_dir = RUNS_DIR / time.strftime("%Y%m%d-%H%M%S", time.localtime(S[0]["t"]))
        mon.run_dir.mkdir(parents=True, exist_ok=True)
    d = mon.run_dir
    radiator = next((k for k in mon.assign if mon.profiles.get(mon.assign[k], {}).get("p_type") == "Graph"), None)
    src_key = None
    if radiator:
        ts = graph_source(mon.profiles[mon.assign[radiator]], mon.profiles)
        src_key = (ts["device_uid"], ts["temp_name"]) if ts else None
    keys = list(mon.assign)
    cols = ["t", "phase", "cpu"] + [f"gpu:{g['name']}" for g in mon.gpus] + ["sensor", "gpu_tlimit", "gpu_power", "gpu_slowdown", "gpu_hotspot"]
    for k in keys:
        cols += [f"{mon.label(k)}_duty", f"{mon.label(k)}_rpm", f"{mon.label(k)}_expected"]
    t0 = S[0]["t"]
    with open(d / "samples.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for x in S:
            row = [f"{x['t'] - t0:.1f}", x["phase"], x["cpu"]]
            row += [x["gpu"].get(g["name"], (None,))[0] for g in mon.gpus]
            row.append(x["temps"].get(src_key) if src_key else None)
            gx = next(iter(x.get("gpux", {}).values()), {})
            row += [gx.get("tlimit"), gx.get("power"),
                    "hw" if gx.get("hw_slow") else ("sw" if gx.get("sw_slow") else ""),
                    x["temps"].get(mon.hotspot_key) if mon.hotspot_key else None]
            for k in keys:
                du, rp = x["chans"].get(k, (None, None))
                ex = x["expected"].get(k)
                row += [du, rp, round(ex, 1) if ex is not None else None]
            w.writerow(["" if v is None else v for v in row])
    meta = {
        "title": title, "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(t0)),
        "cpu": {"name": mon.cpu["name"], "limit": mon.cpu["limit"], "source": mon.cpu["source"]},
        "gpus": [{"name": g["name"], "limit": g["limit"], "source": g["source"]} for g in mon.gpus],
        "abort_margin": L.ABORT_MARGIN, "warn_margin": L.WARN_MARGIN,
        "sensor": src_str({"device_uid": src_key[0], "temp_name": src_key[1]}, mon.devnames, mon.lab) if src_key else None,
        "channels": [{"label": mon.label(k), "pump": "pump" in mon.label(k).lower()} for k in keys],
        "cooling": topology_advice(load_topology()), "aborted": aborted, "live": live,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return build_graph(d)


def live_update(mon, title, status):
    """Refresh the live report every 5 samples; open it in the browser the first time."""
    if len(mon.samples) < 3 or len(mon.samples) % 5:
        return
    html = save_run(mon, title, live=status)
    if not mon.opened:
        print(f"\nlive status: {html}")
        open_file(html)
        mon.opened = True

def report(mon, title, phases=None, aborted=None):
    S, L = mon.samples, mon.L
    if not S:
        print("no samples")
        return
    radiator = next((k for k in mon.assign if mon.profiles.get(mon.assign[k], {}).get("p_type") == "Graph"), None)
    src_key = None
    if radiator:
        ts = graph_source(mon.profiles[mon.assign[radiator]], mon.profiles)
        src_key = (ts["device_uid"], ts["temp_name"]) if ts else None
    gname = mon.gpus[0]["name"] if mon.gpus else None
    print(f"\n== {title}")
    print(L.describe())
    print("Cooling: " + topology_advice(load_topology()))
    groups = phases or [("whole run", S)]
    for name, ss in groups:
        steady = [x for x in ss if x["t"] >= ss[-1]["t"] - 30] if ss else []
        if not steady:
            continue
        cpu = [x["cpu"] for x in steady if x["cpu"] is not None]
        line = f"[{name}] last {len(steady)} s: CPU avg {sum(cpu)/len(cpu):.1f} max {max(cpu):.1f} °C" if cpu else f"[{name}]"
        if gname:
            g = [x["gpu"].get(gname, (None,))[0] for x in steady]
            g = [v for v in g if v is not None]
            if g:
                line += f", GPU max {max(g):.0f} °C"
        if src_key:
            sv = [x["temps"].get(src_key) for x in steady if x["temps"].get(src_key) is not None]
            if sv:
                line += f", sensor avg {sum(sv)/len(sv):.1f} °C"
        print(line)
        for key in mon.assign:
            d = [x["chans"].get(key, (None, None)) for x in steady]
            duty = [a for a, _ in d if a is not None]
            rpm = [b for _, b in d if b is not None]
            exp = [x["expected"].get(key) for x in steady if x["expected"].get(key) is not None]
            if not duty:
                continue
            ad, ed = sum(duty) / len(duty), (sum(exp) / len(exp) if exp else None)
            ok = "" if ed is None else ("  ✓ follows curve" if abs(ad - ed) <= 5 else f"  ✗ curve says {ed:.0f} %")
            print(f"   {mon.label(key):<8} duty {ad:5.1f} %  rpm {min(rpm) if rpm else '-'}-{max(rpm) if rpm else '-'}{ok}")
    print()
    cpu_all = [x["cpu"] for x in S if x["cpu"] is not None]
    if cpu_all:
        m = max(cpu_all)
        flag = "OK" if m < mon.cpu["limit"] - L.WARN_MARGIN else ("WARN (within 10 °C of the limit)" if m < mon.cpu["limit"] - L.ABORT_MARGIN else "STOP LIMIT")
        print(f"CPU max {m:.1f} °C of {mon.cpu['limit']:.0f} °C, headroom {mon.cpu['limit'] - m:.1f} °C: {flag}")
    for g in mon.gpus:
        vals = [x["gpu"].get(g["name"], (None, False)) for x in S]
        temps = [t for t, _ in vals if t is not None]
        thr = sum(1 for _, th in vals if th)
        if temps:
            m = max(temps)
            flag = "OK" if m < g["limit"] - L.WARN_MARGIN else ("WARN" if m < g["limit"] - L.ABORT_MARGIN else "STOP LIMIT")
            print(f"GPU max {m:.0f} °C of {g['limit']:.0f} °C, headroom {g['limit'] - m:.0f} °C: {flag}"
                  + (f"; thermal slowdown in {thr} samples" if thr else ""))
    for key in mon.assign:
        if "pump" in mon.label(key).lower():
            r = [x["chans"].get(key, (None, None))[1] for x in S]
            r = [v for v in r if v is not None]
            if r:
                print(f"Pump rpm {min(r)}-{max(r)}" + ("  (stable)" if max(r) - min(r) < 0.1 * max(r) else "  (varies > 10 %)"))
    if aborted:
        print(f"\n!! STOPPED EARLY: {aborted}")
    html = save_run(mon, title, aborted)
    print(f"samples: {html.parent / 'samples.csv'}\ngraph:   {html}")
    if not mon.opened:
        open_file(html)
    if not mon.api:
        print("(no working token: fan duty/rpm and curve checks need the CoolerControl API)")


def cmd_limits(_args):
    import limits
    print(limits.describe())


def cmd_record(args):
    if not args:
        sys.exit("usage: cc.py record DURATION   (e.g. 300, 90s, 10m)")
    secs = parse_duration(args[0])
    mon, stall, alerted = Monitor(), {}, False
    if mon.api and (busy := mon.calibrating()):
        sys.exit("a CoolerControl fan calibration is running: " + ", ".join(busy) + ". Wait for it to finish.")
    print(mon.L.describe())
    print(f"recording {secs} s — start the load now (game, benchmark, CoolerControl stress test). Ctrl-C ends early.")
    t_end = time.time() + secs
    try:
        while time.time() < t_end:
            s = mon.sample("record")
            reason, _ = mon.check(s, stall)
            live_update(mon, f"måling {secs // 60} min {secs % 60} s", {"phase": "Måling", "elapsed": int(time.time() - (t_end - secs)),
                                                                     "target": secs, "plan": ["Måling"]})
            if reason and not alerted:
                print(f"\n!! {reason} — STOP THE LOAD NOW (this recording can't stop it for you)", file=sys.stderr)
                alerted = True
            time.sleep(max(0, 1 - (time.time() - s["t"])))
    except KeyboardInterrupt:
        pass
    report(mon, f"måling {secs // 60} min {secs % 60} s", aborted=None)


def _stat_state(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0].join("()")
    except (OSError, IndexError):
        return ""


def run_plan(title, plan, confirmed=False):
    """Runs phases [(name, secs, [cmd, …])] while monitoring; every phase's commands start together and
    are killed at the end of the phase or when a safety check trips. Then writes the report."""
    import signal
    mon, stall, phases, aborted, procs = Monitor(), {}, [], None, []
    if not mon.api:
        sys.exit("needs a working API token: without it the pump and fans can't be watched")
    if busy := mon.calibrating():
        sys.exit("a CoolerControl fan calibration is running: " + ", ".join(busy) + ". Wait for it to finish.")
    print(mon.L.describe())
    print("Cooling: " + topology_advice(load_topology()))
    total = sum(e[1] for e in plan)
    most = sum((e[3].get("max_secs", e[1]) if len(e) > 3 else e[1]) for e in plan)
    print(f"{title}: " + " → ".join(f"{e[0]} {e[1] // 60}:{e[1] % 60:02d}" + ("+" if len(e) > 3 and e[3].get("until_stable") else "")
                                     for e in plan)
          + f"  (≈{total // 60} min" + (f", up to {most // 60} min if still warming" if most > total else "") + "). Ctrl-C stops.")
    if not confirmed:
        print("dry run: nothing started. Add --yes to put this load on the machine (only with the user's OK).")
        return

    def tree(pid):
        """pid plus all its descendants (some load programs fork workers into their own groups)."""
        kids = {}
        for st in Path("/proc").glob("[0-9]*/stat"):
            try:
                f = st.read_text().rsplit(")", 1)[1].split()
                kids.setdefault(int(f[1]), []).append(int(st.parent.name))
            except (OSError, IndexError, ValueError):
                pass
        out, todo = [], [pid]
        while todo:
            q = todo.pop()
            out.append(q)
            todo += kids.get(q, [])
        return out

    def stop():
        for pr in procs:
            pids = tree(pr.pid)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                for q in pids:
                    try:
                        os.kill(q, sig)
                    except ProcessLookupError:
                        pass
                try:
                    pr.wait(5)
                    time.sleep(0.5)
                except subprocess.TimeoutExpired:
                    pass
                pids = [q for q in pids if Path(f"/proc/{q}").exists() and "(Z)" not in _stat_state(q)]
                if not pids:
                    break
        procs.clear()

    try:
        for entry in plan:
            name, secs, cmds = entry[:3]
            opt = entry[3] if len(entry) > 3 else {}
            max_secs = opt.get("max_secs", secs)
            for c in cmds:
                # `timeout` makes every load program stop on its own even if this script dies
                c = ["timeout", "--signal=TERM", "--kill-after=10", str(max_secs + 10)] + c
                procs.append(subprocess.Popen(c, start_new_session=True, stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            start, ss, target = time.time(), [], secs
            while time.time() - start < target:
                s = mon.sample(name)
                ss.append(s)
                reason, _ = mon.check(s, stall)
                dead = [c for c, pr in zip(cmds, procs) if pr.poll() not in (None, 0)] if time.time() - start > 3 else []
                if dead:
                    reason = f"load program stopped by itself: {' '.join(dead[0][:4])} … (exit {procs[0].poll()})"
                g = next(iter(s["gpu"].values()), (None,))[0]
                print(f"\r  {name:<12} {int(time.time() - start):>4}/{secs} s  CPU {s['cpu'] or 0:5.1f} °C"
                      + (f"  GPU {g:4.0f} °C" if g is not None else ""), end="", flush=True)
                if reason:
                    aborted = reason
                    break
                total_done = sum(len(p[1]) for p in phases) + len(ss)
                live_update(mon, title, {"phase": phase_da(name), "elapsed": int(time.time() - start), "target": target,
                                         "extendable": bool(opt.get("until_stable")) and target < max_secs,
                                         "slope": mon.slope(ss, 120) if opt.get("until_stable") else None,
                                         "plan": [phase_da(e[0]) for e in plan], "total_elapsed": total_done})
                if opt.get("until_stable") and time.time() - start >= target - 1 and target < max_secs:
                    slope = mon.slope(ss, 120)
                    if slope is not None and slope > 0.3:
                        target = min(max_secs, target + 60)
                        print(f"\n  still rising {slope:.2f} °C/min: extending to {target // 60} min", end="")
                time.sleep(max(0, 1 - (time.time() - s["t"])))
            stop()
            phases.append((name, ss))
            print()
            if aborted:
                break
    except KeyboardInterrupt:
        aborted = aborted or "stopped by user"
    finally:
        stop()
    if aborted:
        print(f"!! {aborted}\nload stopped; recording 30 s of recovery (Ctrl-C skips)")
        ss = []
        try:
            for _ in range(30):
                ss.append(mon.sample("recovery"))
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        phases.append(("recovery", ss))
    report(mon, title, phases, aborted)


def cmd_stresstest(args):
    import shutil
    opts = {"--steps": "25,50,75,100", "--step-secs": "90", "--cooldown": "60", "--method": "matrixprod", "--idle": "20"}
    yes = "--yes" in args
    args = [a for a in args if a != "--yes"]
    it = iter(args)
    for a in it:
        if a in opts:
            opts[a] = next(it)
        else:
            sys.exit(f"unknown option {a}")
    if not shutil.which("stress-ng"):
        sys.exit("stress-ng is not installed (sudo pacman -S stress-ng)")
    step = int(opts["--step-secs"])
    plan = [("idle", int(opts["--idle"]), [])]
    for load in (int(x) for x in opts["--steps"].split(",")):
        plan.append((f"load {load}%", step, [["stress-ng", "--cpu", "0", "--cpu-load", str(load), "--cpu-method",
                                              opts["--method"], "--timeout", f"{step + 5}s", "--quiet"]]))
    if int(opts["--cooldown"]):
        plan.append(("cooldown", int(opts["--cooldown"]), []))
    run_plan("CPU-trintest (stress-ng)", plan, yes)


# ---------- realistic load scenarios ----------

FFMPEG_4K = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi",
             "-i", "testsrc2=size=3840x2160:rate=60"]


SUPERPOSITION = Path("/opt/unigine-superposition/bin")


def superposition_cmd():
    """Unigine Superposition's benchmark, fullscreen 4K Optimized, started straight from its binary.

    superposition_cli is Pro-only, but the engine binary takes the launcher's arguments directly, even in
    the free Basic edition. `-mode 0` is the benchmark: the 17-scene run takes ~3 min, then the engine keeps
    rendering the last scene at the same power (measured 2026-10-03: 365-387 W on the 4090 for 15 min) until
    it is killed. The interactive Game modes (1/3) idle at ~70 W without input, so they're no use unattended.
    It must run from its own directory and needs the user's graphical session (DISPLAY)."""
    args = ["./superposition", "-preset", "5", "-video_app", "opengl", "-shaders_quality", "4", "-textures_quality", "2",
            "-dof", "1", "-motion_blur", "1", "-video_vsync", "0", "-video_mode", "-1",
            "-console_command", "world_load superposition/superposition && render_manager_create_textures 1",
            "-project_name", "Superposition", "-video_fullscreen", "1", "-video_width", "3840", "-video_height", "2160",
            "-mode", "0", "-sound", "0", "-tooltips", "1"]
    return ["sh", "-c", f'cd "{SUPERPOSITION}" && exec "$@"', "superposition"] + args


def gpu_load_cmd():
    """A command that loads the GPU hard, from whatever is installed, or None."""
    import shutil
    if shutil.which("gpu_burn") or shutil.which("gpu-burn"):
        # no -d: doubles run at 1/64 rate on GeForce cards and barely load them
        return [shutil.which("gpu_burn") or shutil.which("gpu-burn"), "86400"]
    return None


SCENARIOS = {
    "encode": {
        "title": "Videoeksport på CPU (SVT-AV1, 4K)",
        "what": "all CPU cores (~13 of 16 threads), GPU idle: like exporting a video with a software encoder",
        "load": lambda: [FFMPEG_4K + ["-c:v", "libsvtav1", "-preset", "6", "-svtav1-params", "lp=6", "-f", "null", "-"]],
        "minutes": 10,
    },
    "nvenc": {
        "title": "Videoeksport på GPU (NVENC + CUDA-skalering)",
        "what": "GPU video encoder + CUDA scaling (~80 W), a few CPU cores: like a DaVinci/OBS/Premiere GPU export. Light on heat",
        "load": lambda: [FFMPEG_4K + ["-vf", "format=nv12,hwupload_cuda,scale_cuda=2560:1440", "-c:v", "hevc_nvenc",
                                     "-preset", "p7", "-f", "null", "-"]],
        "minutes": 10,
    },
    "render": {
        "title": "3D-rendering (Blender Cycles, OptiX)",
        "what": "GPU compute ~99 % (~260 W on the 4090), one CPU core: like a Cycles render. Procedural scene, nothing written",
        "load": lambda: [["blender", "-b", "--factory-startup", "--python", str(Path(__file__).resolve().parent / "blender_load.py")]],
        "needs": "blender",
        "minutes": 10,
    },
    "game": {
        "title": "Spil: Unigine Superposition 4K Optimized",
        "what": "a real game engine fullscreen on the 4K screen (~370-390 W GPU, light CPU): what gaming looks like. "
                "Takes over the screen for the whole run",
        "load": lambda: [superposition_cmd()],
        "needs_file": SUPERPOSITION / "superposition",
        "needs_display": True,
        "minutes": 15,
    },
    "gamelike": {
        "title": "Spil-lignende belastning (syntetisk)",
        "what": "GPU high (Blender OptiX render, ~260 W) + CPU mid (6 threads at 50 %): the load profile of a game. "
                "For a real game, start it yourself and use `record`",
        "load": lambda: [["blender", "-b", "--factory-startup", "--python", str(Path(__file__).resolve().parent / "blender_load.py")],
                         ["stress-ng", "--cpu", "6", "--cpu-load", "50", "--cpu-method", "matrixprod", "--quiet"]],
        "needs": "blender",
        "minutes": 10,
    },
    "heatsoak": {
        "title": "Tung realistisk last: CPU 100 % + GPU-rendering",
        "what": "every CPU core plus a Blender GPU render (~260 W): the heaviest realistic mix, e.g. rendering while encoding",
        "load": lambda: [["stress-ng", "--cpu", "0", "--cpu-method", "matrixprod", "--quiet"],
                         ["blender", "-b", "--factory-startup", "--python", str(Path(__file__).resolve().parent / "blender_load.py")]],
        "needs": "blender",
        "minutes": 10,
    },
    "burn": {
        "title": "Ekstrem syntetisk last: CPU 100 % + gpu_burn",
        "what": "every CPU core plus gpu_burn (~445 W, far denser than games or renders). A synthetic torture test, "
                "not a realistic worst case; GPU hotspot numbers from it overstate real use",
        "load": lambda: ([["stress-ng", "--cpu", "0", "--cpu-method", "matrixprod", "--quiet"]]
                         + ([gpu_load_cmd()] if gpu_load_cmd() else [])),
        "needs_gpu": True,
        "minutes": 10,
    },
}


def cmd_scenario(args):
    if not args or args[0] not in SCENARIOS:
        print("scenarios:")
        for k, v in SCENARIOS.items():
            print(f"  {k:<9} {v['title']}: {v['what']} (default {v['minutes']} min)")
        print("usage: cc.py scenario NAME [--minutes N] [--max-minutes N] [--idle SECS] [--cooldown SECS] [--yes]")
        print("the load runs --minutes, then extends a minute at a time while the curve sensor still rises > 0.3 °C/min (cap --max-minutes)")
        print("games / benchmarks you start yourself: cc.py record 20m")
        sys.exit(0 if not args else 2)
    sc = SCENARIOS[args[0]]
    opts = {"--minutes": str(sc["minutes"]), "--max-minutes": "20", "--idle": "60", "--cooldown": "120"}
    yes = "--yes" in args
    it = iter([a for a in args[1:] if a != "--yes"])
    for a in it:
        if a in opts:
            opts[a] = next(it)
        else:
            sys.exit(f"unknown option {a}")
    if sc.get("needs") and not __import__("shutil").which(sc["needs"]):
        sys.exit(f"this scenario needs {sc['needs']} (not installed)")
    if sc.get("needs_file") and not os.access(sc["needs_file"], os.X_OK):
        sys.exit(f"this scenario needs {sc['needs_file']} (not installed, or not readable for this user)")
    if sc.get("needs_display") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        sys.exit("this scenario opens a fullscreen window and needs the user's graphical session (run it as enzord, not root)")
    if sc.get("needs_gpu") and not gpu_load_cmd():
        sys.exit("this scenario needs gpu_burn (not installed); for a realistic GPU load use the game scenario")
    secs = int(float(opts["--minutes"]) * 60)
    plan = [("idle", int(opts["--idle"]), []),
            (args[0], secs, sc["load"](), {"until_stable": True, "max_secs": max(secs, int(float(opts["--max-minutes"]) * 60))}),
            ("cooldown", int(opts["--cooldown"]), [])]
    run_plan(sc["title"], plan, yes)


def main():
    cmds = {"show": cmd_show, "live": cmd_live, "snapshot": cmd_snapshot, "api": cmd_api, "token": cmd_token, "plot": cmd_plot,
            "limits": cmd_limits, "topology": cmd_topology, "graph": cmd_graph, "record": cmd_record, "stresstest": cmd_stresstest,
            "scenario": cmd_scenario}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
