# Bacterial Motility Analysis — Parameter Reference

This document explains every parameter computed by `analyze_motility.py`, what it measures biologically, and how to interpret the output values.

---

## Acquisition & Calibration Parameters

### `--fps` (frames per second)
The camera acquisition rate. Used to convert frame counts into real time.
- **Default**: 50.0 fps → 1 frame = 20 ms
- **Effect**: All speeds (µm/s), lag times (s), and frequencies (Hz) scale with this value. A wrong fps shifts every time-dependent result proportionally.

### `--px-per-um` (pixels per micron)
The spatial calibration factor linking image pixels to physical micrometres.
- **Default**: 50 px/µm → 1 pixel = 20 nm
- **Effect**: All distances (µm), speeds (µm/s), and arena dimensions scale with this value. Calibrate with a stage micrometer or known feature size.

### `--min-track-length`
Minimum number of consecutive frames a particle must be tracked to be included.
- **Default**: 10 frames = 200 ms at 50 fps
- **Why it matters**: Very short tracks contribute noise to MSD and autocorrelation. Increasing this threshold improves analysis quality but reduces the number of included tracks.

### `--ep-max`
Maximum permitted absolute localisation uncertainty `|ep|` (trackpy units).
- **Default**: 5.0
- **Why it matters**: Trackpy estimates position error for each detection. Detections with high `ep` are likely blurred, out-of-focus, or overlapping particles. Lowering this threshold keeps only the most precisely localised detections.

### `--bac-radius`
Physical radius of a single bacterium (µm), used as the collision distance threshold.
- **Default**: 0.5 µm (typical for *Acinetobacter baumannii* short-axis half-width)
- **Effect on collisions**: Two bacteria are considered to have collided when their centre-to-centre distance ≤ 2 × bac-radius. A bacterium is considered to have touched a wall when its centre is within 1 × bac-radius of the arena edge.

### `--tumble-angle`
Turning angle threshold (degrees) above which a direction change is classified as a tumble.
- **Default**: 90°
- **Interpretation**: Steps where the bacterium turns more than this angle are counted as tumbles; all others are part of a run. Lowering the threshold increases the apparent tumble frequency.

### `--max-lag`
Maximum lag time (frames) computed for MSD and autocorrelation analyses.
- **Default**: 20 frames = 400 ms at 50 fps
- **Constraint**: Should not exceed the median track length. Lag times much longer than the recording window produce unreliable ensemble averages.

### `--stationary-speed`
Speed threshold (µm/s) below which a step is considered stationary / non-motile.
- **Default**: 0.5 µm/s
- **Interpretation**: Used only for the active/stationary phase analysis. Steps slower than this threshold are classified as stationary pauses; faster steps are active swimming.

---

## Analysis 1 — Instantaneous Speed

Speed is computed as the displacement between consecutive frames divided by the inter-frame time interval (1/fps).

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `speed_mean_um_s` | Mean instantaneous speed across all steps (µm/s) | Average swimming velocity of the population |
| `speed_median_um_s` | Median instantaneous speed (µm/s) | Robust central tendency; less sensitive to fast outliers than the mean |
| `speed_std_um_s` | Standard deviation of speed (µm/s) | Speed heterogeneity within the population |
| `speed_p10_um_s` | 10th percentile speed (µm/s) | Lower bound of the typical speed range; represents the slowest swimmers |
| `speed_p90_um_s` | 90th percentile speed (µm/s) | Upper bound; represents the fastest swimmers |

**Typical values** for *A. baumannii* surface motility: 1–10 µm/s.  
**Hypergravity effect to look for**: a downward shift in mean/median speed or a change in the shape of the distribution.

---

## Analysis 2 — Mean Squared Displacement (MSD)

MSD(τ) = ⟨|r(t+τ) − r(t)|²⟩, the average squared displacement at lag time τ, fit to the power law:

> **MSD = 4D · τ^α**

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `msd_D_um2_s` | Effective diffusion coefficient D (µm²/s) | Magnitude of spatial exploration; not true Fickian diffusion for bacteria |
| `msd_alpha` | Anomalous exponent α (dimensionless) | Classifies the mode of motion (see table below) |
| `msd_motion_type` | Text label derived from α | Human-readable motion classification |

