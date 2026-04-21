# -*- coding: utf-8 -*-
"""
알림 파이프라인 일괄 실행 (프로젝트 루트에서).

순서:
  1. merge_sources   (data/raw/*.json → merged/all_sites.json + history)
  2. diff_new          (merged/new.json)
  3. make_mail         (data/mail/mail_body.txt)
  4. make_kakao        (data/kakao/kakao_body.txt)
  5. mailer            (옵션)
  6. kakao_notify      (옵션)

connector는 이 스크립트 밖에서 실행해 data/raw/*.json 을 갱신한다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _run(cmd: list[str]) -> int:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="알림 파이프라인 (merge → diff → mail → kakao → 발송)")
    ap.add_argument("--skip-merge", action="store_true", help="merge_sources 생략")
    ap.add_argument("--skip-diff", action="store_true", help="diff_new 생략")
    ap.add_argument("--skip-mail", action="store_true", help="make_mail 생략")
    ap.add_argument("--skip-kakao", action="store_true", help="make_kakao 생략")
    ap.add_argument("--skip-notify", action="store_true", help="mailer / kakao 발송 생략")
    ap.add_argument("--dry-run", action="store_true", help="mailer만 --dry-run")
    args = ap.parse_args()

    if not args.skip_merge:
        if _run([PY, str(ROOT / "pipeline" / "merge_sources.py")]) != 0:
            return 1
    if not args.skip_diff:
        if _run([PY, str(ROOT / "pipeline" / "diff_new.py")]) != 0:
            return 1
    if not args.skip_mail:
        if _run([PY, str(ROOT / "pipeline" / "make_mail.py")]) != 0:
            return 1
    if not args.skip_kakao:
        if _run([PY, str(ROOT / "pipeline" / "make_kakao.py")]) != 0:
            return 1

    if args.skip_notify:
        print("[run_alerts] 알림 발송 생략", flush=True)
        return 0

    mailer_cmd = [PY, str(ROOT / "mailer.py")]
    if args.dry_run:
        mailer_cmd.append("--dry-run")
    if _run(mailer_cmd) != 0:
        return 1

    if args.dry_run:
        print("[run_alerts] dry-run 이므로 카카오 생략", flush=True)
        return 0

    _run([PY, str(ROOT / "kakao_notify.py")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
