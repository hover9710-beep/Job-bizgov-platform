#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""JBEXPORT 일일 수집 파이프라인.

요약:
1) 전체 공고 수집
2) 접수중/공고중 필터링
3) 오늘 JSON 저장
4) 어제 JSON 로드
5) URL(상세URL) 기준 신규 공고 비교/출력
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JBEXPORT_DIR = DATA_DIR / "jbexport"
JSON_DIR = JBEXPORT_DIR / "json"
FILES_DIR = JBEXPORT_DIR / "files"

JSON_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

import requests

# ===== 설정 =====
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JBEXPORT_DIR = DATA_DIR / "jbexport"
JSON_DIR = JBEXPORT_DIR / "json"
FILES_DIR = JBEXPORT_DIR / "files"

JSON_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

PROXY_BASE = "http://127.0.0.1:5000"
LIST_ENDPOINT = f"{PROXY_BASE}/api/jbexport/list"
LIST_LENGTH = 10
MAX_PAGES = 500
OPEN_STATUSES = {"접수중", "공고중"}


def log(message: str) -> None:
    """콘솔 로그."""
    print(message, flush=True)


def _rows_from_json(payload: Dict[str, Any]) -> List[Any]:
    """응답 JSON에서 목록 배열 후보를 유연하게 탐색."""
    rows = (
        payload.get("data")
        or payload.get("aaData")
        or payload.get("rows")
        or (payload.get("result") or {}).get("data")
        or (payload.get("result") or {}).get("rows")
        or payload.get("resultList")
        or payload.get("list")
        or []
    )
    return rows if isinstance(rows, list) else []


def _extract_announcement(row: Any) -> Dict[str, str] | None:
    """목록 row를 요구 데이터 구조로 변환."""
    if not isinstance(row, dict):
        return None

    sp_seq = str(row.get("SP_SEQ") or row.get("spSeq") or row.get("sp_seq") or "").strip()
    if not sp_seq:
        return None

    title = str(row.get("js_title") or row.get("title") or row.get("TITLE") or "").strip()
    status = str(row.get("STS_TXT") or row.get("status") or "").strip()
    period = str(row.get("period") or row.get("PERIOD") or "").strip()

    detail_url = (
        "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/"
        f"detail1.do?menuUUID=402880867c8174de017c819251e70009&spSeq={sp_seq}"
    )
    return {
        "공고제목": title or f"spSeq={sp_seq}",
        "기관": "전북수출통합지원시스템",
        "기간": period,
        "상태": status,
        "상세URL": detail_url,
    }


def fetch_all_announcements() -> List[Dict[str, str]]:
    """JBEXPORT 전체 공고 수집 (start += length)."""
    log("[수집 시작] JBEXPORT 전체 공고 수집")
    all_items: List[Dict[str, str]] = []
    seen_urls = set()
    start = 0
    draw = 1

    for page in range(1, MAX_PAGES + 1):
        req_payload = {"start": start, "length": LIST_LENGTH, "draw": draw}
        log(f"[LIST] page={page} start={start} length={LIST_LENGTH}")

        try:
            res = requests.post(LIST_ENDPOINT, json=req_payload, timeout=120)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            log(f"[오류] LIST 요청 실패: {e}")
            break

        if not isinstance(data, dict):
            log("[오류] LIST 응답 형식이 JSON object가 아님")
            break

        rows = _rows_from_json(data)
        log(f"[LIST] rows={len(rows)}")
        if not rows:
            break

        for row in rows:
            item = _extract_announcement(row)
            if not item:
                continue
            # URL 없으면 제외하지 말고 빈 문자열 그대로 사용
            url_key = str(item.get("상세URL", "") or "")
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            all_items.append(item)

        if len(rows) < LIST_LENGTH:
            break

        start += LIST_LENGTH
        draw += 1

    log(f"[수집 완료] 전체 공고 {len(all_items)}건")
    return all_items


def filter_open_announcements(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """상태가 접수중/공고중인 공고만 필터링."""
    filtered: List[Dict[str, str]] = []
    for item in results:
        status = str(item.get("상태") or "").strip()
        if status in OPEN_STATUSES:
            filtered.append(item)
    log(f"[필터] 진행중 공고 {len(filtered)}건")
    return filtered


def json_path_for(target_date: date) -> Path:
    return JSON_DIR / f"jbexport_{target_date.isoformat()}.json"


def new_json_path() -> Path:
    return JBEXPORT_DIR / "jbexport_new.json"

def save_today_json(open_announcements):
    path = json_path_for(date.today())
    path.write_text(
        json.dumps(open_announcements, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log(f"[저장] {path.name} ({len(open_announcements)}건)")
    return path

def load_yesterday_json() -> List[Dict[str, Any]]:
    """어제 파일 로드 (없으면 빈 리스트)."""
    y_path = json_path_for(date.today() - timedelta(days=1))
    if not y_path.exists():
        log(f"[로드] 어제 파일 없음: {y_path.name}")
        return []
    try:
        items = json.loads(y_path.read_text(encoding="utf-8"))
        if isinstance(items, list):
            log(f"[로드] 어제 파일 로드: {y_path.name} ({len(items)}건)")
            return items
    except Exception as e:
        log(f"[오류] 어제 파일 로드 실패: {e}")
    return []


def find_new_announcements(
    today_items: List[Dict[str, str]], yesterday_items: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """상세URL 기준으로 신규 공고 추출."""
    yesterday_urls = {str(item.get("상세URL", "") or "").strip() for item in yesterday_items}
    today_urls = {str(item.get("상세URL", "") or "").strip() for item in today_items}
    new_urls = today_urls - yesterday_urls
    new_items = [
        item
        for item in today_items
        if str(item.get("상세URL", "") or "").strip() in new_urls
    ]
    log(f"[비교] 신규 공고 {len(new_items)}건")
    return new_items


def print_new_announcements(new_items: List[Dict[str, str]]) -> None:
    """신규 공고 출력."""
    if not new_items:
        print("No new announcements")
        return

    print("===== NEW ANNOUNCEMENTS =====")
    for i, item in enumerate(new_items, 1):
        print(f"{i}. {item.get('공고제목', '')}")
        print(f"   기관: {item.get('기관', '')}")
        print(f"   기간: {item.get('기간', '')}")
        print(f"   상태: {item.get('상태', '')}")
        print(f"   URL: {item.get('상세URL', '')}")
    print("=============================")


def pipeline() -> List[Dict[str, str]]:
    """전체 파이프라인 실행 후 신규 공고 리스트 반환."""
    try:
        all_items = fetch_all_announcements()
        open_items = filter_open_announcements(all_items)
        save_today_json(open_items)
        yesterday_items = load_yesterday_json()
        new_items = find_new_announcements(open_items, yesterday_items)
        new_json_path().write_text(
            json.dumps(new_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print_new_announcements(new_items)
        return new_items
    except Exception as e:
        log(f"[치명 오류] pipeline 실패: {e}")
        return []


def main() -> None:
    pipeline()


if __name__ == "__main__":
    main()

# 실행 방법:
# 1) python jbexport_proxy.py
# 2) python jbexport_daily_pipeline.py
