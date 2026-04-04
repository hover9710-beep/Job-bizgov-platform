"""
data/today.json · data/yesterday.json 스냅샷.

- 기존 today.json 이 있으면 내용을 yesterday.json 으로 복사(덮어쓰기)
- 새 수집/병합 결과를 today.json 에 저장

pipeline/compare.py 의 compare_new() 와 함께 쓰기 위한 구조.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"


def promote_today_to_yesterday(data_dir: Path | None = None) -> None:
    """today.json 이 있으면 동일 내용을 yesterday.json 으로 옮긴다."""
    d = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    today = d / "today.json"
    yesterday = d / "yesterday.json"
    if today.exists():
        yesterday.write_text(today.read_text(encoding="utf-8"), encoding="utf-8")


def save_today_snapshot(items: List[Any], data_dir: Path | None = None) -> Path:
    """
    1) 기존 today → yesterday 복사
    2) items 를 today.json 에 저장 (list JSON)
    """
    d = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    promote_today_to_yesterday(d)
    today = d / "today.json"
    today.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return today
