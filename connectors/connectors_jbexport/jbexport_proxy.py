# -*- coding: utf-8 -*-
"""jbexport Flask 프록시 — getWork1Search.do 를 서버에서 호출해 CORS 회피."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
import urllib3
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request

# 동작 확인용: jbexport HTTPS 인증서 체인 문제 시 SSL 검증 생략 (운영에서는 verify=True 권장)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
PROXY_BUILD = "ssl-verify-false-20250321"
BOOT_TS = int(time.time())
print("[SSL verify disabled for jbexport test]", flush=True)
print(f"[jbexport_proxy build={PROXY_BUILD} pid={os.getpid()} boot={BOOT_TS}]", flush=True)

DEFAULT_VIEW_URL = os.environ.get(
    "JBEXPORT_VIEW_URL",
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/view1.do"
    "?menuUUID=402880867c8174de017c819251e70009",
)
UPSTREAM_REFERER = "https://www.jbexport.or.kr/index.do?menuUUID=402880867c8174de017c81903f270000"
JBEXPORT_LIST_PAGE_URL = "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/getWork1Search.do"
# 상세 upstream Referer 고정(브라우저 목록 흐름과 맞춤). 필요 시 JBEXPORT_DETAIL_REFERER 환경변수로 재정의.
JBEXPORT_DETAIL_REFERER = os.environ.get(
    "JBEXPORT_DETAIL_REFERER",
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/spWorkSupportBusinessList.do",
)
# detail1.do 경로 산출용 기준 URL(항상 view1.do 기준 — detail/view 혼용 방지)
JBEXPORT_DETAIL_PATH_BASE_URL = os.environ.get(
    "JBEXPORT_DETAIL_PATH_BASE_URL",
    "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/view1.do"
    "?menuUUID=402880867c8174de017c819251e70009",
)
# 세션 워밍: 목록 HTML(쿠키) 선획득
JBEXPORT_LIST_WARM_URL = os.environ.get("JBEXPORT_LIST_WARM_URL", DEFAULT_VIEW_URL)
DEFAULT_MENU_UUID = os.environ.get("JBEXPORT_MENU_UUID", "402880867c8174de017c819251e70009")
JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT = os.environ.get("JBEXPORT_PATHNUM", "6")

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
)

app = Flask(__name__)
ATTACH_NAME_CACHE: Dict[str, str] = {}

# #region agent log
_DEBUG_LOG_PATH = Path(__file__).resolve().parent / "debug-15fb3d.log"


def _agent_log(location: str, message: str, data: dict, hypothesis_id: str = "") -> None:
    try:
        line = (
            json.dumps(
                {
                    "sessionId": "15fb3d",
                    "timestamp": int(time.time() * 1000),
                    "location": location,
                    "message": message,
                    "data": data,
                    "hypothesisId": hypothesis_id,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# #endregion


def _session_cookies_snapshot(sess: requests.Session) -> Dict[str, str]:
    return {c.name: c.value for c in sess.cookies}


def _menu_uuid_from_url(url: str) -> str:
    try:
        q = parse_qs(urlparse(url).query, keep_blank_values=True)
        for key in ("menuUUID", "menuuuid"):
            if key in q and q[key]:
                v = (q[key][0] or "").strip()
                if v:
                    return v
        return ""
    except Exception:
        return ""


@app.after_request
def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
    return resp


@app.route("/api/jbexport/list", methods=["OPTIONS"])
def api_jbexport_list_options() -> Any:
    return ("", 204)


def _debug_ndjson_append(payload: Dict[str, Any]) -> None:
    """세션 15fb3d: 브라우저 요청이 프록시에 도달했는지 워크스페이스 NDJSON으로 남김."""
    try:
        p = Path(__file__).resolve().parent / "debug-15fb3d.log"
        line = {
            "sessionId": "15fb3d",
            "timestamp": int(time.time() * 1000),
            **payload,
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _js_unescape(s: str) -> str:
    try:
        return bytes(s, "utf-8").decode("unicode_escape")
    except Exception:
        return s


def _extract_js_field(html: str, key: str) -> str:
    # key: NOTE_CONTENT / NOTE_TITLE ...
    patterns = [
        rf'\b{re.escape(key)}\b\s*[:=]\s*"((?:\\.|[^"\\])*)"',
        rf"\b{re.escape(key)}\b\s*[:=]\s*'((?:\\.|[^'\\])*)'",
        rf"\b{re.escape(key)}\b\s*[:=]\s*`([\s\S]*?)`",
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            return _js_unescape(m.group(1)).strip()
    return ""


def _extract_after_keyword(text: str, key: str) -> str:
    if not text:
        return ""
    m = re.search(rf"{re.escape(key)}\s*[:：]?\s*([^\n\r]{{2,300}})", text, flags=re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _looks_like_noise_text(s: str) -> bool:
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    if not t:
        return True
    if "x-ua-compatible" in t.lower() or "ie=edge" in t.lower():
        return True
    if "<script" in t.lower() or "</script" in t.lower():
        return True
    if re.search(r"\b(content=|charset=|http-equiv=)\b", t, flags=re.I):
        return True
    if re.search(r"\+\s*v\.[A-Z0-9_]+\s*\+", t):
        return True
    if _has_script_keywords(t):
        return True
    return False


SCRIPTY_KEYWORDS = [
    "function",
    "alert(",
    "location.href",
    "var ",
    "return ",
    "menuuuid",
    "script",
]


def _has_script_keywords(text: str) -> bool:
    low = str(text or "").lower()
    return any(k in low for k in SCRIPTY_KEYWORDS)


def _top_longest_div_texts(html: str, top_k: int = 10) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    divs = soup.find_all("div")
    scored: list[tuple[int, str, int]] = []
    for idx, d in enumerate(divs):
        txt = d.get_text(" ", strip=True)
        if not txt:
            continue
        scored.append((len(txt), txt, idx))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for rank, (ln, txt, idx) in enumerate(scored[: max(1, top_k)], 1):
        out.append(
            {
                "rank": rank,
                "index": idx,
                "text_len": ln,
                "has_script_keywords": _has_script_keywords(txt),
                "preview200": re.sub(r"\s+", " ", txt).strip()[:200],
            }
        )
    return out


def _select_best_longest_div(html: str, min_len: int = 120) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    divs = soup.find_all("div")
    scored: list[tuple[int, str]] = []
    for d in divs:
        txt = d.get_text(" ", strip=True)
        if not txt:
            continue
        t = re.sub(r"\s+", " ", txt).strip()
        scored.append((len(t), t))
    scored.sort(key=lambda x: x[0], reverse=True)
    # Observation-first: 상위 10개 후보에서 스크립트성 div 제외 후 최장 선택
    for ln, t in scored[:10]:
        if ln < min_len:
            break
        if _looks_like_noise_text(t):
            continue
        if _has_script_keywords(t):
            continue
        return t
    return ""


def _build_jbexport_download_url(path_num: str, file_uuid: str) -> str:
    pn = (path_num or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT).strip() or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT
    uid = (file_uuid or "").strip()
    return "https://www.jbexport.or.kr/downloadFile.do?" + urlencode({"pathNum": pn, "fileUUID": uid})


def _parse_downloadfile_params(abs_url: str) -> Tuple[str, str] | None:
    low = (abs_url or "").lower()
    if "downloadfile.do" not in low and "fileuuid" not in low:
        return None
    q = parse_qs(urlparse(abs_url).query, keep_blank_values=True)
    uid = (q.get("fileUUID") or q.get("fileuuid") or [""])[0].strip()
    if not uid:
        return None
    pn = (q.get("pathNum") or q.get("pathnum") or [JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT])[0].strip()
    return (pn or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, uid)


def _filename_suggestion_from_text(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"[\w\-–—.· 가-힣()]+\.(pdf|hwp|hwpx|xlsx|xls|docx?|zip|pptx?)\b",
        str(text),
        re.I,
    )
    return (m.group(0) or "").strip() if m else ""


def _tag_attachment_name(tag: Any) -> str:
    for attr in ("title", "data-filename", "data-orgfilename", "aria-label"):
        v = str(tag.get(attr) or "").strip()
        hit = _filename_suggestion_from_text(v)
        if hit:
            return hit
        if v and len(v) < 512:
            if re.search(r"\.(pdf|hwp|hwpx|xlsx|xls|docx?|zip|pptx?)\b", v, re.I):
                return v
    t = tag.get_text(" ", strip=True)
    hit = _filename_suggestion_from_text(t)
    if hit:
        return hit
    parent = getattr(tag, "parent", None)
    if parent is not None:
        pt = parent.get_text(" ", strip=True)
        hit = _filename_suggestion_from_text(pt)
        if hit:
            return hit
    return (t or "").strip()


def _safe_saved_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())


def _looks_like_jbexport_file_uuid(token: str) -> bool:
    """fn_fileDown 인자로 올 법한 토큰(32hex·하이픈 UUID 등). 스크립트 매개변수명(fileKey) 제외."""
    t = (token or "").strip()
    if len(t) < 16:
        return False
    if t.lower() in ("filekey", "e", "code", "uuid", "file_uuid"):
        return False
    if t.startswith("#"):
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F\-]{16,}", t))


def extract_attachments_onclick_tags(soup: BeautifulSoup) -> list[dict[str, str]]:
    """parse_and_download 용: 태그 onclick 속성만 스캔(netevViewBtn / neteViewBtn / fn_fileDown). (fileUUID, pathNum) 중복 제거."""
    attachments: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def try_add(file_uuid: str, path_num: str, name: str) -> None:
        uid = (file_uuid or "").strip()
        pn = (path_num or "").strip() or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT
        if not uid:
            return
        key = (uid, pn)
        if key in seen:
            return
        seen.add(key)
        nm = (name or "").strip()
        du = _build_jbexport_download_url(pn, uid)
        attachments.append(
            {
                "fileUUID": uid,
                "pathNum": pn,
                "name": nm if nm else f"{uid}.bin",
                "download_url": du,
            }
        )

    for tag in soup.find_all(onclick=True):
        onclick = str(tag.get("onclick") or "")
        text = (tag.get_text(strip=True) or "").strip()
        m = re.search(r"netevViewBtn\(\s*'([^']+)'\s*,\s*'(\d+)'\s*\)", onclick, re.I)
        if not m:
            m = re.search(r"neteViewBtn\(\s*'([^']+)'\s*,\s*'(\d+)'\s*\)", onclick, re.I)
        if m:
            try_add(m.group(1), m.group(2), text)
            continue
        m = re.search(r'netevViewBtn\(\s*"([^"]+)"\s*,\s*"(\d+)"\s*\)', onclick, re.I)
        if not m:
            m = re.search(r'neteViewBtn\(\s*"([^"]+)"\s*,\s*"(\d+)"\s*\)', onclick, re.I)
        if m:
            try_add(m.group(1), m.group(2), text)
            continue
        m = re.search(r"fn_fileDown\(\s*'([^']+)'\s*\)", onclick, re.I)
        if not m:
            m = re.search(r'fn_fileDown\(\s*"([^"]+)"\s*\)', onclick, re.I)
        if m:
            try_add(m.group(1), JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, text)

    return attachments


def extract_attachment_records(soup: BeautifulSoup, html: str) -> list[dict[str, str]]:
    """detail HTML에서 첨부 후보를 {fileUUID, pathNum, name, download_url} 형태로 수집."""
    seen_keys: set[str] = set()
    out: list[dict[str, str]] = []

    def add_record(path_num: str, file_uuid: str, name: str, download_url: str) -> None:
        download_url = (download_url or "").strip()
        if not download_url:
            return
        key = re.sub(r"\s+", "", download_url.lower())
        if key in seen_keys:
            return
        seen_keys.add(key)
        nm = (name or "").strip()
        if not nm:
            nm = _filename_suggestion_from_text(download_url) or ""
        pn = (path_num or "").strip()
        if "downloadfile.do" in download_url.lower() and not pn:
            pn = JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT
        rec = {
            "fileUUID": (file_uuid or "").strip(),
            "pathNum": pn,
            "name": nm,
            "download_url": download_url,
        }
        out.append(rec)
        if nm:
            ATTACH_NAME_CACHE[download_url] = nm

    # --- <a href> ---
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_u = urljoin("https://www.jbexport.or.kr/", href)
        low = abs_u.lower()
        if "downloadfile.do" in low or "fileuuid" in low:
            pr = _parse_downloadfile_params(abs_u)
            if pr:
                pn, uid = pr
                add_record(pn, uid, _tag_attachment_name(a), _build_jbexport_download_url(pn, uid))
            continue
        if "filedown.do" in low and "fileseq" in low:
            q = parse_qs(urlparse(abs_u).query, keep_blank_values=True)
            seq = (q.get("fileSeq") or q.get("fileseq") or [""])[0].strip()
            if seq:
                add_record("", seq, _tag_attachment_name(a), abs_u.split("#")[0])

    # --- onclick (태그 속성) ---
    for tag in soup.find_all(onclick=True):
        onclick = str(tag.get("onclick") or "")
        # fn_fileDown('fileUUID') — 실제 첨부는 class="file_txt" 인 <a> 에서 주로 등장
        for m in re.finditer(r"fn_fileDown\s*\(\s*['\"]([^'\"]+)['\"]", onclick, re.I):
            uid = (m.group(1) or "").strip()
            if uid and _looks_like_jbexport_file_uuid(uid):
                add_record(
                    JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT,
                    uid,
                    _tag_attachment_name(tag),
                    _build_jbexport_download_url(JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, uid),
                )
        # neteViewBtn(…): 쪽지 팝업용(스크립트 내 템플릿). 첨부 fileUUID 와 혼동되므로 다운로드 후보에 넣지 않음.

    # --- 원시 HTML: 스크립트·동적 삽입 내 패턴 ---
    src = html or ""
    for m in re.finditer(r"fn_fileDown\s*\(\s*['\"]([^'\"]+)['\"]", src, re.I):
        uid = (m.group(1) or "").strip()
        if uid and _looks_like_jbexport_file_uuid(uid):
            chunk = src[max(0, m.start() - 500) : m.end() + 500]
            nm = _filename_suggestion_from_text(chunk) or ""
            add_record(
                JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT,
                uid,
                nm,
                _build_jbexport_download_url(JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, uid),
            )
    for m in re.finditer(r"['\"](/downloadFile\.do\?[^'\"]+)['\"]", src, re.I):
        abs_u = urljoin("https://www.jbexport.or.kr/", m.group(1))
        pr = _parse_downloadfile_params(abs_u)
        if pr:
            pn, uid = pr
            chunk = src[max(0, m.start() - 400) : m.end() + 400]
            add_record(pn, uid, _filename_suggestion_from_text(chunk) or "", _build_jbexport_download_url(pn, uid))

    # --- HTML/인라인 스크립트·JSON 속 fileUUID 리터럴 ---
    for m in re.finditer(
        r"fileUUID\s*=\s*['\"]?([0-9a-fA-F\-]{16,})['\"]?", src, re.I
    ):
        uid = (m.group(1) or "").strip()
        if uid:
            chunk = src[max(0, m.start() - 600) : m.end() + 600]
            add_record(
                JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT,
                uid,
                _filename_suggestion_from_text(chunk) or "",
                _build_jbexport_download_url(JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, uid),
            )
    for m in re.finditer(
        r'["\']fileUUID["\']\s*:\s*["\']([0-9a-fA-F\-]{16,})["\']',
        src,
        re.I,
    ):
        uid = (m.group(1) or "").strip()
        if uid:
            chunk = src[max(0, m.start() - 600) : m.end() + 600]
            add_record(
                JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT,
                uid,
                _filename_suggestion_from_text(chunk) or "",
                _build_jbexport_download_url(JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT, uid),
            )

    return out


def _extract_attachments_from_soup(soup: BeautifulSoup, html: str = "") -> list[dict[str, str]]:
    recs = extract_attachment_records(soup, html or "")
    return [{"파일명": r["name"], "파일URL": r["download_url"]} for r in recs]


def _extract_js_endpoints(html: str) -> list[str]:
    src = str(html or "")
    found = set()
    patterns = [
        r"\$\.ajax\(\s*\{[\s\S]*?url\s*:\s*['\"]([^'\"]+)['\"]",
        r"\$\.post\(\s*['\"]([^'\"]+)['\"]",
        r"fetch\(\s*['\"]([^'\"]+)['\"]",
    ]
    for pat in patterns:
        for m in re.finditer(pat, src, flags=re.I):
            u = (m.group(1) or "").strip()
            if u:
                found.add(u)
    # JS 내 일반 .do 경로도 보조 수집
    for m in re.finditer(r"['\"](/[^'\"]+?\.do(?:\?[^'\"]*)?)['\"]", src, flags=re.I):
        u = (m.group(1) or "").strip()
        if u:
            found.add(u)
    return sorted(found)


def _extract_attachment_records_from_json(payload: Any) -> list[dict[str, str]]:
    raw: list[dict[str, str]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            low_map = {str(k).lower(): v for k, v in x.items()}
            file_uuid = (
                low_map.get("fileuuid")
                or low_map.get("file_uuid")
                or low_map.get("filekey")
                or low_map.get("uuid")
            )
            file_seq = low_map.get("fileseq") or low_map.get("file_seq")
            path_num = (
                low_map.get("pathnum")
                or low_map.get("path_num")
                or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT
            )
            file_name = (
                low_map.get("filename")
                or low_map.get("file_name")
                or low_map.get("orgfilename")
                or low_map.get("originalfilename")
                or low_map.get("name")
                or ""
            )
            if file_uuid:
                uid = str(file_uuid).strip()
                pn = str(path_num or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT).strip() or JBEXPORT_DOWNLOAD_PATHNUM_DEFAULT
                if uid:
                    du = _build_jbexport_download_url(pn, uid)
                    raw.append(
                        {
                            "fileUUID": uid,
                            "pathNum": pn,
                            "name": str(file_name or "").strip(),
                            "download_url": du,
                        }
                    )
            elif file_seq:
                seq = str(file_seq).strip()
                if seq:
                    du = "https://www.jbexport.or.kr/common/file/fileDown.do?" + urlencode({"fileSeq": seq})
                    raw.append(
                        {
                            "fileUUID": "",
                            "pathNum": "",
                            "name": str(file_name or "").strip(),
                            "download_url": du,
                        }
                    )
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    seen: set[str] = set()
    dedup: list[dict[str, str]] = []
    for it in raw:
        u = str(it.get("download_url") or "")
        if not u or u in seen:
            continue
        seen.add(u)
        dedup.append(it)
        nm = str(it.get("name") or "")
        if nm:
            ATTACH_NAME_CACHE[u] = nm
    return dedup


def _extract_attachments_from_json_payload(payload: Any) -> list[dict[str, str]]:
    recs = _extract_attachment_records_from_json(payload)
    return [{"파일명": r["name"], "파일URL": r["download_url"]} for r in recs]


def parse_detail_content(detail_url: str, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n", strip=True) if soup else ""
    note_title = _extract_js_field(html, "NOTE_TITLE")
    note_content = _extract_js_field(html, "NOTE_CONTENT")
    support_content = _extract_after_keyword(text, "지원내용")
    apply_method = _extract_after_keyword(text, "신청방법")
    support_scale = _extract_after_keyword(text, "지원규모")
    if note_content:
        support_content = support_content or note_content
    # Observation-first fallback: div 중 가장 긴 텍스트를 본문 후보로 사용
    if not support_content or len(support_content.strip()) < 30 or _looks_like_noise_text(support_content):
        best = _select_best_longest_div(html)
        if best:
            support_content = best
    attachments = _extract_attachments_from_soup(soup, html)
    return {
        "상세URL": detail_url or "",
        "지원내용": support_content or "",
        "신청방법": apply_method or "",
        "지원규모": support_scale or "",
        "첨부파일": attachments,
        "_debug": {
            "NOTE_TITLE": note_title,
            "NOTE_CONTENT_len": len(note_content or ""),
            "text_len": len(text or ""),
            "support_len": len(support_content or ""),
            "attach_count": len(attachments),
        },
    }


def get_jbexport_session() -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers.update(dict(SESSION.headers))
    print("[JBEXPORT] session created", flush=True)
    warm_headers = {
        "Referer": UPSTREAM_REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        _ = s.get(JBEXPORT_LIST_WARM_URL, headers=warm_headers, timeout=90, verify=False)
    except Exception:
        pass
    print("[JBEXPORT] list page requested", flush=True)
    return s


def parse_jbexport_detail(session: requests.Session, detail_url: str) -> Dict[str, Any]:
    headers = {
        "Referer": JBEXPORT_DETAIL_REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
    }
    print("[JBEXPORT] detail page requested", flush=True)
    r = session.get(detail_url, headers=headers, timeout=90, verify=False)
    r.raise_for_status()
    html = r.text or ""

    soup = BeautifulSoup(html, "html.parser")
    records = extract_attachments_onclick_tags(soup)
    if not records:
        records = extract_attachment_records(soup, html)
    endpoints = _extract_js_endpoints(html)
    if not records:
        for ep in endpoints:
            low = ep.lower()
            if not any(k in low for k in ["file", "attach", "download", "atch"]):
                continue
            api_url = urljoin("https://www.jbexport.or.kr", ep)
            if "downloadfile.do" in low and "fileuuid=" in low:
                pq = parse_qs(urlparse(api_url).query, keep_blank_values=True)
                if not (pq.get("fileUUID") or pq.get("fileuuid") or [""])[0].strip():
                    continue
            try:
                rr = session.get(
                    api_url,
                    headers={
                        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                        "Referer": detail_url,
                        "Accept": "*/*",
                    },
                    timeout=90,
                    verify=False,
                )
                if rr.status_code >= 400:
                    continue
                ct = (rr.headers.get("content-type") or "").lower()
                if "json" in ct:
                    payload = rr.json()
                    dyn_recs = _extract_attachment_records_from_json(payload)
                    if dyn_recs:
                        records = dyn_recs
                        break
            except Exception:
                continue
    print(f"[JBEXPORT] attachment candidates found: {len(records)}", flush=True)

    parsed = parse_detail_content(detail_url, html)
    parsed["첨부파일"] = [{"파일명": x["name"], "파일URL": x["download_url"]} for x in records]
    attachments = parsed["첨부파일"]

    title = ""
    m_title = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, flags=re.I)
    if m_title:
        title = re.sub(r"\s+", " ", m_title.group(1)).strip()
    period = _extract_after_keyword(re.sub(r"<[^>]+>", " ", html), "접수기간")
    status = "접수중" if re.search(r"접수중|신청\s*중", html) else ("접수마감" if re.search(r"마감|종료", html) else "")
    return {
        "title": title,
        "organization": "전북수출통합지원시스템",
        "status": status,
        "period": period or "",
        "detail_url": detail_url,
        "content": str(parsed.get("지원내용") or ""),
        "apply_method": str(parsed.get("신청방법") or ""),
        "support_scale": str(parsed.get("지원규모") or ""),
        "attachments": [
            {"name": str(x.get("파일명") or ""), "url": str(x.get("파일URL") or "")}
            for x in attachments
        ],
    }


def debug_parse_detail(url: str) -> Dict[str, Any]:
    """단일 상세 URL 디버그: HTML 저장 + 추출 결과 출력 + 누락 키 출력."""
    headers = {
        "Referer": DEFAULT_VIEW_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    r = SESSION.get(url, headers=headers, timeout=90, verify=False)
    html = r.text
    out_path = Path(__file__).resolve().parent / "detail_debug.html"
    out_path.write_text(html, encoding="utf-8")
    result = parse_detail_content(url, html)
    src = html or ""
    missing = []
    for k in ["NOTE_TITLE", "NOTE_CONTENT", "ATTACH", "file", "신청방법", "지원내용"]:
        if k.lower() not in src.lower():
            missing.append(k)
    print(f"[debug_parse_detail] saved: {out_path}", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if missing:
        print(f"[debug_parse_detail] missing keys: {', '.join(missing)}", flush=True)
    else:
        print("[debug_parse_detail] all requested keys found", flush=True)
    return result


def debug_detail_structure(url: str) -> Dict[str, Any]:
    """상세 페이지 구조 디버그 (본문 위치 파악용).

    1) HTML 전체를 detail_debug.html 로 저장
    2) iframe 태그 존재 여부/개수 + src 출력 (있으면 iframe src도 재요청 후 iframe_debug.html 저장)
    3) script 태그 개수 출력
    4) script 텍스트에서 NOTE/CONTENT/file 키워드 존재 여부 출력
    5) 본문으로 보이는 '긴 텍스트 div' 후보 탐색(텍스트 길이 기준) + 상위 몇 개 미리보기 출력
    """
    headers = {
        "Referer": DEFAULT_VIEW_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    r = SESSION.get(url, headers=headers, timeout=90, verify=False)
    html = r.text or ""
    out_path = Path(__file__).resolve().parent / "detail_debug.html"
    out_path.write_text(html, encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")

    iframes = soup.find_all("iframe")
    iframe_srcs = []
    for f in iframes:
        src = (f.get("src") or "").strip()
        if src:
            iframe_srcs.append(src)

    scripts = soup.find_all("script")
    script_texts = []
    for s in scripts:
        t = s.string if s and s.string is not None else s.get_text("", strip=False) if s else ""
        if t:
            script_texts.append(t)
    script_blob = "\n".join(script_texts)

    kw = {
        "NOTE": bool(re.search(r"\bNOTE\b|NOTE_TITLE|NOTE_CONTENT|NOTE_CN|NOTE_NM", script_blob, re.I)),
        "CONTENT": bool(re.search(r"\bCONTENT\b|NOTE_CONTENT|NOTE_CN", script_blob, re.I)),
        "file": bool(re.search(r"fileList|attach|file|download|atch", script_blob, re.I)),
    }

    # 긴 텍스트 div 후보(텍스트 길이 기준)
    div_candidates = []
    for el in soup.find_all(["div", "td", "pre", "article", "section"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if len(txt) >= 300:
            div_candidates.append((len(txt), txt[:300], el.name, (el.get("id") or ""), " ".join(el.get("class") or [])))
    div_candidates.sort(key=lambda x: x[0], reverse=True)

    # iframe src가 상대경로면 절대경로화
    abs_iframe = []
    for src in iframe_srcs:
        try:
            abs_iframe.append(urlparse(url)._replace(path=urlparse(src).path).geturl())
        except Exception:
            abs_iframe.append(src)

    iframe_fetch = None
    iframe_saved = None
    if iframe_srcs:
        # 첫 iframe만 우선 재요청
        first = iframe_srcs[0]
        try:
            base = urlparse(url)
            if first.startswith("/"):
                iframe_url = f"{base.scheme}://{base.netloc}{first}"
            elif first.startswith("http://") or first.startswith("https://"):
                iframe_url = first
            else:
                iframe_url = f"{base.scheme}://{base.netloc}/{first.lstrip('/')}"
            rr = SESSION.get(iframe_url, headers=headers, timeout=90, verify=False)
            iframe_fetch = {"url": iframe_url, "status": rr.status_code, "len": len(rr.text or "")}
            iframe_out = Path(__file__).resolve().parent / "iframe_debug.html"
            iframe_out.write_text(rr.text or "", encoding="utf-8")
            iframe_saved = str(iframe_out)
        except Exception as e:
            iframe_fetch = {"error": str(e)}

    result = {
        "url": url,
        "status": r.status_code,
        "saved_html": str(out_path),
        "iframe_count": len(iframes),
        "iframe_srcs": iframe_srcs[:10],
        "scripts_count": len(scripts),
        "script_keywords": kw,
        "long_blocks_top5": [
            {
                "len": c[0],
                "tag": c[2],
                "id": c[3],
                "class": c[4],
                "preview300": c[1],
            }
            for c in div_candidates[:5]
        ],
        "iframe_fetch": iframe_fetch,
        "iframe_saved_html": iframe_saved,
    }

    print(f"[debug_detail_structure] saved: {out_path}", flush=True)
    if iframe_saved:
        print(f"[debug_detail_structure] iframe saved: {iframe_saved}", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.debug_detail_structure",
            "message": "detail structure debug",
            "data": result,
            "hypothesisId": "H7",
        }
    )
    return result


def debug_longest_div(detail_url: str) -> Dict[str, Any]:
    """Observation-first: div 텍스트 길이 기반으로 본문 위치/후보를 디버깅."""
    headers = {
        "Referer": DEFAULT_VIEW_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    r = SESSION.get(detail_url, headers=headers, timeout=90, verify=False)
    html = r.text or ""
    out_path = Path(__file__).resolve().parent / "detail_debug.html"
    out_path.write_text(html, encoding="utf-8")

    top5 = _top_longest_div_texts(html, top_k=5)
    best = _select_best_longest_div(html)
    best_preview = re.sub(r"\s+", " ", best).strip()[:200]

    result = {
        "detail_url": detail_url,
        "status": r.status_code,
        "saved_html": str(out_path),
        "top5": top5,
        "selected": {
            "text_len": len(best or ""),
            "preview200": best_preview,
            "is_noise": _looks_like_noise_text(best),
        },
    }
    print(f"[debug_longest_div] saved: {out_path}", flush=True)
    for c in top5:
        print(
            f"[candidate] rank={c['rank']} index={c['index']} len={c['text_len']} preview={c['preview200']}",
            flush=True,
        )
    print(
        f"[selected] len={result['selected']['text_len']} noise={result['selected']['is_noise']} preview={best_preview}",
        flush=True,
    )
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.debug_longest_div",
            "message": "longest div candidates",
            "data": result,
            "hypothesisId": "H8",
        }
    )
    return result


def debug_div_candidates(detail_url: str) -> Dict[str, Any]:
    """요청사항 전용 디버그: div 상위 10개 + script 키워드 포함 여부 + 최종 선택."""
    headers = {
        "Referer": DEFAULT_VIEW_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    r = SESSION.get(detail_url, headers=headers, timeout=90, verify=False)
    html = r.text or ""
    out_path = Path(__file__).resolve().parent / "detail_debug.html"
    out_path.write_text(html, encoding="utf-8")

    top10 = _top_longest_div_texts(html, top_k=10)
    best = _select_best_longest_div(html)
    best_preview = re.sub(r"\s+", " ", best).strip()[:200]
    result = {
        "detail_url": detail_url,
        "status": r.status_code,
        "saved_html": str(out_path),
        "candidates_top10": top10,
        "selected": {
            "text_len": len(best or ""),
            "has_script_keywords": _has_script_keywords(best),
            "preview200": best_preview,
        },
    }
    print(f"[debug_div_candidates] saved: {out_path}", flush=True)
    for c in top10:
        print(
            f"[candidate] index={c['index']} len={c['text_len']} scripty={c['has_script_keywords']} preview={c['preview200']}",
            flush=True,
        )
    print(
        f"[selected] len={result['selected']['text_len']} scripty={result['selected']['has_script_keywords']} preview={best_preview}",
        flush=True,
    )
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.debug_div_candidates",
            "message": "div candidates debug",
            "data": result,
            "hypothesisId": "H9",
        }
    )
    return result


def debug_attachment_links(detail_url: str) -> list[dict[str, str]]:
    """1단계: 상세 HTML에서 첨부파일 링크만 추출해서 출력(다운로드는 하지 않음)."""
    raw_url = str(detail_url or "").strip()
    if not raw_url:
        raise ValueError("detail_url 이 비어 있습니다. detail1.do 전체 URL 또는 spSeq 값을 전달하세요.")
    if raw_url == "상세URL":
        raise ValueError(
            "detail_url 에 예시 문자열 '상세URL'이 전달되었습니다. 실제 detail1.do URL을 넣어주세요."
        )
    # spSeq만 넣어도 테스트할 수 있게 URL 자동 조합
    if "://" not in raw_url and re.fullmatch(r"[0-9a-fA-F]{24,64}", raw_url):
        raw_url = (
            "https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do"
            f"?menuUUID=402880867c8174de017c819251e70009&spSeq={raw_url}"
        )
    if not re.match(r"^https?://", raw_url, flags=re.I):
        raise ValueError(
            f"유효하지 않은 detail_url: {raw_url}. http(s):// 로 시작하는 URL 또는 spSeq를 전달하세요."
        )

    headers = {
        "Referer": DEFAULT_VIEW_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    r = SESSION.get(raw_url, headers=headers, timeout=90, verify=False)
    html_text = r.text or ""
    print("[debug_attachment_links] html preview:", html_text[:200], flush=True)
    debug_path = Path(os.getcwd()) / "detail_debug.html"
    with open(debug_path, "wb") as f:
        f.write(r.content or b"")
    html_len = len(r.content or b"")
    file_size = os.path.getsize(debug_path)
    soup = BeautifulSoup(html_text, "html.parser")
    out = _extract_attachments_from_soup(soup, html_text)
    print(f"[debug_attachment_links] html length: {html_len}", flush=True)
    print(f"[debug_attachment_links] saved html: {debug_path}", flush=True)
    print(f"[debug_attachment_links] file size: {file_size} bytes", flush=True)
    for x in out:
        print(f"[ATTACH] {x['파일명']}", flush=True)
        print(f"[ATTACH URL] {x['파일URL']}", flush=True)
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.debug_attachment_links",
            "message": "attachment links extracted",
            "data": {
                "detail_url": detail_url,
                "resolved_url": raw_url,
                "html_length": html_len,
                "file_size": file_size,
                "count": len(out),
                "items": out[:20],
            },
            "hypothesisId": "H11",
        }
    )
    return out


def download_file(session: requests.Session, detail_url: str, file_url: str, save_dir: str = "downloads") -> str:
    """첨부파일 1개 다운로드(세션 쿠키 포함).

    순서:
    1) detail_url 선접속으로 쿠키 획득
    2) 동일 SESSION으로 file_url 다운로드
    3) downloads/파일명 저장 + 크기 출력
    """
    folder = Path(save_dir)
    folder.mkdir(parents=True, exist_ok=True)

    file_name = ATTACH_NAME_CACHE.get(str(file_url).strip(), "")
    if not file_name:
        try:
            file_name = urlparse(file_url).path.rsplit("/", 1)[-1]
        except Exception:
            file_name = ""
    if not file_name:
        file_name = "download.bin"
    file_name = re.sub(r'[\\/:*?"<>|]+', "_", file_name)
    file_path = folder / file_name

    headers = {
        "Referer": str(detail_url or DEFAULT_VIEW_URL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Mozilla/5.0",
    }
    # 1) 상세 선접속으로 세션/쿠키 획득
    _ = session.get(str(detail_url), headers=headers, timeout=90, verify=False)
    # 2) 동일 SESSION으로 파일 다운로드
    resp = session.get(file_url, headers=headers, verify=False, timeout=(10, 120), stream=True)
    resp.raise_for_status()
    with open(file_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if not chunk:
                continue
            f.write(chunk)

    print(f"[JBEXPORT] saved: {file_path}", flush=True)
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.download_file",
            "message": "file downloaded",
            "data": {
                "detail_url": detail_url,
                "file_url": file_url,
                "saved_path": str(file_path),
                "size": file_path.stat().st_size,
            },
            "hypothesisId": "H12",
        }
    )
    return str(file_path)


def _parse_sp_menu_from_detail_url(detail_url: str) -> Tuple[str, str]:
    raw = (detail_url or "").strip()
    if raw.isdigit():
        return raw, DEFAULT_MENU_UUID
    u = urlparse(raw)
    q = parse_qs(u.query or "")
    sp_seq = (q.get("spSeq") or q.get("sp_seq") or [""])[0].strip()
    if not sp_seq:
        m = re.search(r"[?&]spSeq=([^&\s#]+)", raw, re.I)
        if m:
            sp_seq = unquote(m.group(1)).strip()
    menu_uuid = (q.get("menuUUID") or [""])[0].strip() or DEFAULT_MENU_UUID
    return sp_seq, menu_uuid


def _canonical_jbexport_detail_url(sp_seq: str, menu_uuid: str) -> str:
    _, detail1_base = paths_from_view_url(JBEXPORT_DETAIL_PATH_BASE_URL)
    q: Dict[str, str] = {"spSeq": sp_seq, "menuUUID": menu_uuid or DEFAULT_MENU_UUID}
    return f"{detail1_base}?{urlencode(q)}"


def jbexport_canonical_detail_url(sp_seq: str, menu_uuid: str | None = None) -> str:
    """파이프라인 등 외부 모듈용 상세 URL (view1.do 기준 detail1.do)."""
    return _canonical_jbexport_detail_url(sp_seq, menu_uuid or DEFAULT_MENU_UUID)


def jbexport_detail_html_analysis(html: str) -> Dict[str, Any]:
    """detail1.do 응답이 실제 상세 본문인지 추정(길이·첨부 UI·지원사업 키워드 등)."""
    h = html or ""
    info: Dict[str, Any] = {}
    info["html_len"] = len(h)
    info["has_site_title"] = "전북특별자치도 수출통합지원시스템" in h
    info["has_attach_label"] = "첨부파일" in h
    info["fn_filedown_uuid_hits"] = len(
        re.findall(r"fn_fileDown\s*\(\s*['\"]([0-9a-fA-F]{16,})['\"]", h)
    )
    # CSS `.file_txt{` 와 구분: 실제 태그 class 속성에 file_txt 가 있을 때만
    info["has_file_txt_class"] = bool(
        re.search(r'class\s*=\s*["\'][^"\']*\bfile_txt\b', h, re.I)
    )
    info["has_netevViewBtn"] = "netevViewBtn" in h
    info["has_neteViewBtn"] = "neteViewBtn" in h
    info["has_fn_fileDown"] = "fn_fileDown" in h
    info["has_support_flow_keywords"] = any(
        x in h for x in ("지원내용", "접수기간", "신청방법", "지원규모")
    )
    # 숫자 spSeq 등 잘못된 ID로 열 때 공통 껍데기(~31k)만 오는 경우가 있어 상한으로 구분
    shell_ceiling = 32200
    info["plausible_detail_page"] = (
        info["fn_filedown_uuid_hits"] > 0
        or info["has_file_txt_class"]
        or info["html_len"] > shell_ceiling
        or (
            info["has_attach_label"]
            and info["has_support_flow_keywords"]
            and info["html_len"] > shell_ceiling - 1500
        )
    )
    return info


def _fetch_jbexport_detail_html(
    session: requests.Session,
    sp_seq: str,
    menu_uuid: str,
    detail_headers: Dict[str, str],
) -> Tuple[requests.Response, str, str, str]:
    """GET detail1.do?… 후 본문이 비어 보이면 POST detail1.do(spSeq, menuUUID) 재시도.
    반환: (response, html, request_url_for_log, mode get|post)
    """
    canonical = _canonical_jbexport_detail_url(sp_seq, menu_uuid)
    r = session.get(canonical, headers=detail_headers, timeout=90, verify=False)
    html = r.text or ""
    if jbexport_detail_html_analysis(html)["plausible_detail_page"]:
        return r, html, canonical, "get"
    _, detail1_base = paths_from_view_url(JBEXPORT_DETAIL_PATH_BASE_URL)
    post_headers = {
        **detail_headers,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": canonical,
    }
    r2 = session.post(
        detail1_base,
        data={"spSeq": sp_seq, "menuUUID": menu_uuid or DEFAULT_MENU_UUID},
        headers=post_headers,
        timeout=90,
        verify=False,
    )
    return r2, r2.text or "", canonical, "post"


def _jbexport_get_work_search_rows(
    session: requests.Session,
    start: int = 0,
    length: int = 100,
    work_year: str = "2026",
) -> List[Any]:
    """getWork1Search.do JSON 의 data 배열(목록 row)."""
    get_work_url, _ = paths_from_view_url(JBEXPORT_DETAIL_PATH_BASE_URL)
    session.get(
        JBEXPORT_LIST_WARM_URL,
        headers={
            "Referer": UPSTREAM_REFERER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
        },
        timeout=90,
        verify=False,
    )
    payload: Dict[str, str] = {
        "draw": "1",
        "start": str(start),
        "length": str(length),
        "work_year": work_year,
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
    referer = UPSTREAM_REFERER
    referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
        "Origin": referer_origin,
        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    rr = session.post(get_work_url, data=payload, headers=headers, timeout=90, verify=False)
    if rr.status_code >= 400:
        return []
    try:
        j = rr.json()
    except Exception:
        return []
    rows = j.get("data") or []
    return rows if isinstance(rows, list) else []


def jbexport_list_detail_candidates(
    session: Optional[requests.Session] = None,
    work_year: str = "2026",
    max_rows: int = 100,
) -> List[Dict[str, Any]]:
    """목록 API에서 상세 URL 후보 추출. row HTML에 첨부·file_txt 힌트가 있으면 attach_ui_hint=True."""
    s = session or get_jbexport_session()
    rows = _jbexport_get_work_search_rows(s, 0, max_rows, work_year)
    mu = DEFAULT_MENU_UUID
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sp = str(row.get("SP_SEQ") or row.get("spSeq") or row.get("sp_seq") or "").strip()
        if not sp:
            continue
        blob = json.dumps(row, ensure_ascii=False)
        attach_hint = bool(
            re.search(
                r"file_txt|fn_fileDown\s*\(\s*['\"][0-9a-fA-F]{12,}|첨부파일|첨부",
                blob,
                re.I,
            )
        )
        title = str(row.get("js_title") or row.get("TITLE") or row.get("title") or "")[:300]
        out.append(
            {
                "spSeq": sp,
                "menuUUID": mu,
                "detail_url": _canonical_jbexport_detail_url(sp, mu),
                "title": title,
                "attach_ui_hint": attach_hint,
            }
        )
    out.sort(key=lambda x: (not x["attach_ui_hint"], x["spSeq"]))
    return out


def download_jbexport_attachment(
    session: requests.Session,
    detail_page_url: str,
    sp_seq: str,
    record: dict[str, str],
    save_dir: str = "downloads",
) -> str:
    """동일 세션으로 첨부 1건 저장 — 경로 downloads/{spSeq}_{파일명} (이름 없으면 {spSeq}_{fileUUID}.bin)."""
    os.makedirs(save_dir, exist_ok=True)
    name = (record.get("name") or "").strip()
    safe = _safe_saved_filename(name)
    has_ext = bool(re.search(r"\.(pdf|hwp|hwpx|xlsx|xls|docx?|zip|pptx?)\s*$", safe, re.I))
    if not safe or not has_ext:
        fid = (record.get("fileUUID") or "").strip() or "file"
        safe = f"{re.sub(r'[^0-9a-zA-Z._-]+', '_', fid)}.bin"
    dest_name = f"{sp_seq}_{safe}"
    file_path = Path(save_dir) / dest_name

    headers = {
        "Referer": str(detail_page_url),
        "Accept": "*/*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
    }
    url = str(record.get("download_url") or "").strip()
    resp = session.get(url, headers=headers, verify=False, stream=True, timeout=(10, 120))
    resp.raise_for_status()
    with open(file_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)
    rel = str(Path(save_dir) / dest_name).replace("\\", "/")
    print(f"[JBEXPORT] saved: {rel}", flush=True)
    _debug_ndjson_append(
        {
            "location": "jbexport_proxy.download_jbexport_attachment",
            "message": "file downloaded",
            "data": {"detail_url": detail_page_url, "download_url": url, "saved_path": rel, "spSeq": sp_seq},
            "hypothesisId": "H12",
        }
    )
    return rel


def parse_and_download(detail_url: str) -> Dict[str, Any]:
    """list → detail(동일 Session) → HTML 파싱 → downloadFile.do 저장."""
    sp_seq, menu_uuid = _parse_sp_menu_from_detail_url(str(detail_url))
    if not sp_seq:
        return {
            "status": "error",
            "spSeq": "",
            "stage": "detail_parse",
            "error": "spSeq_required: detail_url 에 spSeq 가 없습니다.",
        }

    canonical_detail = _canonical_jbexport_detail_url(sp_seq, menu_uuid)

    try:
        session = get_jbexport_session()
        detail_headers = {
            "Referer": JBEXPORT_DETAIL_REFERER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
        print("[JBEXPORT] detail page requested", flush=True)
        r, html, _, _ = _fetch_jbexport_detail_html(session, sp_seq, menu_uuid, detail_headers)
        if r.status_code >= 400:
            return {
                "status": "error",
                "spSeq": sp_seq,
                "stage": "detail_parse",
                "error": f"upstream_http_{r.status_code}",
            }
        analysis = jbexport_detail_html_analysis(html)
        if not analysis.get("plausible_detail_page"):
            return {
                "status": "error",
                "spSeq": sp_seq,
                "stage": "detail_fetch",
                "error": "detail_page_mismatch",
            }

        soup = BeautifulSoup(html, "html.parser")
        records = extract_attachments_onclick_tags(soup)
        if not records:
            records = extract_attachment_records(soup, html)
        if not records:
            endpoints = _extract_js_endpoints(html)
            for ep in endpoints:
                low = ep.lower()
                if not any(k in low for k in ["file", "attach", "download", "atch"]):
                    continue
                api_url = urljoin("https://www.jbexport.or.kr", ep)
                if "downloadfile.do" in low and "fileuuid=" in low:
                    pq = parse_qs(urlparse(api_url).query, keep_blank_values=True)
                    if not (pq.get("fileUUID") or pq.get("fileuuid") or [""])[0].strip():
                        continue
                try:
                    rr = session.get(
                        api_url,
                        headers={
                            "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                            "Referer": canonical_detail,
                            "Accept": "*/*",
                        },
                        timeout=90,
                        verify=False,
                    )
                    if rr.status_code >= 400:
                        continue
                    ct = (rr.headers.get("content-type") or "").lower()
                    if "json" in ct:
                        rec_more = _extract_attachment_records_from_json(rr.json())
                        if rec_more:
                            records = rec_more
                            break
                except Exception:
                    continue

        print(f"[JBEXPORT] attachment candidates found: {len(records)}", flush=True)

        parsed = parse_detail_content(canonical_detail, html)
        parsed["첨부파일"] = [{"파일명": x["name"], "파일URL": x["download_url"]} for x in records]

        title = ""
        m_title = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, flags=re.I)
        if m_title:
            title = re.sub(r"\s+", " ", m_title.group(1)).strip()

        files_out: list[dict[str, Any]] = []
        for rec in records:
            try:
                saved = download_jbexport_attachment(session, canonical_detail, sp_seq, rec)
                files_out.append(
                    {
                        "name": rec.get("name", ""),
                        "fileUUID": rec.get("fileUUID", ""),
                        "pathNum": rec.get("pathNum", ""),
                        "saved_path": saved,
                    }
                )
            except Exception as e:
                return {
                    "status": "error",
                    "spSeq": sp_seq,
                    "stage": "file_download",
                    "error": str(e),
                }

        return {
            "status": "ok",
            "spSeq": sp_seq,
            "detail_url": canonical_detail,
            "title": title,
            "files": files_out,
        }
    except Exception as e:
        return {
            "status": "error",
            "spSeq": sp_seq,
            "stage": "detail_parse",
            "error": str(e),
        }


def paths_from_view_url(view_url: str) -> Tuple[str, str]:
    u = urlparse(view_url)
    base_dir = u.path.rsplit("/", 1)[0]
    get_work = urlunparse((u.scheme, u.netloc, f"{base_dir}/getWork1Search.do", "", "", ""))
    detail1 = urlunparse((u.scheme, u.netloc, f"{base_dir}/detail1.do", "", "", ""))
    return get_work, detail1


def jbexport_post_work1_search(
    session: requests.Session,
    *,
    start: int,
    length: int = 10,
    draw: int = 1,
    work_year: str = "2026",
    client_view_url: str | None = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """getWork1Search.do POST 한 페이지. 성공 시 upstream JSON dict, 실패 시 (None, 이유)."""
    view = (client_view_url or "").strip() or DEFAULT_VIEW_URL
    referer = UPSTREAM_REFERER
    get_work_url, _ = paths_from_view_url(view)
    payload: Dict[str, str] = {
        "draw": str(draw),
        "start": str(start),
        "length": str(length),
        "work_year": work_year,
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
    referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
        "Origin": referer_origin,
        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    try:
        session.get(
            view,
            headers={"Referer": referer, "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0")},
            timeout=90,
            verify=False,
        )
        r = session.post(get_work_url, data=payload, headers=headers, timeout=90, verify=False)
    except requests.RequestException as e:
        return None, str(e)
    if r.status_code >= 400:
        return None, f"upstream_http_{r.status_code}"
    ct = (r.headers.get("content-type") or "").lower()
    if "json" not in ct:
        return None, "non_json_response"
    try:
        j = r.json()
    except Exception as e:
        return None, f"json_parse_error:{e}"
    if not isinstance(j, dict):
        return None, "invalid_json_shape"
    return j, ""


@app.get("/health")
def health() -> Any:
    return jsonify(
        {
            "ok": True,
            "build": PROXY_BUILD,
            "pid": os.getpid(),
            "boot": BOOT_TS,
            "session_verify": SESSION.verify,
        }
    )


@app.post("/api/jbexport/list")
def api_jbexport_list() -> Any:
    try:
        data = request.get_json(silent=True) or {}
        start = int(data.get("start", 0))
        length = int(data.get("length", 10))
        draw = int(data.get("draw", 1))
        # #region agent log
        _debug_ndjson_append(
            {
                "location": "jbexport_proxy.api_jbexport_list",
                "message": "client POST received",
                "data": {"start": start, "length": length, "draw": draw},
                "hypothesisId": "H3",
            }
        )
        # #endregion
        menu_uuid = (data.get("menuUUID") or "").strip()
        work_year = str(data.get("work_year", "2026"))
        ts_gubun = ""
        search_keyword = data.get("searchKeyword")
        if search_keyword is None:
            search_keyword = ""
        # NOTE: upstream endpoint 경로는 view1.do 기반으로 결정되어야 함.
        # (index.do 기반으로 paths_from_view_url를 만들면 /getWork1Search.do 로 POST되어 404가 날 수 있음)
        client_view_url = str(data.get("refererUrl") or "").strip()
        if not client_view_url:
            client_view_url = DEFAULT_VIEW_URL
        referer = UPSTREAM_REFERER
        extra = data.get("extraParams") or {}

        get_work_url, _ = paths_from_view_url(client_view_url)

        payload: Dict[str, str] = {
            "draw": str(draw),
            "start": str(start),
            "length": str(length),
            "work_year": work_year,
            "tsGubun": ts_gubun,
            "stat": "",
            "js": "",
            "js_input": "",
            "su": "",
            "search[value]": "",
            "search[regex]": "false",
        }
        # DataTables 컬럼 필드(브라우저 실요청 확인값에 맞춤)
        payload["columns[0][data]"] = "0"
        payload["columns[1][data]"] = "CODE_K"
        payload["columns[2][data]"] = "CATEGO"
        payload["columns[3][data]"] = "js_title"
        payload["columns[4][data]"] = "STS_TXT"
        for i in range(5):
            payload[f"columns[{i}][name]"] = ""
            payload[f"columns[{i}][searchable]"] = "true"
            payload[f"columns[{i}][orderable]"] = "true"
            payload[f"columns[{i}][search][value]"] = ""
            payload[f"columns[{i}][search][regex]"] = "false"
        payload["order[0][column]"] = "0"
        payload["order[0][dir]"] = "desc"
        # Colab 성공 조건 기준: menuUUID, searchKeyword 미전송
        if isinstance(extra, dict):
            for k, v in extra.items():
                if v is not None:
                    payload[str(k)] = str(v)

        # 브라우저 실요청에 가깝게 헤더 보강
        referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
            "Origin": referer_origin,
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        try:
            # 일부 전자정부 페이지는 목록(view1) 선행 접근으로 세션 쿠키를 만든 뒤 POST 해야 데이터가 채워짐
            _ = SESSION.get(
                client_view_url,
                headers={"Referer": referer, "User-Agent": "Mozilla/5.0"},
                timeout=30,
                verify=False,
            )
            # #region agent log
            _debug_ndjson_append(
                {
                    "location": "jbexport_proxy.api_jbexport_list",
                    "message": "upstream POST about to send",
                    "data": {
                        "client_view_url": client_view_url,
                        "upstream_url": get_work_url,
                        "headers": headers,
                        "payload": payload,
                    },
                    "hypothesisId": "H4",
                }
            )
            # #endregion
            r = SESSION.post(
                get_work_url, data=payload, headers=headers, timeout=90, verify=False
            )
        except requests.RequestException as e:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "upstream_request_failed",
                        "message": str(e),
                        "build": PROXY_BUILD,
                        "session_verify": SESSION.verify,
                        "request_verify": False,
                    }
                ),
                502,
            )

        ct = (r.headers.get("content-type") or "").lower()
        # #region agent log
        try:
            resp_head = (r.text or "")[:500]
        except Exception:
            resp_head = ""
        can_json = False
        try:
            _ = r.json()
            can_json = True
        except Exception:
            can_json = False
        _debug_ndjson_append(
            {
                "location": "jbexport_proxy.api_jbexport_list",
                "message": "upstream response received",
                "data": {
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type"),
                    "text_head_500": resp_head,
                    "can_json": can_json,
                },
                "hypothesisId": "H4",
            }
        )
        # #endregion
        if r.status_code >= 400:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "upstream_http_error",
                        "status": r.status_code,
                        "body": r.text[:2000],
                    }
                ),
                502,
            )
        if "json" not in ct:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "non_json_response",
                        "content_type": r.headers.get("content-type"),
                        "body": r.text[:2000],
                    }
                ),
                502,
            )

        # recordsTotal=0 + start=0 일 때 세션/필터 이슈 가능성 있어 1회 재시도(같은 payload)
        try:
            j = r.json()
        except Exception:
            j = None
        rt = None
        rows_len = None
        debug_info = {
            "build": PROXY_BUILD,
            "request_verify": False,
            "session_verify": SESSION.verify,
            "upstream_status": r.status_code,
            "upstream_ct": r.headers.get("content-type"),
            "sent": {
                "start": start,
                "length": length,
                "draw": draw,
                "work_year": payload.get("work_year"),
                "tsGubun": payload.get("tsGubun"),
                "columns_data": [
                    payload.get("columns[0][data]"),
                    payload.get("columns[1][data]"),
                    payload.get("columns[2][data]"),
                    payload.get("columns[3][data]"),
                    payload.get("columns[4][data]"),
                ],
            },
        }
        if isinstance(j, dict):
            try:
                rt = int(j.get("recordsTotal", j.get("recordsFiltered", j.get("total", 0))) or 0)
            except Exception:
                rt = 0
            rows = j.get("data", j.get("aaData", j.get("rows", [])))
            rows_len = len(rows) if isinstance(rows, list) else None
            debug_info["upstream_keys"] = sorted(list(j.keys()))[:30]
            debug_info["recordsTotal"] = rt
            debug_info["rows_len"] = rows_len
        else:
            debug_info["upstream_text_head"] = r.text[:300]

        print(
            f"[jbexport_proxy] upstream status={r.status_code} recordsTotal={rt} rows={rows_len} "
            f"keys={debug_info.get('upstream_keys')}",
            flush=True,
        )
        if rt == 0 and start == 0:
            print("[jbexport_proxy] recordsTotal=0 on first call; run probes", flush=True)
            probes = []

            def run_probe(name: str, form_payload: Dict[str, str]) -> tuple[int, int | None, int | None, Any]:
                rp = SESSION.post(
                    get_work_url, data=form_payload, headers=headers, timeout=90, verify=False
                )
                prt = None
                prow_len = None
                pj = None
                if rp.ok and "json" in (rp.headers.get("content-type") or "").lower():
                    try:
                        pj = rp.json()
                        if isinstance(pj, dict):
                            prt = int(
                                pj.get("recordsTotal", pj.get("recordsFiltered", pj.get("total", 0))) or 0
                            )
                            prow = pj.get("data", pj.get("aaData", pj.get("rows", [])))
                            prow_len = len(prow) if isinstance(prow, list) else None
                    except Exception:
                        pass
                probes.append(
                    {
                        "name": name,
                        "status": rp.status_code,
                        "recordsTotal": prt,
                        "rows_len": prow_len,
                        "work_year": form_payload.get("work_year"),
                        "tsGubun": form_payload.get("tsGubun"),
                        "length": form_payload.get("length"),
                        "columns0": form_payload.get("columns[0][data]"),
                    }
                )
                print(
                    f"[jbexport_proxy] probe={name} status={rp.status_code} recordsTotal={prt} rows={prow_len}",
                    flush=True,
                )
                return rp.status_code, prt, prow_len, pj

            variants: list[tuple[str, Dict[str, str]]] = []
            # 1) 같은 payload 1회 재시도
            variants.append(("retry_same", dict(payload)))
            # 2) year/gubun 제거(서버 기본조건 확인)
            p2 = dict(payload)
            p2.pop("work_year", None)
            p2.pop("tsGubun", None)
            variants.append(("no_year_no_gubun", p2))
            # 3) length 10
            p3 = dict(payload)
            p3["length"] = "10"
            variants.append(("length_10", p3))
            # 4) columns data를 숫자 인덱스로
            p4 = dict(payload)
            for i in range(5):
                p4[f"columns[{i}][data]"] = str(i)
            variants.append(("columns_numeric", p4))

            for vname, vp in variants:
                _, vrt, vrows, vjson = run_probe(vname, vp)
                if isinstance(vjson, dict) and ((vrt or 0) > 0 or (vrows or 0) > 0):
                    vjson["_proxy_debug"] = {**debug_info, "probes": probes, "selected_probe": vname}
                    return jsonify(vjson)

            debug_info["probes"] = probes

        if isinstance(j, dict):
            j["_proxy_debug"] = debug_info
            return jsonify(j)
        return Response(r.content, mimetype="application/json; charset=utf-8")

    except Exception as e:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "proxy_handler_error",
                    "message": str(e),
                }
            ),
            500,
        )


def debug_upstream_detail(sp_seq: str) -> Dict[str, Any]:
    """list 워밍 → detail GET/POST 후 첨부 목록·상세 분석 dict 반환."""
    out: Dict[str, Any] = {
        "spSeq": sp_seq.strip(),
        "detail_url": "",
        "http_status": None,
        "html_len": 0,
        "response_url": "",
        "attachments": [],
        "onclick_sample": [],
        "detail_analysis": {},
    }

    menu_uuid = _menu_uuid_from_url(JBEXPORT_DETAIL_PATH_BASE_URL) or _menu_uuid_from_url(DEFAULT_VIEW_URL)
    _, detail1_base = paths_from_view_url(JBEXPORT_DETAIL_PATH_BASE_URL)
    q: Dict[str, str] = {"spSeq": sp_seq.strip()}
    if menu_uuid:
        q["menuUUID"] = menu_uuid
    url = f"{detail1_base}?{urlencode(q)}"
    out["detail_url"] = url
    referer_fixed = JBEXPORT_DETAIL_REFERER
    warm_headers = {
        "Referer": UPSTREAM_REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        SESSION.get(JBEXPORT_LIST_WARM_URL, headers=warm_headers, timeout=90, verify=False)
    except requests.RequestException:
        pass
    detail_headers = {
        "Referer": referer_fixed,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        r, html, _, fetch_mode = _fetch_jbexport_detail_html(
            SESSION, sp_seq.strip(), menu_uuid, detail_headers
        )
    except requests.RequestException as e:
        out["error"] = str(e)
        return out
    out["fetch_mode"] = fetch_mode
    out["http_status"] = r.status_code
    out["response_url"] = r.url
    out["html_len"] = len(html)
    out["detail_analysis"] = jbexport_detail_html_analysis(html)

    soup = BeautifulSoup(html, "html.parser")
    attachments = extract_attachments_onclick_tags(soup)
    if not attachments:
        attachments = extract_attachment_records(soup, html)
    out["attachments"] = attachments

    if len(attachments) == 0:
        out["onclick_sample"] = [tag.get("onclick") for tag in soup.find_all(onclick=True)][:10]

    return out


@app.get("/api/jbexport/detail")
def api_jbexport_detail() -> Any:
    """JSON: parse_and_download(detail_url) 결과. (Flask — FastAPI 아님; HTML pass-through 제거)"""
    try:
        sp_seq = (request.args.get("spSeq") or "").strip()
        menu_uuid_arg = (request.args.get("menuUUID") or "").strip()
        if not sp_seq:
            return (
                jsonify(
                    {
                        "status": "error",
                        "spSeq": "",
                        "stage": "detail_parse",
                        "error": "spSeq_required",
                    }
                ),
                400,
            )

        menu_uuid = (
            menu_uuid_arg
            or _menu_uuid_from_url(JBEXPORT_DETAIL_PATH_BASE_URL)
            or _menu_uuid_from_url(DEFAULT_VIEW_URL)
            or DEFAULT_MENU_UUID
        )
        _, detail1_base = paths_from_view_url(JBEXPORT_DETAIL_PATH_BASE_URL)
        detail_url = f"{detail1_base}?{urlencode({'spSeq': sp_seq, 'menuUUID': menu_uuid})}"

        result = parse_and_download(detail_url)
        if not isinstance(result, dict):
            return (
                jsonify(
                    {
                        "status": "error",
                        "spSeq": sp_seq,
                        "stage": "detail_parse",
                        "error": "invalid_parse_result",
                    }
                ),
                500,
            )

        if result.get("status") == "ok":
            return jsonify(result), 200

        stage = str(result.get("stage") or "")
        err_code = 500
        if stage == "detail_fetch":
            err_code = 422
        elif stage == "detail_parse" and "upstream_http" in str(result.get("error", "")):
            err_code = 502
        elif stage == "file_download":
            err_code = 502
        return jsonify(result), err_code
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "spSeq": (request.args.get("spSeq") or "").strip(),
                    "stage": "proxy_handler",
                    "error": str(e),
                }
            ),
            500,
        )


@app.route("/api/jbexport/run", methods=["OPTIONS"])
def api_jbexport_run_options() -> Any:
    return ("", 204)


@app.route("/api/jbexport/run", methods=["POST"])
def run_pipeline() -> Any:
    """일일 목록 수집·저장·어제 대비 신규 공고 (pipeline.run_daily)."""
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from pipeline.jbexport_daily import run_daily

        result = run_daily()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
