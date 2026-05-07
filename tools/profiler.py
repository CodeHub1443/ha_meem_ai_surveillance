"""
Hardware profiler for the Ha-Meem AI surveillance pipeline.

Run in a separate terminal while the pipeline is active:
    python tools/profiler.py

Options:
    --pid PID        Attach to a specific process (auto-detected if omitted)
    --interval N     Sample interval in seconds (default: 2)
    --duration N     Stop after N seconds (default: run until Ctrl+C)
    --out FILE       CSV output path (default: logs/profile_<timestamp>.csv)
    --no-csv         Disable CSV output

The script prints a live table and writes a CSV.
After stopping (Ctrl+C or --duration), it prints a summary report.
"""

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

# ── Colour helpers (Windows-safe fallback) ────────────────────────────────────
try:
    import colorama
    colorama.init()
    _C = {
        "reset": colorama.Style.RESET_ALL,
        "bold": colorama.Style.BRIGHT,
        "green": colorama.Fore.GREEN,
        "yellow": colorama.Fore.YELLOW,
        "red": colorama.Fore.RED,
        "cyan": colorama.Fore.CYAN,
        "white": colorama.Fore.WHITE,
    }
except ImportError:
    _C = {k: "" for k in ("reset", "bold", "green", "yellow", "red", "cyan", "white")}


def _colour(val: float, low: float, high: float, text: str) -> str:
    if val >= high:
        return f"{_C['red']}{text}{_C['reset']}"
    if val >= low:
        return f"{_C['yellow']}{text}{_C['reset']}"
    return f"{_C['green']}{text}{_C['reset']}"


# ── GPU via nvidia-smi ────────────────────────────────────────────────────────

_NVML_QUERY = (
    "name,memory.used,memory.total,utilization.gpu,utilization.memory,temperature.gpu"
)


def query_gpu() -> dict:
    """Return GPU metrics dict. Returns empty dict if nvidia-smi unavailable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_NVML_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return {}
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 6:
            return {}
        return {
            "gpu_name":       parts[0],
            "gpu_mem_used_mb": float(parts[1]),
            "gpu_mem_total_mb": float(parts[2]),
            "gpu_util_pct":   float(parts[3]),
            "gpu_mem_util_pct": float(parts[4]),
            "gpu_temp_c":     float(parts[5]),
        }
    except Exception:
        return {}


# ── Process discovery ─────────────────────────────────────────────────────────

def find_pipeline_pid() -> int:
    """Auto-detect the pipeline PID by scanning for entry_pipeline in cmdline."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if "entry_pipeline" in cmd and "profiler" not in cmd:
                return proc.pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return -1


# ── Sample ────────────────────────────────────────────────────────────────────

def sample(proc: psutil.Process, gpu: dict) -> dict:
    """Collect one sample from process + system + GPU."""
    try:
        with proc.oneshot():
            cpu_proc   = proc.cpu_percent()          # % across all cores (can exceed 100)
            mem_info   = proc.memory_info()
            rss_mb     = mem_info.rss / 1024 ** 2
            vms_mb     = mem_info.vms / 1024 ** 2
            threads    = proc.num_threads()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        raise RuntimeError(f"Process gone: {e}")

    sys_mem   = psutil.virtual_memory()
    sys_cpu   = psutil.cpu_percent(percpu=False)

    row = {
        "ts":             datetime.now().strftime("%H:%M:%S"),
        "proc_cpu_pct":   round(cpu_proc, 1),
        "sys_cpu_pct":    round(sys_cpu, 1),
        "proc_rss_mb":    round(rss_mb, 1),
        "proc_vms_mb":    round(vms_mb, 1),
        "sys_ram_used_gb": round(sys_mem.used / 1024 ** 3, 2),
        "sys_ram_pct":    round(sys_mem.percent, 1),
        "threads":        threads,
    }
    row.update(gpu)
    return row


# ── Display ───────────────────────────────────────────────────────────────────

_HEADER_PRINTED = False

