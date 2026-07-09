#!/usr/bin/env python3
"""
Bacterial Motility Analyzer — GUI
-----------------------------------
Tab 1 · Full Pipeline  : image folders → track (auto_tracking.py)
                         → analyse (analyze_motility.py)
                         → trajectory graphs (graph.py)
Tab 2 · Analysis Only  : pre-tracked CSV files → analyse
"""

import sys
import os
import json
import tempfile
import threading
import subprocess
import queue
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import cv2 as _cv2
    import numpy as _np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    from PIL import Image as _PImage, ImageTk as _ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# Force UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).parent
ANALYZER   = SCRIPT_DIR / 'analyze_motility.py'
TRACKER    = SCRIPT_DIR / 'auto_tracking.py'
GRAPHER    = SCRIPT_DIR / 'graph.py'


# ─────────────────────────────────────────────────────────────────────────────
# Reusable list-panel widget (used for both folders and CSV files)
# ─────────────────────────────────────────────────────────────────────────────

class _ListPanel(ttk.Frame):
    """A labelled listbox with Add / Remove / Clear buttons."""

    def __init__(self, parent, title, add_cmd, remove_cmd, clear_cmd, **kw):
        super().__init__(parent, **kw)

        ttk.Label(self, text=title,
                  font=('TkDefaultFont', 10, 'bold')).pack(anchor='w', pady=(0, 4))

        lf = ttk.Frame(self)
        lf.pack(fill=tk.BOTH, expand=True)

        sb_y = ttk.Scrollbar(lf, orient=tk.VERTICAL)
        sb_x = ttk.Scrollbar(lf, orient=tk.HORIZONTAL)
        self.lb = tk.Listbox(
            lf, selectmode=tk.EXTENDED,
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set,
            font=('TkFixedFont', 9), bg='white',
            relief='flat', highlightthickness=1, highlightcolor='#1976d2',
        )
        sb_y.config(command=self.lb.yview)
        sb_x.config(command=self.lb.xview)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.lb.pack(fill=tk.BOTH, expand=True)

        self.detail_var = tk.StringVar(value='')
        ttk.Label(self, textvariable=self.detail_var,
                  foreground='grey', font=('TkDefaultFont', 8),
                  wraplength=220, justify='left').pack(anchor='w', pady=(3, 0))

        self.count_var = tk.StringVar(value='0 items')
        ttk.Label(self, textvariable=self.count_var,
                  foreground='grey').pack(anchor='e', pady=(2, 6))

        bf = ttk.Frame(self)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text='＋  Add',    command=add_cmd).pack(fill=tk.X, pady=(0, 3))
        ttk.Button(bf, text='－  Remove', command=remove_cmd).pack(fill=tk.X, pady=(0, 3))
        ttk.Button(bf, text='✕  Clear',  command=clear_cmd).pack(fill=tk.X)


# ─────────────────────────────────────────────────────────────────────────────
# Results viewer
# ─────────────────────────────────────────────────────────────────────────────

