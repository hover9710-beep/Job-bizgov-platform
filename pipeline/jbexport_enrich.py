# -*- coding: utf-8 -*-
"""
JBEXPORT 상세 HTML 보강 — 목록 수집과 분리.

- fetch_jbexport_detail_html / parse_jbexport_detail / merge_detail_into_item
- enrich_jbexport_items: JBEXPORT 항목만 순회·보강
- enrich_jbexport_database: biz.db 의 jbexport 행 상세 반영
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.bizinfo_dates import extract_date_range as extract_date_range_in_line

JBEXPORT_BASE = "https://www.jbexport.or.kr"
DEFAULT_ORG = "전북수출통합지원시스템"
DEFAULT_SOURCE = "jbexport"
TIMEOUT = 30

_DETAIL_SESSION: Optional[requests.Session] = None

DB_PATH_DEFAULT = _ROOT / "db" / "biz.db"

EXTRA_COLUMNS = (
    "receipt_start",
    "receipt_end",
    "biz_start",
    "biz_end",
    "raw_status",
    "attachments_json",
)


def _get_session() -> requests.Session:
    global _DETAIL_SESSION
    if _DETAIL_SESSION is None:
        _DETAIL_SESSION = requests.Session()
        _DETAIL_SESSION.verify = False
    return _DETAIL_SESSION


def ensure_biz_projects_extra_columns(conn: sqlite3.Connection) -> None:
    """biz_projects 에 상세 보강용 컬럼 추가."""
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    for col in EXTRA_COLUMNS:
        if col not in cols:
            conn.execute(f"ALTER TABLE biz_projects ADD COLUMN {col} TEXT")
            cols.add(col)


def fetch_jbexport_detail_html(detail_url: str, *, timeout: int = TIMEOUT) -> str:
    """상세 URL GET. 실패 시 빈 문자열."""
    if not (detail_url or "").strip():
        return ""
    u = detail_url.strip()
    print(f"[jbexport-enrich] GET {u}", flush=True)
    sess = _get_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{JBEXPORT_BASE}/index.do",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        res = sess.get(u, headers=headers, timeout=timeout, verify=False)
        print(f"[jbexport-enrich] status={res.status_code}", flush=True)
        res.raise_for_status()
        return res.text or ""
    except Exception as e:
        print(f"[jbexport-enrich] GET failed: {e}", flush=True)
        return ""


def fetch_detail_html(detail_url: str, *, timeout: int = TIMEOUT) -> str:
    """호환 별칭."""
    return fetch_jbexport_detail_html(detail_url, timeout=timeout)


def _period_dates_from_string(val: str) -> Tuple[str, str]:
    s = re.sub(r"\s+", " ", str(val or "")).strip()
    if not s:
        return "", ""
    return extract_date_range_in_line(s)


# JBEXPORT 상세 전용 — th 없이 td·한 줄 라벨 등
_RE_JB_LABEL_RECEIPT = re.compile(
    r"(?:접수기간|신청기간|모집기간|공고기간|접수\s*일정|신청\s*일정|모집\s*일정|"
    r"신청\s*기간|접수\s*기간|모집\s*기간|공고\s*기간|당해\s*접수|당\s*접수)",
    re.I,
)
_RE_JB_LABEL_BIZ = re.compile(
    r"(?:사업기간|사업수행기간|수행기간|지원기간|행사기간|교육기간|운영기간|과제기간|추진기간|"
    r"사업\s*추진\s*기간|사업\s*수행|사업\s*기간|지원\s*기간|수행\s*기간|"
    r"교육\s*기간|운영\s*기간|과제\s*기간|추진\s*기간)",
    re.I,
)

# HTML/평문에서 라벨 직후 토막 추출 (여러 사이트 변형)
_RE_JB_RECEIPT_LEAD = (
    r"(?:접수기간|신청기간|모집기간|공고기간|접수\s*일정|신청\s*일정|모집\s*일정|공고\s*기간|"
    r"접수\s*기간|신청\s*기간|모집\s*기간|당해\s*접수)"
)
_RE_JB_BIZ_LEAD = (
    r"(?:사업기간|사업수행기간|수행기간|지원기간|행사기간|교육기간|운영기간|과제기간|추진기간|"
    r"사업\s*추진\s*기간|사업\s*기간|지원\s*기간|수행\s*기간|사업\s*수행|"
    r"교육\s*기간|운영\s*기간|과제\s*기간|추진\s*기간)"
)
_RE_JB_STOP_BEFORE_RECEIPT = (
    r"(?:접수기간|신청기간|모집기간|공고기간|접수\s*일정|신청\s*일정|모집\s*일정|"
    r"접수\s*기간|신청\s*기간|모집\s*기간|공고\s*기간)"
)
_RE_JB_STOP_BEFORE_BIZ = (
    r"(?:사업기간|사업수행기간|수행기간|지원기간|행사기간|교육기간|운영기간|과제기간|추진기간|"
    r"사업\s*추진\s*기간|사업\s*기간|지원\s*기간|수행\s*기간|교육\s*기간|운영\s*기간|과제\s*기간|추진\s*기간)"
)
_RE_JB_STOP_STATUS = r"(?:진행상태|공고상태|접수상태|상태|담당|문의|첨부)"

# th/td/dt/strong 등 라벨 문자열 매칭 (요구 라벨 집합)
_JB_RECEIPT_LABEL_KEYS = (
    "접수기간",
    "신청기간",
    "모집기간",
    "공고기간",
    "접수 일정",
    "신청 일정",
    "모집 일정",
    "공고 일정",
)
_JB_BIZ_LABEL_KEYS = (
    "사업기간",
    "사업수행기간",
    "사업 추진기간",
    "수행기간",
    "지원기간",
    "행사기간",
    "교육기간",
    "운영기간",
    "과제기간",
    "추진기간",
    "사업 기간",
    "지원 기간",
    "수행 기간",
    "교육 기간",
    "운영 기간",
    "과제 기간",
    "추진 기간",
)


def _jb_label_has_receipt(label: str) -> bool:
    return any(k in label for k in _JB_RECEIPT_LABEL_KEYS)


def _jb_label_has_biz(label: str) -> bool:
    return any(k in label for k in _JB_BIZ_LABEL_KEYS)


def _jbexport_parse_receipt_from_plaintext(ft: str) -> Tuple[str, str]:
    """JB 라벨이 있는 줄만 — bizinfo 본문 파서 함수 미사용."""
    if not ft or not str(ft).strip():
        return "", ""
    for line in str(ft).splitlines():
        line = line.strip()
        if not line or len(line) > 600:
            continue
        if not _RE_JB_LABEL_RECEIPT.search(line):
            continue
        sd, ed = extract_date_range_in_line(line)
        if sd and ed:
            return sd, ed
        if sd and not ed:
            return sd, ""
    return "", ""


def _jbexport_parse_biz_from_plaintext(ft: str) -> Tuple[str, str]:
    if not ft or not str(ft).strip():
        return "", ""
    for line in str(ft).splitlines():
        line = line.strip()
        if not line or len(line) > 600:
            continue
        if not _RE_JB_LABEL_BIZ.search(line):
            continue
        sd, ed = extract_date_range_in_line(line)
        if sd and ed:
            return sd, ed
        if sd and not ed:
            return sd, ""
    return "", ""


def _jbexport_normalize_text(s: str) -> str:
    """nbsp·제로폭·연속 공백 정리(라벨·날짜 매칭 안정화)."""
    t = str(s or "")
    t = t.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", t).strip()


def _jbexport_fill_periods_from_plaintext(full_text: str, out: Dict[str, str]) -> None:
    """
    표 파싱 후에도 비어 있으면, JB 라벨이 있는 줄에서만 한 줄 범위로 날짜 추출.
    """
    ft = _jbexport_normalize_text(str(full_text or ""))
    if not ft:
        return

    if not (out.get("receipt_start") or "").strip() or not (out.get("receipt_end") or "").strip():
        ps, pe = _jbexport_parse_receipt_from_plaintext(ft)
        if ps and not (out.get("receipt_start") or "").strip():
            out["receipt_start"] = ps
            out["start_date"] = (out.get("start_date") or "").strip() or ps
        if pe and not (out.get("receipt_end") or "").strip():
            out["receipt_end"] = pe
            out["end_date"] = (out.get("end_date") or "").strip() or pe

    if not (out.get("biz_start") or "").strip() or not (out.get("biz_end") or "").strip():
        ps, pe = _jbexport_parse_biz_from_plaintext(ft)
        if ps and not (out.get("biz_start") or "").strip():
            out["biz_start"] = ps
        if pe and not (out.get("biz_end") or "").strip():
            out["biz_end"] = pe


def _jbexport_strip_scripts_styles(html: str) -> str:
    h = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    h = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", h)
    return h


def _jbexport_flat_text_for_regex(html: str) -> str:
    """태그가 라벨·날짜 사이를 끊는 경우 대비: 한 줄짜리 평문으로 합침."""
    h = _jbexport_strip_scripts_styles(html)
    h = re.sub(r"<br\s*/?>", " ", h, flags=re.I)
    h = re.sub(r"</(p|div|li|tr|td|th)\s*>", " ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def _jbexport_collect_receipt_chunks_from_html(html: str) -> List[str]:
    """원본 HTML·평문에서 접수 라벨 직후 토막 후보(JBEXPORT 전용)."""
    if not html or not str(html).strip():
        return []
    seen: set[str] = set()
    out: List[str] = []
    h = _jbexport_strip_scripts_styles(html)

    def _push(raw: str) -> None:
        chunk = _jbexport_normalize_text(re.sub(r"<[^>]+>", " ", raw))
        if len(chunk) < 4:
            return
        if chunk in seen:
            return
        seen.add(chunk)
        out.append(chunk)

    for m in re.finditer(
        _RE_JB_RECEIPT_LEAD + r"\s*[:：]?\s*([^<\n\r]{2,400})",
        h,
        re.I,
    ):
        _push(m.group(1))
    # 라벨과 값이 한 td 안에서 태그로만 구분되는 경우
    for m in re.finditer(
        _RE_JB_RECEIPT_LEAD
        + r"\s*[:：]?\s*</(?:strong|b|span|label|em)>\s*([^<]{2,400}?)(?:<|$)",
        h,
        re.I,
    ):
        _push(m.group(1))

    flat = _jbexport_flat_text_for_regex(html)
    flat = _jbexport_normalize_text(flat)
    for m in re.finditer(
        _RE_JB_RECEIPT_LEAD
        + r"\s*[:：]?\s*(.{4,400}?)(?=\s*(?:"
        + _RE_JB_STOP_BEFORE_BIZ
        + r"|"
        + _RE_JB_STOP_STATUS
        + r"|$))",
        flat,
        re.I,
    ):
        _push(m.group(1))

    return out


def _jbexport_collect_biz_chunks_from_html(html: str) -> List[str]:
    if not html or not str(html).strip():
        return []
    seen: set[str] = set()
    out: List[str] = []
    h = _jbexport_strip_scripts_styles(html)

    def _push(raw: str) -> None:
        chunk = _jbexport_normalize_text(re.sub(r"<[^>]+>", " ", raw))
        if len(chunk) < 4:
            return
        if chunk in seen:
            return
        seen.add(chunk)
        out.append(chunk)

    for m in re.finditer(
        _RE_JB_BIZ_LEAD + r"\s*[:：]?\s*([^<\n\r]{2,400})",
        h,
        re.I,
    ):
        _push(m.group(1))
    for m in re.finditer(
        _RE_JB_BIZ_LEAD
        + r"\s*[:：]?\s*</(?:strong|b|span|label|em)>\s*([^<]{2,400}?)(?:<|$)",
        h,
        re.I,
    ):
        _push(m.group(1))

    flat = _jbexport_flat_text_for_regex(html)
    flat = _jbexport_normalize_text(flat)
    for m in re.finditer(
        _RE_JB_BIZ_LEAD
        + r"\s*[:：]?\s*(.{4,400}?)(?=\s*(?:"
        + _RE_JB_STOP_BEFORE_RECEIPT
        + r"|"
        + _RE_JB_STOP_STATUS
        + r"|$))",
        flat,
        re.I,
    ):
        _push(m.group(1))

    return out


def _jbexport_best_dates_from_chunks(chunks: List[str]) -> Tuple[str, str]:
    """여러 토막 중 (시작·종료) 둘 다 나오는 첫 결과 우선."""
    partial_s, partial_e = "", ""
    for ch in chunks:
        sd, ed = _period_dates_from_string(ch)
        if sd and ed:
            return sd, ed
        if sd and not ed and not partial_s:
            partial_s = sd
        if ed and not sd and not partial_e:
            partial_e = ed
    return partial_s, partial_e


def _extract_period_status_from_jbexport_html(html: str) -> Tuple[str, str]:
    period = ""
    status = ""
    m = re.search(
        r"(?:접수기간|신청기간|공고기간|모집기간)\s*[:：]?\s*([^<\n\r]+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if m:
        period = re.sub(r"\s+", " ", m.group(1)).strip()
    m2 = re.search(
        r"(?:진행상태|공고상태|접수상태|상태)\s*[:：]?\s*([^<\n\r]+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if m2:
        status = re.sub(r"\s+", " ", m2.group(1)).strip()
    return period, status


def _parse_meta_from_html(html: str, *, use_regex_chunks: bool = True) -> Dict[str, str]:
    out: Dict[str, str] = {
        "status": "",
        "start_date": "",
        "end_date": "",
        "receipt_start": "",
        "receipt_end": "",
        "biz_start": "",
        "biz_end": "",
    }
    if not html or not str(html).strip():
        return out

    soup = BeautifulSoup(html, "html.parser")
    full_text = _jbexport_normalize_text(soup.get_text("\n", strip=True))

    def absorb_receipt(val: str) -> None:
        sd, ed = _period_dates_from_string(val)
        if sd:
            out["receipt_start"] = sd
            out["start_date"] = sd
        if ed:
            out["receipt_end"] = ed
            out["end_date"] = ed

    def absorb_biz(val: str) -> None:
        sd, ed = _period_dates_from_string(val)
        if sd:
            out["biz_start"] = sd
        if ed:
            out["biz_end"] = ed

    # <th>…</th><td>값</td> 및 <td class="th">라벨</td><td>값</td> (지원사업 상세 공통)
    for lab_el in soup.select("th, td.th"):
        label = lab_el.get_text(" ", strip=True)
        if not label:
            continue
        val_td = lab_el.find_next("td")
        if not val_td:
            continue
        val = val_td.get_text(" ", strip=True)
        if not val:
            continue
        if _jb_label_has_receipt(label):
            absorb_receipt(val)
        if _jb_label_has_biz(label):
            absorb_biz(val)
        if any(k in label for k in ("진행상태", "접수상태", "공고상태", "상태", "진행 상태")):
            if len(val) < 80 and not re.search(r"function\s*\(", val):
                out["status"] = val

    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True)
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        val = dd.get_text(" ", strip=True)
        if not val:
            continue
        if _jb_label_has_receipt(label):
            absorb_receipt(val)
        if _jb_label_has_biz(label):
            absorb_biz(val)
        if any(k in label for k in ("진행상태", "접수상태", "공고상태", "상태")):
            if len(val) < 80:
                out["status"] = val

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        pairs: List[Tuple[int, int]] = []
        if len(tds) >= 3 and not (tds[0].get_text(" ", strip=True) or "").strip():
            pairs.append((1, 2))
            start_i = 3
        else:
            start_i = 0
        for j in range(start_i, len(tds) - 1, 2):
            pairs.append((j, j + 1))
        for li, vi in pairs:
            label = tds[li].get_text(" ", strip=True)
            val = tds[vi].get_text(" ", strip=True)
            if not val or not label:
                continue
            if len(label) > 120:
                continue
            if _jb_label_has_receipt(label):
                absorb_receipt(val)
            if _jb_label_has_biz(label):
                absorb_biz(val)
            if any(k in label for k in ("진행상태", "접수상태", "공고상태", "상태", "진행 상태")):
                if len(val) < 80 and not re.search(r"function\s*\(", val):
                    out["status"] = val

    for tag in soup.find_all(["strong", "b", "span", "label"]):
        lab = _jbexport_normalize_text(tag.get_text(" ", strip=True))
        if not lab or len(lab) > 200:
            continue
        has_r = _jb_label_has_receipt(lab)
        has_b = _jb_label_has_biz(lab)
        if not has_r and not has_b:
            continue
        if has_r and has_b:
            continue
        parent = tag.parent
        if parent is None or parent.name not in ("td", "div", "dd", "li", "p", "span"):
            continue
        full = _jbexport_normalize_text(parent.get_text(" ", strip=True))
        if not full or len(full) > 800:
            continue
        if has_r:
            absorb_receipt(full)
        else:
            absorb_biz(full)

    for td in soup.find_all("td"):
        t = td.get_text(" ", strip=True)
        if not t or len(t) > 260:
            continue
        head = t[:140]
        if _RE_JB_LABEL_RECEIPT.search(head):
            absorb_receipt(t)
        if _RE_JB_LABEL_BIZ.search(head):
            absorb_biz(t)

    if not out["status"]:
        m = re.search(
            r"(?:진행상태|공고상태|접수상태|상태)\s*[:：]?\s*([^\n\r<]+?)(?:\n|$)",
            full_text,
            re.IGNORECASE,
        )
        if m:
            cand = re.sub(r"\s+", " ", m.group(1)).strip()
            if cand and len(cand) < 80:
                out["status"] = cand

    if not out["status"]:
        _p2, st2 = _extract_period_status_from_jbexport_html(html)
        if st2:
            out["status"] = st2

    _jbexport_fill_periods_from_plaintext(full_text, out)

    if use_regex_chunks:
        if not (out.get("receipt_start") or "").strip() or not (
            out.get("receipt_end") or ""
        ).strip():
            rchunks = _jbexport_collect_receipt_chunks_from_html(html)
            rsd, red_ = _jbexport_best_dates_from_chunks(rchunks)
            if rsd and not (out.get("receipt_start") or "").strip():
                out["receipt_start"] = rsd
                out["start_date"] = (out.get("start_date") or "").strip() or rsd
            if red_ and not (out.get("receipt_end") or "").strip():
                out["receipt_end"] = red_
                out["end_date"] = (out.get("end_date") or "").strip() or red_

        if not (out.get("biz_start") or "").strip() or not (out.get("biz_end") or "").strip():
            bchunks = _jbexport_collect_biz_chunks_from_html(html)
            bsd, bed = _jbexport_best_dates_from_chunks(bchunks)
            if bsd and not (out.get("biz_start") or "").strip():
                out["biz_start"] = bsd
            if bed and not (out.get("biz_end") or "").strip():
                out["biz_end"] = bed

    return out


def _attachments_from_html(html: str) -> List[Dict[str, str]]:
    """상세 HTML에서 첨부 URL·파일명 수집. connectors_jbexport 의 extract_attachment_records 우선."""
    found: List[Dict[str, str]] = []
    seen: set[str] = set()

    def _add(name: str, url: str) -> None:
        url = (url or "").strip()
        if not url or url in seen:
            return
        seen.add(url)
        nm = (name or "").strip() or "첨부파일"
        found.append({"name": nm, "url": url})

    try:
        import importlib.util

        _proxy_path = _ROOT / "connectors" / "connectors_jbexport" / "jbexport_proxy.py"
        if _proxy_path.is_file():
            spec = importlib.util.spec_from_file_location(
                "jbexport_proxy_attach", _proxy_path
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                extract = getattr(mod, "extract_attachment_records", None)
                if callable(extract):
                    soup = BeautifulSoup(html or "", "html.parser")
                    for r in extract(soup, html or ""):
                        u = str(r.get("download_url") or "").strip()
                        nm = str(r.get("name") or "").strip()
                        _add(nm, u)
    except Exception:
        pass

    soup = BeautifulSoup(html or "", "html.parser")
    for th in soup.find_all("th"):
        label = th.get_text(" ", strip=True)
        if "첨부" not in label:
            continue
        td = th.find_next("td")
        if not td:
            continue
        for a in td.find_all("a", href=True):
            name = a.get_text(" ", strip=True) or ""
            href = str(a.get("href") or "").strip()
            if not href:
                continue
            abs_u = urllib.parse.urljoin(JBEXPORT_BASE + "/", href)
            _add(name or "첨부파일", abs_u)

    for path_num, file_uuid in re.findall(
        r"downloadFile\.do\?[^\"' ]*pathNum=([^&\"' ]+)[^\"' ]*fileUUID=([a-fA-F0-9]+)",
        html or "",
        re.IGNORECASE,
    ):
        _add("", _build_download_url(path_num, file_uuid))

    for file_uuid in re.findall(r"fn_fileDown\('([a-fA-F0-9]+)'\)", html or "", re.I):
        _add("", _build_download_url("6", file_uuid))

    return found


def _build_download_url(path_num: str, file_uuid: str) -> str:
    q = urllib.parse.urlencode({"pathNum": path_num, "fileUUID": file_uuid})
    return f"{JBEXPORT_BASE}/downloadFile.do?{q}"


def _title_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for sel in ("h3.tit", "h2.tit", "div.subject", "td.subject"):
        el = soup.select_one(sel)
        if el:
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if t:
                return t
    strong = soup.find("strong")
    if strong:
        t = re.sub(r"\s+", " ", strong.get_text(" ", strip=True)).strip()
        if t:
            return t
    return ""


_JB_NAV_PHRASES = (
    "로그인",
    "회원가입",
    "사이트맵",
    "FAQ",
    "Q&A",
    "이용안내",
    "본문 바로가기",
)
_JB_MENU_LINE = re.compile(
    r"^(로그인|회원가입|사이트맵|FAQ|Q&A|이용안내|본문\s*바로가기|TOP|맨\s*위로)\s*$",
    re.I,
)


def _sanitize_jbexport_description_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    lines: List[str] = []
    for line in s.split("\n"):
        ln = line.strip()
        if not ln:
            continue
        if _JB_MENU_LINE.match(ln):
            continue
        if len(ln) == 1 and ln in "·|-":
            continue
        lines.append(ln)
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _jbexport_description_quality_ok(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 30:
        return False
    nav_hits = sum(1 for k in _JB_NAV_PHRASES if k in t)
    if nav_hits >= 3:
        return False
    if "본문 바로가기" in t:
        return False
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    if len(lines) >= 12:
        c = Counter(lines)
        noisy = sum(1 for L, n in c.items() if len(L) <= 18 and n >= 4)
        if noisy >= 8:
            return False
    return True


def _jbexport_text_from_primary_regions(soup: BeautifulSoup) -> str:
    for sel in (".view-content", ".board-view-content", "#content"):
        el = soup.select_one(sel)
        if not el:
            continue
        t = el.get_text("\n", strip=True)
        t = _sanitize_jbexport_description_text(t)
        if _jbexport_description_quality_ok(t):
            return t[:50000]
    return ""


def _jbexport_description_from_labeled_cells(soup: BeautifulSoup) -> str:
    labels = ("지원내용", "공고내용", "사업개요", "사업내용", "상세내용", "공고 개요")
    for th in soup.find_all("th"):
        label = th.get_text(" ", strip=True)
        if not any(k in label for k in labels):
            continue
        td = th.find_next("td")
        if td:
            t = td.get_text("\n", strip=True)
            t = _sanitize_jbexport_description_text(t)
            if _jbexport_description_quality_ok(t):
                return t[:50000]
    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True)
        if not any(k in label for k in labels):
            continue
        dd = dt.find_next_sibling("dd")
        if dd:
            t = dd.get_text("\n", strip=True)
            t = _sanitize_jbexport_description_text(t)
            if _jbexport_description_quality_ok(t):
                return t[:50000]
    return ""


def _jbexport_description_from_note_script(html: str) -> str:
    for pat in (
        r'NOTE_CONTENT["\']?\s*[:=]\s*["\']([\s\S]{30,20000}?)["\']',
        r"NOTE_CONTENT\s*=\s*['\"]([\s\S]{30,20000}?)['\"]",
    ):
        m = re.search(pat, html, re.I)
        if m:
            raw = m.group(1)
            raw = raw.replace("\\n", "\n").replace("\\r", "")
            t = _sanitize_jbexport_description_text(raw.strip())
            if _jbexport_description_quality_ok(t):
                return t[:50000]
    return ""


def _jbexport_description_from_p_tags(soup: BeautifulSoup) -> str:
    ps = soup.find_all("p")
    chunks: List[str] = []
    for p in ps:
        txt = p.get_text(" ", strip=True)
        if len(txt) >= 35:
            chunks.append(txt)
    if not chunks:
        return ""
    chunks.sort(key=len, reverse=True)
    acc: List[str] = []
    total = 0
    for c in chunks[:14]:
        acc.append(c)
        total += len(c)
        if total >= 1200:
            break
    merged = "\n\n".join(acc)
    merged = _sanitize_jbexport_description_text(merged)
    if _jbexport_description_quality_ok(merged):
        return merged[:50000]
    return ""


def _description_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for step in (
        lambda: _jbexport_text_from_primary_regions(soup),
        lambda: _jbexport_description_from_labeled_cells(soup),
        lambda: _jbexport_description_from_note_script(html),
        lambda: _jbexport_description_from_p_tags(soup),
    ):
        t = step()
        if t:
            return t
    return ""


def parse_jbexport_detail(html: str) -> Dict[str, Any]:
    """
    상세 HTML 파싱.
    raw_status: 표의 진행상태 텍스트.
    """
    meta = _parse_meta_from_html(html)
    title = _title_from_html(html)
    description = _description_from_html(html)
    attachments = _attachments_from_html(html)
    raw_st = str(meta.get("status") or "").strip()

    return {
        "title": title,
        "organization": DEFAULT_ORG,
        "raw_status": raw_st,
        "receipt_start": str(meta.get("receipt_start") or "").strip(),
        "receipt_end": str(meta.get("receipt_end") or "").strip(),
        "biz_start": str(meta.get("biz_start") or "").strip(),
        "biz_end": str(meta.get("biz_end") or "").strip(),
        "description": description,
        "attachments": attachments,
    }


def _item_detail_url(item: dict) -> str:
    return str(
        item.get("url")
        or item.get("상세URL")
        or item.get("detail_url")
        or item.get("detailUrl")
        or ""
    ).strip()


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    return not str(v).strip()


def merge_detail_into_item(item: dict, detail_data: Dict[str, Any]) -> dict:
    """
    상세 파싱 결과를 item에 병합. 기존 값이 있으면 빈 칸만 보강.
    raw_status: 비어 있을 때만 상세 진행상태.
    display_status 는 단일 진입점 infer_status() 가 결정 — 여기서는 덮어쓰지 않음.
    """
    out = dict(item)
    url = _item_detail_url(out)
    dd = dict(detail_data)

    rs = str(dd.get("receipt_start") or "").strip()
    re_ = str(dd.get("receipt_end") or "").strip()
    bs = str(dd.get("biz_start") or "").strip()
    be = str(dd.get("biz_end") or "").strip()
    desc = str(dd.get("description") or "").strip()
    raw_st = str(dd.get("raw_status") or "").strip()
    title = str(dd.get("title") or "").strip()
    org = str(dd.get("organization") or DEFAULT_ORG).strip() or DEFAULT_ORG
    atts = dd.get("attachments")
    if not isinstance(atts, list):
        atts = []

    if title:
        old_t = out.get("title")
        old_kt = out.get("공고제목")
        if _is_empty(old_t) or _title_is_junk(old_t):
            out["title"] = title
        if _is_empty(old_kt) or _title_is_junk(old_kt):
            out["공고제목"] = title

    if org and _is_empty(out.get("organization")) and _is_empty(out.get("기관")):
        out["organization"] = org
        out["기관"] = org

    if raw_st and _is_empty(out.get("raw_status")):
        out["raw_status"] = raw_st

    if url:
        out["url"] = url
        out["상세URL"] = url

    # DB source가 bizinfo면 JB 상세 병합으로 출처 덮어쓰지 않음
    if str(out.get("source") or "").strip().lower() != "bizinfo":
        out["source"] = DEFAULT_SOURCE
        out["_source"] = "JBEXPORT"

    if rs and _is_empty(out.get("receipt_start")):
        out["receipt_start"] = rs
    if re_ and _is_empty(out.get("receipt_end")):
        out["receipt_end"] = re_
    if bs and _is_empty(out.get("biz_start")):
        out["biz_start"] = bs
    if be and _is_empty(out.get("biz_end")):
        out["biz_end"] = be

    if rs and _is_empty(out.get("start_date")):
        out["start_date"] = rs
    if re_ and _is_empty(out.get("end_date")):
        out["end_date"] = re_

    # 상세 HTML에서 온 본문: 파싱 결과로 덮어씀(빈 문자열이면 잡음 제거·미추출 반영)
    out["description"] = desc
    out["지원내용"] = desc

    if atts:
        out["attachments"] = atts

    if rs or re_:
        if rs and re_:
            out["기간"] = f"{rs} ~ {re_}"
        elif rs:
            out["기간"] = rs
        elif re_:
            out["기간"] = re_

    return out


def _is_jbexport_item(item: dict) -> bool:
    """DB·스냅샷 source=bizinfo 이면 URL이 jbexport여도 JB 파이프로 보내지 않음."""
    s = str(item.get("source") or item.get("_db_source_snapshot") or "").strip().lower()
    if s == "bizinfo":
        return False
    if s == "jbexport":
        return True
    site = str(item.get("site") or "").lower()
    src_blob = str(item.get("_source") or "").lower()
    u = str(item.get("url") or item.get("상세URL") or "").lower()
    return "jbexport" in src_blob or site == "jbexport" or "jbexport.or.kr" in u


def enrich_item_with_detail(
    item: dict,
    *,
    html: Optional[str] = None,
    detail_url: Optional[str] = None,
) -> dict:
    u = (detail_url or _item_detail_url(item)).strip()
    if not u:
        return dict(item)
    h = html if html is not None else fetch_jbexport_detail_html(u)
    if not h:
        return dict(item)
    detail = parse_jbexport_detail(h)
    return merge_detail_into_item(item, detail)


def enrich_jbexport_items(items: List[dict], delay_sec: float = 0.0) -> List[dict]:
    """JBEXPORT 항목만 상세 GET·파싱·병합. 요약 로그 출력."""
    total = 0
    parsed_receipt = 0
    parsed_biz = 0
    parsed_receipt_any = 0
    parsed_biz_any = 0
    parsed_attachments = 0
    description_filled = 0
    out: List[dict] = []
    sample_logged = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        if not _is_jbexport_item(item):
            out.append(dict(item))
            continue

        total += 1
        before = dict(item)
        enriched = enrich_item_with_detail(item)

        rs = str(enriched.get("receipt_start") or "").strip()
        re_ = str(enriched.get("receipt_end") or "").strip()
        if rs and re_:
            parsed_receipt += 1
        if rs or re_:
            parsed_receipt_any += 1

        bs = str(enriched.get("biz_start") or "").strip()
        be = str(enriched.get("biz_end") or "").strip()
        if bs and be:
            parsed_biz += 1
        if bs or be:
            parsed_biz_any += 1

        atts = enriched.get("attachments") or []
        if isinstance(atts, list) and len(atts) > 0:
            parsed_attachments += 1

        if str(enriched.get("description") or "").strip() and not str(
            before.get("description") or ""
        ).strip():
            description_filled += 1

        if sample_logged < 10:
            t = str(enriched.get("title") or enriched.get("공고제목") or "")[:70]
            print(f"[jbexport-enrich] title={t}", flush=True)
            print(
                f"[jbexport-enrich] receipt={rs}~{re_}",
                flush=True,
            )
            print(f"[jbexport-enrich] biz={bs}~{be}", flush=True)
            print(
                f"[jbexport-enrich] attachments={len(atts) if isinstance(atts, list) else 0}",
                flush=True,
            )
            sample_logged += 1

        out.append(enriched)
        if delay_sec > 0:
            time.sleep(delay_sec)

    print(f"[jbexport-enrich] total={total}", flush=True)
    print(f"[jbexport-enrich] parsed_receipt={parsed_receipt}", flush=True)
    print(f"[jbexport-enrich] parsed_receipt_any={parsed_receipt_any}", flush=True)
    print(f"[jbexport-enrich] parsed_biz={parsed_biz}", flush=True)
    print(f"[jbexport-enrich] parsed_biz_any={parsed_biz_any}", flush=True)
    print(f"[jbexport-enrich] parsed_attachments={parsed_attachments}", flush=True)
    print(f"[jbexport-enrich] description_filled={description_filled}", flush=True)
    return out


def enrich_items(items: List[dict], *, delay_sec: float = 0.0) -> List[dict]:
    """전체 목록에 대해 enrich (기존 호환). JBEXPORT만 실제 보강."""
    return enrich_jbexport_items(items, delay_sec=delay_sec)


def enrich_json_file(
    path: Path,
    *,
    delay_sec: float = 0.0,
    inplace: bool = True,
) -> Path:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else []
    enriched = enrich_jbexport_items(rows, delay_sec=delay_sec)
    out_path = path if inplace else path.with_name(path.stem + "_enriched.json")
    out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[jbexport_enrich] wrote {out_path} ({len(enriched)} items)", flush=True)
    return out_path


def _sqlite_row_to_enrich_item(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("attachments_json"):
        try:
            d["attachments"] = json.loads(str(d["attachments_json"]))
        except Exception:
            d["attachments"] = []
    return d


def _pick_str(newv: Any, oldv: Any) -> str:
    n = str(newv or "").strip()
    if n:
        return n
    return str(oldv or "").strip()


def _title_is_junk(title: str) -> bool:
    """title 이 spSeq=해시 형태 / 빈 문자열이면 True."""
    t = str(title or "").strip()
    if not t:
        return True
    # spSeq= 로 시작하거나 spSeq= 만 포함된 해시성 문자열
    if t.lower().startswith("spseq="):
        return True
    if "spseq=" in t.lower() and len(t) < 60:
        return True
    return False


def _merge_title(item_title: Any, enriched_title: Any) -> str:
    """
    기존 title 이 정상이면 유지, junk(spSeq=... / 빈값) 면 enriched 로 덮어씀.
    enriched 도 junk 면 기존 값 유지.
    """
    old = str(item_title or "").strip()
    new = str(enriched_title or "").strip()
    if _title_is_junk(old) and new and not _title_is_junk(new):
        return new
    return old


def _merge_row_for_db(item: dict, enriched: dict) -> Tuple[Any, ...]:
    rs = _pick_str(enriched.get("receipt_start"), item.get("receipt_start"))
    re_ = _pick_str(enriched.get("receipt_end"), item.get("receipt_end"))
    bs = _pick_str(enriched.get("biz_start"), item.get("biz_start"))
    be = _pick_str(enriched.get("biz_end"), item.get("biz_end"))
    desc = str(enriched.get("description") or "").strip()
    raw = _pick_str(enriched.get("raw_status"), item.get("raw_status"))
    atts = enriched.get("attachments") or item.get("attachments") or []
    if isinstance(item.get("attachments_json"), str) and not atts:
        try:
            atts = json.loads(item["attachments_json"])
        except Exception:
            atts = []
    if not isinstance(atts, list):
        atts = []
    aj = json.dumps(atts, ensure_ascii=False) if atts else ""
    sd = _pick_str(enriched.get("start_date"), item.get("start_date"))
    ed = _pick_str(enriched.get("end_date"), item.get("end_date"))
    title = _merge_title(item.get("title"), enriched.get("title"))
    return (rs, re_, bs, be, desc, raw, aj, sd, ed, title)


def enrich_jbexport_database(
    db_path: Optional[Path] = None,
    *,
    delay_sec: float = 0.0,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """
    biz.db 에서 source=jbexport 인 행만 상세 보강 후 UPDATE.
    """
    path = Path(db_path) if db_path else DB_PATH_DEFAULT
    if not path.exists():
        print(f"[jbexport-enrich] DB not found: {path}", flush=True)
        return {"updated": 0, "errors": 0}

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_biz_projects_extra_columns(conn)

    try:
        rows = conn.execute(
            """
            SELECT * FROM biz_projects
            WHERE LOWER(TRIM(COALESCE(source,''))) = 'jbexport'
               OR LOWER(COALESCE(url,'')) LIKE '%jbexport.or.kr%'
            """
        ).fetchall()
    except Exception as e:
        print(f"[jbexport-enrich] query failed: {e}", flush=True)
        conn.close()
        return {"updated": 0, "errors": 1}

    total = 0
    parsed_receipt = 0
    parsed_biz = 0
    parsed_attachments = 0
    description_filled = 0
    updated = 0
    errors = 0
    sample_n = 0

    n = 0
    for row in rows:
        if limit is not None and n >= limit:
            break
        n += 1
        item = _sqlite_row_to_enrich_item(row)
        if not _is_jbexport_item(item):
            continue
        total += 1
        try:
            enriched = enrich_item_with_detail(item)
        except Exception as e:
            print(f"[jbexport-enrich] enrich error id={item.get('id')}: {e}", flush=True)
            errors += 1
            continue

        if str(enriched.get("receipt_start") or "").strip() and str(
            enriched.get("receipt_end") or ""
        ).strip():
            if not str(item.get("receipt_start") or "").strip():
                parsed_receipt += 1
        if str(enriched.get("biz_start") or "").strip() and str(
            enriched.get("biz_end") or ""
        ).strip():
            if not str(item.get("biz_start") or "").strip():
                parsed_biz += 1
        atts = enriched.get("attachments") or []
        if isinstance(atts, list) and len(atts) > 0 and not str(
            item.get("attachments_json") or ""
        ).strip():
            parsed_attachments += 1
        if str(enriched.get("description") or "").strip() and not str(
            item.get("description") or ""
        ).strip():
            description_filled += 1

        if sample_n < 10:
            t = str(enriched.get("title") or "")[:70]
            rs = str(enriched.get("receipt_start") or "")
            re_ = str(enriched.get("receipt_end") or "")
            bs = str(enriched.get("biz_start") or "")
            be = str(enriched.get("biz_end") or "")
            print(f"[jbexport-enrich] title={t}", flush=True)
            print(f"[jbexport-enrich] receipt={rs}~{re_}", flush=True)
            print(f"[jbexport-enrich] biz={bs}~{be}", flush=True)
            print(
                f"[jbexport-enrich] attachments={len(atts) if isinstance(atts, list) else 0}",
                flush=True,
            )
            sample_n += 1

        rs, re_, bs, be, desc, raw, aj, sd, ed, title = _merge_row_for_db(
            item, enriched
        )
        eid = int(item["id"])
        try:
            conn.execute(
                """
                UPDATE biz_projects SET
                    title = ?,
                    receipt_start = ?,
                    receipt_end = ?,
                    biz_start = ?,
                    biz_end = ?,
                    description = ?,
                    raw_status = ?,
                    attachments_json = ?,
                    start_date = ?,
                    end_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, rs, re_, bs, be, desc, raw, aj, sd, ed, eid),
            )
            updated += 1
        except Exception as e:
            print(f"[jbexport-enrich] UPDATE failed id={eid}: {e}", flush=True)
            errors += 1

        if delay_sec > 0:
            time.sleep(delay_sec)

    try:
        from pipeline.mirror_projects import mirror_biz_projects_to_projects

        mirror_biz_projects_to_projects(conn)
    except Exception as e:
        print(f"[jbexport-enrich] mirror_projects: {e}", flush=True)

    conn.commit()
    conn.close()

    print(f"[jbexport-enrich] total={total}", flush=True)
    print(f"[jbexport-enrich] parsed_receipt={parsed_receipt}", flush=True)
    print(f"[jbexport-enrich] parsed_biz={parsed_biz}", flush=True)
    print(f"[jbexport-enrich] parsed_attachments={parsed_attachments}", flush=True)
    print(f"[jbexport-enrich] description_filled={description_filled}", flush=True)
    print(f"[jbexport-enrich] rows_updated={updated} errors={errors}", flush=True)
    return {
        "total": total,
        "parsed_receipt": parsed_receipt,
        "parsed_biz": parsed_biz,
        "parsed_attachments": parsed_attachments,
        "description_filled": description_filled,
        "updated": updated,
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="JBEXPORT JSON 또는 DB 상세 보강")
    ap.add_argument(
        "--db",
        action="store_true",
        help="biz.db 의 jbexport 행만 보강",
    )
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("json_path", nargs="?", type=Path, default=None)
    args = ap.parse_args()
    if args.db:
        enrich_jbexport_database(delay_sec=args.delay, limit=args.limit)
    else:
        p = args.json_path
        if not p or not p.exists():
            raise SystemExit("usage: python -m pipeline.jbexport_enrich [--db] [json_path] [--delay N]")
        enrich_json_file(p, delay_sec=args.delay)
