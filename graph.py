"""
graph.py — plot centered trajectories from a tracking CSV.

Usage:
    python graph.py                                   # uses output/tracking.csv
    python graph.py --csv output/20_min/tracking_20_min.csv --output output/20_min
"""

import argparse
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

PIXEL_SIZE = 0.349   # µm / pixel — must match auto_tracking.py


def plot_trajectories(csv_path, output_folder):
    df = pd.read_csv(csv_path)
    plt.figure(figsize=(10, 10))

    for particle, group in df.groupby("particle"):
        if len(group) < 5:
            continue
        x = (group["x"] - group["x"].iloc[0]) * PIXEL_SIZE
        y = (group["y"] - group["y"].iloc[0]) * PIXEL_SIZE
        plt.plot(x, y, marker=".", markersize=1, linewidth=0.5, alpha=0.3)

    plt.scatter(0, 0, s=100, color="black", zorder=5)
    plt.title(f"Centered Cell Trajectories\n{Path(csv_path).name}")
    plt.xlabel("Relative X (µm)")
    plt.ylabel("Relative Y (µm)")
    plt.grid(True)
    plt.axis("equal")
    plt.tight_layout()

    save_path = os.path.join(output_folder, "centered_trajectory_graph.png")
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"  Trajectory graph saved: {save_path}")


def main():
    ap = argparse.ArgumentParser(description="Plot centered trajectories from tracking CSV")
    ap.add_argument("--csv",    default="output/tracking.csv",
                    help="Path to tracking CSV")
    ap.add_argument("--output", default="output",
                    help="Folder to save the graph")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    plot_trajectories(args.csv, args.output)


if __name__ == "__main__":
    main()
