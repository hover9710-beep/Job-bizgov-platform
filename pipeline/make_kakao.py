# -*- coding: utf-8 -*-
"""
카카오 알림용 짧은 본문 → data/kakao/kakao_body.txt
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.data_paths import KAKAO_BODY_TXT, ensure_pipeline_dirs


def build_kakao_body() -> str:
    url = (os.getenv("KAKAO_PUBLIC_URL") or "").strip() or "https://bizinfo.go.kr"

    msg = f"""📢 정부지원사업 추천
✔ 전북 기업 대상 맞춤 공고
✔ 마감 임박 사업 포함

👉 지금 바로 확인하기
{url}
"""
    return msg


def main() -> int:
    ensure_pipeline_dirs()
    body = build_kakao_body()
    KAKAO_BODY_TXT.parent.mkdir(parents=True, exist_ok=True)
    KAKAO_BODY_TXT.write_text(body, encoding="utf-8")
    print(f"[make_kakao] 저장: {KAKAO_BODY_TXT} ({len(body)}자)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