def print_row(row: dict):
    global _HEADER_PRINTED
    if not _HEADER_PRINTED:
        print(
            f"\n{_C['bold']}{'Time':>8}  "
            f"{'ProcCPU':>8}  {'SysCPU':>7}  "
            f"{'ProcRAM':>8}  {'SysRAM':>8}  "
            f"{'Threads':>7}  "
            f"{'GPUUtil':>8}  {'GPUMem':>12}  {'GPUTemp':>7}"
            f"{_C['reset']}"
        )
        print("-" * 95)
        _HEADER_PRINTED = True

    gpu_util  = row.get("gpu_util_pct", 0.0)
    gpu_used  = row.get("gpu_mem_used_mb", 0.0)
    gpu_total = row.get("gpu_mem_total_mb", 0.0)
    gpu_temp  = row.get("gpu_temp_c", 0.0)
    gpu_mem_s = f"{gpu_used:.0f}/{gpu_total:.0f} MB"

    # Pre-format strings to avoid backslashes inside f-string expressions (py<3.12)
    s_pcpu  = _colour(row["proc_cpu_pct"], 80,   150,  f"{row['proc_cpu_pct']:>7.1f}%")
    s_scpu  = _colour(row["sys_cpu_pct"],  60,    85,  f"{row['sys_cpu_pct']:>6.1f}%")
    s_ram   = _colour(row["proc_rss_mb"],  1500, 3000, f"{row['proc_rss_mb']:>6.0f} MB")
    s_sram  = _colour(row["sys_ram_pct"],  70,    88,  f"{row['sys_ram_pct']:>6.1f}% ")
    s_gutil = _colour(gpu_util,            60,    90,  f"{gpu_util:>7.1f}%")
    s_gmem  = _colour(gpu_used / max(gpu_total, 1) * 100, 70, 90, f"{gpu_mem_s:>12}")
    s_gtemp = _colour(gpu_temp,            75,    85,  f"{gpu_temp:>5.0f} C")

    print(
        f"{row['ts']:>8}  {s_pcpu}  {s_scpu}  {s_ram}  {s_sram}  "
        f"{row['threads']:>7}  {s_gutil}  {s_gmem}  {s_gtemp}"
    )


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(rows: list, pid: int, proc_name: str):
    if not rows:
        print("No samples collected.")
        return

    def stat(key):
        vals = [r[key] for r in rows if key in r]
        if not vals:
            return "n/a", "n/a", "n/a"
        return f"{min(vals):.1f}", f"{sum(vals)/len(vals):.1f}", f"{max(vals):.1f}"

    sep = "-" * 60
    print(f"\n{_C['bold']}{sep}")
    print(f"  PROFILING SUMMARY  --  PID {pid}  ({proc_name})")
    print(f"  {len(rows)} samples  .  {rows[0]['ts']} -> {rows[-1]['ts']}")
    print(f"{sep}{_C['reset']}")

    metrics = [
        ("Process CPU %",    "proc_cpu_pct",   "%"),
        ("System CPU %",     "sys_cpu_pct",    "%"),
        ("Process RAM",      "proc_rss_mb",    "MB"),
        ("System RAM %",     "sys_ram_pct",    "%"),
        ("Threads",          "threads",        ""),
        ("GPU utilisation",  "gpu_util_pct",   "%"),
        ("GPU mem used",     "gpu_mem_used_mb","MB"),
        ("GPU temp",         "gpu_temp_c",     "°C"),
    ]

    print(f"  {'Metric':<22} {'Min':>8}  {'Avg':>8}  {'Max':>8}")
    print(f"  {'-'*22} {'-'*8}  {'-'*8}  {'-'*8}")
    for label, key, unit in metrics:
        lo, avg, hi = stat(key)
        print(f"  {label:<22} {lo+unit:>8}  {avg+unit:>8}  {hi+unit:>8}")

    # Bottleneck hint
    gpu_avg = float(stat("gpu_util_pct")[1]) if stat("gpu_util_pct")[1] != "n/a" else 0
    cpu_avg = float(stat("sys_cpu_pct")[1])
    ram_avg = float(stat("proc_rss_mb")[1])
    gpu_mem_avg = float(stat("gpu_mem_used_mb")[1]) if stat("gpu_mem_used_mb")[1] != "n/a" else 0
    gpu_mem_total = max((r.get("gpu_mem_total_mb", 0) for r in rows), default=0)

    print(f"\n  {_C['bold']}Bottleneck analysis:{_C['reset']}")
    if gpu_avg < 30:
        print(f"  {_C['yellow']}[!!] GPU util avg {gpu_avg:.0f}% - pipeline is NOT GPU-bound.")
        print(f"    Likely bottleneck: CPU pre-processing or RTSP decode.{_C['reset']}")
    elif gpu_avg > 85:
        print(f"  {_C['red']}[!!] GPU util avg {gpu_avg:.0f}% - GPU saturated. Consider reducing cameras or FPS.{_C['reset']}")
    else:
        print(f"  {_C['green']}[OK] GPU util avg {gpu_avg:.0f}% - healthy range.{_C['reset']}")

    if gpu_mem_total > 0:
        gpu_mem_pct = gpu_mem_avg / gpu_mem_total * 100
        if gpu_mem_pct > 85:
            print(f"  {_C['red']}[!!] GPU mem avg {gpu_mem_pct:.0f}% - near limit. Risk of OOM.{_C['reset']}")
        else:
            print(f"  {_C['green']}[OK] GPU mem avg {gpu_mem_pct:.0f}% of {gpu_mem_total:.0f} MB.{_C['reset']}")

    if cpu_avg > 80:
        print(f"  {_C['red']}[!!] System CPU avg {cpu_avg:.0f}% - high. Check ORT intra_op_threads.{_C['reset']}")

    if ram_avg > 2000:
        print(f"  {_C['yellow']}[!!] Process RAM avg {ram_avg:.0f} MB - consider gallery size and buffer limits.{_C['reset']}")

    print(f"  {'-'*60}\n")


