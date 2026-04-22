# -*- coding: utf-8 -*-
"""
공고 상태(status) 정규화.

날짜 우선, 없으면 기간 원문 키워드를 좁게 해석, 그래도 불명확하면 '확인 필요'.
좁게 시작해서 오판을 줄인다.
"""
from __future__ import annotations


def infer_status(
    period_text: str,
    start_date: str,
    end_date: str,
    today: str,
) -> str:
    """
    반환값: '접수중' | '마감' | '확인 필요'

    순서
      1) end_date 가 있으면 today 와 비교해 확정
      2) period_text 를 좁은 키워드로 해석
      3) 그 외는 '확인 필요'
    """
    if end_date:
        if end_date >= today:
            return "접수중"
        return "마감"

    text = (period_text or "").strip()
    open_keywords = ["상시", "접수중", "예산 소진 시까지"]
    closed_keywords = ["마감", "종료", "접수마감", "신청마감", "모집완료"]

    if any(k in text for k in open_keywords):
        return "접수중"
    if any(k in text for k in closed_keywords):
        return "마감"

    return "확인 필요"
