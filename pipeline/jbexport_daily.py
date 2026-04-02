import json
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================================================
# 기본 설정
# =========================================================
PROXY_BASE = "http://127.0.0.1:5000"
LIST_ENDPOINT = f"{PROXY_BASE}/api/jbexport/list"

JBEXPORT_BASE = "https://www.jbexport.or.kr"
DETAIL_BASE = f"{JBEXPORT_BASE}/other/spWork/spWorkSupportBusiness/detail1.do"
MENU_UUID = "402880867c8174de017c819251e70009"

LIST_LENGTH = 10
MAX_PAGES = 100
TIMEOUT = 30
OPEN_STATUSES = {"접수중", "공고중"}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

JBEXPORT_DIR = DATA_DIR / "jbexport"
JBEXPORT_DIR.mkdir(parents=True, exist_ok=True)

ATTACH_DIR = JBEXPORT_DIR / "files"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# 공통 로그
# =========================================================
def log(message: str) -> None:
    print(message, flush=True)


# =========================================================
# 경로 함수
# =========================================================
def today_json_path(target_date: date) -> Path:
    return JBEXPORT_DIR / f"{target_date.isoformat()}.json"


def new_json_path() -> Path:
    return DATA_DIR / "jbexport_new.json"


# =========================================================
# 목록 응답에서 rows 꺼내기
# =========================================================
def rows_from_json(payload: Any) -> List[Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


# =========================================================
# 공고 1건 정규화
# =========================================================
def extract_announcement(row: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None

    sp_seq = str(
        row.get("spSeq")
        or row.get("SP_SEQ")
        or row.get("seq")
        or row.get("SEQ")
        or ""
    ).strip()

    if not sp_seq:
        return None

    title = str(
        row.get("title")
        or row.get("사업명")
        or row.get("sj")
        or row.get("subject")
        or ""
    ).strip()

    period = str(
        row.get("period")
        or row.get("접수기간")
        or row.get("rcptPd")
        or row.get("사업기간")
        or ""
    ).strip()

    status = str(
        row.get("status")
        or row.get("상태")
        or row.get("ingYnNm")
        or row.get("progressStatus")
        or ""
    ).strip()

    detail_url = f"{DETAIL_BASE}?menuUUID={MENU_UUID}&spSeq={sp_seq}"

    return {
        "spSeq": sp_seq,
        "공고제목": title or f"spSeq={sp_seq}",
        "기관": "전북수출통합지원시스템",
        "기간": period,
        "상태": status,
        "상세URL": detail_url,
        "files": [],
    }


# =========================================================
# 전체 공고 수집
# =========================================================
def fetch_all_announcements() -> List[Dict[str, Any]]:
    log("[수집 시작] JBEXPORT 전체 공고 수집")

    all_items: List[Dict[str, Any]] = []
    seen_urls = set()

    start = 0

    for page in range(1, MAX_PAGES + 1):
        payload = {
            "start": start,
            "length": LIST_LENGTH,
            "draw": page,
        }

        log(f"[LIST] page={page} start={start} length={LIST_LENGTH}")

        try:
            res = requests.post(
                LIST_ENDPOINT,
                json=payload,
                timeout=TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            log(f"[오류] LIST 요청 실패: {e}")
            break

        rows = rows_from_json(data)
        log(f"[LIST] rows={len(rows)}")

        if not rows:
            break

        for row in rows:
            item = extract_announcement(row)
            if not item:
                continue

            url = item["상세URL"]
            if url in seen_urls:
                continue

            seen_urls.add(url)
            all_items.append(item)

        if len(rows) < LIST_LENGTH:
            break

        start += LIST_LENGTH

    log(f"[수집 완료] 전체 공고 {len(all_items)}건")
    return all_items


# =========================================================
# 진행중 공고만 필터
# =========================================================
def filter_open_announcements(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []

    for item in results:
        status = str(item.get("상태") or "").strip()
        if status in OPEN_STATUSES:
            filtered.append(item)

    log(f"[필터] 진행중 공고 {len(filtered)}건")
    return filtered


# =========================================================
# 오늘 JSON 저장
# =========================================================
def save_today_json(open_announcements: List[Dict[str, Any]]) -> Path:
    path = today_json_path(date.today())
    path.write_text(
        json.dumps(open_announcements, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"[저장] {path.name} ({len(open_announcements)}건)")
    return path


# =========================================================
# 어제 JSON 로드
# =========================================================
def load_yesterday_json() -> List[Dict[str, Any]]:
    y_path = today_json_path(date.today() - timedelta(days=1))

    if not y_path.exists():
        log(f"[로드] 어제 파일 없음: {y_path.name}")
        return []

    try:
        items = json.loads(y_path.read_text(encoding="utf-8"))
        if isinstance(items, list):
            log(f"[로드] 어제 파일 로드: {y_path.name} ({len(items)}건)")
            return items
    except Exception as e:
        log(f"[오류] 어제 파일 로드 실패: {e}")

    return []


# =========================================================
# 신규 공고 찾기
# =========================================================
def find_new_announcements(
    today_items: List[Dict[str, Any]],
    yesterday_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    yesterday_urls = {
        str(item.get("상세URL") or "").strip()
        for item in yesterday_items
        if isinstance(item, dict)
    }

    new_items: List[Dict[str, Any]] = []
    for item in today_items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("상세URL") or "").strip()
        if url and url not in yesterday_urls:
            new_items.append(item)

    log(f"[비교] 신규 공고 {len(new_items)}건")
    return new_items


# =========================================================
# 신규 JSON 저장
# =========================================================
def save_new_json(new_items: List[Dict[str, Any]]) -> Path:
    path = new_json_path()
    path.write_text(
        json.dumps(new_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"[저장] {path.name} ({len(new_items)}건)")
    return path


# =========================================================
# 첨부 dedupe
# =========================================================
def dedupe_attachments(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    for item in items:
        file_uuid = str(item.get("fileUUID") or "").strip()
        path_num = str(item.get("pathNum") or "6").strip()

        if not file_uuid:
            continue

        key = (file_uuid, path_num)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": str(item.get("name") or "").strip(),
            "size": item.get("size"),
        })

    return out


# =========================================================
# JSON/딕셔너리 내부에서 첨부 레코드 추출
# =========================================================
def extract_attachment_records_from_json(payload: Any) -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            low_map = {str(k).lower(): v for k, v in x.items()}

            file_uuid = (
                low_map.get("fileuuid")
                or low_map.get("file_uuid")
                or low_map.get("uuid")
                or low_map.get("fileid")
            )
            path_num = (
                low_map.get("pathnum")
                or low_map.get("path_num")
                or low_map.get("path")
                or "6"
            )
            file_name = (
                low_map.get("name")
                or low_map.get("filename")
                or low_map.get("file_name")
                or low_map.get("originfilenm")
                or low_map.get("orgfilenm")
                or low_map.get("originalfilename")
                or ""
            )
            size = low_map.get("size") or low_map.get("filesize") or low_map.get("file_size")

            if file_uuid:
                raw.append({
                    "fileUUID": str(file_uuid).strip(),
                    "pathNum": str(path_num).strip(),
                    "name": str(file_name).strip(),
                    "size": int(size) if str(size).isdigit() else None,
                })

            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    return dedupe_attachments(raw)


# =========================================================
# 첨부파일 목록 조회 - API 시도
# =========================================================
def get_attachments_from_api(sp_seq: str) -> List[Dict[str, Any]]:
    candidates = [
        f"{JBEXPORT_BASE}/common/file/getFileList.do",
        f"{JBEXPORT_BASE}/common/file/selectFileList.do",
        f"{JBEXPORT_BASE}/common/file/getAtchFileList.do",
    ]

    for url in candidates:
        try:
            res = requests.post(
                url,
                data={"spSeq": sp_seq},
                timeout=TIMEOUT,
                verify=False,
            )
            if res.status_code != 200:
                continue

            try:
                payload = res.json()
            except Exception:
                continue

            records = extract_attachment_records_from_json(payload)
            if records:
                return records
        except Exception:
            continue

    return []


# =========================================================
# 첨부파일 목록 조회 - HTML fallback
# =========================================================
def get_attachments_from_html(detail_url: str) -> List[Dict[str, Any]]:
    try:
        res = requests.get(detail_url, timeout=TIMEOUT, verify=False)
        if res.status_code != 200:
            return []
        html = res.text
    except Exception:
        return []

    found: List[Dict[str, Any]] = []

    # 패턴 1: downloadFile.do?...pathNum=...&fileUUID=...
    pattern1 = re.findall(
        r"downloadFile\.do\?[^\"' ]*pathNum=([^&\"' ]+)[^\"' ]*fileUUID=([a-fA-F0-9]+)",
        html,
        re.IGNORECASE,
    )
    for path_num, file_uuid in pattern1:
        found.append({
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": "",
        })

    # 패턴 2: fn_fileDown('UUID')
    pattern2 = re.findall(
        r"fn_fileDown\('([a-fA-F0-9]+)'\)",
        html,
        re.IGNORECASE,
    )
    for file_uuid in pattern2:
        found.append({
            "fileUUID": file_uuid,
            "pathNum": "6",
            "name": "",
        })

    return dedupe_attachments(found)


# =========================================================
# 첨부파일 목록 조회 통합
# =========================================================
def get_attachments(sp_seq: str, detail_url: str) -> List[Dict[str, Any]]:
    items = get_attachments_from_api(sp_seq)
    if items:
        log(f"[첨부조회] spSeq={sp_seq} API {len(items)}건")
        return items

    items = get_attachments_from_html(detail_url)
    log(f"[첨부조회] spSeq={sp_seq} HTML {len(items)}건")
    return items


# =========================================================
# 파일명 정리
# =========================================================
def sanitize_filename(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return ""
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name


def guess_extension(name: str) -> str:
    safe_name = sanitize_filename(name)
    if "." in safe_name:
        ext = safe_name[safe_name.rfind("."):]
        if 1 < len(ext) <= 10:
            return ext
    return ".bin"


# =========================================================
# 다운로드 URL
# =========================================================
def build_download_url(path_num: str, file_uuid: str) -> str:
    query = urllib.parse.urlencode({
        "pathNum": path_num,
        "fileUUID": file_uuid,
    })
    return f"{JBEXPORT_BASE}/downloadFile.do?{query}"


# =========================================================
# 파일 다운로드
# =========================================================
def download_jbexport_file(file_uuid: str, path_num: str, name: str = "") -> Dict[str, Any]:
    download_url = build_download_url(path_num, file_uuid)

    safe_name = sanitize_filename(name)
    ext = guess_extension(safe_name)

    if safe_name:
        save_path = ATTACH_DIR / f"{file_uuid}_{safe_name}"
    else:
        save_path = ATTACH_DIR / f"{file_uuid}{ext}"

    try:
        res = requests.get(download_url, timeout=TIMEOUT, stream=True, verify=False)
        res.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in res.iter_content(8192):
                if chunk:
                    f.write(chunk)

        size = save_path.stat().st_size
        log(f"[첨부저장] {save_path} ({size} bytes)")
    except Exception as e:
        log(f"[첨부오류] {file_uuid} 다운로드 실패: {e}")
        return {
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": safe_name,
            "saved_path": "",
            "size": 0,
        }

    return {
        "fileUUID": file_uuid,
        "pathNum": path_num,
        "name": safe_name or save_path.name,
        "saved_path": str(save_path),
        "size": size,
    }


# =========================================================
# 신규 공고에 첨부 다운로드 붙이기
# =========================================================
def enrich_new_items_with_files(new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for item in new_items:
        sp_seq = str(item.get("spSeq") or "").strip()
        detail_url = str(item.get("상세URL") or "").strip()

        if not sp_seq or not detail_url:
            item["files"] = []
            continue

        attachments = get_attachments(sp_seq, detail_url)
        downloaded_files: List[Dict[str, Any]] = []

        for att in attachments:
            file_uuid = str(att.get("fileUUID") or "").strip()
            path_num = str(att.get("pathNum") or "6").strip()
            name = str(att.get("name") or "").strip()

            if not file_uuid:
                continue

            file_info = download_jbexport_file(file_uuid, path_num, name)
            downloaded_files.append(file_info)

        item["files"] = downloaded_files

    return new_items


# =========================================================
# 신규 공고 콘솔 출력
# =========================================================
def print_new_announcements(new_items: List[Dict[str, Any]]) -> None:
    if not new_items:
        print("No new announcements")
        return

    print("===== NEW ANNOUNCEMENTS =====")
    for i, item in enumerate(new_items, 1):
        print(f"{i}. {item.get('공고제목', '')}")
        print(f"   기관: {item.get('기관', '')}")
        print(f"   기간: {item.get('기간', '')}")
        print(f"   상태: {item.get('상태', '')}")
        print(f"   URL: {item.get('상세URL', '')}")

        files = item.get("files") or []
        if files:
            print(f"   첨부: {len(files)}개")
            for f in files:
                print(f"      - {f.get('saved_path', '')} ({f.get('size', 0)} bytes)")
        print("-----------------------------")


# =========================================================
# 실행
# =========================================================
def run_daily() -> Dict[str, Any]:
    all_items = fetch_all_announcements()
    open_items = filter_open_announcements(all_items)

    today_path = save_today_json(open_items)

    yesterday_items = load_yesterday_json()
    new_items = find_new_announcements(open_items, yesterday_items)

    new_items = enrich_new_items_with_files(new_items)
    new_path = save_new_json(new_items)

    print_new_announcements(new_items)

    return {
        "date": str(date.today()),
        "new_count": len(new_items),
        "new_items": new_items,
        "today_json": str(today_path),
        "new_json": str(new_path),
    }


if __name__ == "__main__":
    result = run_daily()
    print(json.dumps(result, ensure_ascii=False, indent=2))