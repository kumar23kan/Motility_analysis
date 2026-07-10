# Bacterial Motility Analysis Tool

End-to-end pipeline for tracking and analysing bacterial motility from TIFF microscopy images.
Produces 25 motility metrics per timepoint plus cross-timepoint statistical comparisons.

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
| G-force axis (°) | 90 | Direction of G-force in image coordinates — degrees clockwise from +X (right). 90 = downward (+Y), the default for a horizontally-mounted microscope with gravity pointing down. Used only by the gravitaxis analysis (#21). |

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

# Set G-force direction (e.g. centrifuge oriented to the right = 0°)
python3 analyze_motility.py tracking.csv --gforce-axis-deg 0
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
      …  (25 analyses × plots + CSVs)
```

---

## The 25 motility analyses

### Per-timepoint analyses

| # | Analysis | Key output | Biophysical question |
|---|----------|-----------|----------------------|
| 1 | Swimming speed | mean, median, std, P10/P90 µm/s | How fast are cells swimming? |
| 2 | Mean Squared Displacement (MSD) | D (µm²/s), α, motion type | Is motion directed, diffusive, or confined (population average)? |
| 3 | Directional autocorrelation | persistence time τ_p, persistence length | How long does a cell maintain its swimming direction? |
| 4 | Run-and-tumble | run length, tumble frequency, tumble fraction | How often do cells change direction? |
| 5 | Drift vector | magnitude and angle of population drift | Is there a net collective drift in one direction? |
| 6 | Population heterogeneity | slow / normal / hyper-motile fractions | What fraction of cells are highly motile vs barely moving? |
| 7 | Boundary collisions | frequency per cell per second | How often do cells encounter the arena wall? |
| 8 | Bacteria–bacteria collisions | frequency per cell per second | How often do cells collide with each other? |
| 9 | Velocity autocorrelation (VACF) | zero-crossing time | How quickly does a cell's velocity decorrelate from itself? |
| 10 | Turning angle distribution | forward-biased step fraction | Are cells biased toward straight runs or sharp turns? |
| 11 | Track curvature | mean absolute curvature (rad/µm) | How curved are swimming paths? |
| 12 | Confinement ratio | end-to-end / total path length | How far do cells travel from their starting point relative to total path? |
| 13 | Speed–persistence correlation | Pearson r | Do faster cells also swim straighter? |
| 14 | Non-Gaussianity α₂ | peak α₂ | Is displacement heterogeneous beyond what Gaussian statistics predict? |
| 15 | Active / stationary phases | mean active fraction per track | What fraction of each cell's time is spent actively swimming? |
| 16 | Speed–track-length correlation | Pearson r | Do longer-lived tracks belong to faster or slower cells? |
| 17 | Pair correlation g(r) | spatial clustering profile | Are cells spatially clustered or uniformly distributed? |
| 18 | Spatial velocity correlation C_v(r) | collective alignment length scale | At what distance does collective swimming alignment decay? |
| 19 | Near-wall speed profile | speed vs distance from boundary | Do cells near walls swim differently from cells in the bulk? |
| 20 | Per-track α distribution | histogram of individual MSD exponents | Are all cells the same motion type, or is there a mixture of confined/diffusive/directed cells? |
| 21 | Gravitaxis / G-force directional bias | bias index, p-value, rose diagram | Do cells preferentially swim toward or away from the G-force direction? |
| 22 | Motility state dwell-time analysis | mean active/stationary dwell times, switching rates | How long do cells stay active or stationary before switching? Relates to flagellar motor switching rate. |
| 23 | Multi-feature behavioral clustering | cluster labels, fractions, scatter matrix | What distinct behavioral phenotypes exist in the population, defined by speed + motion type + path shape? |
| 24 | Polar order parameter φ | φ vs time (0 = random, 1 = fully aligned) | Does collective swimming alignment emerge or break down over time? |
| 25 | Speed power spectral density (PSD) | frequency spectrum of speed fluctuations | Are there characteristic frequencies in swimming activity? Changes in peak frequency indicate motor-level biophysical shifts. |

### Cross-timepoint analyses (when >1 CSV supplied)

| Analysis | Output |
|----------|--------|
| Speed comparison | Box/violin plot across all conditions |
| Motility timeseries | Key metrics plotted vs timepoint |
| Subpopulation evolution | Slow/normal/hyper fractions across timepoints |
| Statistical comparisons | Pairwise KS test + Mann-Whitney U p-values (`statistical_comparisons.csv`) |
