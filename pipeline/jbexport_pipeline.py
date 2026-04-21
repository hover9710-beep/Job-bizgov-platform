# -*- coding: utf-8 -*-
"""
JBEXPORT 공고 처리 통합 파이프라인.

- dedupe: 완전 동일 공고만 대표 1건으로 축약 (follow-up 제목은 절대 dedupe 대상 아님)
- related_group: 같은 사업 계열 묶음 (유사도·키워드·기간 겹침/연속)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

from pipeline import make_mail as m

_RE_BRACKET = re.compile(r"^\[[^\]]{1,40}\]\s*")

REGION_NAMES: tuple[str, ...] = (
    "전북",
    "전라북도",
    "전북도",
    "전주시",
    "김제시",
    "군산시",
    "익산시",
)
_REGION_SORTED = sorted(REGION_NAMES, key=len, reverse=True)

BIZ_KEYWORDS: tuple[str, ...] = (
    "국제특송",
    "해외물류비",
    "통상닥터",
    "통상마스터",
    "해외바이어",
    "해외통상거점",
    "수출통합지원센터",
    "수출애로",
    "외국어 번역",
    "외국어 통역",
    "해외규격인증",
    "해외파트너",
    "수출보험",
    "무역사절단",
    "전시회",
    "수출바우처",
    "규제지원",
    "샘플발송",
    "FTA통상",
    "처음수출",
)


def strip_leading_regions(title: str) -> str:
    t = str(title or "").strip()
    while True:
        mm = _RE_BRACKET.match(t)
        if not mm:
            break
        t = t[mm.end() :].strip()
    return t


def normalize_core(title: str) -> str:
    """선행 [지역] 제거 후 본문 — 완전 중복 판별에 사용 (지역명은 유지)."""
    t = strip_leading_regions(title)
    return re.sub(r"\s+", " ", t).strip()


def normalize_title(title: str) -> str:
    """지역 토큰 제거 후 문자열 — 유사도·비교용."""
    t = normalize_core(title)
    for name in _REGION_SORTED:
        if name in t:
            t = t.replace(name, " ")
    return re.sub(r"\s+", " ", t).strip()


def normalize_for_similarity(title: str) -> str:
    """(추가)/차수/연장 등 제거 후 유사도."""
    t = normalize_core(title)
    t = re.sub(r"\s*\(추가\)\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[234]차\s*", "", t)
    t = re.sub(r"\s*연장\s*", "", t)
    t = re.sub(r"\s*재공고\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def is_followup_title(title: str) -> bool:
    keywords = [
        "추가",
        "추가모집",
        "재공고",
        "연장",
        "2차",
        "3차",
        "4차",
        "수정",
        "변경",
        "정정",
    ]
    t = str(title or "")
    return any(k in t for k in keywords)


def org_key(item: dict) -> str:
    return str(
        item.get("organization")
        or item.get("org_name")
        or item.get("org")
        or ""
    ).strip()


def period_key(item: dict) -> str:
    return f"{m._effective_start_date_str(item)}|{m._effective_end_date_str(item)}"


def _parse_iso(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def period_span_days(item: dict) -> int:
    a = _parse_iso(m._effective_start_date_str(item))
    b = _parse_iso(m._effective_end_date_str(item))
    if not a or not b:
        return 0
    return max(0, (b - a).days)


def periods_equivalent_or_similar(a: dict, b: dict) -> bool:
    """기간 동일 또는 시작·종료 각각 1일 이내."""
    if period_key(a) == period_key(b):
        return True
    s1, e1 = _parse_iso(m._effective_start_date_str(a)), _parse_iso(
        m._effective_end_date_str(a)
    )
    s2, e2 = _parse_iso(m._effective_start_date_str(b)), _parse_iso(
        m._effective_end_date_str(b)
    )
    if not all((s1, e1, s2, e2)):
        return False
    return (
        abs((s1 - s2).days) <= 1
        and abs((e1 - e2).days) <= 1
    )


def periods_overlap(a: dict, b: dict) -> bool:
    s1, e1 = _parse_iso(m._effective_start_date_str(a)), _parse_iso(
        m._effective_end_date_str(a)
    )
    s2, e2 = _parse_iso(m._effective_start_date_str(b)), _parse_iso(
        m._effective_end_date_str(b)
    )
    if not all((s1, e1, s2, e2)):
        return False
    return s1 <= e2 and s2 <= e1


def periods_consecutive(a: dict, b: dict) -> bool:
    """한쪽 종료일 다음날 이전에 다른 쪽 시작(또는 맞닿음)."""
    pairs = [
        (
            _parse_iso(m._effective_end_date_str(a)),
            _parse_iso(m._effective_start_date_str(b)),
        ),
        (
            _parse_iso(m._effective_end_date_str(b)),
            _parse_iso(m._effective_start_date_str(a)),
        ),
    ]
    for e, s in pairs:
        if e and s:
            gap = (s - e).days
            if 0 <= gap <= 1:
                return True
    return False


def periods_related_time(a: dict, b: dict) -> bool:
    return periods_overlap(a, b) or periods_consecutive(a, b)


def primary_biz_keyword(title: str) -> str:
    t = normalize_for_similarity(title)
    for kw in sorted(BIZ_KEYWORDS, key=len, reverse=True):
        if kw in t:
            return kw
    return ""


def title_similarity(a: str, b: str) -> float:
    x = normalize_for_similarity(a)
    y = normalize_for_similarity(b)
    if not x or not y:
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def pick_representative(items: list[dict]) -> dict:
    """기간 긴 것 우선, 같으면 시작일 최신."""

    def key(it: dict) -> tuple:
        return (period_span_days(it), m._effective_start_date_str(it) or "")

    return max(items, key=key)


def are_strict_duplicate_pair(a: dict, b: dict) -> bool:
    """
    완전 중복 후보만 True. follow-up 제목이 하나라도 있으면 절대 True 아님.
    제목은 normalize_core 동일(완전 동일 문구) + 기관 + 기간 유사.
    (전주시/전북도처럼 본문이 다르면 normalize_core가 달라 dedupe 안 됨.)
    """
    ta = str(a.get("title") or "")
    tb = str(b.get("title") or "")
    if is_followup_title(ta) or is_followup_title(tb):
        return False
    if org_key(a) != org_key(b) or not org_key(a):
        return False
    if normalize_core(ta) != normalize_core(tb):
        return False
    if not periods_equivalent_or_similar(a, b):
        return False
    return True


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def cluster_strict_dedupe(rows: list[dict]) -> list[list[dict]]:
    """완전 중복만 동일 클러스터."""
    items = [x for x in rows if isinstance(x, dict)]
    n = len(items)
    if n == 0:
        return []
    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if are_strict_duplicate_pair(items[i], items[j]):
                uf.union(i, j)
    roots: dict[int, list[int]] = {}
    for i in range(n):
        r = uf.find(i)
        roots.setdefault(r, []).append(i)
    return [[items[i] for i in idxs] for idxs in roots.values()]


def dedupe_representatives(rows: list[dict]) -> list[dict]:
    """클러스터별 대표 1건씩 반환."""
    groups = cluster_strict_dedupe(rows)
    return [pick_representative(g) for g in groups]


def are_related_pair(
    a: dict,
    b: dict,
    *,
    sim_threshold: float = 0.8,
) -> bool:
    if org_key(a) != org_key(b) or not org_key(a):
        return False
    ka = primary_biz_keyword(a.get("title") or "")
    kb = primary_biz_keyword(b.get("title") or "")
    if not ka or ka != kb:
        return False
    ta = str(a.get("title") or "")
    tb = str(b.get("title") or "")
    if title_similarity(ta, tb) < sim_threshold:
        return False
    if not periods_related_time(a, b):
        return False
    return True


@dataclass
class RelatedGroup:
    group_id: str
    representative: dict
    related_items: list[dict] = field(default_factory=list)


def build_related_groups(
    items_after_dedupe: list[dict],
    *,
    sim_threshold: float = 0.8,
    id_prefix: str = "rel",
) -> list[RelatedGroup]:
    items = [x for x in items_after_dedupe if isinstance(x, dict)]
    n = len(items)
    if n < 2:
        return []

    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if are_related_pair(items[i], items[j], sim_threshold=sim_threshold):
                uf.union(i, j)

    roots: dict[int, list[int]] = {}
    for i in range(n):
        r = uf.find(i)
        roots.setdefault(r, []).append(i)

    out: list[RelatedGroup] = []
    gid = 0
    for _root, idxs in sorted(roots.items(), key=lambda x: x[0]):
        if len(idxs) < 2:
            continue
        grp = [items[i] for i in idxs]
        rep = pick_representative(grp)
        rel = [x for x in grp if id(x) != id(rep)]
        gid += 1
        out.append(
            RelatedGroup(
                group_id=f"{id_prefix}-{gid:03d}",
                representative=rep,
                related_items=rel,
            )
        )
    return out


def item_summary(x: dict) -> dict[str, Any]:
    return {
        "title": x.get("title"),
        "organization": org_key(x),
        "period": period_key(x),
        "url": x.get("url") or x.get("detail_url"),
        "status": x.get("status"),
        "is_followup": is_followup_title(str(x.get("title") or "")),
    }


def related_groups_to_jsonable(groups: list[RelatedGroup]) -> list[dict[str, Any]]:
    return [
        {
            "group_id": g.group_id,
            "representative": item_summary(g.representative),
            "related_items": [item_summary(x) for x in g.related_items],
        }
        for g in groups
    ]


def process_jbexport_rows(
    rows: list[dict],
    *,
    related_sim_threshold: float = 0.8,
) -> dict[str, Any]:
    """
    최종 JSON 구조 + 디버그용 카운트.

    Returns:
      items: dedupe 대표 목록
      related_groups: 연관 묶음
      _debug: 총 건수, dedupe 제거 수, follow-up 수, related 그룹 수
    """
    raw = [x for x in rows if isinstance(x, dict)]
    n_total = len(raw)
    n_followup = sum(
        1 for x in raw if is_followup_title(str(x.get("title") or ""))
    )

    clusters = cluster_strict_dedupe(raw)
    items = [pick_representative(c) for c in clusters]
    n_after = len(items)
    n_deduped_removed = n_total - n_after

    rel = build_related_groups(items, sim_threshold=related_sim_threshold)
    rel_json = related_groups_to_jsonable(rel)

    return {
        "items": [item_summary(x) for x in items],
        "related_groups": rel_json,
        "_debug": {
            "total": n_total,
            "dedupe_removed": n_deduped_removed,
            "followup_in_source": n_followup,
            "items_after_dedupe": n_after,
            "related_group_count": len(rel_json),
        },
    }


def process_jbexport_json(rows: list[dict], **kwargs: Any) -> str:
    return json.dumps(process_jbexport_rows(rows, **kwargs), ensure_ascii=False, indent=2)
