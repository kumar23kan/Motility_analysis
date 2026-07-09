"""
auto_tracking.py — detect and link bacterial cells in a folder of .tiff frames.

Usage:
    python auto_tracking.py                          # uses images/ → output/
    python auto_tracking.py --input test-data/20_min_frames --output output/20min
    python auto_tracking.py --input images/ --label T10_20min
"""

import os
import re
import argparse
import cv2
import numpy as np
import pandas as pd
import trackpy as tp
from glob import glob
from pathlib import Path

# ===============================
# DEFAULT SETTINGS
# ===============================
PIXEL_SIZE   = 0.349   # µm / pixel  (images resized to half of original)
FPS          = 10

DIAMETER     = 9       # feature diameter in pixels (must be odd)
MIN_MASS     = 200     # minimum integrated brightness — raise to reject background
                       # (50 was too low: dim noise and debris passed through)
SEARCH_RANGE = 8       # max displacement (px) between frames to link the same cell
MEMORY       = 3       # frames a cell may vanish and still be re-linked

# ===============================
# NOTE for analyze_motility.py
# ===============================
# Pass these flags when analysing the CSV produced here:
#   --fps 10  --px-per-um 2.87   (= 1 / PIXEL_SIZE)


def numeric_sort_key(path):
    """Sort filenames by the last integer found, so frame_9 < frame_10."""
    nums = re.findall(r'\d+', Path(path).stem)
    return int(nums[-1]) if nums else 0


def run_tracking(input_folder, output_folder, label=""):
    os.makedirs(output_folder, exist_ok=True)

    pattern = [
        os.path.join(input_folder, "*.tiff"),
        os.path.join(input_folder, "*.tif"),
    ]
    files = sorted(
        [f for p in pattern for f in glob(p)],
        key=numeric_sort_key,
    )

    if not files:
        raise RuntimeError(f"No .tiff/.tif images found in '{input_folder}/'")

    # ── Load + preprocess ──────────────────────────────────────────────────
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    frames = []
    for f in files:
        img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"  WARNING: could not read {f}, skipping", flush=True)
            continue
        img = cv2.resize(img, (1232, 1028))
        # CLAHE: gentle local contrast enhancement without boosting noise
        img = clahe.apply(img)
        img = cv2.GaussianBlur(img, (3, 3), 0)
        frames.append(img)

    print(f"  Loaded {len(frames)} frames from '{input_folder}'", flush=True)

    # ── Detect ────────────────────────────────────────────────────────────
    features = tp.batch(frames, diameter=DIAMETER, minmass=MIN_MASS, processes=1)
    print(f"  Detected {len(features):,} features", flush=True)

    # ── Link ──────────────────────────────────────────────────────────────
    tracks = tp.link_df(features, search_range=SEARCH_RANGE, memory=MEMORY)
    n_tracks = tracks["particle"].nunique()
    print(f"  Linked into {n_tracks:,} tracks", flush=True)

    # ── Save CSV ──────────────────────────────────────────────────────────
    tag = f"_{label}" if label else ""
    csv_path = os.path.join(output_folder, f"tracking{tag}.csv")
    tracks.to_csv(csv_path, index=False)
    print(f"  CSV saved: {csv_path}", flush=True)

    # ── Save raw video ────────────────────────────────────────────────────
    h, w = frames[0].shape
    raw_path = os.path.join(output_folder, f"raw_video{tag}.avi")
    writer1 = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*"XVID"), FPS, (w, h), False)
    for fr in frames:
        writer1.write(fr)
    writer1.release()
    print(f"  Raw video saved: {raw_path}", flush=True)

    # ── Save trajectory video ─────────────────────────────────────────────
    traj_path = os.path.join(output_folder, f"trajectory_video{tag}.avi")
    writer2 = cv2.VideoWriter(traj_path, cv2.VideoWriter_fourcc(*"XVID"), FPS, (w, h))
    for i, fr in enumerate(frames):
        color = cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR)
        subset = tracks[tracks["frame"] <= i]
        for pid in subset["particle"].unique():
            d = subset[subset["particle"] == pid]
            pts = d[["x", "y"]].values.astype(int)
            for j in range(1, len(pts)):
                cv2.line(color, tuple(pts[j - 1]), tuple(pts[j]), (0, 255, 0), 1)
        bar_px = int(50 / PIXEL_SIZE)
        x1, y1 = 40, h - 40
        cv2.line(color, (x1, y1), (x1 + bar_px, y1), (255, 255, 255), 4)
        cv2.putText(color, "50 um", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        writer2.write(color)
    writer2.release()
    print(f"  Trajectory video saved: {traj_path}", flush=True)

    return csv_path


def main():
    ap = argparse.ArgumentParser(description="Detect and track bacteria in .tiff frames")
    ap.add_argument("--input",  default="images",  help="Folder containing .tiff frames")
    ap.add_argument("--output", default="output",  help="Folder for CSV and videos")
    ap.add_argument("--label",  default="",        help="Label appended to output filenames")
    args = ap.parse_args()

    run_tracking(args.input, args.output, args.label)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
