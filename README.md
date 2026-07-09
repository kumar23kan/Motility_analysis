# Bacterial Motility Analysis Tool

End-to-end pipeline for tracking and analysing bacterial motility from TIFF microscopy images.
Produces 19 motility metrics per timepoint plus cross-timepoint statistical comparisons.

---

## Requirements

Python 3.9+ and the following packages:

| Package | Purpose |
|---------|---------|
| numpy ≥ 1.24 | Numerical computing |
| pandas ≥ 1.5 | Data handling |
| matplotlib ≥ 3.6 | Plotting |
| scipy ≥ 1.10 | Statistics |
| opencv-python-headless ≥ 4.7 | Image preprocessing |
| trackpy ≥ 0.6 | Particle tracking |
| Pillow ≥ 9.0 | GUI image display |

`tkinter` is included with most Python installations.

Install all dependencies:

```bash
pip install -r requirements.txt
```

---

## Quick start — GUI

```bash
python3 motility_gui.py
```

The GUI has three tabs:

### 🔬 Full Pipeline

Runs the complete workflow: image folders → tracking → motility analysis → trajectory graphs.

1. Click **＋ Add** to add one image folder per timepoint (folder must contain `.tiff`/`.tif` frames)
2. *(Optional)* Click **"🔬 Preview cell detection on a frame…"** in the Tracking sub-tab to tune parameters visually before running (see [Parameter Tuner](#parameter-tuner) below)
3. *(Optional)* Draw a **polygonal ROI mask** to restrict analysis to a specific region (see [ROI Mask](#roi-mask) below)
4. Click **▶ Run Full Pipeline**

Output appears in the configured output folder (default: `output/`).

#### Tracking parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Pixel size (µm/px) | 0.349 | Spatial calibration after image resize |
| FPS | 10 | Camera frame rate |
| Feature diameter (px) | 9 | Odd integer ≈ apparent cell width in pixels |
| Min mass | 200 | Minimum integrated brightness — raise to reject background |
| Search range (px) | 8 | Max cell displacement between frames |
| Memory (frames) | 3 | Frames a cell may disappear and still be re-linked |

#### Analysis parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Min track length | 10 | Frames — shorter tracks excluded |
| ep max | 1.0 | Max localisation error \|ep\| to keep |
| Min mass (post-track) | 0 | Extra brightness filter after tracking (0 = off) |
| Bacterium radius (µm) | 0.5 | Used for boundary and cell–cell collision detection |
| Tumble angle (°) | 90 | Direction change above this → classified as tumble |
| Max lag (frames) | 20 | Maximum lag for MSD and autocorrelation |
| Stationary speed (µm/s) | 0.5 | Steps slower than this → classified as stationary |

### 📊 Analysis Only

Load pre-tracked trackpy CSV files directly and run only the motility analysis (skips tracking).
Useful when you already have tracking CSVs from a previous run or from another tool.

### 📈 Results

Browse and view all output files after a run:

- **File tree** — navigate `output/` with icons: 🖼 images, 📊 CSVs, 🎬 videos
- **Image viewer** — click any `.tiff`/`.png` to display it; zoom with mouse wheel or buttons; **Fit** / **1:1** controls
- **CSV viewer** — click any `.csv` to view the table (up to 300 rows)
- **Video** — click any `.avi` and use **Open in app** to play in your system player
- Auto-refreshes after every pipeline run

---

## Parameter Tuner

Open from the **Tracking** sub-tab → **"🔬 Preview cell detection on a frame…"**

Loads all TIFF frames from the first selected folder (with the same CLAHE + Gaussian preprocessing used by the tracker), then runs detection on demand as you adjust sliders:

- **Feature diameter** — slide to match the apparent pixel width of your bacteria; circles on the image show the exact size used
- **Min mass** — raise until background spots disappear; lower if real cells are being missed
- **Frame slider** — browse all frames to check detection is consistent
- **Stats panel** — live count, mass range, mean mass, physical cell size in µm
- **✓ Apply to Pipeline** — writes the tuned values back to the Tracking tab

---

## ROI Mask

In the **Full Pipeline** tab, the **Polygonal ROI Mask** section (below the parameter tabs) lets you define an arbitrary region of interest:

1. Click **Draw ROI on frame…** — opens an image editor showing the first TIFF frame
2. **Left-click** to place polygon vertices; **right-click** or **Z** to undo; **double-click** to confirm
3. The status bar shows the **masked area** (inside polygon, included in analysis) and **unmasked area** (excluded) in µm² as you draw

When the pipeline runs with an ROI:
- Detections **outside** the polygon are discarded before analysis
- Boundary collisions are computed as proximity to the **polygon edge** instead of a bounding rectangle
- ROI area, unmasked area, and vertex count are saved in `output/roi_polygon.json` and reported in `summary.csv`

---

## Command-line usage

### Full pipeline (all timepoints)

```bash
python3 master_pipeline.py
```

Scans `test-data/` for timepoint folders, runs tracking on each, then runs the motility analysis across all timepoints.

### Tracking only

```bash
python3 auto_tracking.py --input images/ --output output/20_min --label 20_min
```

### Motility analysis only

```bash
python3 analyze_motility.py output/20_min/tracking_20_min.csv \
    --fps 10 --px-per-um 2.87 --output-dir output/motility_analysis

# Multiple timepoints compared together
python3 analyze_motility.py output/*/tracking_*.csv \
    --fps 10 --px-per-um 2.87 --output-dir output/motility_analysis

# With polygonal ROI mask
python3 analyze_motility.py output/20_min/tracking_20_min.csv \
    --fps 10 --px-per-um 2.87 \
    --roi-polygon-file output/roi_polygon.json \
    --output-dir output/motility_analysis

# Skip slow steps on large datasets
python3 analyze_motility.py tracking.csv --skip-bac-bac --skip-gr
```

### Trajectory graphs

```bash
python3 graph.py --csv output/20_min/tracking_20_min.csv --output output/20_min
```

---

## Input format

Trackpy CSV with columns:

```
y, x, mass, size, ecc, signal, raw_mass, ep, frame, particle
```

Place TIFF image sequences in separate folders, one folder per timepoint:

```
test-data/
  T10_01-07-26_20_min_001.tiff
  T10_01-07-26_20_min_002.tiff
  ...
  T10_01-07-26_60_min_100.tiff
```

---

## Output structure

```
output/
  roi_polygon.json                  ← saved ROI polygon (if drawn)
  20_min/
    tracking_20_min.csv             ← trackpy detections and links
    raw_video_20_min.avi            ← preprocessed frames as video
    trajectory_video_20_min.avi     ← tracking overlay video
    centered_trajectory_graph.png   ← all tracks centred at origin
  30_min/ … 60_min/                 ← same structure per timepoint
  motility_analysis/
    summary.csv                     ← one row per timepoint, all metrics
    speed_comparison.tiff
    motility_timeseries.tiff
    subpopulation_evolution.tiff
    statistical_comparisons.csv     ← KS + Mann-Whitney p-values
    ks_pvalue_heatmap.tiff
    mw_pvalue_heatmap.tiff
    tracking_20_min/                ← per-timepoint plots and CSVs
      trajectories.tiff
      speed_distribution.tiff
      msd.tiff
      …  (19 analyses × plots + CSVs)
```

---

## The 19 motility analyses

| # | Analysis | Key output |
|---|----------|-----------|
| 1 | Swimming speed | mean, median, std, P10/P90 µm/s |
| 2 | Mean Squared Displacement (MSD) | D (µm²/s), α, motion type |
| 3 | Directional autocorrelation | persistence time τ_p, persistence length |
| 4 | Run-and-tumble | run length, tumble frequency, tumble fraction |
| 5 | Drift vector | population-level directional bias |
| 6 | Population heterogeneity | slow / normal / hyper-motile fractions |
| 7 | Boundary collisions | frequency per cell per second |
| 8 | Bacteria–bacteria collisions | frequency per cell per second |
| 9 | Velocity autocorrelation (VACF) | zero-crossing time |
| 10 | Turning angle distribution | forward-biased step fraction |
| 11 | Track curvature | mean absolute curvature (rad/µm) |
| 12 | Confinement ratio | end-to-end / total path length |
| 13 | Speed–persistence correlation | Pearson r |
| 14 | Non-Gaussianity α₂ | peak α₂ |
| 15 | Active / stationary phases | mean active fraction per track |
| 16 | Speed–track-length correlation | Pearson r |
| 17 | Pair correlation g(r) | spatial clustering |
| 18 | Spatial velocity correlation C_v(r) | collective motion range |
| 19 | Near-wall speed profile | speed vs distance from boundary |

Cross-timepoint analyses (when >1 CSV supplied): speed comparison, motility timeseries, subpopulation evolution, pairwise KS and Mann-Whitney U tests.
