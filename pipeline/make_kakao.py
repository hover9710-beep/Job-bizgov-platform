# -*- coding: utf-8 -*-
"""
카카오 알림용 짧은 본문 → data/kakao/kakao_body.txt

mail_view 기반:
  - DB(biz_projects) → period_text/infer_status() 로 상태 단일화
  - 섹션: 신규 / 마감임박 / 접수중 카운트 + 상위 3건 제목
  - 카카오 Memo API 본문 길이 제한(≈200자) 고려해 짧게 포맷
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.data_paths import KAKAO_BODY_TXT, ensure_pipeline_dirs
from pipeline.mail_view import (
    _today_str,
    filter_active,
    filter_ending_soon,
    filter_new,
    load_db_rows,
    to_mail_item,
)

TOP_TITLES = 3
TITLE_MAX = 22
MAX_BODY_CHARS = 900


def _top_titles(items: List[Dict[str, Any]], n: int = TOP_TITLES) -> List[str]:
    out: List[str] = []
    for it in items[:n]:
        ttl = (it.get("title") or "").strip() or "(제목없음)"
        if len(ttl) > TITLE_MAX:
            ttl = ttl[:TITLE_MAX] + "…"
        out.append(ttl)
    return out


def build_kakao_body(
    rows: Optional[List[Dict[str, Any]]] = None,
    today: Optional[str] = None,
) -> str:
    """카카오 알림용 요약 본문."""
    t = today or _today_str()
    if rows is None:
        rows = load_db_rows()

    items = [to_mail_item(r, today=t) for r in rows]
    new_items = filter_new(items, days=7, today=t)
    ending_items = filter_ending_soon(items, days=7, today=t)
    active_items = filter_active(items, today=t)

    active_items.sort(
        key=lambda x: (x.get("end_date") or "9999-12-31")
    )
    ending_items.sort(key=lambda x: (x.get("end_date") or "9999-12-31"))
    new_items.sort(key=lambda x: (x.get("start_date") or ""), reverse=True)

    lines: List[str] = []
    lines.append("[전북지원사업 알림]")
    lines.append(f"🔥 신규 {len(new_items)}건")
    lines.append(f"⚠ 마감임박 {len(ending_items)}건")
    lines.append(f"📌 접수중 {len(active_items)}건")

    preview_source = ending_items or new_items or active_items
    titles = _top_titles(preview_source, n=TOP_TITLES)
    if titles:
        lines.append("")
        lines.append("상위:")
        for i, ttl in enumerate(titles, 1):
            lines.append(f"{i}. {ttl}")

    lines.append("")
    lines.append("상세는 메일 확인.")

    print(
        f"[make_kakao] today={t} rows={len(rows)} "
        f"new={len(new_items)} ending={len(ending_items)} active={len(active_items)}",
        flush=True,
    )

    body = "\n".join(lines)
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 1].rstrip() + "…"
    return body


def main() -> int:
    ensure_pipeline_dirs()
    body = build_kakao_body()
    KAKAO_BODY_TXT.parent.mkdir(parents=True, exist_ok=True)
    KAKAO_BODY_TXT.write_text(body, encoding="utf-8")
    print(f"[make_kakao] 저장: {KAKAO_BODY_TXT} ({len(body)}자)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