# ── CSV ───────────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "ts", "proc_cpu_pct", "sys_cpu_pct", "proc_rss_mb", "proc_vms_mb",
    "sys_ram_used_gb", "sys_ram_pct", "threads",
    "gpu_util_pct", "gpu_mem_util_pct", "gpu_mem_used_mb", "gpu_mem_total_mb", "gpu_temp_c",
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline hardware profiler")
    parser.add_argument("--pid",      type=int,   default=-1,   help="Pipeline PID (auto-detect)")
    parser.add_argument("--interval", type=float, default=2.0,  help="Sample interval seconds")
    parser.add_argument("--duration", type=float, default=0,    help="Stop after N seconds (0=forever)")
    parser.add_argument("--out",      type=str,   default="",   help="CSV output path")
    parser.add_argument("--no-csv",   action="store_true",      help="Disable CSV output")
    args = parser.parse_args()

    # Resolve PID
    pid = args.pid
    if pid == -1:
        pid = find_pipeline_pid()
    if pid == -1:
        print("Pipeline process not found. Start the pipeline first, then run this script.")
        sys.exit(1)

    try:
        proc = psutil.Process(pid)
        proc_name = " ".join(proc.cmdline())[-60:]
    except psutil.NoSuchProcess:
        print(f"PID {pid} not found.")
        sys.exit(1)

    # CSV path
    csv_path = None
    csv_writer = None
    csv_file = None
    if not args.no_csv:
        ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = args.out or f"logs/profile_{ts_tag}.csv"
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        csv_file = open(csv_path, "w", newline="")
        csv_writer = csv.DictWriter(csv_file, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        csv_writer.writeheader()

    print(f"{_C['bold']}Ha-Meem Pipeline Profiler{_C['reset']}")
    print(f"PID: {pid}  |  interval: {args.interval}s  |  CSV: {csv_path or 'disabled'}")
    print("Press Ctrl+C to stop.\n")

    # Warm-up: first cpu_percent call always returns 0.0
    proc.cpu_percent()
    psutil.cpu_percent()

    rows = []
    start = time.time()

    try:
        while True:
            gpu = query_gpu()

            try:
                row = sample(proc, gpu)
            except RuntimeError as e:
                print(f"\n{_C['red']}{e}{_C['reset']}")
                break

            rows.append(row)
            print_row(row)

            if csv_writer:
                csv_writer.writerow(row)
                csv_file.flush()

            if args.duration > 0 and (time.time() - start) >= args.duration:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        if csv_file:
            csv_file.close()
        if csv_path and rows:
            print(f"\nCSV saved -> {csv_path}")

    print_summary(rows, pid, proc_name)


if __name__ == "__main__":
    main()
