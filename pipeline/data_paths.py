# -*- coding: utf-8 -*-
"""알림 파이프라인 공통 경로 (프로젝트 루트 기준)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
MERGED_DIR = DATA / "merged"
HISTORY_DIR = DATA / "history"
MAIL_DIR = DATA / "mail"
KAKAO_DIR = DATA / "kakao"

ALL_SITES_JSON = MERGED_DIR / "all_sites.json"
NEW_JSON = MERGED_DIR / "new.json"
MAIL_BODY_TXT = MAIL_DIR / "mail_body.txt"
KAKAO_BODY_TXT = KAKAO_DIR / "kakao_body.txt"

# 레거시 (일부 스크립트·문서 호환)
LEGACY_ALL_SITES = DATA / "all_sites.json"
LEGACY_NEW = DATA / "new.json"


def ensure_pipeline_dirs() -> None:
    for d in (RAW_DIR, MERGED_DIR, HISTORY_DIR, MAIL_DIR, KAKAO_DIR):
        d.mkdir(parents=True, exist_ok=True)
