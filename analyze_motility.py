#!/usr/bin/env python3
"""
Bacterial Motility & Collision Frequency Analyzer
--------------------------------------------------
Input : trackpy CSV file(s) with columns:
        y, x, mass, size, ecc, signal, raw_mass, ep, frame, particle

Analyses (per file):
  1.  Instantaneous speed — distribution + per-track stats
  2.  Mean Squared Displacement — D, alpha, motion classification
  3.  Directional autocorrelation — persistence time
  4.  Run-and-tumble — run length & tumble frequency
  5.  Drift vector — population-level directional bias
  6.  Population heterogeneity — slow / normal / hyper-motile
  7.  Bacteria-to-boundary collision frequency
  8.  Bacteria-to-bacteria collision frequency
  9.  Velocity autocorrelation function (VACF)
  10. Turning angle distribution
  11. Track curvature (mean absolute curvature per track)
  12. Confinement ratio (end-to-end / total path length)
  13. Speed–persistence correlation
  14. Non-Gaussianity parameter α₂
  15. Active vs. stationary phase segmentation
  16. Speed–track-length correlation
  17. Pair correlation function g(r)
  18. Spatial velocity correlation C_v(r)
  19. Near-wall speed profile

Cross-file analyses (when >1 CSV supplied):
  20. Motility time-series across conditions / timepoints
  21. Statistical comparisons (KS test + Mann-Whitney U)
  22. Subpopulation fraction evolution

Usage:
  python analyze_motility.py data.csv
  python analyze_motility.py *.csv --fps 50 --px-per-um 50
  python analyze_motility.py data.csv --skip-bac-bac
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial import cKDTree
from scipy import stats as spstats

warnings.filterwarnings('ignore')

# Output format constants
_DPI = 600
_FMT = '.tiff'


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description='Bacterial motility and collision frequency analyzer',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('csv_files', nargs='+', help='Input trackpy CSV file(s)')

    acq = p.add_argument_group('Acquisition parameters')
    acq.add_argument('--fps', type=float, default=50.0,
                     help='Camera frame rate (frames per second)')
    acq.add_argument('--px-per-um', type=float, default=50.0,
                     help='Pixels per micron (spatial calibration)')

    filt = p.add_argument_group('Filtering')
    filt.add_argument('--min-track-length', type=int, default=10,
                      help='Minimum track length (frames) to include')
    filt.add_argument('--ep-max', type=float, default=5.0,
                      help='Maximum absolute localization error |ep| to keep')

    ana = p.add_argument_group('Analysis parameters')
    ana.add_argument('--bac-radius', type=float, default=0.5,
                     help='Bacterial body radius (µm)')
    ana.add_argument('--tumble-angle', type=float, default=90.0,
                     help='Angular change (°) above which a step is a tumble')
    ana.add_argument('--max-lag', type=int, default=20,
                     help='Maximum lag (frames) for MSD / autocorrelation')
    ana.add_argument('--stationary-speed', type=float, default=0.5,
                     help='Speed threshold (µm/s) below which a step is stationary')
    ana.add_argument('--skip-bac-bac', action='store_true',
                     help='Skip bacteria-bacteria collision detection')
    ana.add_argument('--skip-gr', action='store_true',
                     help='Skip pair-correlation g(r) (slow for large datasets)')

    bnd = p.add_argument_group('Arena boundary (µm) — omit any to auto-detect from data')
    bnd.add_argument('--boundary-x-lo', type=float, default=None,
                     help='Left boundary of arena (µm)')
    bnd.add_argument('--boundary-x-hi', type=float, default=None,
                     help='Right boundary of arena (µm)')
    bnd.add_argument('--boundary-y-lo', type=float, default=None,
                     help='Bottom boundary of arena (µm)')
    bnd.add_argument('--boundary-y-hi', type=float, default=None,
                     help='Top boundary of arena (µm)')

    out = p.add_argument_group('Output')
    out.add_argument('--output-dir', type=str, default='motility_analysis',
                     help='Root directory for results')

    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Data loading & preparation
# ─────────────────────────────────────────────────────────────────────────────

def load_and_filter(csv_path, min_track_length, ep_max):
    for enc in ('utf-8-sig', 'latin-1', 'utf-8', 'cp1252'):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot read {csv_path} — tried utf-8-sig, latin-1, utf-8, cp1252")
    df.columns = df.columns.str.strip().str.lstrip('﻿')
    n_raw = len(df)
    df = df[df['ep'].abs() < ep_max]
    n_ep = len(df)
    track_len = df.groupby('particle')['frame'].count()
    valid_ids = track_len[track_len >= min_track_length].index
    df = df[df['particle'].isin(valid_ids)].copy()
    df = df.sort_values(['particle', 'frame']).reset_index(drop=True)
    print(f"  {n_raw:>9,}  raw detections")
    print(f"  {n_ep:>9,}  after |ep| < {ep_max}  ({n_raw - n_ep:,} removed)")
    print(f"  {len(df):>9,}  after min-track-length = {min_track_length}")
    print(f"  {df['particle'].nunique():>9,}  valid tracks kept")
    return df


def add_micron_coords(df, px_per_um):
    df = df.copy()
    df['x_um'] = df['x'] / px_per_um
    df['y_um'] = df['y'] / px_per_um
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 1. Instantaneous speed
# ─────────────────────────────────────────────────────────────────────────────

def compute_speeds(df, fps):
    s = df.sort_values(['particle', 'frame'])
    g = s.groupby('particle')
    dx = g['x_um'].diff()
    dy = g['y_um'].diff()
    d_frm = g['frame'].diff()
    mask = d_frm == 1
    speed = np.sqrt(dx**2 + dy**2) / (1.0 / fps)
    return speed[mask].dropna().reset_index(drop=True)


def compute_per_track_speeds(df, fps):
    rows = []
    for pid, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        step_speeds = []
        for i in range(len(track) - 1):
            if fr[i+1] - fr[i] == 1:
                step_speeds.append(np.hypot(x[i+1]-x[i], y[i+1]-y[i]) * fps)
        if step_speeds:
            rows.append({
                'particle':        pid,
                'mean_speed_um_s': float(np.mean(step_speeds)),
                'max_speed_um_s':  float(np.max(step_speeds)),
                'std_speed_um_s':  float(np.std(step_speeds)),
                'track_length':    len(track),
                'n_steps':         len(step_speeds),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 2. MSD
# ─────────────────────────────────────────────────────────────────────────────

def compute_msd(df, fps, max_lag=20):
    accum = {}
    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        for lag in range(1, min(max_lag + 1, n)):
            dx = x[lag:] - x[:n-lag]
            dy = y[lag:] - y[:n-lag]
            ok = (fr[lag:] - fr[:n-lag]) == lag
            if ok.any():
                accum.setdefault(lag, []).extend((dx[ok]**2 + dy[ok]**2).tolist())
    if not accum:
        return np.array([]), np.array([]), np.array([])
    lags = sorted(accum)
    lag_times = np.array(lags, dtype=float) / fps
    msd_vals = np.array([np.mean(accum[l]) for l in lags])
    n_pairs = np.array([len(accum[l]) for l in lags])
    return lag_times, msd_vals, n_pairs


def fit_msd(lag_times, msd_vals):
    ok = np.isfinite(msd_vals) & (msd_vals > 0) & (lag_times > 0)
    if ok.sum() < 4:
        return None, None
    try:
        coeffs = np.polyfit(np.log(lag_times[ok]), np.log(msd_vals[ok]), 1)
        return float(np.exp(coeffs[1]) / 4.0), float(coeffs[0])
    except Exception:
        return None, None


def motion_label(alpha):
    if alpha is None:
        return 'unknown'
    if alpha > 1.5:
        return 'Ballistic / Directed'
    if alpha > 0.9:
        return 'Diffusive'
    return 'Confined / Subdiffusive'


# ─────────────────────────────────────────────────────────────────────────────
# 3. Directional autocorrelation
# ─────────────────────────────────────────────────────────────────────────────

def compute_directional_autocorr(df, fps, max_lag=20):
    accum = {}
    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        step_dir, step_fr = [], []
        for i in range(n - 1):
            if fr[i+1] - fr[i] == 1:
                dx = x[i+1] - x[i]
                dy = y[i+1] - y[i]
                d = np.hypot(dx, dy)
                if d > 0:
                    step_dir.append(np.arctan2(dy, dx))
                    step_fr.append(fr[i])
        m = len(step_dir)
        if m < 2:
            continue
        dirs = np.array(step_dir)
        sfrms = np.array(step_fr)
        for lag in range(1, min(max_lag + 1, m)):
            cos_diff = np.cos(dirs[lag:] - dirs[:m-lag])
            ok = (sfrms[lag:] - sfrms[:m-lag]) == lag
            if ok.any():
                accum.setdefault(lag, []).extend(cos_diff[ok].tolist())
    if not accum:
        return np.array([]), np.array([]), np.array([])
    lags = sorted(accum)
    lag_times = np.array(lags, dtype=float) / fps
    C_tau = np.array([np.mean(accum[l]) for l in lags])
    n_pairs = np.array([len(accum[l]) for l in lags])
    return lag_times, C_tau, n_pairs


def fit_persistence(lag_times, C_tau):
    ok = (C_tau > 0) & np.isfinite(C_tau) & (lag_times > 0)
    if ok.sum() < 3:
        return None
    try:
        slope, _ = np.polyfit(lag_times[ok], np.log(C_tau[ok]), 1)
        return float(-1.0 / slope) if slope < 0 else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Run-and-tumble
# ─────────────────────────────────────────────────────────────────────────────

def compute_run_tumble(df, fps, tumble_threshold_deg=90.0):
    thresh_rad = np.radians(tumble_threshold_deg)
    run_lengths, run_durations = [], []
    total_transitions = total_tumbles = 0

    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        dx_list, dy_list, dist_list = [], [], []
        for i in range(n - 1):
            if fr[i+1] - fr[i] == 1:
                dx = x[i+1] - x[i]
                dy = y[i+1] - y[i]
                d = np.hypot(dx, dy)
                if d > 0:
                    dx_list.append(dx)
                    dy_list.append(dy)
                    dist_list.append(d)
        if len(dx_list) < 2:
            continue
        directions = np.arctan2(dy_list, dx_list)
        d_theta = np.diff(directions)
        d_theta = (d_theta + np.pi) % (2 * np.pi) - np.pi
        is_tumble = np.abs(d_theta) > thresh_rad
        total_transitions += len(is_tumble)
        total_tumbles += int(is_tumble.sum())
        in_run = False
        run_dist = run_steps = 0
        for i, tumble in enumerate(is_tumble):
            if not tumble:
                if not in_run:
                    in_run = True
                    run_dist = dist_list[i]
                    run_steps = 1
                else:
                    run_dist += dist_list[i]
                    run_steps += 1
            else:
                if in_run:
                    run_lengths.append(run_dist)
                    run_durations.append(run_steps / fps)
                    in_run = False
        if in_run:
            run_lengths.append(run_dist)
            run_durations.append(run_steps / fps)

    total_time_s = total_transitions / fps if total_transitions > 0 else 1.0
    return {
        'mean_run_length_um':   float(np.mean(run_lengths))   if run_lengths else 0.0,
        'median_run_length_um': float(np.median(run_lengths)) if run_lengths else 0.0,
        'mean_run_duration_s':  float(np.mean(run_durations)) if run_durations else 0.0,
        'tumble_frequency_hz':  total_tumbles / total_time_s,
        'tumble_fraction':      total_tumbles / total_transitions if total_transitions else 0.0,
        'n_runs':               len(run_lengths),
        'n_tumbles':            total_tumbles,
        'run_lengths':          run_lengths,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Drift vector
# ─────────────────────────────────────────────────────────────────────────────

def compute_drift_vector(df):
    net_x, net_y = [], []
    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        if len(track) < 2:
            continue
        net_x.append(track['x_um'].iloc[-1] - track['x_um'].iloc[0])
        net_y.append(track['y_um'].iloc[-1] - track['y_um'].iloc[0])
    if not net_x:
        return {'drift_x_um': 0.0, 'drift_y_um': 0.0,
                'drift_magnitude_um': 0.0, 'drift_angle_deg': 0.0,
                'net_x': np.array([]), 'net_y': np.array([])}
    nx, ny = np.array(net_x), np.array(net_y)
    mx, my = float(np.mean(nx)), float(np.mean(ny))
    return {
        'drift_x_um':         mx,
        'drift_y_um':         my,
        'drift_magnitude_um': float(np.hypot(mx, my)),
        'drift_angle_deg':    float(np.degrees(np.arctan2(my, mx))),
        'net_x':              nx,
        'net_y':              ny,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Population heterogeneity
# ─────────────────────────────────────────────────────────────────────────────

def compute_population_heterogeneity(pt_df):
    if pt_df.empty:
        return pt_df, {}
    q25 = pt_df['mean_speed_um_s'].quantile(0.25)
    q75 = pt_df['mean_speed_um_s'].quantile(0.75)
    pt = pt_df.copy()
    pt['subpopulation'] = 'normal'
    pt.loc[pt['mean_speed_um_s'] <= q25, 'subpopulation'] = 'slow'
    pt.loc[pt['mean_speed_um_s'] >= q75, 'subpopulation'] = 'hyper-motile'
    counts = pt['subpopulation'].value_counts()
    fracs = pt['subpopulation'].value_counts(normalize=True)
    stats = {
        'slow_threshold_um_s':        round(q25, 4),
        'hypermotile_threshold_um_s': round(q75, 4),
        'n_slow':        int(counts.get('slow', 0)),
        'n_normal':      int(counts.get('normal', 0)),
        'n_hypermotile': int(counts.get('hyper-motile', 0)),
        'frac_slow':        round(float(fracs.get('slow', 0)), 4),
        'frac_normal':      round(float(fracs.get('normal', 0)), 4),
        'frac_hypermotile': round(float(fracs.get('hyper-motile', 0)), 4),
    }
    return pt, stats


# ─────────────────────────────────────────────────────────────────────────────
# 7. Boundary collisions
# ─────────────────────────────────────────────────────────────────────────────

def compute_boundary_collisions(df, px_per_um, bac_radius_um, fps,
                                x_lo_um=None, x_hi_um=None,
                                y_lo_um=None, y_hi_um=None):
    r_px = bac_radius_um * px_per_um

    # Convert user-supplied µm boundaries to pixels; fall back to data extent
    x_lo = (x_lo_um * px_per_um) if x_lo_um is not None else df['x'].min()
    x_hi = (x_hi_um * px_per_um) if x_hi_um is not None else df['x'].max()
    y_lo = (y_lo_um * px_per_um) if y_lo_um is not None else df['y'].min()
    y_hi = (y_hi_um * px_per_um) if y_hi_um is not None else df['y'].max()

    nl = df['x'] <= x_lo + r_px
    nr = df['x'] >= x_hi - r_px
    nb = df['y'] <= y_lo + r_px
    nt = df['y'] >= y_hi - r_px
    ev = df[nl | nr | nb | nt].copy()
    ev['x_um'] = ev['x'] / px_per_um
    ev['y_um'] = ev['y'] / px_per_um
    wall = pd.Series('corner', index=ev.index)
    wall[nl[ev.index] & ~nb[ev.index] & ~nt[ev.index]] = 'left'
    wall[nr[ev.index] & ~nb[ev.index] & ~nt[ev.index]] = 'right'
    wall[nb[ev.index] & ~nl[ev.index] & ~nr[ev.index]] = 'bottom'
    wall[nt[ev.index] & ~nl[ev.index] & ~nr[ev.index]] = 'top'
    ev['wall'] = wall
    n_tracks = df['particle'].nunique()
    duration = df['frame'].nunique() / fps
    freq = len(ev) / (n_tracks * duration) if n_tracks > 0 and duration > 0 else 0.0
    return {
        'total_events':        len(ev),
        'freq_per_cell_per_s': freq,
        'wall_counts':         ev['wall'].value_counts().to_dict(),
        'events_df':           ev,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. Bacteria-bacteria collisions
# ─────────────────────────────────────────────────────────────────────────────

def compute_bac_bac_collisions(df, px_per_um, bac_radius_um, fps):
    thresh_px = 2.0 * bac_radius_um * px_per_um
    events = []
    for frame_id, fdata in df.groupby('frame'):
        if len(fdata) < 2:
            continue
        pos = fdata[['x', 'y']].values
        parts = fdata['particle'].values
        tree = cKDTree(pos)
        for i, j in tree.query_pairs(thresh_px):
            dist_um = np.hypot(pos[i,0]-pos[j,0], pos[i,1]-pos[j,1]) / px_per_um
            events.append({
                'frame': frame_id,
                'particle_1': int(parts[i]),
                'particle_2': int(parts[j]),
                'distance_um': round(dist_um, 4),
                'x_mid_um': round((pos[i,0]+pos[j,0])/2/px_per_um, 4),
                'y_mid_um': round((pos[i,1]+pos[j,1])/2/px_per_um, 4),
            })
    ev_df = pd.DataFrame(events) if events else pd.DataFrame(
        columns=['frame','particle_1','particle_2','distance_um','x_mid_um','y_mid_um'])
    n_tracks = df['particle'].nunique()
    duration = df['frame'].nunique() / fps
    freq = len(ev_df) / (n_tracks * duration) if n_tracks > 0 and duration > 0 else 0.0
    return {'total_events': len(ev_df), 'freq_per_cell_per_s': freq, 'events_df': ev_df}


# ─────────────────────────────────────────────────────────────────────────────
# 9. Velocity autocorrelation function (VACF)
# ─────────────────────────────────────────────────────────────────────────────

def compute_vacf(df, fps, max_lag=20):
    """
    VACF: ⟨v(t)·v(t+τ)⟩ normalised by ⟨v(0)²⟩.
    Returns (lag_times_s, vacf_vals, n_pairs).
    """
    accum = {}
    norm_vals = []

    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)

        vx, vy, vfr = [], [], []
        for i in range(n - 1):
            if fr[i+1] - fr[i] == 1:
                vx.append((x[i+1]-x[i]) * fps)
                vy.append((y[i+1]-y[i]) * fps)
                vfr.append(fr[i])

        m = len(vx)
        if m < 2:
            continue
        vx = np.array(vx)
        vy = np.array(vy)
        vfr = np.array(vfr)
        norm_vals.extend((vx**2 + vy**2).tolist())

        for lag in range(1, min(max_lag + 1, m)):
            dot = vx[:m-lag]*vx[lag:] + vy[:m-lag]*vy[lag:]
            ok = (vfr[lag:] - vfr[:m-lag]) == lag
            if ok.any():
                accum.setdefault(lag, []).extend(dot[ok].tolist())

    if not accum or not norm_vals:
        return np.array([]), np.array([]), np.array([])

    v0_sq = float(np.mean(norm_vals))
    lags = sorted(accum)
    lag_times = np.array(lags, dtype=float) / fps
    vacf_vals = np.array([np.mean(accum[l]) for l in lags]) / (v0_sq if v0_sq > 0 else 1.0)
    n_pairs = np.array([len(accum[l]) for l in lags])
    return lag_times, vacf_vals, n_pairs


# ─────────────────────────────────────────────────────────────────────────────
# 10. Turning angle distribution
# ─────────────────────────────────────────────────────────────────────────────

def compute_turning_angles(df):
    """Return array of all per-step turning angles in degrees (−180 to +180)."""
    angles = []
    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        dirs = []
        for i in range(n - 1):
            if fr[i+1] - fr[i] == 1:
                dx = x[i+1] - x[i]
                dy = y[i+1] - y[i]
                if np.hypot(dx, dy) > 0:
                    dirs.append(np.arctan2(dy, dx))
        for i in range(len(dirs) - 1):
            da = dirs[i+1] - dirs[i]
            da = (da + np.pi) % (2*np.pi) - np.pi
            angles.append(np.degrees(da))
    return np.array(angles)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Track curvature
# ─────────────────────────────────────────────────────────────────────────────

def compute_track_curvature(df, fps):
    """
    Mean absolute curvature κ = |dθ/ds| per track (rad/µm).
    High κ → circular swimming; low κ → straight runs.
    Returns a Series of per-track mean curvatures.
    """
    rows = []
    for pid, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        kappas = []
        for i in range(n - 2):
            if fr[i+1]-fr[i] == 1 and fr[i+2]-fr[i+1] == 1:
                dx1 = x[i+1]-x[i];  dy1 = y[i+1]-y[i]
                dx2 = x[i+2]-x[i+1]; dy2 = y[i+2]-y[i+1]
                d1 = np.hypot(dx1, dy1)
                d2 = np.hypot(dx2, dy2)
                if d1 > 0 and d2 > 0:
                    cos_a = (dx1*dx2 + dy1*dy2) / (d1*d2)
                    cos_a = np.clip(cos_a, -1, 1)
                    arc = (d1 + d2) / 2
                    kappas.append(np.arccos(cos_a) / arc if arc > 0 else 0.0)
        if kappas:
            rows.append({'particle': pid, 'mean_curvature_rad_um': float(np.mean(kappas))})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Confinement ratio
# ─────────────────────────────────────────────────────────────────────────────

def compute_confinement_ratio(df):
    """
    CR = end-to-end distance / total path length per track.
    CR → 1 : straight (directed); CR → 0 : confined / circular.
    """
    rows = []
    for pid, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        end_to_end = np.hypot(x[-1]-x[0], y[-1]-y[0])
        path_len = sum(np.hypot(x[i+1]-x[i], y[i+1]-y[i])
                       for i in range(n-1) if fr[i+1]-fr[i] == 1)
        if path_len > 0:
            rows.append({'particle': pid,
                         'confinement_ratio': float(end_to_end / path_len),
                         'end_to_end_um': float(end_to_end),
                         'path_length_um': float(path_len)})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Speed–persistence correlation
# ─────────────────────────────────────────────────────────────────────────────

def compute_speed_persistence_corr(pt_df, cr_df):
    """Pearson r between per-track mean speed and confinement ratio."""
    merged = pt_df.merge(cr_df[['particle','confinement_ratio']], on='particle', how='inner')
    if len(merged) < 5:
        return None, None, merged
    r, pval = spstats.pearsonr(merged['mean_speed_um_s'], merged['confinement_ratio'])
    return float(r), float(pval), merged


# ─────────────────────────────────────────────────────────────────────────────
# 14. Non-Gaussianity parameter α₂
# ─────────────────────────────────────────────────────────────────────────────

def compute_non_gaussianity(df, fps, max_lag=20):
    """
    α₂(τ) = ⟨r⁴⟩ / (2⟨r²⟩²) − 1
    = 0 for Gaussian displacement; > 0 for heavy-tailed (heterogeneous) motion.
    """
    r2_accum = {}
    r4_accum = {}

    for _, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        for lag in range(1, min(max_lag+1, n)):
            dx = x[lag:] - x[:n-lag]
            dy = y[lag:] - y[:n-lag]
            ok = (fr[lag:] - fr[:n-lag]) == lag
            if ok.any():
                r2 = dx[ok]**2 + dy[ok]**2
                r2_accum.setdefault(lag, []).extend(r2.tolist())
                r4_accum.setdefault(lag, []).extend((r2**2).tolist())

    if not r2_accum:
        return np.array([]), np.array([])

    lags = sorted(r2_accum)
    lag_times = np.array(lags, dtype=float) / fps
    alpha2 = []
    for l in lags:
        mr2 = np.mean(r2_accum[l])
        mr4 = np.mean(r4_accum[l])
        denom = 2 * mr2**2
        alpha2.append((mr4 / denom - 1) if denom > 0 else 0.0)
    return lag_times, np.array(alpha2)


# ─────────────────────────────────────────────────────────────────────────────
# 15. Active / stationary phase segmentation
# ─────────────────────────────────────────────────────────────────────────────

def compute_active_stationary(df, fps, stationary_speed_um_s=0.5):
    """
    Classify each step as active (speed ≥ threshold) or stationary.
    Returns per-track fractions and global summary.
    """
    rows = []
    for pid, track in df.groupby('particle'):
        track = track.sort_values('frame')
        fr = track['frame'].values
        x = track['x_um'].values
        y = track['y_um'].values
        n = len(track)
        n_active = n_stat = 0
        for i in range(n - 1):
            if fr[i+1]-fr[i] == 1:
                sp = np.hypot(x[i+1]-x[i], y[i+1]-y[i]) * fps
                if sp >= stationary_speed_um_s:
                    n_active += 1
                else:
                    n_stat += 1
        total = n_active + n_stat
        if total > 0:
            rows.append({
                'particle': pid,
                'n_active_steps': n_active,
                'n_stationary_steps': n_stat,
                'frac_active': n_active / total,
            })
    df_out = pd.DataFrame(rows)
    if df_out.empty:
        return df_out, {}
    summary = {
        'mean_frac_active': float(df_out['frac_active'].mean()),
        'median_frac_active': float(df_out['frac_active'].median()),
        'frac_always_active': float((df_out['frac_active'] == 1.0).mean()),
        'frac_always_stationary': float((df_out['frac_active'] == 0.0).mean()),
    }
    return df_out, summary


# ─────────────────────────────────────────────────────────────────────────────
# 16. Speed–track-length correlation
# ─────────────────────────────────────────────────────────────────────────────

def compute_speed_tracklength_corr(pt_df):
    """Pearson r between per-track mean speed and track length (frames)."""
    if len(pt_df) < 5:
        return None, None
    r, pval = spstats.pearsonr(pt_df['mean_speed_um_s'], pt_df['track_length'])
    return float(r), float(pval)


# ─────────────────────────────────────────────────────────────────────────────
# 17. Pair correlation function g(r)
# ─────────────────────────────────────────────────────────────────────────────

def compute_pair_correlation(df, px_per_um, r_max_um=5.0, n_bins=50, n_frames_sample=10):
    """
    g(r): probability of finding a neighbour at distance r relative to ideal gas.
    Averaged over a random sample of frames (controlled by n_frames_sample).
    """
    frames = df['frame'].unique()
    if len(frames) > n_frames_sample:
        rng = np.random.default_rng(42)
        frames = rng.choice(frames, n_frames_sample, replace=False)

    bin_edges = np.linspace(0, r_max_um, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    dr = bin_edges[1] - bin_edges[0]
    g_accum = np.zeros(n_bins)
    frame_count = 0

    for fid in frames:
        fdata = df[df['frame'] == fid]
        pos = fdata[['x_um', 'y_um']].values
        N = len(pos)
        if N < 2:
            continue
        tree = cKDTree(pos)
        pairs = tree.query_pairs(r_max_um)
        dists = [np.hypot(pos[i,0]-pos[j,0], pos[i,1]-pos[j,1]) for i, j in pairs]
        if not dists:
            continue
        counts, _ = np.histogram(dists, bins=bin_edges)
        # ideal gas normalisation: 2 * pi * r * dr * rho * N
        x_range = pos[:,0].max() - pos[:,0].min()
        y_range = pos[:,1].max() - pos[:,1].min()
        area = x_range * y_range if x_range * y_range > 0 else 1.0
        rho = N / area
        norm = 2 * np.pi * bin_centers * dr * rho * N
        norm[norm == 0] = 1
        g_accum += counts / norm
        frame_count += 1

    if frame_count == 0:
        return bin_centers, np.zeros(n_bins)
    return bin_centers, g_accum / frame_count


# ─────────────────────────────────────────────────────────────────────────────
# 18. Spatial velocity correlation C_v(r)
# ─────────────────────────────────────────────────────────────────────────────

def compute_spatial_velocity_corr(df, fps, r_max_um=5.0, n_bins=20, n_frames_sample=10):
    """
    C_v(r) = ⟨v̂ᵢ·v̂ⱼ⟩ for pairs at separation r (averaged over frames).
    Measures collective motion / alignment.
    """
    frames = df['frame'].unique()
    if len(frames) > n_frames_sample:
        rng = np.random.default_rng(42)
        frames = rng.choice(frames, n_frames_sample, replace=False)

    # Build velocity per particle per frame
    df_sorted = df.sort_values(['particle', 'frame'])
    g = df_sorted.groupby('particle')
    df_sorted = df_sorted.copy()
    df_sorted['vx'] = g['x_um'].diff() * fps
    df_sorted['vy'] = g['y_um'].diff() * fps
    df_sorted['d_frame'] = g['frame'].diff()
    df_v = df_sorted[(df_sorted['d_frame'] == 1)].copy()
    v_mag = np.hypot(df_v['vx'], df_v['vy'])
    df_v = df_v[v_mag > 0].copy()
    df_v['vx_n'] = df_v['vx'] / np.hypot(df_v['vx'], df_v['vy'])
    df_v['vy_n'] = df_v['vy'] / np.hypot(df_v['vx'], df_v['vy'])

    bin_edges = np.linspace(0, r_max_um, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    cv_accum = np.zeros(n_bins)
    cv_count = np.zeros(n_bins)

    for fid in frames:
        fdata = df_v[df_v['frame'] == fid]
        if len(fdata) < 2:
            continue
        pos = fdata[['x_um', 'y_um']].values
        vn = fdata[['vx_n', 'vy_n']].values
        tree = cKDTree(pos)
        for i, j in tree.query_pairs(r_max_um):
            d = np.hypot(pos[i,0]-pos[j,0], pos[i,1]-pos[j,1])
            b = int(d / (r_max_um / n_bins))
            if b < n_bins:
                cv_accum[b] += vn[i,0]*vn[j,0] + vn[i,1]*vn[j,1]
                cv_count[b] += 1

    cv_count[cv_count == 0] = 1
    return bin_centers, cv_accum / cv_count


# ─────────────────────────────────────────────────────────────────────────────
# 19. Near-wall speed profile
# ─────────────────────────────────────────────────────────────────────────────

def compute_near_wall_speed(df, fps, px_per_um, n_bins=20):
    """
    Mean speed binned by distance-to-nearest-wall.
    Reveals whether bacteria speed up or slow down near surfaces.
    """
    x_lo, x_hi = df['x_um'].min(), df['x_um'].max()
    y_lo, y_hi = df['y_um'].min(), df['y_um'].max()

    df_s = df.sort_values(['particle', 'frame']).copy()
    g = df_s.groupby('particle')
    df_s['vx'] = g['x_um'].diff() * fps
    df_s['vy'] = g['y_um'].diff() * fps
    df_s['d_frame'] = g['frame'].diff()
    df_s = df_s[df_s['d_frame'] == 1].copy()

    df_s['dist_to_wall'] = np.minimum.reduce([
        df_s['x_um'] - x_lo,
        x_hi - df_s['x_um'],
        df_s['y_um'] - y_lo,
        y_hi - df_s['y_um'],
    ])
    df_s['speed'] = np.hypot(df_s['vx'], df_s['vy'])

    wall_max = df_s['dist_to_wall'].max()
    bin_edges = np.linspace(0, wall_max, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    mean_speed = np.zeros(n_bins)
    std_speed = np.zeros(n_bins)
    for b in range(n_bins):
        mask = (df_s['dist_to_wall'] >= bin_edges[b]) & (df_s['dist_to_wall'] < bin_edges[b+1])
        vals = df_s.loc[mask, 'speed']
        mean_speed[b] = vals.mean() if len(vals) > 0 else np.nan
        std_speed[b] = vals.std() if len(vals) > 0 else np.nan

    return bin_centers, mean_speed, std_speed


# ─────────────────────────────────────────────────────────────────────────────
# Cross-file analyses
# ─────────────────────────────────────────────────────────────────────────────

def cross_timepoint_stats_test(all_speeds):
    """
    Pairwise KS test and Mann-Whitney U between all conditions.
    Returns a DataFrame of results.
    """
    labels = list(all_speeds.keys())
    rows = []
    for i in range(len(labels)):
        for j in range(i+1, len(labels)):
            a = all_speeds[labels[i]].values
            b = all_speeds[labels[j]].values
            ks_stat, ks_p = spstats.ks_2samp(a, b)
            mw_stat, mw_p = spstats.mannwhitneyu(a, b, alternative='two-sided')
            rows.append({
                'condition_1': labels[i],
                'condition_2': labels[j],
                'ks_statistic': round(ks_stat, 5),
                'ks_pvalue':    round(ks_p,   8),
                'mw_statistic': round(mw_stat, 1),
                'mw_pvalue':    round(mw_p,   8),
                'mean_diff_um_s': round(float(a.mean()) - float(b.mean()), 4),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Plots  (all saved at 600 dpi, TIFF)
# ─────────────────────────────────────────────────────────────────────────────

def _save(fig, path):
    fig.savefig(str(path), dpi=_DPI, format='tiff')
    plt.close(fig)


def plot_trajectories(df, out_path, title):
    particles = df['particle'].unique()
    if len(particles) > 2000:
        particles = np.random.default_rng(42).choice(particles, 2000, replace=False)
    fig, ax = plt.subplots(figsize=(8, 8))
    cmap = plt.cm.tab20(np.linspace(0, 1, 20))
    for k, pid in enumerate(particles):
        t = df[df['particle'] == pid].sort_values('frame')
        ax.plot(t['x_um'] - t['x_um'].iloc[0], t['y_um'] - t['y_um'].iloc[0],
                lw=0.4, alpha=0.5, color=cmap[k % 20])
    ax.axhline(0, color='k', lw=0.5, alpha=0.3)
    ax.axvline(0, color='k', lw=0.5, alpha=0.3)
    ax.set_xlabel('Relative X (µm)'); ax.set_ylabel('Relative Y (µm)')
    ax.set_title(title); ax.set_aspect('equal'); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_speed_hist(speeds, out_path, title):
    cap = speeds.quantile(0.99)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(speeds.clip(upper=cap), bins=80, color='steelblue',
            edgecolor='white', lw=0.3, alpha=0.85)
    ax.axvline(speeds.mean(),   color='red',    ls='--', lw=1.5,
               label=f'Mean   {speeds.mean():.2f} µm/s')
    ax.axvline(speeds.median(), color='orange', ls='--', lw=1.5,
               label=f'Median {speeds.median():.2f} µm/s')
    ax.set_xlabel('Speed (µm/s)'); ax.set_ylabel('Count')
    ax.set_title(title); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_msd(lag_times, msd_vals, D, alpha, out_path, title):
    ok = np.isfinite(msd_vals) & (msd_vals > 0)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.loglog(lag_times[ok], msd_vals[ok], 'o-',
              color='steelblue', ms=5, lw=1.5, label='MSD (data)')
    if D is not None:
        ax.loglog(lag_times[ok], 4.0*D*lag_times[ok]**alpha, '--',
                  color='red', lw=1.5,
                  label=f'Fit: D = {D:.5f} µm²/s,  α = {alpha:.2f}')
        ax.set_title(f'{title}\n{motion_label(alpha)}  (α = {alpha:.2f})')
    else:
        ax.set_title(title)
    ax.set_xlabel('Lag time (s)'); ax.set_ylabel('MSD (µm²)')
    ax.legend(fontsize=9); ax.grid(True, which='both', alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_directional_autocorr(lag_times, C_tau, tau_p, out_path, title):
    ok = np.isfinite(C_tau)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(lag_times[ok], C_tau[ok], 'o-',
            color='steelblue', ms=5, lw=1.5, label='C(τ) data')
    ax.axhline(0, color='k', lw=0.8, ls='--', alpha=0.4)
    if tau_p is not None:
        ax.plot(lag_times[ok], np.exp(-lag_times[ok]/tau_p), '--',
                color='red', lw=1.5,
                label=f'Fit: τ_p = {tau_p*1000:.1f} ms')
    ax.set_xlabel('Lag time (s)'); ax.set_ylabel('C(τ) = ⟨cos Δθ⟩')
    ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_run_length_dist(run_lengths, out_path, title):
    if not run_lengths:
        return
    rl = np.array(run_lengths)
    cap = np.percentile(rl, 99)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(rl[rl <= cap], bins=60, color='teal',
            edgecolor='white', lw=0.3, alpha=0.85)
    ax.axvline(float(np.mean(rl)),   color='red',    ls='--', lw=1.5,
               label=f'Mean   {np.mean(rl):.3f} µm')
    ax.axvline(float(np.median(rl)), color='orange', ls='--', lw=1.5,
               label=f'Median {np.median(rl):.3f} µm')
    ax.set_xlabel('Run length (µm)'); ax.set_ylabel('Count')
    ax.set_title(title); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_drift_vector(drift, out_path, title):
    nx, ny = drift['net_x'], drift['net_y']
    if len(nx) == 0:
        return
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(nx, ny, alpha=0.15, s=4, color='steelblue',
               label='Per-track net displacement')
    mx, my = drift['drift_x_um'], drift['drift_y_um']
    ax.annotate('', xy=(mx, my), xytext=(0, 0),
                arrowprops=dict(arrowstyle='->', color='red', lw=2.5))
    ax.plot([], [], color='red', lw=2.5,
            label=f"Mean drift: {drift['drift_magnitude_um']:.4f} µm "
                  f"@ {drift['drift_angle_deg']:.1f}°")
    ax.axhline(0, color='k', lw=0.5, alpha=0.4)
    ax.axvline(0, color='k', lw=0.5, alpha=0.4)
    ax.set_xlabel('Net displacement X (µm)'); ax.set_ylabel('Net displacement Y (µm)')
    ax.set_title(title); ax.set_aspect('equal')
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_population_heterogeneity(pt_df, stats, out_path, title):
    if pt_df.empty:
        return
    colors = {'slow': '#d62728', 'normal': '#1f77b4', 'hyper-motile': '#2ca02c'}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    cap = pt_df['mean_speed_um_s'].quantile(0.99)
    for subpop, grp in pt_df.groupby('subpopulation'):
        axes[0].hist(grp['mean_speed_um_s'].clip(upper=cap), bins=50, alpha=0.7,
                     color=colors.get(subpop, 'grey'),
                     label=f"{subpop}  n={len(grp)}  ({len(grp)/len(pt_df):.0%})")
    axes[0].axvline(stats['slow_threshold_um_s'], color='r', ls=':', lw=1.5)
    axes[0].axvline(stats['hypermotile_threshold_um_s'], color='g', ls=':', lw=1.5)
    axes[0].set_xlabel('Mean speed per track (µm/s)'); axes[0].set_ylabel('Count')
    axes[0].set_title('Speed by subpopulation'); axes[0].legend(fontsize=7)
    axes[0].grid(True, alpha=0.3)
    sizes   = [stats['n_slow'], stats['n_normal'], stats['n_hypermotile']]
    palette = [colors['slow'], colors['normal'], colors['hyper-motile']]
    axes[1].pie(sizes, labels=['Slow','Normal','Hyper-motile'],
                colors=palette, autopct='%1.1f%%', startangle=90,
                wedgeprops={'edgecolor':'white','linewidth':1.2})
    axes[1].set_title('Subpopulation fractions')
    fig.suptitle(title, fontsize=12, fontweight='bold')
    plt.tight_layout(); _save(fig, out_path)


def plot_heatmap(events_df, x_col, y_col, x_max_um, y_max_um, out_path, title):
    if events_df is None or len(events_df) == 0:
        return
    fig, ax = plt.subplots(figsize=(8, 7))
    h = ax.hist2d(events_df[x_col], events_df[y_col], bins=50,
                  cmap='hot_r', range=[[0, x_max_um],[0, y_max_um]])
    plt.colorbar(h[3], ax=ax, label='Event count')
    ax.set_xlabel('X (µm)'); ax.set_ylabel('Y (µm)'); ax.set_title(title)
    plt.tight_layout(); _save(fig, out_path)


def plot_vacf(lag_times, vacf_vals, out_path, title):
    ok = np.isfinite(vacf_vals)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(lag_times[ok], vacf_vals[ok], 'o-',
            color='darkorange', ms=5, lw=1.5, label='VACF (normalised)')
    ax.axhline(0, color='k', lw=0.8, ls='--', alpha=0.4)
    ax.set_xlabel('Lag time (s)'); ax.set_ylabel('VACF / ⟨v²⟩')
    ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_turning_angles(angles, out_path, title):
    if len(angles) == 0:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(angles, bins=72, range=(-180, 180), color='mediumpurple',
            edgecolor='white', lw=0.3, alpha=0.85)
    ax.axvline(0, color='k', lw=0.8, ls='--', alpha=0.5)
    ax.set_xlabel('Turning angle (°)'); ax.set_ylabel('Count')
    ax.set_title(title); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_curvature(curv_df, out_path, title):
    if curv_df.empty:
        return
    cap = curv_df['mean_curvature_rad_um'].quantile(0.99)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(curv_df['mean_curvature_rad_um'].clip(upper=cap), bins=60,
            color='coral', edgecolor='white', lw=0.3, alpha=0.85)
    ax.axvline(curv_df['mean_curvature_rad_um'].mean(), color='red', ls='--', lw=1.5,
               label=f"Mean κ = {curv_df['mean_curvature_rad_um'].mean():.4f} rad/µm")
    ax.set_xlabel('Mean curvature κ (rad/µm)'); ax.set_ylabel('Count')
    ax.set_title(title); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_confinement_ratio(cr_df, out_path, title):
    if cr_df.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(cr_df['confinement_ratio'], bins=60, color='teal',
            edgecolor='white', lw=0.3, alpha=0.85)
    ax.axvline(cr_df['confinement_ratio'].mean(), color='red', ls='--', lw=1.5,
               label=f"Mean CR = {cr_df['confinement_ratio'].mean():.3f}")
    ax.set_xlabel('Confinement ratio (end-to-end / path length)')
    ax.set_ylabel('Count'); ax.set_title(title); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_speed_persistence(merged_df, r, pval, out_path, title):
    if merged_df is None or merged_df.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(merged_df['mean_speed_um_s'], merged_df['confinement_ratio'],
               alpha=0.3, s=6, color='steelblue')
    lbl = f'r = {r:.3f}  p = {pval:.2e}' if r is not None else 'insufficient data'
    ax.set_xlabel('Mean speed (µm/s)'); ax.set_ylabel('Confinement ratio')
    ax.set_title(f'{title}\n{lbl}'); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_non_gaussianity(lag_times, alpha2, out_path, title):
    if len(lag_times) == 0:
        return
    ok = np.isfinite(alpha2)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(lag_times[ok], alpha2[ok], 'o-', color='darkgreen', ms=5, lw=1.5)
    ax.axhline(0, color='k', lw=0.8, ls='--', alpha=0.4, label='Gaussian (α₂=0)')
    ax.set_xlabel('Lag time (s)'); ax.set_ylabel('Non-Gaussianity α₂(τ)')
    ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_active_stationary(act_df, summary, out_path, title):
    if act_df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].hist(act_df['frac_active'], bins=50, color='steelblue',
                 edgecolor='white', lw=0.3, alpha=0.85)
    axes[0].axvline(summary['mean_frac_active'], color='red', ls='--', lw=1.5,
                    label=f"Mean active = {summary['mean_frac_active']:.2%}")
    axes[0].set_xlabel('Fraction of time active'); axes[0].set_ylabel('# Tracks')
    axes[0].set_title('Active fraction distribution'); axes[0].legend(); axes[0].grid(True, alpha=0.3)
    phases = ['Active', 'Stationary']
    vals   = [summary['mean_frac_active'], 1 - summary['mean_frac_active']]
    axes[1].bar(phases, vals, color=['steelblue','salmon'], edgecolor='white')
    axes[1].set_ylabel('Mean fraction of time'); axes[1].set_title('Active vs. stationary')
    axes[1].set_ylim(0, 1); axes[1].grid(True, alpha=0.3, axis='y')
    fig.suptitle(title, fontsize=12, fontweight='bold')
    plt.tight_layout(); _save(fig, out_path)


def plot_speed_tracklength(pt_df, r, pval, out_path, title):
    if pt_df.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(pt_df['track_length'], pt_df['mean_speed_um_s'],
               alpha=0.3, s=6, color='darkorchid')
    lbl = f'r = {r:.3f}  p = {pval:.2e}' if r is not None else ''
    ax.set_xlabel('Track length (frames)'); ax.set_ylabel('Mean speed (µm/s)')
    ax.set_title(f'{title}\n{lbl}'); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_pair_correlation(r_vals, g_r, out_path, title):
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(r_vals, g_r, '-', color='royalblue', lw=1.8)
    ax.axhline(1, color='k', lw=0.8, ls='--', alpha=0.5, label='Ideal gas g(r)=1')
    ax.set_xlabel('Separation r (µm)'); ax.set_ylabel('g(r)')
    ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_spatial_velocity_corr(r_vals, cv, out_path, title):
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(r_vals, cv, 'o-', color='firebrick', ms=5, lw=1.5)
    ax.axhline(0, color='k', lw=0.8, ls='--', alpha=0.4)
    ax.set_xlabel('Separation r (µm)'); ax.set_ylabel('C_v(r)  =  ⟨v̂ᵢ·v̂ⱼ⟩')
    ax.set_title(title); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_near_wall_speed(dist, mean_sp, std_sp, out_path, title):
    fig, ax = plt.subplots(figsize=(8, 5))
    ok = np.isfinite(mean_sp)
    ax.plot(dist[ok], mean_sp[ok], 'o-', color='steelblue', ms=5, lw=1.5, label='Mean speed')
    ax.fill_between(dist[ok],
                    mean_sp[ok] - std_sp[ok], mean_sp[ok] + std_sp[ok],
                    alpha=0.2, color='steelblue', label='±1 std')
    ax.set_xlabel('Distance to nearest wall (µm)'); ax.set_ylabel('Speed (µm/s)')
    ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_speed_comparison(all_speeds, out_path):
    if len(all_speeds) < 2:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = plt.cm.Set2(np.linspace(0, 1, len(all_speeds)))
    for (label, speeds), color in zip(all_speeds.items(), colors):
        ax.hist(speeds.clip(upper=speeds.quantile(0.99)), bins=60, alpha=0.5,
                label=f'{label}  (mean {speeds.mean():.2f} µm/s)',
                color=color, density=True)
    ax.set_xlabel('Speed (µm/s)'); ax.set_ylabel('Density')
    ax.set_title('Speed Distribution Comparison')
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    plt.tight_layout(); _save(fig, out_path)


def plot_timeseries(summary_df, out_path):
    """Plot key motility metrics across files / timepoints."""
    if len(summary_df) < 2:
        return
    metrics = [
        ('speed_mean_um_s',      'Mean speed (µm/s)'),
        ('msd_alpha',            'MSD anomalous exponent α'),
        ('tumble_freq_hz',       'Tumble frequency (Hz)'),
        ('frac_hypermotile',     'Hyper-motile fraction'),
        ('boundary_freq_per_cell_s', 'Boundary collision freq (/cell/s)'),
        ('mean_frac_active',     'Mean active fraction'),
        ('mean_confinement_ratio', 'Mean confinement ratio'),
        ('non_gaussianity_peak', 'Non-Gaussianity peak α₂'),
    ]
    avail = [(m, l) for m, l in metrics if m in summary_df.columns]
    if not avail:
        return
    ncols = 2
    nrows = (len(avail) + 1) // 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(13, 4*nrows))
    axes = axes.flatten()
    for ax, (m, l) in zip(axes, avail):
        vals = pd.to_numeric(summary_df[m], errors='coerce')
        ax.plot(range(len(summary_df)), vals, 'o-', color='steelblue', ms=7, lw=1.8)
        ax.set_xticks(range(len(summary_df)))
        ax.set_xticklabels(summary_df['file'].tolist(), rotation=20, ha='right', fontsize=7)
        ax.set_ylabel(l); ax.grid(True, alpha=0.3)
    for ax in axes[len(avail):]:
        ax.set_visible(False)
    fig.suptitle('Motility metrics across conditions / timepoints',
                 fontsize=13, fontweight='bold')
    plt.tight_layout(); _save(fig, out_path)


def plot_subpopulation_evolution(summary_df, out_path):
    """Stacked bar chart of subpopulation fractions across files."""
    cols = ['frac_slow', 'frac_normal', 'frac_hypermotile']
    if not all(c in summary_df.columns for c in cols):
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(summary_df))
    slow_v  = pd.to_numeric(summary_df['frac_slow'],        errors='coerce').fillna(0)
    norm_v  = pd.to_numeric(summary_df['frac_normal'],      errors='coerce').fillna(0)
    hyper_v = pd.to_numeric(summary_df['frac_hypermotile'], errors='coerce').fillna(0)
    ax.bar(x, slow_v,  color='#d62728', label='Slow',         edgecolor='white')
    ax.bar(x, norm_v,  bottom=slow_v, color='#1f77b4',
           label='Normal',       edgecolor='white')
    ax.bar(x, hyper_v, bottom=slow_v+norm_v, color='#2ca02c',
           label='Hyper-motile', edgecolor='white')
    ax.set_xticks(x)
    ax.set_xticklabels(summary_df['file'].tolist(), rotation=20, ha='right', fontsize=8)
    ax.set_ylabel('Fraction'); ax.set_ylim(0, 1)
    ax.set_title('Subpopulation fraction evolution'); ax.legend(); ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout(); _save(fig, out_path)


def plot_stats_heatmap(stats_df, metric, out_path, title):
    """Heatmap of pairwise p-values."""
    if stats_df.empty:
        return
    labels = sorted(set(stats_df['condition_1'].tolist() + stats_df['condition_2'].tolist()))
    n = len(labels)
    mat = np.ones((n, n))
    idx = {l: i for i, l in enumerate(labels)}
    for _, row in stats_df.iterrows():
        i, j = idx[row['condition_1']], idx[row['condition_2']]
        mat[i, j] = mat[j, i] = row[metric]
    fig, ax = plt.subplots(figsize=(max(5, n), max(4, n)))
    im = ax.imshow(mat, cmap='RdYlGn_r', vmin=0, vmax=0.05)
    plt.colorbar(im, ax=ax, label=metric)
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f'{mat[i,j]:.2e}', ha='center', va='center', fontsize=6)
    ax.set_title(title)
    plt.tight_layout(); _save(fig, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Per-file orchestration
# ─────────────────────────────────────────────────────────────────────────────

def analyze_file(csv_path, args, root_out):
    name    = Path(csv_path).stem
    out_dir = root_out / name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'\n{"=" * 64}')
    print(f'  {Path(csv_path).name}')
    print(f'{"=" * 64}')

    df_raw = load_and_filter(csv_path, args.min_track_length, args.ep_max)
    df     = add_micron_coords(df_raw, args.px_per_um)

    fps       = args.fps
    px_per_um = args.px_per_um
    bac_r     = args.bac_radius
    arena_x   = df['x'].max() / px_per_um
    arena_y   = df['y'].max() / px_per_um
    duration  = df['frame'].nunique() / fps

    # Boundary: use user-supplied values or fall back to data extent
    bnd_x_lo = args.boundary_x_lo if args.boundary_x_lo is not None else df['x_um'].min()
    bnd_x_hi = args.boundary_x_hi if args.boundary_x_hi is not None else df['x_um'].max()
    bnd_y_lo = args.boundary_y_lo if args.boundary_y_lo is not None else df['y_um'].min()
    bnd_y_hi = args.boundary_y_hi if args.boundary_y_hi is not None else df['y_um'].max()
    bnd_source = 'user-specified' if any(v is not None for v in [
        args.boundary_x_lo, args.boundary_x_hi,
        args.boundary_y_lo, args.boundary_y_hi]) else 'auto-detected'

    print(f"\n  Arena            : {arena_x:.2f} × {arena_y:.2f} µm")
    print(f"  Recording window : {duration:.3f} s  ({df['frame'].nunique()} frames @ {fps} fps)")
    print(f"  Boundary ({bnd_source}): "
          f"X [{bnd_x_lo:.2f}, {bnd_x_hi:.2f}]  "
          f"Y [{bnd_y_lo:.2f}, {bnd_y_hi:.2f}] µm\n")

    # ── 1. Speed ──────────────────────────────────────────────────────────────
    print('[1 ] Swimming speed ...')
    speeds = compute_speeds(df, fps)
    pt_df  = compute_per_track_speeds(df, fps)
    sp = {
        'mean_um_s':   float(speeds.mean()),
        'median_um_s': float(speeds.median()),
        'std_um_s':    float(speeds.std()),
        'p10_um_s':    float(speeds.quantile(0.10)),
        'p90_um_s':    float(speeds.quantile(0.90)),
        'n_steps':     int(len(speeds)),
    }
    print(f"      Mean {sp['mean_um_s']:.3f}  Median {sp['median_um_s']:.3f}  "
          f"Std {sp['std_um_s']:.3f} µm/s  (n={sp['n_steps']:,})")

    # ── 2. MSD ────────────────────────────────────────────────────────────────
    print('[2 ] MSD ...')
    lt, mv, nc = compute_msd(df, fps, args.max_lag)
    D, alpha   = fit_msd(lt, mv)
    if D is not None:
        print(f"      D = {D:.5f} µm²/s   α = {alpha:.3f}   → {motion_label(alpha)}")

    # ── 3. Directional autocorrelation ────────────────────────────────────────
    print('[3 ] Directional autocorrelation ...')
    dac_lt, dac_ct, dac_n = compute_directional_autocorr(df, fps, args.max_lag)
    tau_p = fit_persistence(dac_lt, dac_ct)
    persist_len = sp['mean_um_s'] * tau_p if tau_p is not None else None
    if tau_p is not None:
        print(f"      τ_p = {tau_p*1000:.1f} ms   persistence length ≈ {persist_len:.4f} µm")

    # ── 4. Run-and-tumble ─────────────────────────────────────────────────────
    print('[4 ] Run-and-tumble ...')
    rt = compute_run_tumble(df, fps, args.tumble_angle)
    print(f"      Mean run {rt['mean_run_length_um']:.4f} µm  "
          f"Tumble freq {rt['tumble_frequency_hz']:.2f} Hz  "
          f"Tumble frac {rt['tumble_fraction']:.2%}")

    # ── 5. Drift vector ───────────────────────────────────────────────────────
    print('[5 ] Drift vector ...')
    drift = compute_drift_vector(df)
    print(f"      Drift {drift['drift_magnitude_um']:.5f} µm  @ {drift['drift_angle_deg']:.1f}°")

    # ── 6. Population heterogeneity ───────────────────────────────────────────
    print('[6 ] Population heterogeneity ...')
    pt_classified, het_stats = compute_population_heterogeneity(pt_df)
    if het_stats:
        print(f"      Slow {het_stats['frac_slow']:.1%}  "
              f"Normal {het_stats['frac_normal']:.1%}  "
              f"Hyper {het_stats['frac_hypermotile']:.1%}")

    # ── 7. Boundary collisions ────────────────────────────────────────────────
    print('[7 ] Boundary collisions ...')
    bc = compute_boundary_collisions(df, px_per_um, bac_r, fps,
                                     x_lo_um=args.boundary_x_lo,
                                     x_hi_um=args.boundary_x_hi,
                                     y_lo_um=args.boundary_y_lo,
                                     y_hi_um=args.boundary_y_hi)
    print(f"      {bc['total_events']:,} events  freq = {bc['freq_per_cell_per_s']:.3f} /cell/s")

    # ── 8. Bacteria-bacteria collisions ───────────────────────────────────────
    bb = {'total_events': 'skipped', 'freq_per_cell_per_s': 'skipped', 'events_df': None}
    if not args.skip_bac_bac:
        print('[8 ] Bacteria-bacteria collisions ...')
        bb = compute_bac_bac_collisions(df, px_per_um, bac_r, fps)
        print(f"      {bb['total_events']:,} events  freq = {bb['freq_per_cell_per_s']:.3f} /cell/s")
    else:
        print('[8 ] Bacteria-bacteria collisions ... skipped')

    # ── 9. VACF ───────────────────────────────────────────────────────────────
    print('[9 ] Velocity autocorrelation function (VACF) ...')
    vlt, vacf, vn = compute_vacf(df, fps, args.max_lag)
    vacf_zero_cross = None
    if len(vlt) > 0:
        neg = np.where(vacf <= 0)[0]
        if len(neg) > 0:
            vacf_zero_cross = float(vlt[neg[0]])
        print(f"      VACF zero crossing: "
              f"{vacf_zero_cross*1000:.1f} ms" if vacf_zero_cross else "      VACF stays positive (no zero crossing in range)")

    # ── 10. Turning angle distribution ────────────────────────────────────────
    print('[10] Turning angle distribution ...')
    turn_angles = compute_turning_angles(df)
    fwd_bias = float(np.mean(np.abs(turn_angles) < 45)) if len(turn_angles) > 0 else 0.0
    print(f"      {len(turn_angles):,} angles  "
          f"Forward-biased steps (<45°): {fwd_bias:.1%}")

    # ── 11. Track curvature ───────────────────────────────────────────────────
    print('[11] Track curvature ...')
    curv_df = compute_track_curvature(df, fps)
    mean_curv = float(curv_df['mean_curvature_rad_um'].mean()) if not curv_df.empty else 0.0
    print(f"      Mean κ = {mean_curv:.5f} rad/µm")

    # ── 12. Confinement ratio ─────────────────────────────────────────────────
    print('[12] Confinement ratio ...')
    cr_df = compute_confinement_ratio(df)
    mean_cr = float(cr_df['confinement_ratio'].mean()) if not cr_df.empty else 0.0
    print(f"      Mean CR = {mean_cr:.4f}  (1=straight, 0=confined)")

    # ── 13. Speed–persistence correlation ─────────────────────────────────────
    print('[13] Speed–persistence correlation ...')
    sp_r, sp_p, sp_merged = compute_speed_persistence_corr(pt_df, cr_df)
    if sp_r is not None:
        print(f"      r = {sp_r:.3f}  p = {sp_p:.2e}")

    # ── 14. Non-Gaussianity ───────────────────────────────────────────────────
    print('[14] Non-Gaussianity α₂ ...')
    ng_lt, ng_a2 = compute_non_gaussianity(df, fps, args.max_lag)
    ng_peak = float(np.nanmax(ng_a2)) if len(ng_a2) > 0 else 0.0
    print(f"      Peak α₂ = {ng_peak:.4f}")

    # ── 15. Active / stationary phases ────────────────────────────────────────
    print('[15] Active / stationary phase segmentation ...')
    act_df, act_summary = compute_active_stationary(df, fps, args.stationary_speed)
    if act_summary:
        print(f"      Mean active fraction = {act_summary['mean_frac_active']:.2%}")

    # ── 16. Speed–track-length correlation ────────────────────────────────────
    print('[16] Speed–track-length correlation ...')
    stl_r, stl_p = compute_speed_tracklength_corr(pt_df)
    if stl_r is not None:
        print(f"      r = {stl_r:.3f}  p = {stl_p:.2e}")

    # ── 17. Pair correlation g(r) ─────────────────────────────────────────────
    gr_r = gr_g = None
    if not args.skip_gr:
        print('[17] Pair correlation function g(r) ...')
        gr_r, gr_g = compute_pair_correlation(df, px_per_um)
        print(f"      g(r) computed over {min(10, df['frame'].nunique())} sample frames")
    else:
        print('[17] Pair correlation g(r) ... skipped')

    # ── 18. Spatial velocity correlation ──────────────────────────────────────
    print('[18] Spatial velocity correlation C_v(r) ...')
    cv_r, cv_v = compute_spatial_velocity_corr(df, fps)

    # ── 19. Near-wall speed profile ───────────────────────────────────────────
    print('[19] Near-wall speed profile ...')
    nw_dist, nw_speed, nw_std = compute_near_wall_speed(df, fps, px_per_um)

    # ── Save plots ─────────────────────────────────────────────────────────────
    print('\n  Saving plots ...')
    ext = _FMT

    plot_trajectories(df, out_dir / f'trajectories{ext}',
                      f'Centered Trajectories — {name}')
    plot_speed_hist(speeds, out_dir / f'speed_distribution{ext}',
                   f'Speed Distribution — {name}')
    if len(lt) > 0:
        plot_msd(lt, mv, D, alpha, out_dir / f'msd{ext}', f'MSD — {name}')
    if len(dac_lt) > 0:
        plot_directional_autocorr(dac_lt, dac_ct, tau_p,
                                   out_dir / f'directional_autocorr{ext}',
                                   f'Directional Autocorrelation — {name}')
    if rt['run_lengths']:
        plot_run_length_dist(rt['run_lengths'], out_dir / f'run_length_distribution{ext}',
                             f'Run Length Distribution — {name}')
    plot_drift_vector(drift, out_dir / f'drift_vector{ext}', f'Drift Vector — {name}')
    if not pt_classified.empty and het_stats:
        plot_population_heterogeneity(pt_classified, het_stats,
                                       out_dir / f'population_heterogeneity{ext}',
                                       f'Population Heterogeneity — {name}')
    if len(bc['events_df']) > 0:
        plot_heatmap(bc['events_df'], 'x_um', 'y_um', arena_x, arena_y,
                     out_dir / f'boundary_collision_heatmap{ext}',
                     f'Boundary Collisions — {name}')
    if isinstance(bb['events_df'], pd.DataFrame) and len(bb['events_df']) > 0:
        plot_heatmap(bb['events_df'], 'x_mid_um', 'y_mid_um', arena_x, arena_y,
                     out_dir / f'bac_bac_collision_heatmap{ext}',
                     f'Bacteria–Bacteria Collisions — {name}')
    if len(vlt) > 0:
        plot_vacf(vlt, vacf, out_dir / f'vacf{ext}', f'VACF — {name}')
    if len(turn_angles) > 0:
        plot_turning_angles(turn_angles, out_dir / f'turning_angle_distribution{ext}',
                            f'Turning Angle Distribution — {name}')
    if not curv_df.empty:
        plot_curvature(curv_df, out_dir / f'track_curvature{ext}',
                       f'Track Curvature — {name}')
    if not cr_df.empty:
        plot_confinement_ratio(cr_df, out_dir / f'confinement_ratio{ext}',
                               f'Confinement Ratio — {name}')
    if sp_merged is not None and not sp_merged.empty:
        plot_speed_persistence(sp_merged, sp_r, sp_p,
                               out_dir / f'speed_persistence_corr{ext}',
                               f'Speed–Persistence Correlation — {name}')
    if len(ng_lt) > 0:
        plot_non_gaussianity(ng_lt, ng_a2, out_dir / f'non_gaussianity{ext}',
                             f'Non-Gaussianity α₂ — {name}')
    if not act_df.empty and act_summary:
        plot_active_stationary(act_df, act_summary,
                               out_dir / f'active_stationary{ext}',
                               f'Active / Stationary Phases — {name}')
    if not pt_df.empty:
        plot_speed_tracklength(pt_df, stl_r, stl_p,
                               out_dir / f'speed_tracklength_corr{ext}',
                               f'Speed–Track-Length Correlation — {name}')
    if gr_r is not None:
        plot_pair_correlation(gr_r, gr_g, out_dir / f'pair_correlation_gr{ext}',
                              f'Pair Correlation g(r) — {name}')
    plot_spatial_velocity_corr(cv_r, cv_v, out_dir / f'spatial_velocity_corr{ext}',
                               f'Spatial Velocity Correlation — {name}')
    plot_near_wall_speed(nw_dist, nw_speed, nw_std,
                         out_dir / f'near_wall_speed_profile{ext}',
                         f'Near-Wall Speed Profile — {name}')

    # ── Save numerics ─────────────────────────────────────────────────────────
    speeds.to_csv(out_dir / 'speeds.csv', index=False, header=['speed_um_s'])
    if not pt_classified.empty:
        pt_classified.to_csv(out_dir / 'per_track_speeds.csv', index=False)
    if len(lt) > 0:
        pd.DataFrame({'lag_time_s': lt, 'msd_um2': mv, 'n_pairs': nc}).to_csv(
            out_dir / 'msd.csv', index=False)
    if len(dac_lt) > 0:
        pd.DataFrame({'lag_time_s': dac_lt, 'C_tau': dac_ct, 'n_pairs': dac_n}).to_csv(
            out_dir / 'directional_autocorr.csv', index=False)
    if len(drift['net_x']) > 0:
        pd.DataFrame({'net_x_um': drift['net_x'], 'net_y_um': drift['net_y']}).to_csv(
            out_dir / 'drift_vectors.csv', index=False)
    if len(bc['events_df']) > 0:
        bc['events_df'][['frame','particle','x_um','y_um','wall']].to_csv(
            out_dir / 'boundary_collisions.csv', index=False)
    if isinstance(bb['events_df'], pd.DataFrame) and len(bb['events_df']) > 0:
        bb['events_df'].to_csv(out_dir / 'bac_bac_collisions.csv', index=False)
    if len(vlt) > 0:
        pd.DataFrame({'lag_time_s': vlt, 'vacf': vacf, 'n_pairs': vn}).to_csv(
            out_dir / 'vacf.csv', index=False)
    if not curv_df.empty:
        curv_df.to_csv(out_dir / 'track_curvature.csv', index=False)
    if not cr_df.empty:
        cr_df.to_csv(out_dir / 'confinement_ratio.csv', index=False)
    if len(ng_lt) > 0:
        pd.DataFrame({'lag_time_s': ng_lt, 'alpha2': ng_a2}).to_csv(
            out_dir / 'non_gaussianity.csv', index=False)
    if not act_df.empty:
        act_df.to_csv(out_dir / 'active_stationary.csv', index=False)
    if gr_r is not None:
        pd.DataFrame({'r_um': gr_r, 'g_r': gr_g}).to_csv(
            out_dir / 'pair_correlation.csv', index=False)
    pd.DataFrame({'r_um': cv_r, 'Cv': cv_v}).to_csv(
        out_dir / 'spatial_velocity_corr.csv', index=False)
    pd.DataFrame({'dist_to_wall_um': nw_dist,
                  'mean_speed_um_s': nw_speed,
                  'std_speed_um_s':  nw_std}).to_csv(
        out_dir / 'near_wall_speed.csv', index=False)

    # ── Summary row ───────────────────────────────────────────────────────────
    row = {
        'file':       name,
        'n_tracks':   df['particle'].nunique(),
        'n_frames':   df['frame'].nunique(),
        'duration_s': round(duration, 4),
        'arena_x_um': round(arena_x, 3),
        'arena_y_um': round(arena_y, 3),
        # speed
        'speed_mean_um_s':   round(sp['mean_um_s'],   4),
        'speed_median_um_s': round(sp['median_um_s'], 4),
        'speed_std_um_s':    round(sp['std_um_s'],    4),
        'speed_p10_um_s':    round(sp['p10_um_s'],    4),
        'speed_p90_um_s':    round(sp['p90_um_s'],    4),
        # MSD
        'msd_D_um2_s':     round(D, 6)     if D     is not None else None,
        'msd_alpha':       round(alpha, 4) if alpha is not None else None,
        'msd_motion_type': motion_label(alpha),
        # directional autocorrelation
        'persistence_time_ms':   round(tau_p*1000, 2) if tau_p is not None else None,
        'persistence_length_um': round(persist_len, 5) if persist_len is not None else None,
        # run-tumble
        'run_mean_length_um':  round(rt['mean_run_length_um'],  4),
        'run_mean_duration_s': round(rt['mean_run_duration_s'], 4),
        'tumble_freq_hz':      round(rt['tumble_frequency_hz'], 4),
        'tumble_fraction':     round(rt['tumble_fraction'],     4),
        'n_runs':              rt['n_runs'],
        # drift
        'drift_magnitude_um': round(drift['drift_magnitude_um'], 5),
        'drift_angle_deg':    round(drift['drift_angle_deg'],    2),
        # population heterogeneity
        'frac_slow':        het_stats.get('frac_slow',        None),
        'frac_normal':      het_stats.get('frac_normal',      None),
        'frac_hypermotile': het_stats.get('frac_hypermotile', None),
        'slow_thresh_um_s': het_stats.get('slow_threshold_um_s',        None),
        'fast_thresh_um_s': het_stats.get('hypermotile_threshold_um_s', None),
        # boundary
        'boundary_x_lo_um': round(bnd_x_lo, 3),
        'boundary_x_hi_um': round(bnd_x_hi, 3),
        'boundary_y_lo_um': round(bnd_y_lo, 3),
        'boundary_y_hi_um': round(bnd_y_hi, 3),
        'boundary_source':  bnd_source,
        'boundary_events':          bc['total_events'],
        'boundary_freq_per_cell_s': round(bc['freq_per_cell_per_s'], 4),
        'boundary_left':   bc['wall_counts'].get('left',   0),
        'boundary_right':  bc['wall_counts'].get('right',  0),
        'boundary_top':    bc['wall_counts'].get('top',    0),
        'boundary_bottom': bc['wall_counts'].get('bottom', 0),
        # bac-bac
        'bac_bac_events':          bb['total_events'],
        'bac_bac_freq_per_cell_s': (round(bb['freq_per_cell_per_s'], 4)
                                    if isinstance(bb['freq_per_cell_per_s'], float)
                                    else 'skipped'),
        # VACF
        'vacf_zero_cross_ms': round(vacf_zero_cross*1000, 2) if vacf_zero_cross else None,
        # turning angles
        'fwd_bias_frac_lt45deg': round(fwd_bias, 4),
        # curvature
        'mean_curvature_rad_um': round(mean_curv, 6),
        # confinement ratio
        'mean_confinement_ratio': round(mean_cr, 5),
        # speed–persistence
        'speed_persistence_r': round(sp_r, 4) if sp_r is not None else None,
        'speed_persistence_p': round(sp_p, 6) if sp_p is not None else None,
        # non-gaussianity
        'non_gaussianity_peak': round(ng_peak, 5),
        # active fraction
        'mean_frac_active': round(act_summary.get('mean_frac_active', 0.0), 4) if act_summary else None,
        # speed–track-length
        'speed_tracklength_r': round(stl_r, 4) if stl_r is not None else None,
        'speed_tracklength_p': round(stl_p, 6) if stl_p is not None else None,
    }

    return row, speeds


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    args     = parse_args()
    root_out = Path(args.output_dir)
    root_out.mkdir(parents=True, exist_ok=True)

    print('\nBacterial Motility & Collision Analyzer  (19 analyses)')
    print(f'  fps={args.fps}  px/µm={args.px_per_um}  '
          f'min_track={args.min_track_length}  bac_r={args.bac_radius} µm  '
          f'ep_max={args.ep_max}  output={root_out}')

    summaries:  list[dict]           = []
    all_speeds: dict[str, pd.Series] = {}

    for path in args.csv_files:
        try:
            row, spd = analyze_file(path, args, root_out)
            summaries.append(row)
            all_speeds[row['file']] = spd
        except Exception as exc:
            print(f'\n  ERROR processing {path}: {exc}')
            import traceback; traceback.print_exc()

    if not summaries:
        sys.exit(1)

    s_df   = pd.DataFrame(summaries)
    s_path = root_out / 'summary.csv'
    s_df.to_csv(s_path, index=False)

    # ── Cross-file analyses ────────────────────────────────────────────────────
    if len(all_speeds) > 1:
        print('\n  Running cross-file analyses ...')
        ext = _FMT
        plot_speed_comparison(all_speeds, root_out / f'speed_comparison{ext}')
        plot_timeseries(s_df, root_out / f'motility_timeseries{ext}')
        plot_subpopulation_evolution(s_df, root_out / f'subpopulation_evolution{ext}')
        stat_df = cross_timepoint_stats_test(all_speeds)
        if not stat_df.empty:
            stat_df.to_csv(root_out / 'statistical_comparisons.csv', index=False)
            plot_stats_heatmap(stat_df, 'ks_pvalue',
                               root_out / f'ks_pvalue_heatmap{ext}',
                               'KS test p-values (pairwise speed distributions)')
            plot_stats_heatmap(stat_df, 'mw_pvalue',
                               root_out / f'mw_pvalue_heatmap{ext}',
                               'Mann-Whitney U p-values (pairwise speed distributions)')
            print(f'  Statistical comparisons  →  {root_out}/statistical_comparisons.csv')

    print(f'\n{"=" * 64}')
    print('SUMMARY')
    print(f'{"=" * 64}')
    display = [
        'file', 'n_tracks',
        'speed_mean_um_s', 'msd_alpha', 'msd_motion_type',
        'tumble_freq_hz', 'drift_magnitude_um',
        'mean_confinement_ratio', 'non_gaussianity_peak',
        'mean_frac_active', 'frac_hypermotile',
        'boundary_freq_per_cell_s', 'bac_bac_freq_per_cell_s',
    ]
    avail = [c for c in display if c in s_df.columns]
    print(s_df[avail].to_string(index=False))
    print(f'\nFull summary        →  {s_path}')
    print(f'Per-file outputs    →  {root_out}/<file_name>/')
    print(f'All plots saved at  →  {_DPI} dpi TIFF')


if __name__ == '__main__':
    main()
