# -*- coding: utf-8 -*-
"""JBEXPORT 목록·병합·DB 적재 시 제외 규칙."""

from __future__ import annotations

from typing import Any, Dict


def should_exclude_jbexport_item(item: Dict[str, Any]) -> bool:
    """기타 지원사업만 제외. 전북 핵심 공고는 유지."""
    support_type = str(
        item.get("support_type")
        or item.get("지원사업")
        or item.get("supportType")
        or item.get("SUPPORT_TYPE")
        or ""
    ).strip()
    return support_type == "기타 지원사업"