class _ResultsViewer(ttk.Frame):
    """Browse and view pipeline output files (images, CSVs, videos)."""

    _IMG_EXTS = {'.tiff', '.tif', '.png'}
    _CSV_EXTS = {'.csv'}
    _VID_EXTS = {'.avi', '.mp4'}
    _ICONS    = {'.tiff': '🖼', '.tif': '🖼', '.png': '🖼',
                 '.csv': '📊', '.avi': '🎬', '.mp4': '🎬'}

    def __init__(self, parent, out_var: tk.StringVar, **kw):
        super().__init__(parent, **kw)
        self._out_var   = out_var
        self._photo     = None      # keep reference to prevent GC
        self._img_orig  = None      # PIL Image at original size
        self._zoom      = 1.0
        self._cur_path: Path | None = None
        self._fit_pending = True
        self._build()

    def _build(self):
        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        left  = ttk.Frame(pw, padding=4)
        right = ttk.Frame(pw, padding=4)
        pw.add(left,  weight=1)
        pw.add(right, weight=3)

        # ── Left: file tree ───────────────────────────────────────────────────
        ttk.Button(left, text='⟳  Refresh',
                   command=self.refresh).pack(fill=tk.X, pady=(0, 4))
        frm = ttk.Frame(left)
        frm.pack(fill=tk.BOTH, expand=True)
        sby = ttk.Scrollbar(frm, orient=tk.VERTICAL)
        self._tree = ttk.Treeview(frm, show='tree', selectmode='browse',
                                   yscrollcommand=sby.set)
        sby.config(command=self._tree.yview)
        sby.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)

        # ── Right: toolbar + canvas ───────────────────────────────────────────
        tb = ttk.Frame(right)
        tb.pack(fill=tk.X, pady=(0, 3))
        ttk.Button(tb, text='🔍+', width=4, command=self._zoom_in ).pack(side=tk.LEFT)
        ttk.Button(tb, text='🔍−', width=4, command=self._zoom_out).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='Fit', width=4, command=self._zoom_fit).pack(side=tk.LEFT)
        ttk.Button(tb, text='1:1', width=4, command=self._zoom_100).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='Open in app',
                   command=self._open_ext).pack(side=tk.RIGHT)
        self._title_var = tk.StringVar(value='Select a file from the list')
        ttk.Label(tb, textvariable=self._title_var,
                  font=('TkDefaultFont', 9, 'bold'),
                  foreground='#569cd6').pack(side=tk.LEFT, padx=(10, 0))

        # canvas + scrollbars
        cf = ttk.Frame(right)
        cf.pack(fill=tk.BOTH, expand=True)
        sbx = ttk.Scrollbar(cf, orient=tk.HORIZONTAL)
        sby2 = ttk.Scrollbar(cf, orient=tk.VERTICAL)
        self._canvas = tk.Canvas(cf, bg='#1e1e1e',
                                  xscrollcommand=sbx.set,
                                  yscrollcommand=sby2.set)
        sbx.config(command=self._canvas.xview)
        sby2.config(command=self._canvas.yview)
        sbx.pack(side=tk.BOTTOM, fill=tk.X)
        sby2.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind('<Configure>',  self._on_configure)
        self._canvas.bind('<MouseWheel>', self._on_wheel)
        self._canvas.bind('<Button-4>',   self._on_wheel)
        self._canvas.bind('<Button-5>',   self._on_wheel)

        # status bar
        self._status_var = tk.StringVar(value='')
        ttk.Label(right, textvariable=self._status_var,
                  foreground='grey', font=('TkDefaultFont', 8)).pack(anchor='w')

    # ── Tree ─────────────────────────────────────────────────────────────────

    def refresh(self):
        self._tree.delete(*self._tree.get_children())
        out = Path(self._out_var.get() or 'output')
        if not out.exists():
            self._tree.insert('', 'end', text=f'(not found: {out})')
            return
        self._fill('' , out, depth=0)

    def _fill(self, parent_iid, path: Path, depth: int):
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return
        all_exts = self._IMG_EXTS | self._CSV_EXTS | self._VID_EXTS
        for entry in entries:
            if entry.is_dir():
                iid = self._tree.insert(parent_iid, 'end',
                                         text=f'📁  {entry.name}',
                                         values=[str(entry)],
                                         open=(depth == 0))
                self._fill(iid, entry, depth + 1)
            elif entry.suffix.lower() in all_exts:
                icon  = self._ICONS.get(entry.suffix.lower(), '📄')
                sz    = entry.stat().st_size
                label = (f'{sz // 1024} KB' if sz < 1_048_576
                         else f'{sz / 1_048_576:.1f} MB')
                self._tree.insert(parent_iid, 'end',
                                   text=f'{icon}  {entry.name}   ({label})',
                                   values=[str(entry)])

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], 'values')
        if not vals:
            return
        path = Path(vals[0])
        if not path.is_file():
            return
        self._cur_path = path
        self._title_var.set(path.name)
        ext = path.suffix.lower()
        if ext in self._IMG_EXTS:
            self._load_image(path)
        elif ext in self._CSV_EXTS:
            self._show_csv(path)
        elif ext in self._VID_EXTS:
            self._show_video_info(path)

    # ── Image viewer ──────────────────────────────────────────────────────────

    def _load_image(self, path: Path):
        if not _HAS_PIL:
            self._msg('PIL/Pillow not installed — cannot display images')
            return
        try:
            img = _PImage.open(str(path))
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                img.seek(0)
            self._img_orig = img.convert('RGB') if img.mode not in ('RGB','RGBA','L') else img
            self._fit_pending = True
            self._zoom_fit()
        except Exception as exc:
            self._msg(f'Cannot open: {exc}')

    def _render(self):
        if self._img_orig is None or not _HAS_PIL:
            return
        w = max(1, int(self._img_orig.width  * self._zoom))
        h = max(1, int(self._img_orig.height * self._zoom))
        try:
            resamp = _PImage.Resampling.LANCZOS
        except AttributeError:
            resamp = _PImage.LANCZOS  # type: ignore[attr-defined]
        self._photo = _ImageTk.PhotoImage(self._img_orig.resize((w, h), resamp))
        self._canvas.delete('all')
        self._canvas.create_image(0, 0, anchor='nw', image=self._photo)
        self._canvas.configure(scrollregion=(0, 0, w, h))
        sz = self._cur_path.stat().st_size if self._cur_path else 0
        self._status_var.set(
            f'{self._img_orig.width}×{self._img_orig.height} px  '
            f'zoom {self._zoom:.0%}  '
            f'{sz // 1024} KB'
        )

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.3, 8.0);  self._render()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.3, 0.04); self._render()

    def _zoom_fit(self):
        if self._img_orig is None:
            return
        cw = max(self._canvas.winfo_width(),  100)
        ch = max(self._canvas.winfo_height(), 100)
        self._zoom = max(min(cw / self._img_orig.width,
                             ch / self._img_orig.height, 1.0), 0.02)
        self._render()

    def _zoom_100(self):
        self._zoom = 1.0; self._render()

    def _on_wheel(self, event):
        factor = 1.15 if (event.num == 4 or getattr(event, 'delta', 0) > 0) else 1/1.15
        self._zoom = max(0.04, min(8.0, self._zoom * factor))
        self._render()

    def _on_configure(self, _event=None):
        if self._img_orig is not None and self._fit_pending:
            self._fit_pending = False
            self._zoom_fit()

    # ── CSV viewer ────────────────────────────────────────────────────────────

    def _show_csv(self, path: Path):
        self._img_orig = None
        self._canvas.delete('all')
        try:
            import pandas as pd
            df = pd.read_csv(path)
            n, m = df.shape
            MAX = 300
            snippet = df.head(MAX).to_string(index=False)
            if n > MAX:
                snippet += f'\n\n... ({n - MAX} more rows not shown)'
            self._canvas.create_text(8, 8, anchor='nw', text=snippet,
                                     font=('TkFixedFont', 8), fill='#d4d4d4',
                                     tags='data')
            self._canvas.update_idletasks()
            bb = self._canvas.bbox('data')
            if bb:
                self._canvas.configure(scrollregion=(0, 0, bb[2]+16, bb[3]+16))
            sz = path.stat().st_size
            self._status_var.set(
                f'{n} rows × {m} columns   '
                f'{sz // 1024} KB'
            )
        except Exception as exc:
            self._msg(f'Cannot read CSV: {exc}')

    # ── Video info ────────────────────────────────────────────────────────────

    def _show_video_info(self, path: Path):
        self._img_orig = None
        self._canvas.delete('all')
        sz_mb = path.stat().st_size / 1_048_576
        self._msg(
            f'{path.name}\n\n'
            f'Size: {sz_mb:.1f} MB\n\n'
            f'Click  "Open in app"  to play in your system video player.'
        )
        self._status_var.set(f'{sz_mb:.1f} MB  —  video file')

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _msg(self, text: str):
        self._canvas.delete('all')
        cx = max(self._canvas.winfo_width(),  300) // 2
        cy = max(self._canvas.winfo_height(), 200) // 2
        self._canvas.create_text(cx, cy, text=text,
                                  fill='#888', font=('TkDefaultFont', 11),
                                  justify='center')

    def _open_ext(self):
        target = self._cur_path or Path(self._out_var.get() or '.')
        try:
            import subprocess as sp
            sp.Popen(['xdg-open', str(target)])
        except FileNotFoundError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ROI polygon editor
# ─────────────────────────────────────────────────────────────────────────────

