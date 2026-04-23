# -*- coding: utf-8 -*-
"""
pipeline/url_utils.py
=====================

URL 정규화 유틸. 같은 리소스를 가리키지만 쿼리 파라미터 순서만 다른 URL을
같은 키로 인식시키기 위한 얇은 헬퍼.

jbexport 상세 URL 예:
  spSeq=X&menuUUID=Y
  menuUUID=Y&spSeq=X
둘 다 같은 페이지지만 문자열 비교로는 다르게 보여서 DB에 이중 저장되는
문제가 있었다. 이 파일의 `canonical_url()` 로 dedupe / upsert 키를 통일한다.

설계 원칙
  - 예상 가능한 범위에서만 정규화한다 (scheme/host 소문자, 쿼리 key 정렬,
    trailing slash/fragment 는 그대로 유지).
  - 대소문자 보존이 필요한 path (예: REST 리소스) 는 건드리지 않는다.
  - 빈 문자열/None 입력은 "" 반환.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def canonical_url(url: str) -> str:
    """쿼리 파라미터를 key 이름순으로 정렬한 URL 을 반환.

    - scheme/host 를 소문자로 통일.
    - 쿼리는 `parse_qsl` 로 파싱 후 key 이름순 정렬 → `urlencode` 로 재조립.
    - fragment/path 는 건드리지 않는다 (대소문자 보존).
    """
    s = str(url or "").strip()
    if not s:
        return ""
    try:
        p = urlparse(s)
    except Exception:
        return s

    params = parse_qsl(p.query, keep_blank_values=True)
    params.sort(key=lambda kv: kv[0])
    new_query = urlencode(params, doseq=True)

    return urlunparse(
        (
            (p.scheme or "").lower(),
            (p.netloc or "").lower(),
            p.path or "",
            p.params or "",
            new_query,
            p.fragment or "",
        )
    )