**Interpretation of α:**

| α range | Classification | Biological meaning |
|---------|---------------|-------------------|
| > 1.5 | Ballistic / Directed | Persistent straight-line swimming; strong motility |
| 0.9 – 1.5 | Diffusive | Random walk; no preferred direction |
| < 0.9 | Confined / Subdiffusive | Bacteria constrained by crowding, surface adhesion, or confined geometry |

---

## Analysis 3 — Directional Autocorrelation

C(τ) = ⟨cos(θ(t+τ) − θ(t))⟩  
Measures how well a bacterium remembers its swimming direction after a time lag τ. Fit to an exponential decay: C(τ) = exp(−τ / τ_p).

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `persistence_time_ms` | Persistence time τ_p (ms) | Time over which a bacterium maintains its swimming direction before randomising |
| `persistence_length_um` | τ_p × mean speed (µm) | Average distance swum before losing directional memory |

**C(τ) interpretation:**
- C(τ) = 1 → perfect direction memory (straight swimmers)
- C(τ) = 0 → no memory (random direction after lag τ)
- C(τ) < 0 → anti-persistence (bacteria tend to reverse direction)

**Note**: With a 2-second recording window (100 frames at 50 fps), the persistence time fit is reliable only if τ_p is well within the lag range measured. Very long τ_p values indicate the bacterium barely changes direction within the recording window.

---

## Analysis 4 — Run-and-Tumble Statistics

Steps with turning angle > `--tumble-angle` are tumbles; consecutive steps below the threshold form a run.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `run_mean_length_um` | Mean run length (µm) | Average straight-line distance covered between direction changes |
| `run_mean_duration_s` | Mean run duration (s) | Average time between tumbles |
| `tumble_freq_hz` | Tumble frequency (Hz = events/s) | How often bacteria change direction; inversely related to run duration |
| `tumble_fraction` | Fraction of all steps classified as tumbles | 0 = all straight; 1 = all tumbling; healthy swimmers typically 0.1–0.4 |
| `n_runs` | Total number of complete runs detected | Statistical support for the above metrics |

**Hypergravity effect to look for**: increased tumble frequency, shorter run lengths.

---

## Analysis 5 — Drift Vector

Net displacement per track from start to end position, averaged across all tracks.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `drift_magnitude_um` | Magnitude of the mean net displacement vector (µm) | True population-level directional bias; near zero if motion is isotropic |
| `drift_angle_deg` | Direction of the drift vector (degrees, 0° = +X) | Compass bearing of any net population movement |

**Interpretation**: If `drift_magnitude_um` is large relative to the mean run length, bacteria are collectively biased in one direction — this could indicate chemotaxis, gravitaxis, or flow artefact. A near-zero value confirms isotropic random motility.

---

## Analysis 6 — Population Heterogeneity

Each track is classified into a subpopulation based on its mean speed relative to the distribution:

| Subpopulation | Definition | Typical fraction |
|--------------|------------|-----------------|
| Slow | Mean speed ≤ 25th percentile | 25% by construction |
| Normal | Mean speed between 25th and 75th percentiles | 50% by construction |
| Hyper-motile | Mean speed ≥ 75th percentile | 25% by construction |

| Parameter | Definition |
|-----------|------------|
| `frac_slow` | Fraction of tracks in the slow subpopulation |
| `frac_normal` | Fraction of tracks in the normal subpopulation |
| `frac_hypermotile` | Fraction of tracks in the hyper-motile subpopulation |
| `slow_thresh_um_s` | Speed threshold separating slow from normal (µm/s) |
| `fast_thresh_um_s` | Speed threshold separating normal from hyper-motile (µm/s) |

**Note**: Because the thresholds are percentile-based within each dataset, fractions are always ~25/50/25 within a single file. The biologically informative comparison is the **absolute threshold speeds** across timepoints or conditions.

---

## Analysis 7 — Bacteria-to-Boundary Collision Frequency

A collision event is any detection within `bac_radius` of the nearest arena edge.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `boundary_events` | Total count of boundary proximity events | Raw number of wall contacts across the entire recording |
| `boundary_freq_per_cell_s` | Events / (n_tracks × duration) | Per-bacterium rate of wall contact (s⁻¹) |
| `boundary_left/right/top/bottom` | Count of events at each wall | Identifies asymmetric accumulation at specific surfaces |

