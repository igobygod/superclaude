#!/usr/bin/env python3
"""One quick look at the Mac screen for the voice assistant (used via mac-run).

  python3 ~/bin/mac-look.py          -> prints LOCKED, or the path of a downscaled JPEG screenshot
  python3 ~/bin/mac-look.py --clean  -> deletes the screenshots (always run after reading)
Screenshots live in ~/.mac-run/look/ for seconds only; leftovers older than 2 minutes are deleted on every run.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DIR = Path.home() / ".mac-run" / "look"


def clean(max_age: float = 0) -> None:
    for f in DIR.glob("*.jpg"):
        if time.time() - f.stat().st_mtime >= max_age:
            f.unlink(missing_ok=True)


def locked() -> bool:
    out = subprocess.run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True).stdout
    return '"CGSSessionScreenIsLocked"=Yes' in out.replace(" ", "")


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    if "--clean" in sys.argv:
        clean()
        print("cleaned")
        return 0
    clean(120)
    if locked():
        print("LOCKED: the screen is locked, so nothing was captured.")
        return 0
    f = Path(tempfile.mkstemp(prefix="look-", suffix=".jpg", dir=DIR)[1])
    r = subprocess.run(["screencapture", "-x", "-t", "jpg", str(f)], capture_output=True, text=True)
    if r.returncode or f.stat().st_size == 0:
        f.unlink(missing_ok=True)
        print(f"FAILED: screencapture error {r.returncode}: {r.stderr.strip()[:200]} (Screen Recording permission?)")
        return 1
    subprocess.run(["sips", "-Z", "1280", str(f)], capture_output=True)
    print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
