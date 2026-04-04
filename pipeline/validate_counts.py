# -*- coding: utf-8 -*-
"""
원본 API 건수와 DB(biz_projects=canonical) 대조 + projects(mirror) 일치 검증.
AI 검증은 anthropic + ANTHROPIC_API_KEY 가 있을 때만.

실행(프로젝트 루트):
  py pipeline/validate_counts.py --skip-raw
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

import requests
import urllib3
from reports.blueprints.connector_www_bizinfo_go_kr import (
    LIST_API,
    LIST_PAGE_ROWS,
    parse_bizinfo_list_html,
)
from project_quality import infer_source

DEFAULT_JBEXPORT_VIEW_URL = os.environ.get(
    "JBEXPORT_VIEW_URL",
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/view1.do"
    "?menuUUID=402880867c8174de017c819251e70009",
)
JBEXPORT_UPSTREAM_REFERER = os.environ.get(
    "JBEXPORT_UPSTREAM_REFERER",
    "https://www.jbexport.or.kr/index.do?menuUUID=402880867c8174de017c81903f270000",
)

CANONICAL_TABLE = "biz_projects"
MIRROR_TABLE = "projects"
KNOWN_SOURCES = frozenset({"jbexport", "bizinfo", "jbba", "jbtp", "kotra", "unknown"})
ALL_JSON_PATH = _ROOT / "data" / "all_jb" / "all_jb.json"

JBEXPORT_LIST_MAX_LENGTH = int(os.environ.get("JBEXPORT_LIST_MAX_LENGTH", "5000"))

BIZINFO_LIST_URL = os.environ.get("BIZINFO_LIST_URL", LIST_API)
BIZINFO_LIST_ROWS = int(os.environ.get("BIZINFO_LIST_ROWS", str(LIST_PAGE_ROWS)))


class CanonicalTableError(Exception):
    """canonical(biz_projects) 테이블이 없거나 필수 컬럼이 없을 때."""


@dataclass
class SourceDistribution:
    jbexport: int
    bizinfo: int
    none: int


def _repo_root() -> Path:
    return _ROOT


def _jbexport_paths(view_url: str) -> Tuple[str, str]:
    u = urlparse(view_url)
    base_dir = u.path.rsplit("/", 1)[0]
    get_work = urlunparse((u.scheme, u.netloc, f"{base_dir}/getWork1Search.do", "", "", ""))
    return get_work, view_url


def fetch_jbexport_raw_count(
    *,
    work_year: Optional[str] = None,
    verify_ssl: Optional[bool] = None,
    session: Optional[requests.Session] = None,
) -> Tuple[int, str]:
    if verify_ssl is None:
        verify_ssl = os.environ.get("JBEXPORT_VERIFY_SSL", "").lower() in ("1", "true", "yes")
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    year = (
        work_year
        or os.environ.get("JBEXPORT_WORK_YEAR")
        or str(datetime.now().year)
    ).strip()
    view = DEFAULT_JBEXPORT_VIEW_URL.strip()
    get_work_url, _ = _jbexport_paths(view)
    referer = JBEXPORT_UPSTREAM_REFERER
    referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"

    sess = session or requests.Session()
    sess.verify = verify_ssl
    ua = sess.headers.get("User-Agent") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    sess.headers.setdefault("User-Agent", ua)

    payload = {
        "draw": "1",
        "start": "0",
        "length": str(max(10, min(JBEXPORT_LIST_MAX_LENGTH, 20000))),
        "work_year": year,
        "tsGubun": "",
        "stat": "",
        "js": "",
        "js_input": "",
        "su": "",
        "search[value]": "",
        "search[regex]": "false",
        "columns[0][data]": "0",
        "columns[1][data]": "CODE_K",
        "columns[2][data]": "CATEGO",
        "columns[3][data]": "js_title",
        "columns[4][data]": "STS_TXT",
    }
    for i in range(5):
        payload[f"columns[{i}][name]"] = ""
        payload[f"columns[{i}][searchable]"] = "true"
        payload[f"columns[{i}][orderable]"] = "true"
        payload[f"columns[{i}][search][value]"] = ""
        payload[f"columns[{i}][search][regex]"] = "false"
    payload["order[0][column]"] = "0"
    payload["order[0][dir]"] = "desc"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
        "Origin": referer_origin,
        "User-Agent": ua,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    try:
        sess.get(
            view,
            headers={"Referer": referer, "User-Agent": ua},
            timeout=90,
            verify=verify_ssl,
        )
        r = sess.post(get_work_url, data=payload, headers=headers, timeout=90, verify=verify_ssl)
    except requests.RequestException as exc:
        return -1, f"요청 실패: {exc}"

    if r.status_code >= 400:
        return -1, f"HTTP {r.status_code}"
    ct = (r.headers.get("content-type") or "").lower()
    if "json" not in ct:
        return -1, "응답이 JSON이 아님"
    try:
        j = r.json()
    except Exception as exc:
        return -1, f"JSON 파싱 실패: {exc}"
    if not isinstance(j, dict):
        return -1, "JSON 루트가 객체가 아님"

    rt = j.get("recordsTotal", j.get("recordsFiltered", j.get("total")))
    rows = j.get("data", j.get("aaData", j.get("rows", [])))
    try:
        rt_int = int(rt) if rt is not None else None
    except (TypeError, ValueError):
        rt_int = None
    data_len = len(rows) if isinstance(rows, list) else 0

    if rt_int is not None and rt_int > 0:
        count = rt_int
        basis = "recordsTotal/recordsFiltered/total"
        if data_len > 0 and data_len != rt_int:
            basis += f" (data 행 {data_len}건과 불일치, API total 기준)"
    elif isinstance(rows, list) and data_len > 0:
        count = data_len
        basis = "len(data) (total 필드 없음·0)"
    else:
        count = 0 if rt_int is None else max(0, int(rt_int))
        basis = "빈 목록"

    memo = (
        f"getWork1Search.do + view 선행 GET; work_year={year}; "
        f"총건 근거={basis}; SSL verify={verify_ssl}. "
        "파이프라인과 동일 건수를 맞추려면 work_year·필터를 동일하게 유지할 것."
    )
    return count, memo


def fetch_bizinfo_raw_count(
    *,
    session: Optional[requests.Session] = None,
    max_pages: int = 5000,
) -> Tuple[int, str]:
    s = session or requests.Session()
    s.headers.setdefault(
        "User-Agent",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    s.headers.setdefault("Accept-Language", "ko-KR,ko;q=0.9")

    total = 0
    cpage = 1
    prev_key = ""
    while cpage <= max_pages:
        try:
            r = s.get(
                BIZINFO_LIST_URL,
                params={"pageNo": 1, "rows": BIZINFO_LIST_ROWS, "cpage": cpage},
                timeout=int(os.environ.get("BIZINFO_TIMEOUT", "25")),
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            return -1, f"요청 실패 (cpage={cpage}): {exc}"

        rows = parse_bizinfo_list_html(r.text)
        if not rows:
            break
        key = rows[0].get("title", "") + "|" + str(rows[0].get("seq", ""))
        if cpage > 1 and key and key == prev_key:
            break
        prev_key = key
        total += len(rows)
        cpage += 1

    memo = (
        f"GET {BIZINFO_LIST_URL} - pageNo=1, rows={BIZINFO_LIST_ROWS}, cpage=N; "
        "파싱=connector.parse_bizinfo_list_html. pageNo 단독은 동일 페이지 반복이므로 cpage 필수."
    )
    return total, memo


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def classify_source(raw: Any) -> str:
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower()
    if not s:
        return "unknown"
    if s in KNOWN_SOURCES:
        return s
    return "unknown"


def _count_dist(conn: sqlite3.Connection, table: str) -> Tuple[int, SourceDistribution]:
    total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    cols = set(_table_columns(conn, table))
    dist = SourceDistribution(jbexport=0, bizinfo=0, none=0)
    if "source" not in cols:
        dist.none = total
        return total, dist
    for (raw,) in conn.execute(f"SELECT source FROM {table}"):
        label = classify_source(raw)
        if label == "jbexport":
            dist.jbexport += 1
        elif label == "bizinfo":
            dist.bizinfo += 1
        else:
            dist.none += 1
    return total, dist


def _load_json_items() -> List[Dict[str, Any]]:
    if not ALL_JSON_PATH.exists():
        return []
    try:
        data = json.loads(ALL_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def json_source_counts(items: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    """JBEXPORT / bizinfo / 기타 로 JSON 기준 건수."""
    jb = bi = ot = 0
    for it in items:
        url = str(it.get("url") or "")
        site = str(it.get("site") or "")
        s = infer_source(
            url,
            site,
            str(it.get("source") or ""),
            organization=str(it.get("organization") or ""),
            title=str(it.get("title") or ""),
        )
        if s == "jbexport":
            jb += 1
        elif s == "bizinfo":
            bi += 1
        else:
            ot += 1
    return jb, bi, ot


def db_unknown_and_fields(conn: sqlite3.Connection) -> Tuple[int, int, int, int]:
    """unknown 수, start/end/status 미채움 (biz_projects)."""
    n = int(conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()[0])
    if n == 0:
        return 0, 0, 0, 0
    unk = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM biz_projects
            WHERE LOWER(TRIM(COALESCE(source,''))) = 'unknown'
            """
        ).fetchone()[0]
    )
    sd = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM biz_projects
            WHERE start_date IS NULL OR TRIM(start_date) = ''
            """
        ).fetchone()[0]
    )
    ed = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM biz_projects
            WHERE end_date IS NULL OR TRIM(end_date) = ''
            """
        ).fetchone()[0]
    )
    st = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM biz_projects
            WHERE status IS NULL OR TRIM(status) = '' OR status = '확인 필요'
            """
        ).fetchone()[0]
    )
    return unk, sd, ed, st


def load_db_state(db_path: Path) -> Tuple[int, SourceDistribution, int, Optional[SourceDistribution]]:
    """biz_projects(canonical) + projects(mirror) 행 수·분포."""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, CANONICAL_TABLE):
            raise CanonicalTableError(
                f"SQLite에 '{CANONICAL_TABLE}' 테이블이 없습니다: {db_path}"
            )
        cols = set(_table_columns(conn, CANONICAL_TABLE))
        if "source" not in cols:
            raise CanonicalTableError(
                f"'{CANONICAL_TABLE}' 테이블에 source 컬럼이 없습니다. "
                "마이그레이션 후 다시 실행하세요."
            )

        biz_total, biz_dist = _count_dist(conn, CANONICAL_TABLE)

        if not _table_exists(conn, MIRROR_TABLE):
            return biz_total, biz_dist, 0, None

        proj_total, proj_dist = _count_dist(conn, MIRROR_TABLE)
        return biz_total, biz_dist, proj_total, proj_dist
    finally:
        conn.close()


def run_rule_checks(
    raw_jb: int,
    raw_biz: int,
    dist: SourceDistribution,
    *,
    skip_network: bool,
    unknown_count: int,
    bizinfo_collect_rate: float,
) -> list[str]:
    msgs: list[str] = []
    if unknown_count > 0:
        msgs.append(
            f"[경고] source='unknown' 행이 {unknown_count}건입니다. "
            "URL·site 기준으로 jbexport/bizinfo 등으로 보정하는 것을 권장합니다."
        )
    if not skip_network and raw_biz > 0 and bizinfo_collect_rate < 0.05:
        pct = bizinfo_collect_rate * 100.0
        msgs.append(
            f"[경고] 기업마당(bizinfo) DB 수집률이 낮습니다 "
            f"(DB {dist.bizinfo}건 / 원본 {raw_biz}건 ≈ {pct:.1f}%, 임계 5% 미만). "
            "파이프라인 확장·크롤 보강 검토."
        )
    if not skip_network:
        if raw_jb >= 0 and dist.jbexport != raw_jb:
            msgs.append(
                f"[참고] JBEXPORT API 총건({raw_jb})과 DB source=jbexport({dist.jbexport})는 "
                "연도·필터·병합·추론 소스가 달라 1:1 일치를 기대하지 않습니다."
            )
        if raw_biz >= 0 and dist.bizinfo != raw_biz:
            msgs.append(
                f"[참고] 기업마당 목록 총건({raw_biz})과 DB source=bizinfo({dist.bizinfo})는 "
                "수집 범위·과거 행·organization 추론 등으로 수치가 다를 수 있습니다."
            )
        if raw_jb < 0:
            msgs.append("[WARNING] JBEXPORT 원본 건수를 가져오지 못했습니다.")
        if raw_biz < 0:
            msgs.append("[WARNING] 기업마당 원본 건수를 가져오지 못했습니다.")
    return msgs


def maybe_ai_summary(
    *,
    raw_jb: int,
    raw_biz: int,
    jb_memo: str,
    biz_memo: str,
    total: int,
    dist: SourceDistribution,
) -> None:
    try:
        import anthropic  # type: ignore
    except ImportError:
        print("[AI 검증] 건너뜀: anthropic 패키지가 설치되어 있지 않습니다.")
        return
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        print("[AI 검증] 건너뜀: ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")
        return

    client = anthropic.Anthropic(api_key=key)
    prompt = (
        "다음은 지원사업 DB 검증 수치입니다. 한국어로 2~4문장만 요약하세요.\n"
        f"- biz_projects(canonical) 총 행: {total}\n"
        f"- 원본 JBEXPORT 건수: {raw_jb}\n"
        f"- 원본 기업마당 건수: {raw_biz}\n"
        f"- DB source jbexport/bizinfo/기타: {dist.jbexport}/{dist.bizinfo}/{dist.none}\n"
        f"- JBEXPORT 신뢰도 메모: {jb_memo}\n"
        f"- 기업마당 신뢰도 메모: {biz_memo}\n"
    )
    try:
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in getattr(msg, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "") or ""
        print("[AI 검증] 요약:")
        print(text.strip() or "(빈 응답)")
    except Exception as exc:
        print(f"[AI 검증] 실패(규칙 검증은 이미 완료): {exc}")


def main(argv: Optional[list[str]] = None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="원본 vs biz_projects + projects 미러 검증")
    parser.add_argument(
        "--db",
        type=Path,
        default=_repo_root() / "db" / "biz.db",
        help="SQLite DB 경로 (기본: db/biz.db)",
    )
    parser.add_argument(
        "--skip-network",
        "--skip-raw",
        dest="skip_network",
        action="store_true",
        help="원본 HTTP 호출 생략 (skip-raw 동일)",
    )
    parser.add_argument("--no-ai", action="store_true", help="AI 검증 생략")
    args = parser.parse_args(argv)

    db_path = args.db.resolve()
    print("=== validate_counts ===")
    print(f"DB: {db_path}")

    try:
        biz_total, biz_dist, proj_total, proj_dist = load_db_state(db_path)
    except CanonicalTableError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[ERROR] DB 열기 실패: {exc}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    try:
        unk_n, sd_miss, ed_miss, st_miss = db_unknown_and_fields(conn)
    finally:
        conn.close()

    items = _load_json_items()
    merged = len(items)
    jb_json, bi_json, _ot_json = json_source_counts(items)

    print(f"[DB] canonical (source of truth): {CANONICAL_TABLE}")
    print(f"[DB] mirror target: {MIRROR_TABLE}")

    mirror_ok = True
    mirror_reason = ""

    print("\n[mirror check]")
    print(f"biz_projects rows: {biz_total}")
    if proj_dist is None:
        print("projects rows: 0 (테이블 없음)")
        mirror_ok = False
        mirror_reason = "projects table missing"
        print("biz_projects source:")
        print(f"  jbexport: {biz_dist.jbexport}")
        print(f"  bizinfo: {biz_dist.bizinfo}")
        print(f"  기타: {biz_dist.none}")
        print("projects source:")
        print("  jbexport: 0")
        print("  bizinfo: 0")
        print("  기타: 0")
        print("result: FAIL")
        print(f"reason: {mirror_reason}")
        print("판정: [심각] 미러 테이블 없음")
    else:
        print(f"projects rows: {proj_total}")
        print("biz_projects source:")
        print(f"  jbexport: {biz_dist.jbexport}")
        print(f"  bizinfo: {biz_dist.bizinfo}")
        print(f"  기타: {biz_dist.none}")
        print("projects source:")
        print(f"  jbexport: {proj_dist.jbexport}")
        print(f"  bizinfo: {proj_dist.bizinfo}")
        print(f"  기타: {proj_dist.none}")
        if (
            biz_total == proj_total
            and biz_dist.jbexport == proj_dist.jbexport
            and biz_dist.bizinfo == proj_dist.bizinfo
            and biz_dist.none == proj_dist.none
        ):
            print("result: OK")
            print("판정: [정상] (미러 일치)")
        else:
            mirror_ok = False
            mirror_reason = (
                "row count mismatch"
                if biz_total != proj_total
                else "source distribution mismatch"
            )
            print("result: FAIL")
            print(f"reason: {mirror_reason}")
            print("판정: [심각] 미러 불일치")

    raw_jb = -1
    raw_biz = -1
    jb_memo = "(네트워크 생략)"
    biz_memo = "(네트워크 생략)"

    if not args.skip_network:
        print("\n[원본] JBEXPORT ...")
        raw_jb, jb_memo = fetch_jbexport_raw_count()
        print(f"  건수: {raw_jb}")
        print("\n[원본] 기업마당 ...")
        raw_biz, biz_memo = fetch_bizinfo_raw_count()
        print(f"  건수: {raw_biz}")
    else:
        print("\n[원본] --skip-network/--skip-raw 로 원본 건수를 가져오지 않았습니다.")

    bizinfo_rate = (biz_dist.bizinfo / raw_biz) if raw_biz and raw_biz > 0 else 0.0

    n_db = biz_total if biz_total else 1
    pct = lambda x: (x / n_db * 100) if n_db else 0.0

    print("\n== 검증 요약 ==")
    print(f"JBEXPORT raw: {raw_jb}")
    print(f"JBEXPORT collected: {biz_dist.jbexport}")
    print(f"bizinfo raw: {raw_biz}")
    print(f"bizinfo collected: {biz_dist.bizinfo}")
    print(f"merged: {merged}")
    print(f"DB 저장: {biz_total}")
    print(f"source unknown: {unk_n}")

    print("\n== 필드 완성도 (biz_projects) ==")
    print(f"source unknown: {unk_n} ({pct(unk_n):.0f}%)")
    print(f"start_date NULL: {sd_miss} ({pct(sd_miss):.0f}%)")
    print(f"end_date NULL: {ed_miss} ({pct(ed_miss):.0f}%)")
    print(f"status 미확인: {st_miss} ({pct(st_miss):.0f}%)")

    print("\n== 규칙 기반 판정 ==")
    rule_msgs = run_rule_checks(
        raw_jb,
        raw_biz,
        biz_dist,
        skip_network=args.skip_network,
        unknown_count=unk_n,
        bizinfo_collect_rate=bizinfo_rate,
    )
    for line in rule_msgs:
        print(line)
    if not rule_msgs:
        print("  특이사항 없음 (미러·원본 대조 기준).")

    if not args.no_ai:
        print("")
        maybe_ai_summary(
            raw_jb=raw_jb,
            raw_biz=raw_biz,
            jb_memo=jb_memo,
            biz_memo=biz_memo,
            total=biz_total,
            dist=biz_dist,
        )

    print("")
    print("---")
    print(f"canonical_table: {CANONICAL_TABLE}")
    print(f"mirror_table: {MIRROR_TABLE}")
    print(f"source_jbexport: {biz_dist.jbexport}")
    print(f"source_bizinfo: {biz_dist.bizinfo}")
    print(f"source_기타: {biz_dist.none}")
    print(f"raw_jbexport_count: {raw_jb}")
    print(f"raw_bizinfo_count: {raw_biz}")
    print(
        "raw_reliability: "
        f"JBEXPORT - {jb_memo} | "
        f"BIZINFO - {biz_memo}"
    )

    def _is_bizinfo_rate_soft_warning(msg: str) -> bool:
        """기업마당 수집률만 '참고' 수준 — 최종 FAIL/WARNING 판정에서 제외."""
        return (
            msg.startswith("[경고]")
            and "기업마당(bizinfo)" in msg
            and "수집률" in msg
        )

    verdict = "PASS"
    if not mirror_ok or any(w.startswith("[심각]") for w in rule_msgs):
        verdict = "FAIL"
    elif unk_n > 0 or any(
        (w.startswith("[경고]") and not _is_bizinfo_rate_soft_warning(w))
        or w.startswith("[WARNING]")
        for w in rule_msgs
    ):
        verdict = "WARNING"
    print(f"\n[최종 판정] {verdict}")

    exit_code = 0 if verdict == "PASS" else 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