**Biological context**: Many bacteria accumulate near surfaces due to hydrodynamic attraction. Hypergravity may reduce surface exploration or alter wall accumulation patterns.

---

## Analysis 8 — Bacteria-to-Bacteria Collision Frequency

Two bacteria are considered to have collided when their centre-to-centre distance ≤ 2 × `bac_radius`.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `bac_bac_events` | Total pairwise proximity events per frame | Raw collision count |
| `bac_bac_freq_per_cell_s` | Events / (n_tracks × duration) | Per-bacterium collision rate (s⁻¹) |

**Computational note**: KD-tree is used for efficient pairwise distance search. For very dense datasets (>10,000 bacteria/frame), use `--skip-bac-bac` to avoid long runtimes.

---

## Analysis 9 — Velocity Autocorrelation Function (VACF)

VACF(τ) = ⟨v(t) · v(t+τ)⟩ / ⟨v(0)²⟩  
Measures how well the velocity vector (magnitude and direction) is preserved over time. Normalised to 1 at τ = 0.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `vacf_zero_cross_ms` | Lag time at which VACF first crosses zero (ms) | Characteristic timescale of velocity decorrelation |

**Interpretation:**
- VACF decays from 1 to 0 as the bacterium loses its initial velocity direction.
- A slow decay → long-lived, persistent swimming.
- VACF < 0 (anti-correlated) → bacteria systematically reverse velocity, as seen in some surface-associated motility modes.
- VACF decays faster than directional autocorrelation C(τ) because VACF encodes both direction and speed fluctuations simultaneously.

---

## Analysis 10 — Turning Angle Distribution

The angular change Δθ between consecutive steps, computed for every valid step pair in every track. Expressed in degrees (−180° to +180°).

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `fwd_bias_frac_lt45deg` | Fraction of turns with \|Δθ\| < 45° | Proportion of near-straight steps; high value → persistent swimmers |

**Shape interpretation:**
- **Peaked near 0°**: bacteria predominantly swim straight — directed or persistent motion.
- **Broad / flat**: frequent large turns — highly tumbling or diffusive bacteria.
- **Peaked near ±180°**: bacteria reverse frequently — characteristic of *E. coli*-like run-reverse or surface-stuck cells.

---

## Analysis 11 — Track Curvature

Mean absolute curvature κ per track, estimated as |dθ/ds| (radians per micron of arc length), where θ is the swimming direction and s is the arc length along the track.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `mean_curvature_rad_um` | Population mean of per-track κ (rad/µm) | Average degree of circular swimming across all tracks |

**Interpretation:**
- Low κ (near 0) → straight-line swimmers.
- High κ → bacteria swimming in tight circles or spirals, often observed in surface-bound flagellated cells or cells near walls.
- Circular swimming near surfaces can indicate flagellar function, cell asymmetry, or hydrodynamic effects.

---

## Analysis 12 — Confinement Ratio (CR)

CR = end-to-end displacement / total path length, computed per track.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `mean_confinement_ratio` | Population mean CR (dimensionless, 0–1) | Average straightness of bacterial trajectories |

**Interpretation:**
- CR = 1 → perfectly straight track (ballistic).
- CR → 0 → track returns near its start (confined, circular, or caged).
- CR is a spatial counterpart to α from MSD: low CR is consistent with subdiffusive/confined motion.

---

## Analysis 13 — Speed–Persistence Correlation

Pearson correlation coefficient between per-track mean speed and per-track confinement ratio.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `speed_persistence_r` | Pearson r (−1 to +1) | Sign and strength of the speed–straightness relationship |
| `speed_persistence_p` | Two-sided p-value | Statistical significance of the correlation |

**Interpretation:**
- r > 0: faster bacteria also swim straighter (speed and persistence are linked — consistent with a single flagellar bundle driving both).
- r < 0: faster bacteria tumble more (speed increases with swimming activity but so does turning).
- r ≈ 0: speed and directionality are decoupled (independent phenotypes within the population).

---

## Analysis 14 — Non-Gaussianity Parameter α₂

