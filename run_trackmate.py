"""
Run the TrackMate ImageJ macro via Fiji.

Usage:
    python run_trackmate.py
    python run_trackmate.py --fiji /path/to/Fiji.app/ImageJ-linux64
    python run_trackmate.py --macro /path/to/trackmate.ijm
"""

import subprocess
import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def find_fiji():
    """Return the first Fiji executable found in common locations."""
    candidates = [
        # Linux
        Path("/opt/fiji/Fiji.app/ImageJ-linux64"),
        Path.home() / "Fiji.app/ImageJ-linux64",
        # macOS
        Path("/Applications/Fiji.app/Contents/MacOS/ImageJ-macosx"),
        Path.home() / "Applications/Fiji.app/Contents/MacOS/ImageJ-macosx",
        # Windows
        Path("C:/Fiji.app/ImageJ-win64.exe"),
        Path("C:/Program Files/Fiji.app/ImageJ-win64.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def main():
    ap = argparse.ArgumentParser(description="Run TrackMate via Fiji")
    ap.add_argument("--fiji",  default=None,
                    help="Path to Fiji/ImageJ executable")
    ap.add_argument("--macro", default=str(SCRIPT_DIR / "trackmate.ijm"),
                    help="Path to the .ijm macro file")
    args = ap.parse_args()

    fiji = args.fiji or find_fiji()
    if fiji is None:
        print("ERROR: Fiji executable not found. Install Fiji or pass --fiji /path/to/fiji")
        sys.exit(1)

    macro = args.macro
    if not Path(macro).exists():
        print(f"ERROR: Macro not found: {macro}")
        sys.exit(1)

    print(f"Fiji : {fiji}")
    print(f"Macro: {macro}")
    print("Running TrackMate...")

    subprocess.run([fiji, "-macro", macro], check=True)
    print("Finished")


if __name__ == "__main__":
    main()
