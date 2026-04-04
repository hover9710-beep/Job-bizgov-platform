# -*- coding: utf-8 -*-
"""
Lock or unlock the project root .env file (read-only on Windows).

Usage:
  py scripts/env_lock.py          # lock (default)
  py scripts/env_lock.py unlock   # unlock
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def lock(path: Path) -> int:
    if not path.is_file():
        print(f"[env_lock] No file at: {path}")
        print("[env_lock] Nothing to lock.")
        return 1
    mode = path.stat().st_mode
    # Windows: clear user write bit → read-only
    os.chmod(path, mode & ~stat.S_IWRITE)
    print(f"[env_lock] Locked (read-only): {path}")
    return 0


def unlock(path: Path) -> int:
    if not path.is_file():
        print(f"[env_lock] No file at: {path}")
        print("[env_lock] Nothing to unlock.")
        return 1
    mode = path.stat().st_mode
    os.chmod(path, mode | stat.S_IWRITE)
    print(f"[env_lock] Unlocked (writable): {path}")
    return 0


def main() -> int:
    argv = [a.lower() for a in sys.argv[1:]]
    if "unlock" in argv:
        return unlock(ENV_PATH)
    return lock(ENV_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
