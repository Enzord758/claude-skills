"""Safe temperature limits for CPUs and GPUs, and live readings to check them against.

Priority, most trustworthy first:
  1. hardware / driver: Intel coretemp tempN_crit (TjMax from MSR_IA32_TEMPERATURE_TARGET),
     amdgpu tempN_crit / tempN_emergency, NVIDIA's HW thermal-slowdown flag (the card's emergency
     throttle). NVIDIA's SW thermal slowdown is only GPU Boost dropping clock bins because of
     temperature, which is normal on RTX cards, so it is logged but never treated as a stop signal
  2. vendor spec tables (below) matched on the model name
  3. a conservative default
When a value is uncertain the LOWER one is used: stopping a test early is harmless,
stopping it late is not.

Sources (checked 2026-09-27):
  AMD product pages "Max. Operating Temperature (Tjmax)": 7800X3D/7950X3D 89 °C,
    9950X/9800X3D/9950X3D 95 °C, 5800X/5800X3D 90 °C
  Intel spec pages: Core i9-14900K TjMax 100 °C, Core Ultra 9 285K 105 °C
  NVIDIA RTX 4090 spec page: Maximum GPU Temperature 90 °C
  AMD: RX 7900 series "can operate up to 110 °C junction temperature"
  kernel docs: hwmon/coretemp (tempX_crit = TjMax), gpu/amdgpu/thermal (tempN_crit/_emergency)
"""
import re
import subprocess
from pathlib import Path

HWMON = Path("/sys/class/hwmon")
WARN_MARGIN = 10   # °C below the limit: flag in the report
ABORT_MARGIN = 3   # °C below the limit: stop the stress test

# (regex on the CPU model name, TjMax °C, note). First match wins, so specific before generic.
AMD_CPU_TABLE = [
    (r"Threadripper", 95, "AMD spec: Threadripper"),
    (r"Ryzen .*\b\d{4}(HS|HX|H|U)\b", 95, "AMD spec: mobile Ryzen (95-100 °C; lower used)"),
    (r"Ryzen .*\b7\d{3}X3D\b", 89, "AMD spec: Ryzen 7000 X3D"),
    (r"Ryzen .*\b9\d{3}X3D\b", 95, "AMD spec: Ryzen 9000 X3D"),
    (r"Ryzen .*\b9\d{3}X?\b", 95, "AMD spec: Ryzen 9000"),
    (r"Ryzen .*\b5\d{3}X3D\b", 90, "AMD spec: Ryzen 5000 X3D"),
    (r"Ryzen .*\b5\d{3}", 90, "AMD spec: Ryzen 5000 (lowest desktop value used)"),
    (r"Ryzen .*\b8\d{3}G", 95, "AMD spec: Ryzen 8000G"),
    (r"Ryzen .*\b7\d{3}X?\b", 95, "AMD spec: Ryzen 7000"),
]
AMD_CPU_DEFAULT = (89, "unknown AMD model: lowest modern desktop TjMax (conservative)")
INTEL_CPU_TABLE = [
    (r"Core\(TM\) Ultra \d+ 2\d{2}", 105, "Intel spec: Core Ultra 200S"),
    (r"Intel", 100, "Intel spec: Core desktop/mobile TjMax"),
]
NVIDIA_GPU_TABLE = [
    (r"RTX 40\d0", 90, "NVIDIA spec: RTX 40 series (4090 page: 90 °C)"),
]
NVIDIA_GPU_DEFAULT = (87, "no verified spec for this model: conservative default")
INTEL_GPU_DEFAULT = (90, "no reliable driver limit: conservative default")


def _read(p):
    try:
        return p.read_text().strip()
    except OSError:
        return None


def _hwmon(name):
    for h in sorted(HWMON.iterdir()):
        if _read(h / "name") == name:
            return h
    return None


def _match(table, text):
    for rx, val, note in table:
        if re.search(rx, text):
            return val, note
    return None


def cpu_model():
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "unknown CPU"


