"""DB 경로 통일 helper (백로그 044).

모든 DB-touching 코드는 이 모듈의 resolve_db_path() 를 사용해
환경변수 DB_PATH (Render 운영 /var/data/biz.db) 와 fallback (db/biz.db) 를 일관되게 처리한다.

배경:
- update_db.py 만 _resolve_db_path() 를 갖고 있었음
- 7 connector 와 다수 pipeline 스크립트가 hardcoded 'db/biz.db' 또는 _ROOT 기반 경로 사용
- → Render 환경에서 envvar DB_PATH 가 설정되어 있어도 무시되는 위험
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def resolve_db_path() -> Path:
    """환경변수 DB_PATH 우선, 없으면 db/biz.db (프로젝트 루트 기준).

    상대 경로는 프로젝트 루트 기준으로 해석하고, 절대 경로는 그대로 사용.
    """
    raw = (os.getenv("DB_PATH") or "db/biz.db").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (_ROOT / p).resolve()
    else:
        p = p.resolve()
    return p
