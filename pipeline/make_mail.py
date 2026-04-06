# -*- coding: utf-8 -*-
"""
pipeline/make_mail.py
전북지원사업 메일자동알림서비스 메일 본문 생성
"""

import json
from pathlib import Path
from datetime import datetime

TODAY = datetime.now().strftime("%Y-%m-%d")

NEW_FILE      = Path("data/processed/new.json")
DEADLINE_FILE = Path("data/processed/deadline.json")
ALL_FILE      = Path("data/raw") / f"{TODAY}_all.json"
OUT_FILE      = Path("data/mail/mail_body.txt")


def load_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_items(data):
    if isinstance(data, dict):
        return data.get("items", [])
    if isinstance(data, list):
        return data
    return []


def fmt_new_item(x: dict) -> str:
    return (
        f"- 사업명: {x.get('title', '')}\n"
        f"  기관: {x.get('org_name', x.get('agency', ''))}\n"
        f"  접수기간: {x.get('start_date', '')} ~ {x.get('end_date', '')}\n"
        f"  링크: {x.get('url', x.get('detail_url', ''))}\n"
    )


def fmt_deadline_item(x: dict) -> str:
    return (
        f"- 사업명: {x.get('title', '')}\n"
        f"  기관: {x.get('org_name', x.get('agency', ''))}\n"
        f"  마감일: {x.get('end_date', '')} (D-{x.get('d_day', '')})\n"
        f"  링크: {x.get('url', x.get('detail_url', ''))}\n"
    )


def fmt_all_preview_item(x: dict) -> str:
    return (
        f"- {x.get('title', '')} / "
        f"{x.get('org_name', x.get('agency', ''))} / "
        f"{x.get('end_date', '')}"
    )


def build_ai_summary() -> str:
    return "\n".join([
        "- 최근 전북 지역 수출·판로·전시회 관련 지원사업 공고가 꾸준히 올라오고 있습니다.",
        "- 마감 임박 공고는 조기 마감될 수 있으므로 빠른 확인이 필요합니다.",
        "- 자세한 신청 조건과 제출 서류는 반드시 각 기관의 공고문 원문을 확인해 주세요.",
    ])


def main():
    new_data      = load_json(NEW_FILE)
    deadline_data = load_json(DEADLINE_FILE)
    all_data      = load_json(ALL_FILE)

    new_items      = get_items(new_data)
    deadline_items = get_items(deadline_data)
    all_items      = get_items(all_data)

    total_count    = len(all_items)
    new_count      = len(new_items)
    deadline_count = len(deadline_items)

    new_section      = "\n".join(fmt_new_item(x) for x in new_items[:20])      if new_items      else "신규 공고가 없습니다."
    deadline_section = "\n".join(fmt_deadline_item(x) for x in deadline_items[:20]) if deadline_items else "마감 임박 공고가 없습니다."
    all_preview      = "\n".join(fmt_all_preview_item(x) for x in all_items[:30])   if all_items      else "전체 공고 데이터가 없습니다."
    ai_summary       = build_ai_summary()

    body = f"""전북지원사업 메일자동알림서비스입니다.

매일 전북 지역 지원사업 공고를 수집하여
신규 공고와 마감 임박 공고를 안내드립니다.

────────────────────────────
1. 오늘 신규 공고
────────────────────────────

{new_section}

────────────────────────────
2. 마감 임박 공고 (D-7 이내)
────────────────────────────

{deadline_section}

────────────────────────────
3. 전체 공고 현황
────────────────────────────

- 오늘 기준 전체 공고 수: {total_count}건
- 신규 공고: {new_count}건
- 마감 임박 공고: {deadline_count}건

{all_preview}

────────────────────────────
4. AI 요약
────────────────────────────

{ai_summary}

※ 본 메일은 전북 지원사업 공고를 자동 수집하여 발송되는 알림 메일입니다.
※ AI는 거짓말을 할 수 있으니, 자세한 신청 조건과 제출 서류는 반드시 각 기관의 공고문 원문을 확인해 주세요.
"""

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(body, encoding="utf-8")

    print(f"[make_mail] 메일 본문 생성 완료 → {OUT_FILE}")
    print(f"[make_mail] 전체 {total_count}건 / 신규 {new_count}건 / 마감임박 {deadline_count}건")


if __name__ == "__main__":
    main()