def cpu_limit():
    """dict(name, limit, source, sensor) for the CPU."""
    model = cpu_model()
    h = _hwmon("coretemp")
    if h:
        crits = [int(v) / 1000 for f in h.glob("temp*_crit") if (v := _read(f))]
        if crits:
            return {"name": model, "limit": min(crits), "source": "hardware: coretemp TjMax", "sensor": "coretemp"}
        hit = _match(INTEL_CPU_TABLE, model)
        return {"name": model, "limit": hit[0], "source": hit[1], "sensor": "coretemp"}
    if _hwmon("k10temp"):
        val, note = _match(AMD_CPU_TABLE, model) or AMD_CPU_DEFAULT
        return {"name": model, "limit": val, "source": note, "sensor": "k10temp"}
    return {"name": model, "limit": 85, "source": "no known sensor driver: conservative default", "sensor": None}


def cpu_temp():
    """Hottest relevant CPU reading in °C (AMD: max of Tctl/Tccd*, Intel: package/cores)."""
    for name in ("k10temp", "coretemp"):
        h = _hwmon(name)
        if h:
            vals = [int(v) / 1000 for f in h.glob("temp*_input") if (v := _read(f))]
            return max(vals) if vals else None
    return None


def _nvidia_query(fields):
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [[c.strip() for c in line.split(",")] for line in out.splitlines() if line.strip()]


def gpu_limits():
    """list of dicts(name, limit, source, kind, ...) for every GPU found."""
    gpus = []
    for row in _nvidia_query("index,name"):
        idx, name = row[0], row[1]
        val, note = _match(NVIDIA_GPU_TABLE, name) or NVIDIA_GPU_DEFAULT
        gpus.append({"name": name, "limit": val, "source": note + " + driver HW thermal-slowdown flag",
                     "kind": "nvidia", "index": idx})
    for h in sorted(HWMON.iterdir()):
        if _read(h / "name") == "amdgpu":
            labels = {f.stem.split("_")[0]: _read(f) for f in h.glob("temp*_label")}
            chan = next((c for c, l in labels.items() if l == "junction"), "temp1")
            crit = _read(h / f"{chan}_crit") or _read(h / f"{chan}_emergency")
            limit = int(crit) / 1000 if crit and int(crit) > 0 else 100
            src = f"driver: amdgpu {chan}_crit ({labels.get(chan, 'edge')})" if crit else "amdgpu without crit: default"
            gpus.append({"name": _read(h / "device/product_name") or "AMD GPU", "limit": limit,
                         "source": src, "kind": "amdgpu", "hwmon": str(h), "chan": chan})
        elif _read(h / "name") in ("i915", "xe"):
            gpus.append({"name": "Intel GPU", "limit": INTEL_GPU_DEFAULT[0], "source": INTEL_GPU_DEFAULT[1],
                         "kind": "intel", "hwmon": str(h)})
    return gpus


def gpu_readings(gpus):
    """{gpu name: {temp, sw_slow, hw_slow, tlimit (°C of headroom, NVIDIA), power (W)}}"""
    out = {}
    nv = [g for g in gpus if g["kind"] == "nvidia"]
    if nv:
        rows = _nvidia_query("index,temperature.gpu,clocks_event_reasons.sw_thermal_slowdown,"
                             "clocks_event_reasons.hw_thermal_slowdown,temperature.gpu.tlimit,power.draw")
        by_idx = {r[0]: r for r in rows}
        num = lambda v: float(v) if v.lstrip("-").replace(".", "").isdigit() else None
        for g in nv:
            r = by_idx.get(g["index"])
            if r:
                out[g["name"]] = {"temp": num(r[1]), "sw_slow": r[2] == "Active", "hw_slow": r[3] == "Active",
                                  "tlimit": num(r[4]) if len(r) > 4 else None, "power": num(r[5]) if len(r) > 5 else None}
    for g in gpus:
        if g["kind"] in ("amdgpu", "intel"):
            h = Path(g["hwmon"])
            v = _read(h / f"{g.get('chan', 'temp1')}_input")
            out[g["name"]] = {"temp": int(v) / 1000 if v else None, "sw_slow": False, "hw_slow": False,
                              "tlimit": None, "power": None}
    return out


def describe():
    c = cpu_limit()
    lines = [f"CPU  {c['name']}: limit {c['limit']:.0f} °C (stop at {c['limit'] - ABORT_MARGIN:.0f}, "
             f"warn at {c['limit'] - WARN_MARGIN:.0f}), source: {c['source']}"]
    for g in gpu_limits():
        lines.append(f"GPU  {g['name']}: limit {g['limit']:.0f} °C (stop at {g['limit'] - ABORT_MARGIN:.0f}, "
                     f"warn at {g['limit'] - WARN_MARGIN:.0f}), source: {g['source']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