α₂(τ) = ⟨r⁴(τ)⟩ / (2⟨r²(τ)⟩²) − 1  
Measures deviations from a Gaussian displacement distribution at each lag time.

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `non_gaussianity_peak` | Maximum α₂ observed across all lag times | Overall degree of population heterogeneity in motility |

**Interpretation:**
- α₂ = 0 at all lags → displacements are Gaussian; all bacteria are statistically equivalent (homogeneous population).
- α₂ > 0 → heavy-tailed distribution; some bacteria move much more than others at the same time lag. This is the hallmark of a **heterogeneous** population with coexisting fast and slow subpopulations.
- α₂ peaks at intermediate lag times in most bacterial populations, then returns toward 0 at long lags as the fast and slow subpopulations both spread.

---

## Analysis 15 — Active / Stationary Phase Segmentation

Each step is classified as active (speed ≥ `--stationary-speed`) or stationary (speed < threshold).

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `mean_frac_active` | Mean fraction of time each bacterium spends in the active phase | Overall motility engagement of the population |
| `frac_always_active` | Fraction of tracks with 100% active steps | Proportion of obligate swimmers |
| `frac_always_stationary` | Fraction of tracks with 0% active steps | Proportion of non-motile / attached bacteria |

**Biological context**: Bacteria can switch between swimming and surface attachment or stationary pauses. Under hypergravity, bacteria may spend more time stationary (sedimentation-driven attachment) or, conversely, show increased motility (stress response). This parameter directly quantifies the balance.

---

## Analysis 16 — Speed–Track-Length Correlation

Pearson correlation between per-track mean speed and track length (number of frames).

| Parameter | Definition | Biological meaning |
|-----------|------------|-------------------|
| `speed_tracklength_r` | Pearson r | Sign and strength of the relationship |
| `speed_tracklength_p` | Two-sided p-value | Statistical significance |

**Interpretation:**
- r < 0 (common): faster bacteria are tracked for fewer frames, likely because they move out of the focal plane or field of view sooner.
- r > 0: faster bacteria are detected more reliably for longer — suggests the tracking algorithm performs better on clearly-moving particles.
- A strong correlation here is a **detection bias** warning: the sample of long tracks may be enriched for slow bacteria, skewing population statistics.

---

## Analysis 17 — Pair Correlation Function g(r)

g(r) is the probability of finding a second bacterium at distance r from a given bacterium, normalised by the expectation for a uniform random (ideal gas) distribution.

| Output | Definition | Biological meaning |
|--------|------------|-------------------|
| `pair_correlation.csv` | g(r) vs r (µm) | Spatial organisation of the bacterial population |

**Interpretation:**
- g(r) = 1 at all r → bacteria are randomly distributed (no spatial order).
- g(r) > 1 at small r → bacteria cluster together (aggregation, biofilm nucleation).
- g(r) < 1 at small r → bacteria maintain minimum separation (steric exclusion or active avoidance).
- The first peak position in g(r) gives the typical nearest-neighbour distance.

---

## Analysis 18 — Spatial Velocity Correlation C_v(r)

C_v(r) = ⟨v̂ᵢ · v̂ⱼ⟩ averaged over all pairs (i, j) separated by distance r. Here v̂ is the unit velocity vector (direction only).

| Output | Definition | Biological meaning |
|--------|------------|-------------------|
| `spatial_velocity_corr.csv` | C_v(r) vs r (µm) | Extent of collective / coordinated swimming |

**Interpretation:**
- C_v(r) = 1 → all bacteria at separation r swim in the same direction (perfect collective motion).
- C_v(r) = 0 → swimming directions are uncorrelated at separation r.
- C_v(r) < 0 → bacteria at separation r tend to swim toward each other or in opposite directions.
- The **correlation length** (r at which C_v drops to ~1/e ≈ 0.37) is the spatial scale of collective behaviour.
- Collective motion is common in dense bacterial suspensions (bacterial turbulence); it tends to be suppressed by hypergravity if cells are pushed toward surfaces.

---

## Analysis 19 — Near-Wall Speed Profile

Mean speed binned by the distance of each bacterium from the nearest arena wall.

| Output | Definition | Biological meaning |
|--------|------------|-------------------|
| `near_wall_speed.csv` | Mean ± std speed (µm/s) vs distance to wall (µm) | How bacterial swimming speed varies with proximity to surfaces |

