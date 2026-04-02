import subprocess
import sys
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = BASE_DIR / "pipeline"


def _run(cmd: List[str], cwd: Path) -> None:
    print(f"[run_pipeline] run: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> None:
    try:
        _run([sys.executable, str(PIPELINE_DIR / "merge_jb.py")], cwd=BASE_DIR)
        _run([sys.executable, str(PIPELINE_DIR / "update_db.py")], cwd=BASE_DIR)
    except subprocess.CalledProcessError as exc:
        print(f"[run_pipeline] 실패: {exc}")
        raise SystemExit(1)

    print("[run_pipeline] merge + update 완료")


if __name__ == "__main__":
    main()
