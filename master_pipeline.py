"""
master_pipeline.py — track all timepoints then run the full motility analysis.

Steps:
  1. auto_tracking.py on each timepoint folder → one CSV per timepoint
  2. analyze_motility.py on all CSVs together  → cross-timepoint comparison
  3. graph.py on each CSV                      → centered trajectory plots

Usage:
    python master_pipeline.py
"""

import subprocess
import sys
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PY = sys.executable

# ── calibration ───────────────────────────────────────────────────────────────
PIXEL_SIZE = 0.349          # µm/pixel (set in auto_tracking.py)
PX_PER_UM  = round(1.0 / PIXEL_SIZE, 4)   # ≈ 2.87
FPS        = 10

# ── locate timepoint folders inside test-data/ ───────────────────────────────
TEST_DATA = SCRIPT_DIR / "test-data"
OUTPUT    = SCRIPT_DIR / "output"
OUTPUT.mkdir(exist_ok=True)

# Group images by timepoint label extracted from filenames
timepoints = {}
for f in sorted(TEST_DATA.glob("*.tiff"), key=lambda p: (re.search(r'(\d+)_min', p.name).group(0) if re.search(r'(\d+)_min', p.name) else "", int(re.findall(r'\d+', p.stem)[-1]))):
    m = re.search(r'(\d+)_min', f.name)
    if m:
        tp_label = m.group(0)          # e.g. "20_min"
        timepoints.setdefault(tp_label, []).append(f)

if not timepoints:
    print("No timepoint images found in test-data/. Exiting.")
    sys.exit(1)

print(f"Found {len(timepoints)} timepoints: {', '.join(sorted(timepoints))}")
print()

# ── STEP 1: track each timepoint ─────────────────────────────────────────────
csv_files = []
for tp_label in sorted(timepoints):
    tp_out = OUTPUT / tp_label
    tp_out.mkdir(exist_ok=True)

    # Write a temp folder with symlinks so auto_tracking sees a clean images/ dir
    tmp_images = tp_out / "images"
    tmp_images.mkdir(exist_ok=True)
    for f in timepoints[tp_label]:
        link = tmp_images / f.name
        if not link.exists():
            link.symlink_to(f.resolve())

    print(f"{'='*55}")
    print(f"  Tracking {tp_label}  ({len(timepoints[tp_label])} frames)")
    print(f"{'='*55}")
    subprocess.run([
        PY, str(SCRIPT_DIR / "auto_tracking.py"),
        "--input",  str(tmp_images),
        "--output", str(tp_out),
        "--label",  tp_label,
    ], check=True)

    csv_path = tp_out / f"tracking_{tp_label}.csv"
    if csv_path.exists():
        csv_files.append(str(csv_path))
    print()

# ── STEP 2: motility analysis across all timepoints ──────────────────────────
if not csv_files:
    print("No tracking CSVs produced — aborting analysis.")
    sys.exit(1)

print(f"{'='*55}")
print(f"  Motility analysis ({len(csv_files)} timepoints)")
print(f"{'='*55}")
analysis_out = OUTPUT / "motility_analysis"
subprocess.run([
    PY, str(SCRIPT_DIR / "analyze_motility.py"),
    *csv_files,
    "--fps",        str(FPS),
    "--px-per-um",  str(PX_PER_UM),
    "--output-dir", str(analysis_out),
], check=True)
print()

# ── STEP 3: trajectory graph per timepoint ───────────────────────────────────
print(f"{'='*55}")
print("  Trajectory graphs")
print(f"{'='*55}")
for csv_path in csv_files:
    subprocess.run([
        PY, str(SCRIPT_DIR / "graph.py"),
        "--csv",    csv_path,
        "--output", str(Path(csv_path).parent),
    ], check=True)

print()
print("ALL DONE")
print(f"Results → {analysis_out}")