class _ROIEditor(tk.Toplevel):
    """
    Opens a frame from the selected image folder and lets the user click to
    draw a polygonal ROI.

    - Left-click         : add vertex
    - Right-click / Z    : undo last vertex
    - Double-left-click  : confirm & close
    - Escape             : cancel

    Stores vertices in the image pixel coordinate space that matches
    auto_tracking.py (resized to 1232×1028).
    """

    # Image size used by auto_tracking.py after resize
    _IMG_W, _IMG_H = 1232, 1028

    def __init__(self, parent, folder: str | None, px_per_um: float,
                 existing_verts=None, callback=None):
        super().__init__(parent)
        self.title('Draw Polygonal ROI — left-click to add, double-click to confirm')
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._px_per_um = px_per_um
        self._callback  = callback          # called with (vertices_list, img_w, img_h) on confirm
        self._vertices  = list(existing_verts) if existing_verts else []  # [(x, y) in image px]
        self._photo     = None              # keep reference to avoid GC
        self._tmp_png   = None

        # ── Canvas size (fit to screen, keep aspect ratio) ────────────────────
        scr_w = self.winfo_screenwidth()
        scr_h = self.winfo_screenheight()
        max_cw = max(640, scr_w - 120)
        max_ch = max(480, scr_h - 200)
        scale  = min(max_cw / self._IMG_W, max_ch / self._IMG_H, 1.0)
        self._cw = int(self._IMG_W * scale)
        self._ch = int(self._IMG_H * scale)
        self._scale = scale                 # image_px → canvas_px

        self.geometry(f'{self._cw + 20}x{self._ch + 120}')

        # ── Toolbar ───────────────────────────────────────────────────────────
        tf = ttk.Frame(self, padding=(6, 4))
        tf.pack(fill=tk.X)
        ttk.Button(tf, text='↩  Undo vertex',  command=self._undo).pack(side=tk.LEFT, padx=3)
        ttk.Button(tf, text='✕  Clear all',    command=self._clear).pack(side=tk.LEFT, padx=3)
        ttk.Button(tf, text='✓  Confirm ROI',  command=self._confirm,
                   style='Run.TButton').pack(side=tk.RIGHT, padx=3)
        ttk.Button(tf, text='Cancel',          command=self.destroy).pack(side=tk.RIGHT, padx=3)

        # ── Canvas ────────────────────────────────────────────────────────────
        cf = ttk.Frame(self)
        cf.pack(fill=tk.BOTH, expand=True, padx=6)
        self._canvas = tk.Canvas(cf, width=self._cw, height=self._ch,
                                 bg='#111', cursor='crosshair',
                                 highlightthickness=1, highlightcolor='#555')
        self._canvas.pack()

        self._canvas.bind('<Button-1>',        self._on_lclick)
        self._canvas.bind('<Double-Button-1>', self._on_dbl)
        self._canvas.bind('<Button-3>',        self._undo)
        self.bind('<z>', self._undo)
        self.bind('<Escape>', lambda _: self.destroy())

        # ── Status bar ────────────────────────────────────────────────────────
        self._info_var = tk.StringVar(value='No image loaded — click "Confirm ROI" '
                                      'without an image to use coordinates only.')
        ttk.Label(self, textvariable=self._info_var,
                  relief='sunken', anchor='w', padding=(6, 2)).pack(fill=tk.X, padx=6, pady=(2, 6))

        # ── Load background image ─────────────────────────────────────────────
        self._load_frame(folder)
        self._redraw()

    # ── Image loading ─────────────────────────────────────────────────────────

    def _load_frame(self, folder):
        if not folder or not _HAS_CV2:
            self._update_info()
            return
        folder = Path(folder)
        tiffs = sorted(list(folder.glob('*.tiff')) + list(folder.glob('*.tif')))
        if not tiffs:
            self._update_info()
            return
        img = _cv2.imread(str(tiffs[0]), _cv2.IMREAD_GRAYSCALE)
        if img is None:
            self._update_info()
            return
        img = _cv2.resize(img, (self._IMG_W, self._IMG_H))
        disp = _cv2.resize(img, (self._cw, self._ch))
        # Use PIL if available, else temp PNG
        if _HAS_PIL:
            pil_img = _PImage.fromarray(disp)
            self._photo = _ImageTk.PhotoImage(pil_img)
        else:
            self._tmp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            _cv2.imwrite(self._tmp_png.name, disp)
            self._photo = tk.PhotoImage(file=self._tmp_png.name)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self):
        self._canvas.delete('all')
        # Background image
        if self._photo:
            self._canvas.create_image(0, 0, anchor='nw', image=self._photo)
        else:
            self._canvas.create_rectangle(0, 0, self._cw, self._ch, fill='#222')
            self._canvas.create_text(self._cw // 2, self._ch // 2,
                                     text='No image  (click to add vertices)',
                                     fill='#888', font=('TkDefaultFont', 12))
        if not self._vertices:
            self._update_info()
            return
        # Draw polygon fill (translucent via stipple)
        cverts = [self._to_canvas(x, y) for x, y in self._vertices]
        flat = [c for xy in cverts for c in xy]
        if len(cverts) >= 3:
            self._canvas.create_polygon(flat, fill='#4fc3f7', stipple='gray25',
                                        outline='#29b6f6', width=2)
        elif len(cverts) >= 2:
            self._canvas.create_line(flat, fill='#29b6f6', width=2)
        # Closing line (dashed) from last to first
        if len(cverts) >= 3:
            self._canvas.create_line(*cverts[-1], *cverts[0],
                                     fill='#29b6f6', width=1, dash=(4, 4))
        # Vertices
        for i, (cx, cy) in enumerate(cverts):
            r = 5
            color = '#ef5350' if i == 0 else '#fff176'
            self._canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                     fill=color, outline='black', width=1)
            self._canvas.create_text(cx+8, cy-8, text=str(i+1),
                                     fill='white', font=('TkDefaultFont', 8))
        self._update_info()

    def _to_canvas(self, ix, iy):
        """Image pixel → canvas pixel."""
        return ix * self._scale, iy * self._scale

    def _to_image(self, cx, cy):
        """Canvas pixel → image pixel (rounded)."""
        return round(cx / self._scale), round(cy / self._scale)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_lclick(self, event):
        ix, iy = self._to_image(event.x, event.y)
        self._vertices.append((ix, iy))
        self._redraw()

    def _on_dbl(self, event):
        # double-click fires single then double; undo the extra single vertex
        if self._vertices:
            self._vertices.pop()
        self._confirm()

    def _undo(self, _event=None):
        if self._vertices:
            self._vertices.pop()
        self._redraw()

    def _clear(self):
        self._vertices.clear()
        self._redraw()

    def _confirm(self):
        if len(self._vertices) < 3:
            messagebox.showwarning('ROI', 'Draw at least 3 vertices to define a polygon.',
                                   parent=self)
            return
        if self._callback:
            self._callback(list(self._vertices), self._IMG_W, self._IMG_H)
        self.destroy()

    # ── Area / info ───────────────────────────────────────────────────────────

    def _update_info(self):
        n = len(self._vertices)
        if n == 0:
            self._info_var.set('Click on the image to place polygon vertices.  '
                               'Right-click or Z to undo.  Double-click to confirm.')
            return
        parts = [f'{n} vertices']
        if n >= 3:
            import math
            verts = self._vertices
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            n2 = len(verts)
            area_px2 = abs(sum(
                xs[i]*ys[(i+1)%n2] - xs[(i+1)%n2]*ys[i]
                for i in range(n2)
            )) / 2
            area_um2 = area_px2 / (self._px_per_um ** 2)
            total_px2 = self._IMG_W * self._IMG_H
            total_um2 = total_px2 / (self._px_per_um ** 2)
            unmasked  = total_um2 - area_um2
            parts.append(f'Masked (ROI) area = {area_um2:,.1f} µm²')
            parts.append(f'Unmasked area = {unmasked:,.1f} µm²')
        self._info_var.set('  |  '.join(parts))

    def __del__(self):
        if self._tmp_png:
            try:
                os.unlink(self._tmp_png.name)
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class MotilityGUI(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('Bacterial Motility Analyzer')
        self.geometry('1220x860')
        self.minsize(960, 680)

        self._apply_style()

        # data lists
        self._folders: list[str] = []   # pipeline mode
        self._files:   list[str] = []   # analysis-only mode

        # ROI polygon state (pipeline mode)
        self._roi_vertices: list[tuple[int, int]] = []  # [(x, y) in image px]
        self._roi_img_w: int = _ROIEditor._IMG_W
        self._roi_img_h: int = _ROIEditor._IMG_H

        # Output folder var — initialised here so _ResultsViewer can use it
        # during _build_ui(); _build_bottom() will reuse the same StringVar.
        self.out_var = tk.StringVar(value=str(SCRIPT_DIR / 'output'))

        self._running = False
        self._process = None
        self._log_q:  queue.Queue = queue.Queue()

        self._build_ui()
        self._poll_log()

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        s.configure('Run.TButton',
                    font=('TkDefaultFont', 10, 'bold'),
                    foreground='white', background='#1565c0', padding=6)
        s.map('Run.TButton',
              background=[('active', '#1976d2'), ('disabled', '#9e9e9e')])
        s.configure('RunA.TButton',
                    font=('TkDefaultFont', 10, 'bold'),
                    foreground='white', background='#2e7d32', padding=6)
        s.map('RunA.TButton',
              background=[('active', '#388e3c'), ('disabled', '#9e9e9e')])
        s.configure('Stop.TButton',
                    font=('TkDefaultFont', 10),
                    foreground='white', background='#c62828', padding=6)
        s.map('Stop.TButton',
              background=[('active', '#d32f2f'), ('disabled', '#9e9e9e')])

    # ── Top-level layout ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Mode notebook (top)
        self._mode_nb = ttk.Notebook(self)
        self._mode_nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        self._mode_nb.bind('<<NotebookTabChanged>>', self._on_mode_change)

        pipeline_frame = ttk.Frame(self._mode_nb, padding=4)
        analysis_frame = ttk.Frame(self._mode_nb, padding=4)
        results_frame  = ttk.Frame(self._mode_nb, padding=4)
        self._mode_nb.add(pipeline_frame, text='  🔬  Full Pipeline  ')
        self._mode_nb.add(analysis_frame, text='  📊  Analysis Only  ')
        self._mode_nb.add(results_frame,  text='  📈  Results  ')

        self._build_pipeline_tab(pipeline_frame)
        self._build_analysis_tab(analysis_frame)

        self._results_viewer = _ResultsViewer(results_frame, self.out_var)
        self._results_viewer.pack(fill=tk.BOTH, expand=True)

        # Shared bottom: output folder, log, progress, buttons, status
        self._build_bottom(self)

    # ── Pipeline tab ──────────────────────────────────────────────────────────

    def _build_pipeline_tab(self, parent):
        pw = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        left  = ttk.Frame(pw, padding=4)
        right = ttk.Frame(pw, padding=4)
        pw.add(left,  weight=1)
        pw.add(right, weight=3)

        # Folder list panel
        self._folder_panel = _ListPanel(
            left, 'Image Folders (one per timepoint)',
            self._add_folders, self._remove_folders, self._clear_folders,
        )
        self._folder_panel.pack(fill=tk.BOTH, expand=True)
        self._folder_panel.lb.bind('<<ListboxSelect>>', self._on_folder_select)

        # Parameter notebook
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.X, pady=(0, 4))

        trk_frame  = ttk.Frame(nb, padding=(14, 10))
        ana_frame  = ttk.Frame(nb, padding=(14, 10))
        adv_frame  = ttk.Frame(nb, padding=(14, 10))
        nb.add(trk_frame,  text='  Tracking  ')
        nb.add(ana_frame,  text='  Analysis (Basic)  ')
        nb.add(adv_frame,  text='  Analysis (Advanced)  ')

        self._build_tracking_tab(trk_frame)
        self._build_pl_analysis_tab(ana_frame)
        self._build_pl_adv_tab(adv_frame)

        # ROI panel (below parameter notebook, inside right pane)
        self._build_roi_panel(right)

    def _build_tracking_tab(self, p):
        p.columnconfigure(2, weight=1)
        self.pixel_size_var   = self._param_row(p, 0, 'Pixel size (µm/px)', tk.DoubleVar, 0.349,
                                                 'µm per pixel after resize  (1 / px_per_µm)')
        self.trk_fps_var      = self._param_row(p, 1, 'FPS',                tk.DoubleVar, 10.0,
                                                 'Camera frame rate')
        self.diameter_var     = self._param_row(p, 2, 'Feature diameter (px)', tk.IntVar,  9,
                                                 'Must be odd; ~apparent cell size in pixels')
        self.trk_minmass_var  = self._param_row(p, 3, 'Min mass',           tk.DoubleVar, 200.0,
                                                 'Min integrated brightness — raise to reject background')
        self.search_range_var = self._param_row(p, 4, 'Search range (px)',  tk.IntVar,    8,
                                                 'Max displacement between frames to link same cell')
        self.memory_var       = self._param_row(p, 5, 'Memory (frames)',    tk.IntVar,    3,
                                                 'Frames a cell may vanish and still be re-linked')

        ttk.Separator(p, orient='horizontal').grid(
            row=6, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(p,
                  text='FPS and pixel size are shared with the analysis step automatically.',
                  foreground='grey', font=('TkDefaultFont', 8),
                  ).grid(row=7, column=0, columnspan=3, sticky='w')

    def _build_pl_analysis_tab(self, p):
        p.columnconfigure(2, weight=1)
        self.pl_min_trk_var = self._param_row(p, 0, 'Min track length',    tk.IntVar,    10,
                                               'Frames — shorter tracks excluded')
        self.pl_ep_var      = self._param_row(p, 1, 'ep max',              tk.DoubleVar, 1.0,
                                               'Max |ep| localisation error to keep')
        self.pl_min_mass_var= self._param_row(p, 2, 'Min mass (post-track)',tk.DoubleVar, 0.0,
                                               'Extra brightness filter after tracking (0 = off)')
        self.pl_bac_r_var   = self._param_row(p, 3, 'Bacterium radius (µm)',tk.DoubleVar, 0.5,
                                               'Used for collision distance thresholds')

    def _build_pl_adv_tab(self, p):
        p.columnconfigure(2, weight=1)
        self.pl_tumble_var  = self._param_row(p, 0, 'Tumble angle (°)',     tk.DoubleVar, 90.0,
                                               'Direction change above this → tumble')
        self.pl_maxlag_var  = self._param_row(p, 1, 'Max lag (frames)',     tk.IntVar,    20,
                                               'Maximum lag for MSD / autocorrelation')
        self.pl_statsp_var  = self._param_row(p, 2, 'Stationary speed (µm/s)', tk.DoubleVar, 0.5,
                                               'Steps below this → stationary')
        ttk.Separator(p, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky='ew', pady=8)
        self.pl_skip_bac_var = tk.BooleanVar(value=False)
        self.pl_skip_gr_var  = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text='Skip bacteria–bacteria collisions',
                        variable=self.pl_skip_bac_var,
                        ).grid(row=4, column=0, columnspan=3, sticky='w')
        ttk.Checkbutton(p, text='Skip pair correlation g(r)  (slow for large datasets)',
                        variable=self.pl_skip_gr_var,
                        ).grid(row=5, column=0, columnspan=3, sticky='w')

    # ── ROI panel ─────────────────────────────────────────────────────────────

    def _build_roi_panel(self, parent):
        lf = ttk.LabelFrame(parent, text=' Polygonal ROI Mask  (optional) ', padding=(8, 5))
        lf.pack(fill=tk.X, pady=(6, 0))

        # Info row
        self._roi_info_var = tk.StringVar(value='No ROI defined — full image will be analysed.')
        ttk.Label(lf, textvariable=self._roi_info_var,
                  font=('TkDefaultFont', 8), foreground='grey',
                  wraplength=500, justify='left').pack(anchor='w')

        # Button row
        bf = ttk.Frame(lf)
        bf.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(bf, text='Draw ROI on frame…', command=self._draw_roi).pack(side=tk.LEFT)
        ttk.Button(bf, text='Clear ROI',          command=self._clear_roi).pack(side=tk.LEFT, padx=(6, 0))
        if not _HAS_CV2:
            ttk.Label(bf, text='(cv2 not found — no image preview, vertex entry only)',
                      foreground='#c62828', font=('TkDefaultFont', 8)).pack(side=tk.LEFT, padx=(10, 0))

    def _draw_roi(self):
        folder = self._folders[0] if self._folders else None
        px_per_um = self.pixel_size_var.get()

        def _on_confirm(verts, img_w, img_h):
            self._roi_vertices = verts
            self._roi_img_w    = img_w
            self._roi_img_h    = img_h
            self._refresh_roi_info()

        _ROIEditor(self, folder, px_per_um,
                   existing_verts=self._roi_vertices,
                   callback=_on_confirm)

    def _clear_roi(self):
        self._roi_vertices = []
        self._refresh_roi_info()

    def _refresh_roi_info(self):
        n = len(self._roi_vertices)
        if n == 0:
            self._roi_info_var.set('No ROI defined — full image will be analysed.')
            return
        px_per_um = self.pixel_size_var.get()
        xs = [v[0] for v in self._roi_vertices]
        ys = [v[1] for v in self._roi_vertices]
        area_px2 = abs(sum(
            xs[i]*ys[(i+1)%n] - xs[(i+1)%n]*ys[i] for i in range(n)
        )) / 2
        area_um2    = area_px2 / (px_per_um ** 2)
        total_um2   = (self._roi_img_w * self._roi_img_h) / (px_per_um ** 2)
        unmasked_um2 = total_um2 - area_um2
        self._roi_info_var.set(
            f'{n} vertices  |  Masked (ROI) area: {area_um2:,.1f} µm²  |  '
            f'Unmasked area: {unmasked_um2:,.1f} µm²  '
            f'({area_um2/total_um2:.1%} of image)'
        )

    # ── Analysis-only tab ─────────────────────────────────────────────────────

    def _build_analysis_tab(self, parent):
        pw = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        left  = ttk.Frame(pw, padding=4)
        right = ttk.Frame(pw, padding=4)
        pw.add(left,  weight=1)
        pw.add(right, weight=3)

        # CSV file list panel
        self._file_panel = _ListPanel(
            left, 'Input CSV Files',
            self._add_files, self._remove_files, self._clear_files,
        )
        self._file_panel.pack(fill=tk.BOTH, expand=True)
        self._file_panel.lb.bind('<<ListboxSelect>>', self._on_file_select)

        # Parameter notebook
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.X, pady=(0, 4))

        basic = ttk.Frame(nb, padding=(14, 10))
        adv   = ttk.Frame(nb, padding=(14, 10))
        nb.add(basic, text='  Basic Parameters  ')
        nb.add(adv,   text='  Advanced Parameters  ')
        self._build_basic_tab(basic)
        self._build_adv_tab(adv)

    def _build_basic_tab(self, p):
        p.columnconfigure(2, weight=1)
        self.fps_var      = self._param_row(p, 0, 'FPS',                 tk.DoubleVar, 50.0,
                                             'Camera frame rate (frames per second)')
        self.px_var       = self._param_row(p, 1, 'Pixels / µm',        tk.DoubleVar, 50.0,
                                             'Spatial calibration  (50 px/µm → 1 px = 20 nm)')
        self.min_trk_var  = self._param_row(p, 2, 'Min track length',   tk.IntVar,    10,
                                             'Frames — tracks shorter than this are excluded')
        self.ep_var       = self._param_row(p, 3, 'ep max',             tk.DoubleVar, 1.0,
                                             'Max localisation error |ep| to keep')
        self.min_mass_var = self._param_row(p, 4, 'Min mass',           tk.DoubleVar, 0.0,
                                             'Min integrated intensity; raise to reject dim background (0 = off)')
        self.bac_r_var    = self._param_row(p, 5, 'Bacterium radius (µm)', tk.DoubleVar, 0.5,
                                             'Half-width used for collision distance thresholds')

    def _build_adv_tab(self, p):
        p.columnconfigure(2, weight=1)
        self.tumble_var  = self._param_row(p, 0, 'Tumble angle (°)',      tk.DoubleVar, 90.0,
                                            'Direction change above this → classified as tumble')
        self.max_lag_var = self._param_row(p, 1, 'Max lag (frames)',      tk.IntVar,    20,
                                            'Maximum lag computed for MSD and autocorrelation')
        self.stat_sp_var = self._param_row(p, 2, 'Stationary speed (µm/s)', tk.DoubleVar, 0.5,
                                            'Steps slower than this → classified as stationary')
        ttk.Separator(p, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(p, text='Arena boundaries  (leave empty → auto-detect from data)',
                  foreground='grey', font=('TkDefaultFont', 8),
                  ).grid(row=4, column=0, columnspan=3, sticky='w')
        self.bnd_xlo_var = self._param_row(p, 5, 'Boundary X lo (µm)', tk.StringVar, '', '')
        self.bnd_xhi_var = self._param_row(p, 6, 'Boundary X hi (µm)', tk.StringVar, '', '')
        self.bnd_ylo_var = self._param_row(p, 7, 'Boundary Y lo (µm)', tk.StringVar, '', '')
        self.bnd_yhi_var = self._param_row(p, 8, 'Boundary Y hi (µm)', tk.StringVar, '', '')
        ttk.Separator(p, orient='horizontal').grid(
            row=9, column=0, columnspan=3, sticky='ew', pady=8)
        self.skip_bac_var = tk.BooleanVar(value=False)
        self.skip_gr_var  = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text='Skip bacteria–bacteria collisions  (recommended for >10 000 bacteria/frame)',
                        variable=self.skip_bac_var,
                        ).grid(row=10, column=0, columnspan=3, sticky='w')
        ttk.Checkbutton(p, text='Skip pair correlation g(r)  (slow for large datasets)',
                        variable=self.skip_gr_var,
                        ).grid(row=11, column=0, columnspan=3, sticky='w')

    # ── Shared bottom (output folder + log + controls) ────────────────────────

    def _build_bottom(self, parent):
        # Output folder  (out_var already created in __init__)
        olf = ttk.LabelFrame(parent, text=' Output Folder ', padding=(8, 5))
        olf.pack(fill=tk.X, padx=8, pady=(4, 0))
        ttk.Entry(olf, textvariable=self.out_var,
                  font=('TkFixedFont', 9)).pack(side=tk.LEFT, fill=tk.X,
                                                 expand=True, padx=(0, 6))
        ttk.Button(olf, text='Browse…', command=self._browse_out).pack(side=tk.LEFT)

        # Log
        llf = ttk.LabelFrame(parent, text=' Log ', padding=(5, 5))
        llf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(6, 0))
        self.log = scrolledtext.ScrolledText(
            llf, font=('TkFixedFont', 9),
            bg='#1e1e1e', fg='#d4d4d4', insertbackground='white',
            state=tk.DISABLED, wrap=tk.NONE, height=14,
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_config('err', foreground='#f48771')
        self.log.tag_config('ok',  foreground='#89d185')
        self.log.tag_config('hdr', foreground='#569cd6')
        self.log.tag_config('dim', foreground='#888888')
        self.log.tag_config('sep', foreground='#c586c0')

        # Progress
        self.progress = ttk.Progressbar(parent, mode='indeterminate')
        self.progress.pack(fill=tk.X, padx=8, pady=(4, 0))

        # Buttons
        bf = ttk.Frame(parent, padding=(8, 4))
        bf.pack(fill=tk.X)

        self.run_btn = ttk.Button(bf, text='▶   Run Full Pipeline',
                                   command=self._run, style='Run.TButton')
        self.run_btn.pack(side=tk.LEFT)

        self.stop_btn = ttk.Button(bf, text='■   Stop',
                                    command=self._stop, state=tk.DISABLED,
                                    style='Stop.TButton')
        self.stop_btn.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bf, text='Open Output Folder',
                   command=self._open_out).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(bf, text='Clear Log',
                   command=self._clear_log).pack(side=tk.RIGHT)

        # Status bar
        self.status_var = tk.StringVar(value='Ready.')
        ttk.Label(parent, textvariable=self.status_var,
                  relief='sunken', anchor='w',
                  padding=(6, 2)).pack(fill=tk.X, padx=8, pady=(2, 6))

    # ── Mode switch ───────────────────────────────────────────────────────────

    def _on_mode_change(self, _event=None):
        idx = self._mode_nb.index('current')
        if idx == 0:
            self.run_btn.config(text='▶   Run Full Pipeline',
                                style='Run.TButton', state=tk.NORMAL,
                                command=self._run)
        elif idx == 1:
            self.run_btn.config(text='▶   Run Analysis',
                                style='RunA.TButton', state=tk.NORMAL,
                                command=self._run)
        else:
            # Results tab: repurpose run button as Refresh
            self.run_btn.config(text='⟳   Refresh Results',
                                style='RunA.TButton', state=tk.NORMAL,
                                command=self._results_viewer.refresh)
            self._results_viewer.refresh()

    def _current_mode(self) -> str:
        idx = self._mode_nb.index('current')
        return ('pipeline', 'analysis', 'results')[idx]

    # ── Helper: parameter row ─────────────────────────────────────────────────

    def _param_row(self, parent, row, label, vtype, default, hint=''):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky='w', padx=(0, 12), pady=4)
        var = vtype(value=default)
        ttk.Entry(parent, textvariable=var, width=12).grid(
            row=row, column=1, sticky='w', pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground='grey',
                      font=('TkDefaultFont', 8)).grid(
                row=row, column=2, sticky='w', padx=(10, 0))
        return var

    # ── Folder management (pipeline) ──────────────────────────────────────────

    def _add_folders(self):
        folders = filedialog.askdirectory(
            title='Select image folder (one timepoint)',
            mustexist=True,
        )
        if folders and folders not in self._folders:
            self._folders.append(folders)
            self._folder_panel.lb.insert(tk.END, Path(folders).name)
            self._update_folder_count()
            self._folder_panel.lb.see(tk.END)

    def _remove_folders(self):
        for i in reversed(self._folder_panel.lb.curselection()):
            self._folder_panel.lb.delete(i)
            del self._folders[i]
        self._update_folder_count()
        self._folder_panel.detail_var.set('')

    def _clear_folders(self):
        self._folder_panel.lb.delete(0, tk.END)
        self._folders.clear()
        self._update_folder_count()
        self._folder_panel.detail_var.set('')

    def _update_folder_count(self):
        n = len(self._folders)
        self._folder_panel.count_var.set(f'{n} folder{"s" if n != 1 else ""}')

    def _on_folder_select(self, _event=None):
        sel = self._folder_panel.lb.curselection()
        if sel:
            self._folder_panel.detail_var.set(self._folders[sel[-1]])
        else:
            self._folder_panel.detail_var.set('')

    # ── File management (analysis-only) ──────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title='Select trackpy CSV files',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')],
        )
        existing = set(self._files)
        for p in paths:
            if p not in existing:
                self._files.append(p)
                self._file_panel.lb.insert(tk.END, Path(p).name)
                existing.add(p)
        self._update_file_count()
        if paths:
            self._file_panel.lb.see(tk.END)

    def _remove_files(self):
        for i in reversed(self._file_panel.lb.curselection()):
            self._file_panel.lb.delete(i)
            del self._files[i]
        self._update_file_count()
        self._file_panel.detail_var.set('')

    def _clear_files(self):
        self._file_panel.lb.delete(0, tk.END)
        self._files.clear()
        self._update_file_count()
        self._file_panel.detail_var.set('')

    def _update_file_count(self):
        n = len(self._files)
        self._file_panel.count_var.set(f'{n} file{"s" if n != 1 else ""}')

    def _on_file_select(self, _event=None):
        sel = self._file_panel.lb.curselection()
        if sel:
            self._file_panel.detail_var.set(self._files[sel[-1]])
        else:
            self._file_panel.detail_var.set('')

    # ── Output / log helpers ──────────────────────────────────────────────────

    def _browse_out(self):
        d = filedialog.askdirectory(title='Select output folder',
                                    initialdir=self.out_var.get() or '.')
        if d:
            self.out_var.set(d)

    def _open_out(self):
        import subprocess as sp
        p = self.out_var.get() or '.'
        Path(p).mkdir(parents=True, exist_ok=True)
        try:
            sp.Popen(['xdg-open', p])
        except FileNotFoundError:
            messagebox.showinfo('Output folder', p)

    def _log_write(self, text, tag=None):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _clear_log(self):
        self.log.config(state=tk.NORMAL)
        self.log.delete('1.0', tk.END)
        self.log.config(state=tk.DISABLED)

    def _poll_log(self):
        while not self._log_q.empty():
            text, tag = self._log_q.get_nowait()
            self._log_write(text, tag)
        self.after(80, self._poll_log)

    # ── Command builders ──────────────────────────────────────────────────────

    def _build_pipeline_steps(self) -> list[tuple[str, list[str]]]:
        """Return [(step_label, cmd), ...] for the full pipeline."""
        if not self._folders:
            raise ValueError('Add at least one image folder before running.')
        for script in (TRACKER, ANALYZER, GRAPHER):
            if not script.exists():
                raise FileNotFoundError(f'Script not found: {script}')

        pixel_size = self.pixel_size_var.get()
        fps        = self.trk_fps_var.get()
        px_per_um  = round(1.0 / pixel_size, 6)
        out_base   = Path(self.out_var.get() or 'output')

        steps: list[tuple[str, list[str]]] = []
        csv_paths: list[str] = []

        # --- tracking steps (one per folder) ---
        for folder in self._folders:
            label   = Path(folder).name
            out_dir = out_base / label
            csv_paths.append(str(out_dir / f'tracking_{label}.csv'))
            steps.append((
                f'Tracking  →  {label}',
                [
                    sys.executable, '-u', str(TRACKER),
                    '--input',  folder,
                    '--output', str(out_dir),
                    '--label',  label,
                ],
            ))

        # --- serialise ROI polygon if defined ---
        roi_file = None
        if self._roi_vertices:
            roi_file = str(out_base / 'roi_polygon.json')
            with open(roi_file, 'w') as f:
                json.dump({
                    'vertices': [list(v) for v in self._roi_vertices],
                    'image_w':  self._roi_img_w,
                    'image_h':  self._roi_img_h,
                }, f, indent=2)

        # --- analysis step (all CSVs together) ---
        ana_out = out_base / 'motility_analysis'
        ana_cmd = [
            sys.executable, '-u', str(ANALYZER),
            *csv_paths,
            '--fps',              str(fps),
            '--px-per-um',        str(px_per_um),
            '--min-track-length', str(self.pl_min_trk_var.get()),
            '--ep-max',           str(self.pl_ep_var.get()),
            '--min-mass',         str(self.pl_min_mass_var.get()),
            '--bac-radius',       str(self.pl_bac_r_var.get()),
            '--tumble-angle',     str(self.pl_tumble_var.get()),
            '--max-lag',          str(self.pl_maxlag_var.get()),
            '--stationary-speed', str(self.pl_statsp_var.get()),
            '--output-dir',       str(ana_out),
        ]
        if roi_file:
            ana_cmd += ['--roi-polygon-file', roi_file]
        if self.pl_skip_bac_var.get():
            ana_cmd.append('--skip-bac-bac')
        if self.pl_skip_gr_var.get():
            ana_cmd.append('--skip-gr')
        steps.append(('Motility Analysis  (all timepoints)', ana_cmd))

        # --- graph steps (one per folder) ---
        for folder, csv_path in zip(self._folders, csv_paths):
            label   = Path(folder).name
            out_dir = out_base / label
            steps.append((
                f'Trajectory graph  →  {label}',
                [
                    sys.executable, '-u', str(GRAPHER),
                    '--csv',    csv_path,
                    '--output', str(out_dir),
                ],
            ))

        return steps

    def _build_analysis_cmd(self) -> list[str]:
        if not self._files:
            raise ValueError('Add at least one CSV file before running.')
        if not ANALYZER.exists():
            raise FileNotFoundError(f'Analyzer not found: {ANALYZER}')
        cmd = [
            sys.executable, '-u', str(ANALYZER),
            *self._files,
            '--fps',              str(self.fps_var.get()),
            '--px-per-um',        str(self.px_var.get()),
            '--min-track-length', str(self.min_trk_var.get()),
            '--ep-max',           str(self.ep_var.get()),
            '--min-mass',         str(self.min_mass_var.get()),
            '--bac-radius',       str(self.bac_r_var.get()),
            '--tumble-angle',     str(self.tumble_var.get()),
            '--max-lag',          str(self.max_lag_var.get()),
            '--stationary-speed', str(self.stat_sp_var.get()),
            '--output-dir',       self.out_var.get() or 'motility_analysis',
        ]
        if self.skip_bac_var.get():
            cmd.append('--skip-bac-bac')
        if self.skip_gr_var.get():
            cmd.append('--skip-gr')
        for val, flag in [
            (self.bnd_xlo_var.get(), '--boundary-x-lo'),
            (self.bnd_xhi_var.get(), '--boundary-x-hi'),
            (self.bnd_ylo_var.get(), '--boundary-y-lo'),
            (self.bnd_yhi_var.get(), '--boundary-y-hi'),
        ]:
            if val.strip():
                cmd += [flag, val.strip()]
        return cmd

    # ── Run / stop ────────────────────────────────────────────────────────────

    def _run(self):
        if self._running:
            return
        mode = self._current_mode()
        if mode == 'results':
            self._results_viewer.refresh()
            return
        try:
            if mode == 'pipeline':
                steps = self._build_pipeline_steps()
                n_folders = len(self._folders)
                header = (
                    f'Mode   : Full Pipeline\n'
                    f'Folders: {n_folders}  →  '
                    + ', '.join(Path(f).name for f in self._folders) + '\n'
                    f'Output : {self.out_var.get()}\n'
                    f'Steps  : {len(steps)}  '
                    f'({n_folders} tracking + 1 analysis + {n_folders} graphs)\n'
                    f'{"─" * 64}\n\n'
                )
                worker_target = self._worker_pipeline
                worker_args   = (steps,)
                status_msg    = 'Running full pipeline…'
            else:
                cmd = self._build_analysis_cmd()
                n = len(self._files)
                header = (
                    f'Mode  : Analysis Only\n'
                    f'Files : {n} CSV file{"s" if n != 1 else ""}\n'
                    f'Output: {self.out_var.get()}\n'
                    f'{"─" * 64}\n\n'
                )
                worker_target = self._worker_analysis
                worker_args   = (cmd,)
                status_msg    = 'Running analysis…'
        except (ValueError, FileNotFoundError) as e:
            messagebox.showwarning('Cannot start', str(e))
            return

        self._running = True
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set(status_msg)
        self._clear_log()
        self._log_write(header, 'hdr')
        self.progress.start(12)
        threading.Thread(target=worker_target, args=worker_args, daemon=True).start()

    # ── Pipeline worker: runs steps sequentially ──────────────────────────────

    _ENV = dict(os.environ, PYTHONUNBUFFERED='1')

    def _worker_pipeline(self, steps: list[tuple[str, list[str]]]):
        success = True
        n = len(steps)
        for i, (label, cmd) in enumerate(steps, 1):
            sep = f'\n{"─" * 64}\n  [{i}/{n}]  {label}\n{"─" * 64}\n'
            self._log_q.put((sep, 'sep'))
            self.after(0, lambda l=f'[{i}/{n}] {label}': self.status_var.set(l))
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env=self._ENV,
                )
                for line in self._process.stdout:
                    self._log_q.put((line, self._classify_line(line)))
                    hint = self._status_hint(line, label)
                    if hint:
                        self.after(0, lambda h=hint: self.status_var.set(h))
                self._process.wait()
                if self._process.returncode != 0:
                    self._log_q.put((
                        f'\n✗  Step failed (exit {self._process.returncode})\n', 'err'))
                    success = False
                    break
                self._log_q.put((f'✓  Done\n', 'ok'))
            except Exception as exc:
                self._log_q.put((f'\n✗  {exc}\n', 'err'))
                success = False
                break

        self._running = False
        self._process = None
        out = self.out_var.get()
        msg = (f'Pipeline complete — results in: {out}/motility_analysis'
               if success else 'Pipeline failed — see log')
        if success:
            self._log_q.put((f'\n{"=" * 64}\n✓  Pipeline completed successfully.\n{"=" * 64}\n', 'ok'))
        self.after(0, lambda m=msg: self._on_done(m))

    # ── Analysis-only worker ──────────────────────────────────────────────────

    def _worker_analysis(self, cmd: list[str]):
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env=self._ENV,
            )
            for line in self._process.stdout:
                self._log_q.put((line, self._classify_line(line)))
                hint = self._status_hint(line, 'Analysis')
                if hint:
                    self.after(0, lambda h=hint: self.status_var.set(h))
            self._process.wait()
            rc = self._process.returncode
            if rc == 0:
                self._log_q.put(('\n✓  Analysis completed successfully.\n', 'ok'))
                msg = f'Done — results in: {self.out_var.get()}'
            else:
                self._log_q.put((f'\n✗  Process exited with code {rc}\n', 'err'))
                msg = f'Failed (exit code {rc})'
        except Exception as exc:
            self._log_q.put((f'\n✗  {exc}\n', 'err'))
            msg = 'Error — see log'
        finally:
            self._running  = False
            self._process  = None
            self.after(0, lambda m=msg: self._on_done(m))

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _classify_line(line: str) -> str | None:
        lo = line.lower()
        stripped = line.strip()
        if any(k in lo for k in ('error', 'traceback', 'exception', '✗')):
            return 'err'
        if line.startswith('==') or 'SUMMARY' in line or stripped.startswith('✓'):
            return 'ok'
        # Analysis step markers like "[1 ] Swimming speed ..."
        import re
        if re.match(r'^\[(\d+\s*)\]', stripped):
            return 'sep'
        if stripped.startswith('[') or stripped.startswith('Files') or stripped.startswith('==='):
            return 'hdr'
        if stripped.startswith('  ') and any(
            k in lo for k in ('mean', 'median', 'drift', 'frac', 'α', 'tau',
                              'loaded', 'detected', 'linked', 'saved', 'csv', 'video')
        ):
            return 'dim'
        return None

    @staticmethod
    def _status_hint(line: str, step_label: str) -> str | None:
        """Extract a short status message from a subprocess output line."""
        import re
        stripped = line.strip()
        # Analysis steps: "[7 ] Boundary collisions ..."
        m = re.match(r'^\[(\d+\s*)\]\s+(.+?)(\s*\.\.\..*)?$', stripped)
        if m:
            return f'{step_label}  ›  [{m.group(1).strip()}] {m.group(2)}'
        # Trackpy frame progress: "Frame 45: 312 trajectories present."
        m = re.match(r'Frame (\d+):\s+(\d+) trajectories', stripped)
        if m:
            return f'{step_label}  ›  Frame {m.group(1)} — {m.group(2)} trajectories'
        # Loaded / detected / linked
        for kw in ('Loaded ', 'Detected ', 'Linked ', 'Saving plots', 'CSV saved', 'Raw video', 'Trajectory video'):
            if stripped.startswith(kw):
                return f'{step_label}  ›  {stripped[:80]}'
        return None

    def _on_done(self, msg: str):
        self.progress.stop()
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set(msg)
        self._on_mode_change()          # restore correct run-button label/command
        self._results_viewer.refresh()  # populate Results tab with new files

    def _stop(self):
        if self._process and self._running:
            self._process.terminate()
            self._running = False
            self._log_q.put(('\n⚠  Stopped by user.\n', 'err'))
            self.after(0, lambda: self._on_done('Stopped.'))


# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = MotilityGUI()
    app.mainloop()


if __name__ == '__main__':
    main()
