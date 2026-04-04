# -*- coding: utf-8 -*-
"""
표준 공고(Notice) 스키마 — 모든 커넥터는 동일 키를 사용합니다.

- organization: 레거시 호환(지원기관 등 기존 필드)
- ministry: 정책·예산 소관 부처
- executing_agency: 실제 사업 수행·지원 운영 기관
"""

from __future__ import annotations

from typing import Any, Dict

NOTICE_SCHEMA: Dict[str, type] = {
    "title": str,
    "url": str,
    "source": str,
    "organization": str,
    "ministry": str,
    "executing_agency": str,
    "start_date": str,
    "end_date": str,
    "description": str,
}


def notice_keys() -> tuple[str, ...]:
    return tuple(NOTICE_SCHEMA.keys())


def empty_notice() -> Dict[str, Any]:
    return {k: "" for k in NOTICE_SCHEMA}