**Interpretation:**
- Flat profile → surface proximity does not affect swimming.
- Speed drops near walls → hydrodynamic braking, surface adhesion slowing bacteria.
- Speed increases near walls → bacteria that reach the wall are still actively swimming (wall-following behaviour), while those far from walls are diffusing.
- Under hypergravity, bacteria may sediment toward the bottom wall; the near-wall profile then reflects the behaviour of the most gravity-affected subpopulation.

---

## Cross-File Analyses (≥ 2 input files)

### Motility Time Series (`motility_timeseries.tiff`)
Plots of key scalar metrics across all input files in the order they were supplied. Useful for visualising how motility evolves across experimental timepoints (e.g., 16 h, 18 h, 23 h).

### Subpopulation Fraction Evolution (`subpopulation_evolution.tiff`)
Stacked bar chart showing the slow / normal / hyper-motile fractions at each timepoint. Reveals whether the proportion of hyper-motile bacteria increases or decreases over time under hypergravity.

### Statistical Comparisons (`statistical_comparisons.csv`)
Pairwise hypothesis tests on the instantaneous speed distributions between all pairs of input files:

| Statistic | Definition | Interpretation |
|-----------|------------|---------------|
| `ks_statistic` | Kolmogorov-Smirnov test statistic D | Maximum absolute difference between the two cumulative speed distributions |
| `ks_pvalue` | KS test p-value | p < 0.05 → the two speed distributions are statistically different |
| `mw_statistic` | Mann-Whitney U statistic | Non-parametric rank-sum comparison |
| `mw_pvalue` | Mann-Whitney p-value | p < 0.05 → significant difference in median speed |
| `mean_diff_um_s` | Difference of means (condition 1 − condition 2, µm/s) | Magnitude of the speed shift between the two conditions |

**KS pvalue heatmap** (`ks_pvalue_heatmap.tiff`): cells coloured red (p < 0.05, significant) to green (p > 0.05, not significant). Use this to identify which timepoints differ most from each other.

---

## Interpreting Results in the Context of Hypergravity

| Observation | Likely biological interpretation |
|-------------|----------------------------------|
| Lower `speed_mean_um_s` under G-force | Motility suppressed by gravitational stress |
| Lower `msd_alpha` (more confined) | Bacteria less able to explore space; sedimentation-enhanced crowding |
| Higher `tumble_freq_hz` | Increased directional randomisation; stress-response |
| Lower `mean_confinement_ratio` | More circular / confined trajectories |
| Higher `non_gaussianity_peak` | Increased population heterogeneity; subpopulations responding differently to G-force |
| Lower `mean_frac_active` | More bacteria in stationary/attached phase under higher gravity |
| Asymmetric `boundary_left/right/top/bottom` | Net gravitational drift toward one wall |
| Decreased C_v(r) correlation length | Collective swimming broken up by gravity-driven sedimentation |
| Speed drops near bottom wall | Surface accumulation with speed reduction at the sedimenting surface |

---

## Output File Reference

```
motility_analysis/
├── summary.csv                       ← all scalar metrics, one row per file
├── statistical_comparisons.csv       ← pairwise KS + MW tests
├── speed_comparison.tiff
├── motility_timeseries.tiff
├── subpopulation_evolution.tiff
├── ks_pvalue_heatmap.tiff
├── mw_pvalue_heatmap.tiff
└── <file_stem>/
    ├── trajectories.tiff
    ├── speed_distribution.tiff
    ├── msd.tiff
    ├── directional_autocorr.tiff
    ├── run_length_distribution.tiff
    ├── drift_vector.tiff
    ├── population_heterogeneity.tiff
    ├── boundary_collision_heatmap.tiff
    ├── bac_bac_collision_heatmap.tiff
    ├── vacf.tiff
    ├── turning_angle_distribution.tiff
    ├── track_curvature.tiff
    ├── confinement_ratio.tiff
    ├── speed_persistence_corr.tiff
    ├── non_gaussianity.tiff
    ├── active_stationary.tiff
    ├── speed_tracklength_corr.tiff
    ├── pair_correlation_gr.tiff
    ├── spatial_velocity_corr.tiff
    ├── near_wall_speed_profile.tiff
    └── *.csv  (raw numeric data for each plot)
```
