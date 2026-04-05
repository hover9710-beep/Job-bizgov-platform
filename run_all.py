# -*- coding: utf-8 -*-
"""
Run the full pipeline in order (project root = cwd for each subprocess).

1) JBEXPORT: connectors/connectors_jbexport/jbexport_proxy.py (Flask — background for pipeline duration)
2) BIZINFO: connectors/connector_bizinfo.py
3) filter_recommend
4) notify_dispatch --dry-run
5) notify_dispatch (real send)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

PROXY_SCRIPT = ROOT / "connectors" / "connectors_jbexport" / "jbexport_proxy.py"


def _utf8_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _section(title: str) -> None:
    print("\n" + "=" * 60, flush=True)
    print(f"  {title}", flush=True)
    print("=" * 60 + "\n", flush=True)


def _run(cmd: list[str]) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    _utf8_stdio()

    _section("1) JBEXPORT crawler (jbexport_proxy — background)")
    if not PROXY_SCRIPT.is_file():
        print(f"[run_all] Missing script: {PROXY_SCRIPT}", flush=True)
        return 1

    proxy_cmd = [PY, str(PROXY_SCRIPT)]
    print(
        "[run_all] Starting Flask proxy in background (required for local jbexport API).",
        flush=True,
    )
    print(f"$ {' '.join(proxy_cmd)}", flush=True)
    proc = subprocess.Popen(proxy_cmd, cwd=str(ROOT))
    time.sleep(0.2)
    if proc.poll() is not None:
        print(
            f"[run_all] JBEXPORT proxy exited immediately (code {proc.returncode}).",
            flush=True,
        )
        return proc.returncode if proc.returncode is not None else 1

    time.sleep(2)
    if proc.poll() is not None:
        print(
            f"[run_all] JBEXPORT proxy stopped (code {proc.returncode}).",
            flush=True,
        )
        return proc.returncode if proc.returncode is not None else 1

    try:
        steps: list[tuple[str, list[str]]] = [
            (
                "2) BIZINFO crawler",
                [PY, str(ROOT / "connectors" / "connector_bizinfo.py")],
            ),
            (
                "3) Filter recommend",
                [PY, str(ROOT / "pipeline" / "filter_recommend.py")],
            ),
            (
                "4) Notify dispatch (dry-run)",
                [PY, str(ROOT / "pipeline" / "notify_dispatch.py"), "--dry-run"],
            ),
        ]

        for title, cmd in steps:
            _section(title)
            rc = _run(cmd)
            if rc != 0:
                print(f"[run_all] FAILED: {title} (exit {rc})", flush=True)
                return rc

        _section("5) Notify dispatch (real send)")
        smtp_user = (os.environ.get("SMTP_USER") or "").strip()
        smtp_pass = (os.environ.get("SMTP_PASS") or "").strip()
        if not smtp_user or not smtp_pass:
            print(
                "[run_all] Skipped: SMTP_USER and SMTP_PASS must both be set for real send.",
                flush=True,
            )
            print(
                "  (notify_dispatch.py would exit 1 without them.)",
                flush=True,
            )
        else:
            rc = _run(
                [PY, str(ROOT / "pipeline" / "notify_dispatch.py")],
            )
            if rc != 0:
                print(
                    f"[run_all] FAILED: 5) Notify dispatch (real send) (exit {rc})",
                    flush=True,
                )
                return rc

        print("\nALL PIPELINE COMPLETED", flush=True)
        return 0
    finally:
        print("\n[run_all] Stopping JBEXPORT proxy...", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
