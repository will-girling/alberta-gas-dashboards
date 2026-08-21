"""Refresh every NGTL feed and rebuild the dashboard's inputs.

One entry point so everything runs on the same schedule rather than CSR
being automated and the rest being remembered by hand.

Steps, in dependency order:

  1. download_csr_v3.py          intraday CSR observations
  2. download_and_compile_gdsr.py   daily gas-day reports (+ compile)
  3. download_outages.py         new tracker publications
  4. prepare_outage_areas.py     capacity-area polygons and base capability
  5. prepare_bc_pipelines.py     BC Energy Regulator transmission lines
  6. download_westcoast.py       Westcoast/BC Pipeline critical notices
  7. prepare_outages.py          outage master, from the newest publication
  8. prepare_outage_changes.py   publication-over-publication diff
  9. slim_map_layers.py          browser-sized copies of the map layers

Steps 4-6 depend on 3, and 5 depends on 4 for its fallback base series,
so order matters. The GIS preparation scripts (pipelines, installations,
TC stations) are deliberately absent: their sources are static PDFs and
shapefiles that only change when TC or AER republish, and re-running them
nightly would burn minutes for no change. Run those by hand after a
source refresh.

Design notes
------------
- A failing step never blocks the others. A TC endpoint being down should
  not stop the outage diff from rebuilding, so each step is isolated and
  the run continues.
- Every step is idempotent: downloaders skip what they already hold and
  preparation scripts rebuild from scratch, so running this more often
  than the data changes is harmless.
- The exit code is non-zero if any step failed, so launchd surfaces it.

Usage
-----
    python3 refresh_ngtl.py              # everything
    python3 refresh_ngtl.py --skip gdsr  # everything except GDSR
    python3 refresh_ngtl.py --only outages prepare
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
LOG_FILE = PROJECT_ROOT / "refresh_log.json"

PYTHON = sys.executable

# name, script, arguments, per-step timeout in seconds
STEPS: list[tuple[str, str, list[str], int]] = [
    ("csr", "download_csr_v3.py", [], 300),
    ("gdsr", "download_and_compile_gdsr.py", [], 900),
    ("outages", "download_outages.py", ["--limit", "5"], 600),
    ("areas", "prepare_outage_areas.py", [], 180),
    ("bc", "prepare_bc_pipelines.py", [], 300),
    ("westcoast", "download_westcoast.py", [], 300),
    ("prepare", "prepare_outages.py", [], 180),
    ("changes", "prepare_outage_changes.py", [], 180),
    # Last: rebuilds the browser-sized copies of whatever the steps above
    # regenerated, so processed/map/ can never lag processed/.
    ("slim", "slim_map_layers.py", [], 300),
]


def run_step(name: str, script: str, args: list[str], timeout: int) -> dict:
    path = PROJECT_ROOT / script
    started = time.time()

    if not path.exists():
        print(f"  SKIPPED {name}: {script} not found")
        return {"step": name, "status": "missing", "seconds": 0}

    print(f"\n=== {name} ({script}) " + "=" * (46 - len(name) - len(script)))
    try:
        result = subprocess.run(
            [PYTHON, str(path), *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  TIMED OUT after {timeout}s")
        return {"step": name, "status": "timeout", "seconds": timeout}

    elapsed = round(time.time() - started, 1)
    tail = [ln for ln in result.stdout.strip().split("\n") if ln.strip()][-6:]
    for line in tail:
        print(f"  {line}")

    if result.returncode != 0:
        error = result.stderr.strip().split("\n")[-1] if result.stderr else ""
        print(f"  FAILED (exit {result.returncode}) {error}")
        return {
            "step": name, "status": "failed", "seconds": elapsed,
            "exit_code": result.returncode, "error": error[:400],
        }

    print(f"  ok ({elapsed}s)")
    return {"step": name, "status": "ok", "seconds": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", metavar="STEP",
                        help="run only these steps")
    parser.add_argument("--skip", nargs="*", metavar="STEP", default=[],
                        help="skip these steps")
    args = parser.parse_args()

    steps = STEPS
    if args.only:
        steps = [s for s in steps if s[0] in args.only]
    steps = [s for s in steps if s[0] not in args.skip]

    started = datetime.now()
    print(f"NGTL refresh starting {started:%Y-%m-%d %H:%M:%S}")
    print(f"  python: {PYTHON}")
    print(f"  steps : {', '.join(s[0] for s in steps)}")

    results = [run_step(*step) for step in steps]

    ok = [r for r in results if r["status"] == "ok"]
    bad = [r for r in results if r["status"] not in ("ok", "missing")]

    summary = {
        "run_started": started.isoformat(timespec="seconds"),
        "run_finished": datetime.now().isoformat(timespec="seconds"),
        "total_seconds": round((datetime.now() - started).total_seconds(), 1),
        "succeeded": [r["step"] for r in ok],
        "failed": bad,
        "results": results,
    }
    LOG_FILE.write_text(json.dumps(summary, indent=1), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"{len(ok)}/{len(results)} steps ok in "
          f"{summary['total_seconds']:.0f}s")
    if bad:
        print("failed: " + ", ".join(
            f"{r['step']} ({r['status']})" for r in bad
        ))
    print(f"log: {LOG_FILE.name}")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
