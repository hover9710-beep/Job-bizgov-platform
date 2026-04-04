"""
통합 파이프라인 (프로젝트 루트 기준)

0) connectors/connector_bizinfo.py — 기업마당 전체 수집 → data/bizinfo/json/bizinfo_all.json
1) pipeline/merge_jb.py  — data/*.json 병합 → data/all_jb/all_jb.json, today/yesterday
2) pipeline/update_db.py — all_jb.json → db/biz.db (biz_projects upsert 후 projects 미러링)

실행(루트에서):
  py pipeline/run_pipeline.py
  py pipeline/run_pipeline.py --skip-bizinfo   # 기업마당 수집 생략
  py pipeline/run_pipeline.py --skip-collect   # merge_jb 생략
  py pipeline/run_pipeline.py --post-process   # filter_recommend + notify_dispatch
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


def main() -> None:
    parser = argparse.ArgumentParser(description="bizinfo 수집 + merge_jb + update_db")
    parser.add_argument(
        "--skip-bizinfo",
        action="store_true",
        help="connectors/connector_bizinfo.py 생략",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="merge_jb 생략 (이미 all_jb.json 이 준비된 경우)",
    )
    parser.add_argument(
        "--post-process",
        action="store_true",
        help="update_db 이후 filter_recommend.py + notify_dispatch.py 실행",
    )
    args = parser.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_bizinfo:
            run_bizinfo()
        else:
            print("[run_pipeline] --skip-bizinfo: connector_bizinfo.py 건너뜀", flush=True)
        if not args.skip_collect:
            _run_script("merge_jb.py")
        else:
            print("[run_pipeline] --skip-collect: merge_jb.py 건너뜀", flush=True)
        _run_script("update_db.py")
        if args.post_process:
            _run_script("filter_recommend.py")
            cmd = [
                sys.executable,
                str(PIPELINE_DIR / "notify_dispatch.py"),
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
