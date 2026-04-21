"""
통합 파이프라인 (프로젝트 루트 기준)

0a) connectors/connector_bizinfo.py  — 기업마당 전체 수집 → data/bizinfo/json/bizinfo_all.json
0b) connectors/connector_kstartup.py — K-Startup 전체 수집 → data/kstartup/kstartup_all.json
1)  pipeline/merge_jb.py  — data/*.json 병합 → data/all_jb/all_jb.json, today/yesterday
2)  pipeline/update_db.py — all_jb.json → db/biz.db (biz_projects upsert 후 projects 미러링)

실행(루트에서):
  py pipeline/run_pipeline.py
  py pipeline/run_pipeline.py --skip-bizinfo    # 기업마당 수집 생략
  py pipeline/run_pipeline.py --skip-kstartup   # K-Startup 수집 생략
  py pipeline/run_pipeline.py --skip-collect    # merge_jb 생략
  py pipeline/run_pipeline.py --post-process    # filter_recommend + mailer (dry-run)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 커서앱통합_v1 루트 = pipeline/ 의 부모
ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / "pipeline"
LOGS_DIR = ROOT_DIR / "logs"


def _run_script(script_name: str) -> None:
    script_path = PIPELINE_DIR / script_name
    cmd = [sys.executable, str(script_path)]
    print(f"[run_pipeline] {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)


def run_bizinfo() -> None:
    """기업마당 전체 수집 → data/bizinfo/json/bizinfo_all.json"""
    script_path = ROOT_DIR / "connectors" / "connector_bizinfo.py"
    cmd = [sys.executable, str(script_path)]
    print(f"[run_pipeline] {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)


def run_kstartup() -> None:
    """K-Startup 전체 수집 → data/kstartup/kstartup_all.json.

    실패해도 전체 파이프라인은 중단하지 않는다 (K-Startup 네트워크 이슈가
    bizinfo 처리까지 막지 않도록). 실패 시 경고만 남김.
    """
    script_path = ROOT_DIR / "connectors" / "connector_kstartup.py"
    cmd = [sys.executable, str(script_path)]
    print(f"[run_pipeline] {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if result.returncode != 0:
        print(
            f"[run_pipeline] connector_kstartup.py exit {result.returncode} — "
            "기존 kstartup_all.json 이 있으면 계속 사용합니다.",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="bizinfo + kstartup 수집 + merge_jb + update_db")
    parser.add_argument(
        "--skip-bizinfo",
        action="store_true",
        help="connectors/connector_bizinfo.py 생략",
    )
    parser.add_argument(
        "--skip-kstartup",
        action="store_true",
        help="connectors/connector_kstartup.py 생략",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="merge_jb 생략 (이미 all_jb.json 이 준비된 경우)",
    )
    parser.add_argument(
        "--post-process",
        action="store_true",
        help="update_db 이후 filter_recommend.py + mailer.py (--dry-run) 실행",
    )
    args = parser.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_bizinfo:
            run_bizinfo()
        else:
            print("[run_pipeline] --skip-bizinfo: connector_bizinfo.py 건너뜀", flush=True)
        if not args.skip_kstartup:
            run_kstartup()
        else:
            print("[run_pipeline] --skip-kstartup: connector_kstartup.py 건너뜀", flush=True)
        if not args.skip_collect:
            _run_script("merge_jb.py")
        else:
            print("[run_pipeline] --skip-collect: merge_jb.py 건너뜀", flush=True)
        _run_script("update_db.py")
        if args.post_process:
            _run_script("filter_recommend.py")
            cmd = [
                sys.executable,
                str(ROOT_DIR / "mailer.py"),
                "--dry-run",
            ]
            print(f"[run_pipeline] {' '.join(cmd)}", flush=True)
            subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[run_pipeline] 실패: {exc}", flush=True)
        raise SystemExit(1) from exc

    print("[run_pipeline] update_db 완료 (merge_jb는 옵션)", flush=True)


if __name__ == "__main__":
    main()
