"""BizGovPlanner Flask app: UI reads persisted rows from biz.db.

DB-centered: request handlers do not run crawlers, remote attachment fetches, or on-demand text extraction.
Background collection: POST /api/run spawns subprocess run_all.py only.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from ai_analyzer import analyze_project
from pdf_generator import create_pdf, create_recommendation_report_pdf
from mailer import send_email as do_send

from pipeline.recommend_projects import score_company_project

from kakao_notify import build_recommend_kakao_text, send_kakao_memo

DB_PATH = os.getenv("DB_PATH", "db/biz.db")


def ensure_db_file():
    target = Path(DB_PATH)
    source = Path("db/biz.db")
    if str(target) != "db/biz.db":
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() and source.exists():
            shutil.copy2(source, target)
        if not target.exists():
            target.touch()


app = Flask(__name__)


@app.before_request
def log_visit():
    try:
        if request.method != "GET":
            return
        path = request.path or ""
        if path.startswith("/static"):
            return
        if path == "/favicon.ico":
            return
        if path.startswith("/api/run/status"):
            return
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        ua = request.headers.get("User-Agent", "")
        traffic_source = detect_traffic_source()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO visit_log (path, method, ip, user_agent, traffic_source) VALUES (?, ?, ?, ?, ?)",
                (path, request.method, ip, ua[:500], traffic_source),
            )
            conn.commit()
    except Exception as e:
        print("[visit_log] skipped:", repr(e), flush=True)


app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
ADMIN_KEY = os.getenv("ADMIN_KEY", "dev-admin-key")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cur = conn.cursor()
    col_names = {str(c[1]) for c in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in col_names:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_projects (
            id INTEGER PRIMARY KEY,
            title TEXT,
            organization TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            url TEXT,
            description TEXT,
            ai_result TEXT,
            pdf_path TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cols = cur.execute("PRAGMA table_info(biz_projects)").fetchall()
    col_names = {str(c[1]) for c in cols}
    if "organization" not in col_names:
        cur.execute("ALTER TABLE biz_projects ADD COLUMN organization TEXT")
    col_names = {str(c[1]) for c in cur.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "source" not in col_names:
        cur.execute("ALTER TABLE biz_projects ADD COLUMN source TEXT")
    col_names = {str(c[1]) for c in cur.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "ministry" not in col_names:
        cur.execute("ALTER TABLE biz_projects ADD COLUMN ministry TEXT")
    col_names = {str(c[1]) for c in cur.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "executing_agency" not in col_names:
        cur.execute("ALTER TABLE biz_projects ADD COLUMN executing_agency TEXT")
    for _jbcol in (
        "receipt_start",
        "receipt_end",
        "biz_start",
        "biz_end",
        "raw_status",
        "attachments_json",
    ):
        col_names = {
            str(c[1]) for c in cur.execute("PRAGMA table_info(biz_projects)").fetchall()
        }
        if _jbcol not in col_names:
            cur.execute(
                f"ALTER TABLE biz_projects ADD COLUMN {_jbcol} TEXT"
            )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            industry TEXT,
            region TEXT,
            employee_count TEXT,
            revenue TEXT,
            export_flag TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, project_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS click_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT,
            action TEXT,
            source TEXT,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_column(conn, "companies", "export_amount", "TEXT")
    _ensure_column(conn, "companies", "business_number", "TEXT")
    _ensure_column(conn, "companies", "visitor_id", "TEXT")
    _ensure_column(conn, "companies", "interest_keywords", "TEXT")
    _ensure_column(conn, "companies", "consent_accepted", "INTEGER DEFAULT 0")
    _ensure_column(conn, "companies", "consent_version", "TEXT")
    _ensure_column(conn, "companies", "cert_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "companies", "catalog_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "companies", "social_enterprise", "INTEGER DEFAULT 0")
    _ensure_column(conn, "companies", "female_ceo", "INTEGER DEFAULT 0")
    _ensure_column(conn, "companies", "export_tower", "INTEGER DEFAULT 0")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS consent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            company_id INTEGER,
            consent_text TEXT,
            accepted_at TEXT DEFAULT (datetime('now', 'localtime')),
            user_ip TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            user_ip TEXT,
            action TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS favorite_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            project_id TEXT,
            title TEXT,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(visitor_id, project_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT UNIQUE NOT NULL,
          name TEXT,
          company_name TEXT,
          phone TEXT,
          region TEXT,
          industry TEXT,
          email_enabled INTEGER DEFAULT 1,
          kakao_enabled INTEGER DEFAULT 0,
          consent_accepted INTEGER DEFAULT 0,
          consent_text TEXT,
          source TEXT DEFAULT 'google_form',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS google_form_import_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          imported_count INTEGER DEFAULT 0,
          inserted_count INTEGER DEFAULT 0,
          updated_count INTEGER DEFAULT 0,
          skipped_count INTEGER DEFAULT 0,
          status TEXT,
          message TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT,
            method TEXT,
            ip TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    def ensure_column(conn, table_name, column_name, column_sql):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if column_name not in cols:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
            print(f"[DB] added {table_name}.{column_name}", flush=True)

    ensure_column(conn, "visit_log", "traffic_source", "traffic_source TEXT")
    ensure_column(conn, "click_log", "traffic_source", "traffic_source TEXT")
    conn.commit()
    conn.close()


ensure_db_file()
_init_db()
with sqlite3.connect(DB_PATH) as _conn:
    _cur = _conn.cursor()

    def _safe_add(table, column, coltype):
        try:
            cols = {
                str(r[1])
                for r in _cur.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column in cols:
                return
            _cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        except Exception:
            pass

    _safe_add("biz_projects", "ai_result", "TEXT")
    _safe_add("biz_projects", "pdf_path", "TEXT")
    _safe_add("biz_projects", "site", "TEXT")
    _safe_add("biz_projects", "collected_at", "TEXT")
    _safe_add("biz_projects", "ministry", "TEXT")
    _safe_add("biz_projects", "executing_agency", "TEXT")
    _safe_add("biz_projects", "receipt_start", "TEXT")
    _safe_add("biz_projects", "receipt_end", "TEXT")
    _safe_add("biz_projects", "biz_start", "TEXT")
    _safe_add("biz_projects", "biz_end", "TEXT")
    _safe_add("biz_projects", "raw_status", "TEXT")
    _safe_add("biz_projects", "attachments_json", "TEXT")
    _safe_add("biz_projects", "ai_summary", "TEXT")
    _safe_add("biz_projects", "ai_summary_at", "TEXT")
    _safe_add("biz_projects", "recommend_label", "TEXT")
    _safe_add("biz_projects", "recommend_label_at", "TEXT")
    _safe_add("biz_projects", "period_text", "TEXT")
    _safe_add("biz_projects", "attachment_text", "TEXT")
    _safe_add("biz_projects", "source", "TEXT")
    _safe_add("biz_projects", "score", "REAL")
    _safe_add("biz_projects", "reason", "TEXT")
    _safe_add("biz_projects", "apply_url", "TEXT")
    _safe_add("biz_projects", "view_count", "INTEGER DEFAULT 0")
    _safe_add("companies", "social_enterprise", "INTEGER DEFAULT 0")
    _safe_add("companies", "female_ceo", "INTEGER DEFAULT 0")
    _safe_add("companies", "export_tower", "INTEGER DEFAULT 0")
    _safe_add("companies", "cert_count", "INTEGER DEFAULT 0")
    _safe_add("companies", "catalog_count", "INTEGER DEFAULT 0")
    _conn.commit()


@app.context_processor
def _inject_index_url() -> dict:
    """쿼리스트링을 유지한 채 `index` URL 생성 (필터 링크용)."""

    def index_url(**overrides: Any) -> str:
        d = request.args.to_dict(flat=True)
        for k, v in overrides.items():
            if v is None or (isinstance(v, str) and v.strip() == ""):
                d.pop(k, None)
            else:
                d[k] = str(v).strip() if isinstance(v, str) else v
        d = {k: v for k, v in d.items() if v is not None and str(v) != ""}
        return url_for("index", **d)

    return dict(index_url=index_url)


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── 백그라운드 파이프라인 패널: POST /api/run → subprocess run_all.py (/api/run*) ──
RUN_STATE: dict = {
    "running": False,
    "mode": None,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "pid": None,
}
RUN_LOCK = threading.Lock()
RUN_LOG: deque = deque(maxlen=500)

from pipeline.compare import compare_new
from pipeline.flask_ui_audit import (
    audit_ui_enabled,
    log_detail_consistency,
    log_source_mismatch_and_parser,
)
from pipeline.presenter import normalize_display_item
from pipeline.ui_view import (
    build_recommend_reason,
    filter_items,
    prepare_db_rows_for_ui,
    sort_recommend_items,
    sqlite_row_to_item,
)

REPORTS_DIR = BASE_DIR / "reports"
PIPELINE_SCRIPT = BASE_DIR / "pipeline" / "run_pipeline.py"

LOG_TAIL_CHARS = 6000

# UI 표기용 소스 한글 라벨. pipeline/ui_view.SOURCE_LABELS 와 동일 매핑.
# 템플릿 필터/요약카드에서 키 → 한글 변환시 사용.
SOURCE_LABELS = {
    "jbexport": "전북수출",
    "bizinfo": "기업마당",
    "kstartup": "K-Startup",
}


def _safe_parse_date(s: Any) -> Optional[date]:
    """'YYYY-MM-DD' 접두부만 파싱. 빈값/파싱 실패는 None. 예외 던지지 않음."""
    if not s:
        return None
    txt = str(s).strip()
    if len(txt) < 10:
        return None
    try:
        return datetime.strptime(txt[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _compute_ui_summary(items: List[dict]) -> dict:
    """
    인덱스 카드 요약 집계.
      - total    : 전체
      - open     : display_status == '접수중' 이거나
                   (end_date가 있고 오늘 이상이며 display_status not in ('마감',))
      - closed   : display_status == '마감' 이거나 end_date가 오늘 미만
      - unknown  : 그 외(확인 필요 등)
      - urgent   : open 중 end_date(ISO 문자열)가 오늘 ~ 오늘+3일(포함) 사이
    """
    today = date.today()
    today_str = today.isoformat()
    limit_str = (today + timedelta(days=3)).isoformat()
    total = len(items)
    open_n = closed_n = unknown_n = urgent_n = 0
    for it in items:
        st = (it.get("display_status") or "").strip()
        end = (it.get("end_date") or "").strip()
        if st == "접수중" or (end and end >= today_str and st not in ("마감",)):
            open_n += 1
            if end and today_str <= end <= limit_str:
                urgent_n += 1
        elif st == "마감" or (end and end < today_str):
            closed_n += 1
        else:
            unknown_n += 1
    return {
        "total": total,
        "open": open_n,
        "closed": closed_n,
        "unknown": unknown_n,
        "urgent": urgent_n,
    }


def _project_root() -> Path:
    return BASE_DIR


def _log_line(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with RUN_LOCK:
        RUN_LOG.append(line)


def _build_command(mode: str) -> List[str]:
    """UI 패널에서 run_all.py 를 --mode 와 함께 실행. notify 는 mailer.py 만."""
    root = _project_root()
    if mode == "notify":
        return [
            sys.executable,
            os.path.join(str(root), "mailer.py"),
        ]
    if mode in ("all", "jbexport", "bizinfo"):
        return [
            sys.executable,
            os.path.join(str(root), "run_all.py"),
            "--mode",
            mode,
        ]
    raise ValueError(f"unknown mode: {mode}")


def _pipeline_env_for_subprocess(cwd: str) -> dict:
    """자식 프로세스에 DB_PATH 등 전달 (Flask와 동일 DB 사용)."""
    env = os.environ.copy()
    raw = os.getenv("DB_PATH", "db/biz.db")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cwd) / p
    env["DB_PATH"] = str(p.resolve())
    return env


def _effective_pipeline_mode(requested: str) -> str:
    """Render 등에서 JBEXPORT 프록시(:5001)가 없으면 all → bizinfo 로 대체."""
    if requested != "all":
        return requested
    if os.getenv("PIPELINE_ALL_AS_BIZINFO", "").strip() in ("1", "true", "yes"):
        return "bizinfo"
    if (os.getenv("RENDER") or "").strip():
        return "bizinfo"
    return "all"


def _run_pipeline_background(mode: str) -> None:
    """서브프로세스를 백그라운드 스레드에서 실행하고 RUN_LOG 에 stdout 을 적재."""

    def worker() -> None:
        root = str(_project_root())
        eff = _effective_pipeline_mode(mode)
        cmd = _build_command(eff)
        env = _pipeline_env_for_subprocess(root)
        _log_line(
            f"[pipeline] 크롤링/파이프라인 시작 요청={mode} 실행={eff} DB_PATH={env.get('DB_PATH')}"
        )
        _log_line(f"cwd={root}")
        _log_line("$ " + " ".join(cmd))
        if mode == "all" and eff != "all":
            _log_line(
                "[pipeline] 안내: 이 환경에서는 JBEXPORT 프록시가 없어 "
                "기업마당(bizinfo) 수집·병합·DB 반영만 실행합니다."
            )
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            _log_line(f"[pipeline] Popen 실패: {e}")
            with RUN_LOCK:
                RUN_STATE["running"] = False
                RUN_STATE["returncode"] = -1
                RUN_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return

        with RUN_LOCK:
            RUN_STATE["pid"] = proc.pid

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                _log_line(line.rstrip("\r\n"))
            rc = proc.wait()
        except Exception as e:
            _log_line(f"[pipeline] 실행 중 오류: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            rc = -1

        with RUN_LOCK:
            RUN_STATE["running"] = False
            RUN_STATE["returncode"] = rc
            RUN_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _log_line(f"[pipeline] 서브프로세스 종료 코드: {rc}")
        try:
            conn = sqlite3.connect(env["DB_PATH"])
            try:
                row = conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()
                n = int(row[0]) if row else 0
                _log_line(f"[pipeline] DB insert/반영 후 biz_projects 총 {n}건")
            finally:
                conn.close()
        except Exception as e:
            _log_line(f"[pipeline] DB 건수 확인 실패: {e}")
        _log_line("[pipeline] 크롤링/파이프라인 종료")

    threading.Thread(target=worker, daemon=True).start()


def extract_spseq(item: dict) -> str:
    """spSeq 필드 또는 URL 쿼리에서 추출."""
    for k in ("spSeq", "SP_SEQ", "sp_seq"):
        v = item.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    for ukey in ("url", "detail_url", "detailUrl", "상세URL"):
        u = str(item.get(ukey) or "").strip()
        if not u:
            continue
        m = re.search(r"[?&]spSeq=([^&\s#]+)", u, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _jbexport_period_str(item: dict) -> str:
    rs = str(item.get("receipt_start") or "").strip()
    re_ = str(item.get("receipt_end") or "").strip()
    if rs or re_:
        if rs and re_:
            return f"{rs} ~ {re_}"
        return rs or re_
    sd = str(item.get("start_date") or "").strip()
    ed = str(item.get("end_date") or "").strip()
    if sd or ed:
        if sd and ed:
            return f"{sd} ~ {ed}"
        return sd or ed
    return ""


def _jbexport_status_str(item: dict) -> str:
    for k in ("status", "display_status", "raw_status"):
        v = item.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return "확인 필요"


def _jbexport_title_str(item: dict) -> str:
    t = str(item.get("title") or "").strip()
    if t:
        return t
    return str(item.get("공고제목") or "").strip()


def build_jbexport_api_rows(items: List[dict]) -> List[dict]:
    """jbexport_daily 목록 API가 기대하는 키(spSeq, title, period, status 등)로 변환."""
    rows: List[dict] = []
    for it in items:
        sp = extract_spseq(it)
        title = _jbexport_title_str(it)
        st = _jbexport_status_str(it)
        per = _jbexport_period_str(it)
        rows.append(
            {
                "spSeq": sp,
                "SP_SEQ": sp,
                "js_title": title,
                "title": title,
                "STS_TXT": st,
                "status": st,
                "period": per,
                "PERIOD": per,
            }
        )
    return rows


def get_db():
    if "db" not in g:
        _init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def clamp_int(value, min_value=0, max_value=5):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    return max(min_value, min(max_value, n))


def check_window_limit(
    conn: sqlite3.Connection,
    visitor_id: str,
    user_ip: str,
    action: str = "recommend",
    limit: int = 5,
    window_hours: int = 12,
) -> Tuple[bool, int, Optional[str]]:
    rows = conn.execute(
        """
        SELECT created_at FROM user_request_log
        WHERE created_at >= datetime('now', 'localtime', ?)
          AND action = ?
          AND (visitor_id = ? OR user_ip = ?)
        ORDER BY created_at ASC
        """,
        (f"-{window_hours} hours", action, visitor_id, user_ip),
    ).fetchall()

    count = len(rows)
    if count < limit:
        return True, count, None

    oldest = rows[0][0]
    reset_row = conn.execute(
        "SELECT datetime(?, ?)", (oldest, f"+{window_hours} hours")
    ).fetchone()
    reset_at = reset_row[0] if reset_row else None
    return False, count, reset_at


def save_user_request_log(
    conn: sqlite3.Connection,
    visitor_id: str,
    user_ip: str,
    action: str = "recommend",
) -> None:
    conn.execute(
        """
        INSERT INTO user_request_log (visitor_id, user_ip, action, created_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        """,
        (visitor_id, user_ip, action),
    )
    conn.commit()


def get_or_create_visitor_id() -> str:
    raw = request.cookies.get("visitor_id")
    if raw and str(raw).strip():
        return str(raw).strip()
    return str(uuid.uuid4())


def get_visitor_id() -> str:
    vid = request.cookies.get("visitor_id")
    if not vid or not str(vid).strip():
        return str(uuid.uuid4())
    return str(vid).strip()


def get_usage_status(
    conn: sqlite3.Connection,
    visitor_id: str,
    user_ip: str,
    action: str = "recommend",
    limit: int = 5,
    window_hours: int = 12,
) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM user_request_log
        WHERE created_at >= datetime('now', 'localtime', ?)
          AND action = ?
          AND (visitor_id = ? OR user_ip = ?)
        """,
        (f"-{window_hours} hours", action, visitor_id, user_ip),
    ).fetchone()
    used_count = row[0] if row else 0
    remaining = max(0, limit - used_count)
    return {
        "used_count": used_count,
        "remaining": remaining,
        "limit": limit,
        "window_hours": window_hours,
    }


def clean_display_title(title: Any, fallback: str = "공고 상세보기") -> str:
    s = str(title or "").strip()
    if not s:
        return fallback
    if s.lower().startswith("spseq="):
        return fallback
    if "spseq=" in s.lower() and len(s) < 80:
        return fallback
    return s


def clean_admin_title(title: Any, fallback: str = "공고 상세보기") -> str:
    s = str(title or "").strip()
    if not s:
        return fallback
    if s.lower().startswith("spseq="):
        return fallback
    if "spseq=" in s.lower() and len(s) < 100:
        return fallback
    return s


def resolve_click_log_title(project_title: Any, log_title: Any) -> str:
    """biz_projects.title 우선, 없을 때만 click_log.title 정리(spSeq 등) 후 fallback."""
    pt = str(project_title or "").strip()
    if pt:
        return pt
    return clean_admin_title(log_title)


def load_top_clicked_projects(limit: int = 5) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT
                cl.project_id,
                COALESCE(NULLIF(bp.title, ''), cl.title) AS title,
                COALESCE(NULLIF(bp.source, ''), cl.source) AS source,
                SUM(CASE WHEN cl.action = 'apply' THEN 3 ELSE 1 END) AS score,
                COUNT(*) AS click_count,
                SUM(CASE WHEN cl.action = 'apply' THEN 1 ELSE 0 END) AS apply_count,
                SUM(CASE WHEN cl.action = 'detail' THEN 1 ELSE 0 END) AS detail_count
            FROM click_log cl
            LEFT JOIN biz_projects bp
                ON CAST(bp.id AS TEXT) = CAST(cl.project_id AS TEXT)
            WHERE cl.created_at >= datetime('now', '-30 days')
            GROUP BY cl.project_id,
                COALESCE(NULLIF(bp.title, ''), cl.title),
                COALESCE(NULLIF(bp.source, ''), cl.source)
            ORDER BY score DESC, click_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        out = [
            dict(
                zip(
                    [
                        "project_id",
                        "title",
                        "source",
                        "score",
                        "click_count",
                        "apply_count",
                        "detail_count",
                    ],
                    r,
                )
            )
            for r in rows
        ]
        for item in out:
            item["title"] = clean_display_title(item.get("title"))
        return out
    except Exception:
        return []


get_top_clicked_projects = load_top_clicked_projects


def get_today_top_projects(limit: int = 5):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT project_id, COUNT(*) as cnt
                FROM click_log
                WHERE date(created_at, 'localtime') = date('now', 'localtime')
                GROUP BY project_id
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows
    except Exception as e:
        print("[today_top] error:", repr(e), flush=True)
        return []


@app.teardown_appcontext
def close_db(_error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _prepare_detail_row_for_template(row: sqlite3.Row) -> dict:
    """목록과 동일 sqlite_row_to_item 경로 + description·첨부 보강."""
    d = sqlite_row_to_item(row)
    desc = d.get("description")
    d["description"] = "" if desc is None else str(desc)
    aj = d.get("attachments_json")
    if aj is not None and str(aj).strip():
        try:
            parsed = json.loads(str(aj))
            if isinstance(parsed, list):
                d["attachments"] = parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return d


@app.route("/api/click", methods=["POST"])
def api_click():
    try:
        _init_db()
        data = request.get_json(silent=True) or {}
        project_id = str(data.get("project_id") or "")
        action = str(data.get("action") or "")
        source = str(data.get("source") or "")
        title = str(data.get("title") or "")
        traffic_source = detect_traffic_source()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO click_log (project_id, action, source, title, traffic_source) VALUES (?,?,?,?,?)",
            (project_id, action, source, title, traffic_source),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/api/favorite", methods=["POST"])
def api_favorite():
    data = request.get_json(silent=True) or {}
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
    project_id = str(data.get("project_id") or "")
    title = data.get("title") or ""
    source = data.get("source") or ""
    act = (str(data.get("action") or "add")).strip().lower()
    if act not in ("add", "remove"):
        act = "add"
    if not project_id:
        return jsonify({"ok": False, "error": "missing_project_id"})
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        if act == "remove":
            conn.execute(
                "DELETE FROM favorite_projects WHERE visitor_id = ? AND project_id = ?",
                (visitor_id, project_id),
            )
            conn.commit()
            favorited = False
            out_action = "removed"
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO favorite_projects
                (visitor_id, project_id, title, source)
                VALUES (?, ?, ?, ?)
                """,
                (visitor_id, project_id, title, source),
            )
            conn.commit()
            favorited = True
            out_action = "added"
    finally:
        conn.close()
    resp = make_response(jsonify({"ok": True, "action": out_action, "favorited": favorited}))
    resp.set_cookie(
        "visitor_id",
        visitor_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/api/favorite/list", methods=["GET"])
def api_favorite_list():
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        return jsonify({"ids": []})
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT project_id FROM favorite_projects
            WHERE visitor_id = ?
            ORDER BY created_at DESC
            """,
            (visitor_id,),
        ).fetchall()
        ids = [str(r[0]) for r in rows if r[0] is not None]
    finally:
        conn.close()
    return jsonify({"ids": ids})


def detect_traffic_source():
    try:
        ref = (request.headers.get("Referer") or "").lower()
        ua = (request.headers.get("User-Agent") or "").lower()
        url = (request.url or "").lower()
        src = (request.args.get("src") or request.args.get("utm_source") or "").lower().strip()
        if src in ("kakao", "qr", "naver", "google", "direct", "test"):
            return src
        if "kakao" in ref or "kakaotalk" in ua or "kakao" in ua:
            return "kakao"
        if "utm_source=qr" in url or "src=qr" in url:
            return "qr"
        if not ref:
            return "direct"
        if "google" in ref:
            return "google"
        if "naver" in ref:
            return "naver"
        return "other"
    except Exception as e:
        print("[traffic_source] detect error:", repr(e), flush=True)
        return "unknown"


def check_admin(req: Any) -> bool:
    if (req.args.get("key") or "").strip() == ADMIN_KEY:
        return True
    body = req.get_json(silent=True)
    if isinstance(body, dict) and str(body.get("key") or "").strip() == ADMIN_KEY:
        return True
    return False


def get_today_visit_count():
    """오늘 방문자 수(고유 IP). visit_log 행 수(PV)가 아님 — admin_dashboard 와 동일 기준."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT ip) FROM visit_log "
                "WHERE date(created_at,'localtime')=date('now','localtime')"
            ).fetchone()
            return row[0] if row else 0
    except Exception as e:
        print("[visit_log] count error:", repr(e), flush=True)
        return 0


@app.route("/admin")
def admin_dashboard():
    if not check_admin(request):
        return "403 Forbidden", 403

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()[0]
    by_source = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM biz_projects GROUP BY source"
    ).fetchall()
    by_status = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM biz_projects GROUP BY status"
    ).fetchall()
    co_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    consent_count = conn.execute("SELECT COUNT(*) FROM consent_logs").fetchone()[0]
    click_count = conn.execute("SELECT COUNT(*) FROM click_log").fetchone()[0]
    req_count = conn.execute("SELECT COUNT(*) FROM user_request_log").fetchone()[0]

    recent_companies = conn.execute(
        "SELECT id, company_name, industry, region, created_at "
        "FROM companies ORDER BY id DESC LIMIT 10"
    ).fetchall()
    recent_clicks = conn.execute(
        """
        SELECT cl.project_id, cl.action, cl.source,
          COALESCE(NULLIF(bp.title,''), cl.title) AS title, cl.created_at
        FROM click_log cl
        LEFT JOIN biz_projects bp ON CAST(bp.id AS TEXT) = CAST(cl.project_id AS TEXT)
        ORDER BY cl.id DESC LIMIT 20
        """
    ).fetchall()
    top_projects = conn.execute(
        """
        SELECT cl.project_id,
          COALESCE(NULLIF(bp.title,''), cl.title) AS title,
          COUNT(*) AS cnt
        FROM click_log cl
        LEFT JOIN biz_projects bp ON CAST(bp.id AS TEXT) = CAST(cl.project_id AS TEXT)
        GROUP BY cl.project_id, COALESCE(NULLIF(bp.title,''), cl.title)
        ORDER BY cnt DESC LIMIT 20
        """
    ).fetchall()

    visit_today_raw = conn.execute(
        "SELECT COUNT(*) FROM visit_log WHERE date(created_at,'localtime')=date('now','localtime')"
    ).fetchone()[0]
    visit_today_unique = conn.execute(
        "SELECT COUNT(DISTINCT ip) FROM visit_log WHERE date(created_at,'localtime')=date('now','localtime')"
    ).fetchone()[0]
    visit_total_raw = conn.execute("SELECT COUNT(*) FROM visit_log").fetchone()[0]
    visit_total_unique = conn.execute("SELECT COUNT(DISTINCT ip) FROM visit_log").fetchone()[0]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        admin_key=ADMIN_KEY,
        total=total,
        by_source=by_source,
        by_status=by_status,
        co_count=co_count,
        consent_count=consent_count,
        click_count=click_count,
        req_count=req_count,
        visit_today_raw=visit_today_raw,
        visit_today_unique=visit_today_unique,
        visit_total_raw=visit_total_raw,
        visit_total_unique=visit_total_unique,
        recent_companies=recent_companies,
        recent_clicks=recent_clicks,
        top_projects=top_projects,
    )


@app.route("/admin/visits")
def admin_visits():
    if not check_admin(request):
        return "403 Forbidden", 403
    try:
        with sqlite3.connect(DB_PATH) as conn:
            today = conn.execute(
                "SELECT COUNT(*) FROM visit_log WHERE date(created_at,'localtime')=date('now','localtime')"
            ).fetchone()[0]
            by_path = conn.execute(
                "SELECT path, COUNT(*) as cnt FROM visit_log WHERE date(created_at,'localtime')=date('now','localtime') GROUP BY path ORDER BY cnt DESC LIMIT 20"
            ).fetchall()
        return jsonify({
            "ok": True,
            "today_visits": today,
            "by_path": [{"path": p, "count": c} for p, c in by_path],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": repr(e)}), 500


@app.route("/admin/traffic")
def admin_traffic():
    if not check_admin(request):
        return "403 Forbidden", 403
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT traffic_source, COUNT(*) as cnt
                FROM visit_log
                WHERE date(created_at, 'localtime') = date('now', 'localtime')
                GROUP BY traffic_source
                ORDER BY cnt DESC
            """).fetchall()
        total = sum(r[1] for r in rows)
        return render_template("admin_traffic.html", rows=rows, total=total)
    except Exception as e:
        return f"ERROR: {e}"


@app.route("/admin/status-debug")
def admin_status_debug():
    if not check_admin(request):
        return "unauthorized", 403
    try:
        from datetime import date

        today = date.today().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(biz_projects)"
            ).fetchall()]
            ds_col = "display_status" if "display_status" in cols else "status"
            rows = conn.execute(f"""
                SELECT id, source,
                       substr(title,1,40) as title,
                       end_date,
                       {ds_col} as display_status
                FROM biz_projects
                ORDER BY id DESC
                LIMIT 50
            """).fetchall()
        result = []
        for r in rows:
            end = (r["end_date"] or "").strip()
            ds = (r["display_status"] or "").strip()
            if not end or end in ("-","None","null",""):
                calc = "확인 필요"
            elif end >= today:
                calc = "접수중"
            else:
                calc = "마감"
            result.append({
                "end_date": end,
                "display_status": ds,
                "calc": calc,
            })
        return jsonify({"today": today, "sample": result[:10]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/clicks")
def admin_clicks():
    """클릭 로그 확인용(비로그인). DB 저장만 하던 기록을 표로 확인."""
    if not check_admin(request):
        return "403 Forbidden", 403
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    recent_raw = cur.execute(
        """
        SELECT
            cl.id, cl.project_id, cl.action,
            COALESCE(NULLIF(bp.source, ''), cl.source) AS source,
            bp.title AS project_title,
            cl.title AS log_title,
            cl.created_at
        FROM click_log cl
        LEFT JOIN biz_projects bp
            ON CAST(bp.id AS TEXT) = CAST(cl.project_id AS TEXT)
        ORDER BY cl.id DESC LIMIT 100
        """
    ).fetchall()
    recent_clicks = [
        {
            "id": r[0],
            "project_id": r[1],
            "action": r[2] or "",
            "source": r[3] or "",
            "display_title": resolve_click_log_title(r[4], r[5]),
            "created_at": r[6],
        }
        for r in recent_raw
    ]
    action_counts = cur.execute(
        "SELECT action, COUNT(*) AS cnt FROM click_log GROUP BY action ORDER BY cnt DESC"
    ).fetchall()
    source_counts = cur.execute(
        "SELECT source, COUNT(*) AS cnt FROM click_log GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    top_raw = cur.execute(
        """
        SELECT
            cl.project_id,
            (SELECT p.title FROM biz_projects p
             WHERE CAST(p.id AS TEXT) = CAST(cl.project_id AS TEXT) LIMIT 1) AS project_title,
            (SELECT c2.title FROM click_log c2
             WHERE CAST(c2.project_id AS TEXT) = CAST(cl.project_id AS TEXT)
             ORDER BY c2.id DESC LIMIT 1) AS log_title,
            COUNT(*) AS cnt
        FROM click_log cl
        GROUP BY cl.project_id
        ORDER BY cnt DESC
        LIMIT 20
        """
    ).fetchall()
    top_projects = [
        {
            "project_id": r[0],
            "display_title": resolve_click_log_title(r[1], r[2]),
            "cnt": r[3],
        }
        for r in top_raw
    ]
    conn.close()
    return render_template(
        "admin_clicks.html",
        recent_clicks=recent_clicks,
        action_counts=action_counts,
        source_counts=source_counts,
        top_projects=top_projects,
    )


@app.route("/api/jbexport/list", methods=["POST"])
def api_jbexport_list():
    """JBEXPORT 목록 (DataTables 형식). DB biz_projects 의 jbexport 행만 사용."""
    draw = 1
    try:
        body = request.get_json(silent=True) or {}
        draw = int(body.get("draw", 1))
        start = max(0, int(body.get("start", 0)))
        length = int(body.get("length", 10))
        if length <= 0:
            length = 10
        if length > 10000:
            length = 10000

        db = get_db()
        cur = db.execute(
            """
            SELECT title, status, url, start_date, end_date,
                   receipt_start, receipt_end, raw_status
            FROM biz_projects
            WHERE LOWER(TRIM(COALESCE(source, ''))) = 'jbexport'
            ORDER BY id DESC
            """
        )
        jb = [dict(r) for r in cur.fetchall()]
        rows = build_jbexport_api_rows(jb)
        total = len(rows)
        page = rows[start : start + length]
        return jsonify(
            {
                "draw": draw,
                "recordsTotal": total,
                "recordsFiltered": total,
                "data": page,
            }
        )
    except Exception as e:
        return jsonify(
            {
                "draw": draw,
                "recordsTotal": 0,
                "recordsFiltered": 0,
                "data": [],
                "error": str(e),
            }
        )


@app.route("/")
def index():
    # 필터는 UI 레이어(ui_view.filter_items)에서만 처리.
    # status 는 infer_status() 기반 display_status 기준이므로 DB raw status 로 SQL 필터를 걸지 않는다.
    # status 미지정·"전체" 는 상태 필터 해제.
    tab = (request.args.get("tab") or "").strip()

    status = (request.args.get("status") or "").strip()
    source = (request.args.get("source") or "").strip()
    query = (request.args.get("q") or "").strip()
    deadline = (request.args.get("deadline") or "").strip()
    recent = (request.args.get("recent") or "").strip()
    has_ai_summary = (request.args.get("has_ai_summary") or "").strip()
    has_recommend_label = (request.args.get("has_recommend_label") or "").strip()
    has_attachments = (request.args.get("has_attachments") or "").strip()
    category = (request.args.get("category") or "").strip()

    if tab == "recommend":
        has_recommend_label = "1"

    status_filter = "" if status in ("", "전체") else status
    source_filter = "" if source in ("", "전체") else source.lower()
    fq = request.args.to_dict(flat=True)
    if tab:
        fq["tab"] = tab
    else:
        fq.pop("tab", None)

    sql = """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        WHERE 1=1
    """
    params: list = []

    if query:
        sql += " AND (title LIKE ? OR organization LIKE ? OR description LIKE ?)"
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q])

    rows = get_db().execute(sql, params).fetchall()
    rows_ui = prepare_db_rows_for_ui(rows)
    rows_ui = filter_items(
        rows_ui,
        status=status_filter,
        source=source_filter,
        q=query,
        deadline=deadline or None,
        recent=recent or None,
        has_ai_summary=has_ai_summary or None,
        has_recommend_label=has_recommend_label or None,
        has_attachments=has_attachments or None,
        category=category or None,
    )
    if tab == "recommend":
        rows_ui = sort_recommend_items(rows_ui)
    summary = _compute_ui_summary(rows_ui)
    if audit_ui_enabled():
        log_source_mismatch_and_parser(rows_ui[:10], label="GET / (목록 10)")
        db = get_db()
        for r in rows_ui[:5]:
            rid = r.get("id")
            if rid is not None:
                log_detail_consistency(
                    db,
                    int(rid),
                    prepare_row=_prepare_detail_row_for_template,
                    normalize_item=normalize_display_item,
                )
    today_top = get_today_top_projects()
    today_ids = {row[0] for row in today_top}
    items = rows_ui
    id_set = {str(x) for x in today_ids}
    matched = [item for item in items if str(item.get("id")) in id_set]
    by_id = {str(i.get("id")): i for i in matched}
    top_clicked = []
    for project_id, cnt in today_top:
        item = by_id.get(str(project_id))
        if item is None:
            continue
        top_clicked.append(
            dict(
                project_id=item["id"],
                title=clean_display_title(item.get("display_title") or item.get("title")),
                source=str(item.get("source") or item.get("source_badge") or ""),
                score=cnt,
                click_count=cnt,
                apply_count=0,
                detail_count=cnt,
            )
        )
    if not top_clicked:
        top_clicked = get_top_clicked_projects()
    visitor_id = get_or_create_visitor_id()
    user_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if user_ip and "," in user_ip:
        user_ip = user_ip.split(",")[0].strip()
    conn = sqlite3.connect(DB_PATH)
    try:
        usage = get_usage_status(conn, visitor_id, user_ip)
    finally:
        conn.close()
    resp = make_response(
        render_template(
            "new.html",
            items=rows_ui,
            rows=rows_ui,
            count=len(rows_ui),
            err=None,
            status=status,
            source=source,
            q=query,
            deadline=deadline,
            recent=recent,
            has_ai_summary=has_ai_summary,
            has_recommend_label=has_recommend_label,
            has_attachments=has_attachments,
            category=category,
            tab=tab,
            fq=fq,
            summary=summary,
            source_labels=SOURCE_LABELS,
            top_clicked=top_clicked,
            usage=usage,
            is_admin=False,
            today_visits=get_today_visit_count(),
        )
    )
    resp.set_cookie(
        "visitor_id",
        visitor_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/favorites")
def favorites_list():
    visitor_id = get_or_create_visitor_id()
    _init_db()
    sql = """
        SELECT b.id, b.title, b.organization, b.start_date, b.end_date, b.status, b.url, b.description, b.ai_result, b.pdf_path,
               b.ministry, b.executing_agency, b.source,
               b.receipt_start, b.receipt_end, b.biz_start, b.biz_end, b.raw_status, b.attachments_json,
               b.ai_summary, b.ai_summary_at, b.recommend_label, b.recommend_label_at
        FROM favorite_projects f
        INNER JOIN biz_projects b ON CAST(b.id AS TEXT) = TRIM(f.project_id)
        WHERE f.visitor_id = ?
        ORDER BY f.created_at DESC
        """
    rows = get_db().execute(sql, (visitor_id,)).fetchall()
    items_ui = prepare_db_rows_for_ui(rows)
    resp = make_response(
        render_template(
            "favorites.html",
            items=items_ui,
            count=len(items_ui),
            source_labels=SOURCE_LABELS,
            is_admin=False,
        )
    )
    resp.set_cookie(
        "visitor_id",
        visitor_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/admin/pipeline")
def admin_pipeline():
    if not check_admin(request):
        return "403 Forbidden", 403
    return _render_new_announcements_page(is_admin=True)


@app.route("/company", methods=["GET", "POST"])
def company():
    if request.method == "GET":
        return render_template("company_form.html", is_admin=False)

    company_name = (request.form.get("company_name") or "").strip()
    if not company_name:
        flash("회사명은 필수입니다.", "danger")
        return render_template("company_form.html", is_admin=False), 400

    industry = (request.form.get("industry") or "").strip()
    region = (request.form.get("region") or "").strip()
    employee_count = (request.form.get("employee_count") or "").strip()
    revenue = (request.form.get("revenue") or "").strip()
    export_flag = (request.form.get("export_flag") or "").strip()
    export_amount = request.form.get("export_amount", "").strip()
    business_number = request.form.get("business_number", "").strip()

    db = get_db()
    cur = db.execute(
        """
        INSERT INTO companies (
            company_name, industry, region, employee_count, revenue, export_flag,
            export_amount, business_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_name,
            industry,
            region,
            employee_count,
            revenue,
            export_flag,
            export_amount,
            business_number,
        ),
    )
    db.commit()
    new_cid = int(cur.lastrowid or 0)
    flash("회사 정보가 저장되었습니다.", "success")
    return redirect(url_for("recommend", company_id=new_cid) if new_cid else url_for("recommend"))


@app.route("/company/form", methods=["GET"])
def company_form_page():
    return redirect("/company")


@app.route("/company/save", methods=["POST"])
def save_company():
    _init_db()
    vid = get_visitor_id()
    company_name = (request.form.get("company_name") or "").strip()
    if not company_name:
        return redirect("/company")
    industry = request.form.get("industry") or ""
    industry_other = (request.form.get("industry_other") or "").strip()
    if industry == "기타" and industry_other:
        industry = industry_other
    industry = (industry or "").strip() or None
    region = (request.form.get("region") or "").strip() or None
    try:
        export_flag = int(request.form.get("export_flag", 0) or 0)
    except (TypeError, ValueError):
        export_flag = 0
    keywords = (request.form.get("interest_keywords") or "").strip() or None
    consent = 1 if request.form.get("consent") else 0

    cert_count = clamp_int(request.form.get("cert_count"), 0, 5)
    catalog_count = clamp_int(request.form.get("catalog_count"), 0, 5)
    social_enterprise = 1 if request.form.get("social_enterprise") else 0
    female_ceo = 1 if request.form.get("female_ceo") else 0
    export_tower = 1 if request.form.get("export_tower") else 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO companies
        (visitor_id, company_name, industry, region, export_flag,
         interest_keywords, consent_accepted, consent_version,
         cert_count, catalog_count, social_enterprise, female_ceo, export_tower)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            vid,
            company_name,
            industry,
            region,
            export_flag,
            keywords,
            consent,
            "v1",
            cert_count,
            catalog_count,
            social_enterprise,
            female_ceo,
            export_tower,
        ),
    )
    company_id = int(cur.lastrowid or 0)
    xf = (request.headers.get("X-Forwarded-For") or "").strip()
    if xf:
        user_ip = xf.split(",")[0].strip()
    else:
        user_ip = (request.remote_addr or "").strip()
    cur.execute(
        """
        INSERT INTO consent_logs (visitor_id, company_id, consent_text, user_ip)
        VALUES (?,?,?,?)
        """,
        (vid, company_id, "AI 추천을 위한 기업정보 수집 동의", user_ip),
    )
    conn.commit()
    conn.close()

    resp = make_response(redirect("/recommend"))
    resp.set_cookie(
        "visitor_id", vid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax"
    )
    return resp


@app.route("/projects")
def projects_list():
    rows = get_db().execute(
        """
        SELECT id, title, organization, start_date, end_date, status, url, description,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        ORDER BY COALESCE(end_date, '9999-12-31') DESC
        """
    ).fetchall()
    rows_ui = prepare_db_rows_for_ui(rows)
    if audit_ui_enabled():
        log_source_mismatch_and_parser(rows_ui[:10], label="GET /projects (목록 10)")
    return render_template("projects.html", rows=rows_ui, is_admin=False)


@app.route("/project/<int:pid>")
def project_detail(pid):
    row = get_db().execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("projects_list"))

    items = prepare_db_rows_for_ui([dict(row)], audit=False)
    item = items[0]
    item["recommend_reason"] = build_recommend_reason(item)
    if audit_ui_enabled():
        log_detail_consistency(
            get_db(),
            pid,
            prepare_row=_prepare_detail_row_for_template,
            normalize_item=normalize_display_item,
        )
    return render_template(
        "project_detail.html",
        item=item,
        source_labels=SOURCE_LABELS,
        is_admin=False,
    )


@app.route("/detail/<int:pid>")
def detail(pid):
    row = get_db().execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("index"))

    items = prepare_db_rows_for_ui([dict(row)], audit=False)
    item = items[0]
    item["recommend_reason"] = build_recommend_reason(item)
    if audit_ui_enabled():
        log_detail_consistency(
            get_db(),
            pid,
            prepare_row=_prepare_detail_row_for_template,
            normalize_item=normalize_display_item,
        )
    return render_template(
        "project_detail.html",
        item=item,
        source_labels=SOURCE_LABELS,
        is_admin=False,
    )


@app.route("/analyze/<int:pid>")
def analyze(pid):
    db = get_db()
    row = db.execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("index"))

    ai_result = analyze_project(row["title"], row["description"] or "")
    notice = {
        "title": row["title"] or "",
        "url": row["url"] or "",
        "source": str(row["source"] or "").strip(),
        "organization": row["organization"] or "",
        "ministry": str(row["ministry"] or "").strip(),
        "executing_agency": str(row["executing_agency"] or "").strip(),
        "start_date": row["start_date"] or "",
        "end_date": row["end_date"] or "",
        "description": row["description"] or "",
    }
    pdf_full_path = create_pdf(row["title"], ai_result, notice=notice)
    pdf_filename = Path(pdf_full_path).name

    db.execute(
        """
        UPDATE biz_projects
        SET ai_result = ?, pdf_path = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (ai_result, pdf_filename, pid),
    )
    db.commit()

    return render_template(
        "ai_result.html",
        row=row,
        ai_result=ai_result,
        pdf_filename=pdf_filename,
    )


@app.route("/send_email/<int:pid>")
def send_email_route(pid):
    db = get_db()
    row = db.execute(
        """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("index"))

    if not row["pdf_path"]:
        flash("PDF가 없어 AI 분석을 먼저 실행합니다.", "info")
        return redirect(url_for("analyze", pid=pid))

    to_email = os.getenv("MAIL_TO", "").strip()
    if not to_email:
        flash("MAIL_TO 환경변수를 설정해 주세요.", "danger")
        return redirect(url_for("detail", pid=pid))

    file_path = str(REPORTS_DIR / row["pdf_path"])
    subject = f"[AI 분석 결과] {row['title']}"
    content = f"{row['title']} 공고의 AI 분석 결과 PDF를 첨부합니다."

    try:
        do_send(
            to_email=to_email,
            subject=subject,
            content=content,
            file_path=file_path,
        )
    except Exception as exc:
        flash(f"이메일 발송 실패: {exc}", "danger")
        return redirect(url_for("detail", pid=pid))

    flash("이메일이 발송되었습니다.", "success")
    return redirect(url_for("detail", pid=pid))


@app.route("/download/<path:fname>")
def download(fname):
    return send_from_directory(str(REPORTS_DIR), fname, as_attachment=False)


def _parse_employee_number(raw: Optional[str]) -> Optional[int]:
    if raw is None or not str(raw).strip():
        return None
    m = re.search(r"\d+", str(raw))
    return int(m.group(0)) if m else None


def _calc_score(company: Any, proj: Any) -> Tuple[int, List[str]]:
    """
    company, proj: sqlite3.Row
    반환: (점수, 사유 문구 리스트)
    """
    score = 0
    reasons: List[str] = []

    title = str(proj["title"] or "")
    desc = str(proj["description"] or "")
    org = str(proj["organization"] or "")
    blob_all = title + " " + desc + " " + org

    region = str(company["region"] or "").strip()
    if region and region in blob_all:
        score += 1
        reasons.append(
            f"「{region}」 지역이 공고 제목·설명·기관에 반영되어 지역 조건에 맞아 추천"
        )

    industry_raw = str(company["industry"] or "").strip()
    if industry_raw:
        parts = [p.strip() for p in re.split(r"[,，/|]", industry_raw) if p.strip()]
        if not parts:
            parts = [industry_raw]
        hit = any((kw in title or kw in desc) for kw in parts if kw)
        if hit:
            score += 2
            reasons.append("업종 키워드가 공고 설명·제목과 일치하여 추천")

    _ef = company["export_flag"]
    is_export = False
    if _ef is not None:
        s = str(_ef).strip()
        is_export = s == "예" or s in ("1", "true", "True") or _ef == 1
    if is_export:
        export_kws = ("수출", "해외", "바이어", "전시회")
        if any(k in desc for k in export_kws):
            score += 2
            reasons.append("수출 기업에 맞게 공고에 수출·해외 관련 키워드가 포함되어 추천")

    emp_n = _parse_employee_number(company["employee_count"])
    if emp_n is not None and emp_n < 50:
        smb_kws = ("소기업", "소상공인", "중소")
        if any(k in desc for k in smb_kws):
            score += 1
            reasons.append("소기업 우대 조건이 있어 추천")

    return score, reasons


def _company_export_int(company: Any) -> int:
    ef = company["export_flag"] if company is not None else None
    if ef is None:
        return 0
    if isinstance(ef, int):
        return 1 if ef == 1 else 0
    s = str(ef).strip()
    if s in ("1", "예", "true", "True"):
        return 1
    return 0


def _recommend_score_projects_top20(
    company: Any, db: Any
) -> Tuple[List[dict], int, int, str]:
    """
    접수중 공고만 조회 → 점수/이유 → 전체 후보 수·TOP 20.
    state: 'ok' | 'no_projects'
    """
    rows = db.execute(
        """
        SELECT id, title, organization, status, end_date, source,
               description, ai_summary, url
        FROM biz_projects
        WHERE status = '접수중'
        LIMIT 500
        """
    ).fetchall()
    if not rows:
        return [], 0, 0, "no_projects"

    results: List[dict] = []
    for p in rows:
        score = 0
        reasons: List[str] = []
        text = " ".join(
            [
                str(p["title"] or ""),
                str(p["description"] or ""),
                str(p["ai_summary"] or ""),
                str(p["organization"] or ""),
            ]
        )
        c = company
        if c:
            reg = (c["region"] or "") if c["region"] is not None else ""
            if reg and reg in text:
                score += 30
                reasons.append(f"{reg} 지역 관련 공고")

            if _company_export_int(c) == 1 and any(
                k in text for k in ("수출", "해외", "바이어", "FTA", "무역")
            ):
                score += 30
                reasons.append("수출기업 관련 공고")

            ind = (c["industry"] or "") if c["industry"] is not None else ""
            if ind and ind in text:
                score += 20
                reasons.append(f"{ind} 업종 관련 공고")

            ikw = c["interest_keywords"] if c["interest_keywords"] is not None else None
            if ikw:
                for kw in str(ikw).replace(",", " ").split():
                    if kw and kw in text:
                        score += 10
                        reasons.append(f"관심 키워드 '{kw}' 포함")
                        break

        score = min(score, 100)
        if not reasons:
            reasons.append("기본 조건 기준 검토 대상")
        t = p["title"] or ""
        results.append(
            {
                "id": p["id"],
                "title": t,
                "display_title": t,
                "organization": p["organization"] or "",
                "status": p["status"] or "",
                "end_date": p["end_date"] or "",
                "score": score,
                "reasons": reasons[:3],
                "reason": " · ".join(reasons[:3]),
                "source": p["source"] or "",
                "url": p["url"] or "",
            }
        )

    total_candidates = len(results)
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = results[:20]
    shown_count = len(results)
    return results, total_candidates, shown_count, "ok"


def _recommend_data(
    db: Any,
    company_id: Optional[int] = None,
    visitor_id: Optional[str] = None,
) -> Tuple[Optional[Any], List[dict], str, int, int]:
    """
    추천 목록: recommendations 테이블이 있으면 우선 사용, 없으면 규칙 기반 즉시 계산(레거시).
    반환: (company_row | None, items, state, total_candidates, shown_count)
    state: no_company | no_projects | ok
    """
    _cols = (
        "id, company_name, industry, region, employee_count, revenue, export_flag, created_at, "
        "visitor_id, interest_keywords, consent_accepted, consent_version"
    )
    cnt = db.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"]
    if cnt == 0:
        return None, [], "no_company", 0, 0

    company: Any = None
    if company_id is not None:
        company = db.execute(
            f"""
            SELECT {_cols}
            FROM companies
            WHERE id = ?
            """,
            (int(company_id),),
        ).fetchone()
        if company is None:
            return None, [], "no_company", 0, 0
    elif visitor_id and str(visitor_id).strip():
        company = db.execute(
            f"""
            SELECT {_cols}
            FROM companies
            WHERE visitor_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(visitor_id).strip(),),
        ).fetchone()
    if company is None:
        company = db.execute(
            f"""
            SELECT {_cols}
            FROM companies
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if company is None:
        return None, [], "no_company", 0, 0

    recs = db.execute(
        """
        SELECT
            p.id,
            p.title,
            p.ministry,
            p.executing_agency,
            p.organization,
            p.start_date,
            p.end_date,
            p.url,
            p.source,
            p.status,
            r.score,
            r.reason
        FROM recommendations r
        JOIN biz_projects p ON r.project_id = p.id
        WHERE r.company_id = ?
        ORDER BY r.score DESC
        LIMIT 80
        """,
        (company["id"],),
    ).fetchall()

    if recs:

        def _item_from_rec(row: Any) -> dict:
            reason_str = (row["reason"] or "").strip()
            parts = [x.strip() for x in reason_str.split(" / ")] if reason_str else []
            parts = [x for x in parts if x]
            if not parts:
                parts = ["기본 조건 기준 검토 대상"]
            rsn = parts[:3]
            sd = str(row["start_date"] or "").strip()
            ed = str(row["end_date"] or "").strip()
            period = f"{sd or '—'} ~ {ed or '—'}" if (sd or ed) else "—"
            t = row["title"] or ""
            return {
                "id": row["id"],
                "title": t,
                "display_title": t,
                "organization": row["organization"] or "",
                "ministry": row["ministry"] or "",
                "executing_agency": row["executing_agency"] or "",
                "period": period,
                "score": int(row["score"] or 0),
                "reason": " · ".join(rsn),
                "reasons": rsn,
                "source": str(row["source"] or ""),
                "url": row["url"] or "",
                "pdf_path": None,
                "status": str(row["status"] or ""),
                "end_date": str(row["end_date"] or ""),
            }

        n_all = len(recs)
        rec_list = [_item_from_rec(r) for r in recs]
        rec_list = rec_list[:20]
        return company, rec_list, "ok", n_all, len(rec_list)

    items, total_candidates, shown_count, st = _recommend_score_projects_top20(company, db)
    if st == "no_projects":
        return company, [], "no_projects", 0, 0
    return company, items, "ok", total_candidates, shown_count


def sort_company_recommend_items(items: List[dict]) -> List[dict]:
    def is_urgent(x: dict) -> bool:
        badge = x.get("deadline_badge") or ""
        return badge in ("D-0", "D-1", "D-2", "D-3", "D-Day")

    def score_val(x: dict) -> int:
        try:
            return int(x.get("score") or x.get("match_score") or 0)
        except (TypeError, ValueError):
            return 0

    return sorted(
        items,
        key=lambda x: (
            0 if is_urgent(x) else 1,
            -score_val(x),
            0 if x.get("recommend_label") else 1,
            0 if x.get("ai_summary") else 1,
            x.get("end_date") or "9999-12-31",
        ),
    )


def _enrich_recommend_items_for_ui(db: Any, raw_items: List[dict]) -> List[dict]:
    """biz_projects 전체 행 → prepare_db_rows_for_ui + 추천 점수/사유 병합."""
    if not raw_items:
        return []
    ids = [int(it["id"]) for it in raw_items if it.get("id") is not None]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"""
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        WHERE id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    by_id = {int(r["id"]): r for r in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    if not ordered:
        return []
    prepared = prepare_db_rows_for_ui(ordered, audit=False)
    orig_by_id = {int(it["id"]): it for it in raw_items if it.get("id") is not None}
    for p in prepared:
        oid = int(p["id"])
        o = orig_by_id.get(oid)
        if o is not None:
            try:
                p["score"] = int(o.get("score") or 0)
            except (TypeError, ValueError):
                p["score"] = 0
            if o.get("reason"):
                p["reason"] = str(o["reason"])
    return sort_company_recommend_items(prepared)


def _format_recommend_email_body(company: Any, top_items: List[dict]) -> str:
    lines: List[str] = [
        "맞춤 추천 공고 (상위 10건)",
        "",
        f"기준 회사: {company['company_name'] or '(이름 없음)'}",
        "",
    ]
    for i, it in enumerate(top_items, start=1):
        lines.append(f"{i}. 제목: {it['title']}")
        lines.append(f"   기관: {it['organization']}")
        rtxt = it.get("reason") or " · ".join(it.get("reasons") or [])
        lines.append(f"   이유: {rtxt}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@app.route("/recommend")
@app.route("/recommend/<int:company_id>")
def recommend(company_id: Optional[int] = None):
    db = get_db()
    raw_vid0 = request.cookies.get("visitor_id")
    if raw_vid0 and str(raw_vid0).strip():
        visitor_id = str(raw_vid0).strip()
        visitor_cookie_new = False
    else:
        visitor_id = str(uuid.uuid4())
        visitor_cookie_new = True

    company, items, state, total_candidates, shown_count = _recommend_data(
        db, company_id=company_id, visitor_id=visitor_id
    )
    urgent_count = 0
    ai_count = 0
    if state == "no_company":
        if company_id is not None:
            n = db.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"]
            if int(n) > 0:
                flash("해당 ID의 회사를 찾을 수 없습니다.", "warning")
        return render_template(
            "recommend.html",
            no_company=True,
            no_projects=False,
            items=[],
            company=None,
            company_id_param=company_id,
            urgent_count=0,
            ai_count=0,
            used_count=0,
            remaining=5,
            limit=5,
            total_candidates=0,
            shown_count=0,
        )

    xfwd = (request.headers.get("X-Forwarded-For") or "").strip()
    if xfwd:
        user_ip = xfwd.split(",")[0].strip()
    else:
        user_ip = (request.remote_addr or "").strip()

    conn = sqlite3.connect(DB_PATH)
    try:
        if request.args.get("admin") == "1" and request.args.get("key") == ADMIN_KEY:
            u = get_usage_status(
                conn,
                visitor_id,
                user_ip,
                action="recommend",
                limit=5,
                window_hours=12,
            )
            used_count = u["used_count"]
            remaining = u["remaining"]
        else:
            allowed, used_count, reset_at = check_window_limit(
                conn,
                visitor_id,
                user_ip,
                action="recommend",
                limit=5,
                window_hours=12,
            )
            if not allowed:
                resp = make_response(
                    render_template(
                        "limit_exceeded.html",
                        used_count=used_count,
                        limit=5,
                        reset_at=reset_at,
                        window_hours=12,
                        kakao_url="",
                    )
                )
                resp.set_cookie(
                    "visitor_id",
                    visitor_id,
                    max_age=60 * 60 * 24 * 365,
                    httponly=True,
                    samesite="Lax",
                )
                return resp
            remaining = max(0, 5 - used_count)
            save_user_request_log(conn, visitor_id, user_ip, action="recommend")
    finally:
        conn.close()

    if state == "no_projects":
        tmpl = render_template(
            "recommend.html",
            no_company=False,
            no_projects=True,
            company=company,
            items=[],
            company_id_param=company_id,
            urgent_count=0,
            ai_count=0,
            used_count=used_count,
            remaining=remaining,
            limit=5,
            total_candidates=0,
            shown_count=0,
        )
        if visitor_cookie_new:
            resp = make_response(tmpl)
            resp.set_cookie(
                "visitor_id",
                visitor_id,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                samesite="Lax",
            )
            return resp
        return tmpl

    urgent_badges = ("D-0", "D-1", "D-2", "D-3", "D-Day")
    urgent_count = sum(
        1 for x in items if (x.get("deadline_badge") or "") in urgent_badges
    )
    ai_count = sum(1 for x in items if str(x.get("ai_summary") or "").strip())
    tmpl = render_template(
        "recommend.html",
        no_company=False,
        no_projects=False,
        company=company,
        items=items,
        company_id_param=company_id,
        urgent_count=urgent_count,
        ai_count=ai_count,
        used_count=used_count,
        remaining=remaining,
        limit=5,
        total_candidates=total_candidates,
        shown_count=shown_count,
    )
    if visitor_cookie_new:
        resp = make_response(tmpl)
        resp.set_cookie(
            "visitor_id",
            visitor_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="Lax",
        )
        return resp
    return tmpl


@app.route("/recommend/pdf/<int:company_id>/<int:project_id>")
def recommend_pdf(company_id: int, project_id: int):
    """추천 리포트 PDF (공고+회사+다음 액션)."""
    db = get_db()
    company = db.execute(
        """
        SELECT id, company_name, industry, region, employee_count, revenue, export_flag
        FROM companies WHERE id = ?
        """,
        (company_id,),
    ).fetchone()
    proj = db.execute(
        """
        SELECT id, title, organization, ministry, executing_agency, start_date, end_date,
               url, description, source
        FROM biz_projects WHERE id = ?
        """,
        (project_id,),
    ).fetchone()
    if company is None or proj is None:
        flash("회사 또는 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("recommend", company_id=company_id))

    rec = db.execute(
        """
        SELECT score, reason FROM recommendations
        WHERE company_id = ? AND project_id = ?
        """,
        (company_id, project_id),
    ).fetchone()
    if rec:
        sc = int(rec["score"] or 0)
        reason = str(rec["reason"] or "")
    else:
        sc, reason = score_company_project(dict(company), dict(proj))

    notice = {
        "title": proj["title"] or "",
        "url": proj["url"] or "",
        "source": str(proj["source"] or ""),
        "organization": proj["organization"] or "",
        "ministry": str(proj["ministry"] or ""),
        "executing_agency": str(proj["executing_agency"] or ""),
        "start_date": str(proj["start_date"] or ""),
        "end_date": str(proj["end_date"] or ""),
        "description": str(proj["description"] or ""),
    }
    base = f"{company['company_name'] or 'company'}_{project_id}"
    path = create_recommendation_report_pdf(
        notice=notice,
        company=dict(company),
        score=sc,
        reason=reason,
        safe_basename=base,
    )
    return send_from_directory(str(REPORTS_DIR), Path(path).name, as_attachment=True)


@app.route("/recommend/send", methods=["GET", "POST"])
def recommend_send():
    """추천 상위 10건을 MAIL_TO로 발송 (관리자용)."""
    db = get_db()
    cid = request.form.get("company_id", type=int) if request.method == "POST" else None
    company, items, state, _tc, _sc = _recommend_data(
        db, company_id=cid, visitor_id=get_visitor_id()
    )
    if state == "no_company":
        flash("등록된 회사 정보가 없어 메일을 보낼 수 없습니다.", "warning")
        return redirect(url_for("recommend"))
    if state == "no_projects":
        flash("등록된 공고가 없어 메일을 보낼 수 없습니다.", "warning")
        return redirect(url_for("recommend"))

    company_id_str = str(company["id"])
    base_url = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    rec_url = f"{base_url}/recommend/{company_id_str}" if base_url else ""
    kakao_text = build_recommend_kakao_text(
        str(company["company_name"] or "회사").strip(),
        company_id_str,
        list(items),
    )
    send_kakao_memo(
        kakao_text,
        web_url=rec_url,
        mobile_web_url=rec_url,
    )

    top10 = items[:10]
    body = _format_recommend_email_body(company, top10)
    cname = str(company["company_name"] or "회사").strip()
    subject = f"[맞춤 추천] {cname} 기준 상위 {len(top10)}건"

    mail_to = os.getenv("MAIL_TO", "").strip()
    if not mail_to:
        flash(
            "MAIL_TO 환경변수가 설정되어 있지 않습니다. "
            "수신 주소를 설정한 뒤 다시 시도해 주세요.",
            "info",
        )
        return redirect(url_for("recommend"))

    try:
        do_send(
            to_email=mail_to,
            subject=subject,
            content=body,
            file_path=None,
        )
    except Exception as exc:
        flash(f"추천 결과 메일 발송 실패: {exc}", "danger")
        return redirect(url_for("recommend"))

    flash(f"추천 결과 메일을 {mail_to}(으)로 보냈습니다.", "success")
    return redirect(url_for("recommend", company_id=cid) if cid else url_for("recommend"))


def _tail_output(text: str, max_chars: int = LOG_TAIL_CHARS) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return "… (앞부분 생략) …\n" + text[-max_chars:]


@app.route("/run", methods=["GET", "POST"])
def run_pipeline_route():
    """subprocess 로 pipeline/run_pipeline.py 실행 후 로그 일부 + 신규 공고 수 표시."""
    if request.method == "GET":
        return render_template(
            "run_pipeline.html",
            ran=False,
            log_preview="",
            new_count=None,
            returncode=None,
            success=None,
            error_message=None,
        )

    if not PIPELINE_SCRIPT.exists():
        return (
            render_template(
                "run_pipeline.html",
                ran=True,
                log_preview="",
                new_count=None,
                returncode=None,
                success=False,
                error_message=f"스크립트 없음: {PIPELINE_SCRIPT}",
            ),
            500,
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(PIPELINE_SCRIPT)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return (
            render_template(
                "run_pipeline.html",
                ran=True,
                log_preview="",
                new_count=None,
                returncode=None,
                success=False,
                error_message="파이프라인 실행 시간 초과(10분).",
            ),
            500,
        )
    except Exception as exc:
        return (
            render_template(
                "run_pipeline.html",
                ran=True,
                log_preview="",
                new_count=None,
                returncode=None,
                success=False,
                error_message=str(exc),
            ),
            500,
        )

    combined = ""
    if proc.stdout:
        combined += proc.stdout
    if proc.stderr:
        combined += "\n--- stderr ---\n" + proc.stderr
    log_preview = _tail_output(combined)

    new_items: list = []
    compare_error = None
    try:
        new_items = compare_new()
    except Exception as exc:
        compare_error = str(exc)

    return render_template(
        "run_pipeline.html",
        ran=True,
        log_preview=log_preview,
        new_count=len(new_items) if compare_error is None else None,
        returncode=proc.returncode,
        success=proc.returncode == 0 and compare_error is None,
        error_message=compare_error,
    )


def _render_new_announcements_page(is_admin: bool):
    """DB 기반 신규 공고 화면. 관리자(/admin/pipeline)는 최근 7일 필터 없이 전체 표시."""
    tab = (request.args.get("tab") or "").strip()
    status = request.args.get("status")
    if status is not None:
        status = status.strip()
    else:
        status = ""
    source = (request.args.get("source") or "").strip()
    query = (request.args.get("q") or "").strip()
    deadline = (request.args.get("deadline") or "").strip()
    recent = (request.args.get("recent") or "").strip()
    has_ai_summary = (request.args.get("has_ai_summary") or "").strip()
    has_recommend_label = (request.args.get("has_recommend_label") or "").strip()
    has_attachments = (request.args.get("has_attachments") or "").strip()
    category = (request.args.get("category") or "").strip()

    if tab == "recommend":
        has_recommend_label = "1"

    status_filter = "" if status in (None, "", "전체") else status
    source_filter = "" if source in ("", "전체") else source.lower()
    fq = request.args.to_dict(flat=True)
    if tab:
        fq["tab"] = tab
    else:
        fq.pop("tab", None)

    sql = """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json,
               ai_summary, ai_summary_at, recommend_label, recommend_label_at
        FROM biz_projects
        WHERE 1=1
    """
    params: list = []

    if query:
        sql += " AND (title LIKE ? OR organization LIKE ? OR description LIKE ?)"
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q])

    try:
        rows = get_db().execute(sql, params).fetchall()
    except Exception as e:
        print(f"[new/admin pipeline] DB 조회 실패: {e}", flush=True)
        rows = []

    rows_ui = prepare_db_rows_for_ui(rows)
    rows_ui = filter_items(
        rows_ui,
        status=status_filter,
        source=source_filter,
        q=query,
        deadline=deadline or None,
        recent=recent or None,
        has_ai_summary=has_ai_summary or None,
        has_recommend_label=has_recommend_label or None,
        has_attachments=has_attachments or None,
        category=category or None,
    )

    if not is_admin:
        today = date.today()
        cutoff = today - timedelta(days=7)
        rows_ui = [
            it
            for it in rows_ui
            if (sd := _safe_parse_date(it.get("start_date"))) is not None and sd >= cutoff
        ]

    if tab == "recommend":
        rows_ui = sort_recommend_items(rows_ui)

    summary = _compute_ui_summary(rows_ui)
    label = "GET /admin/pipeline (목록 10)" if is_admin else "GET /new (목록 10)"
    if audit_ui_enabled():
        log_source_mismatch_and_parser(rows_ui[:10], label=label)
        db = get_db()
        for r in rows_ui[:5]:
            rid = r.get("id")
            if rid is not None:
                log_detail_consistency(
                    db,
                    int(rid),
                    prepare_row=_prepare_detail_row_for_template,
                    normalize_item=normalize_display_item,
                )
    today_top = get_today_top_projects()
    today_ids = {row[0] for row in today_top}
    items = rows_ui
    id_set = {str(x) for x in today_ids}
    matched = [item for item in items if str(item.get("id")) in id_set]
    by_id = {str(i.get("id")): i for i in matched}
    top_clicked = []
    for project_id, cnt in today_top:
        item = by_id.get(str(project_id))
        if item is None:
            continue
        top_clicked.append(
            dict(
                project_id=item["id"],
                title=clean_display_title(item.get("display_title") or item.get("title")),
                source=str(item.get("source") or item.get("source_badge") or ""),
                score=cnt,
                click_count=cnt,
                apply_count=0,
                detail_count=cnt,
            )
        )
    if not top_clicked:
        top_clicked = get_top_clicked_projects()
    visitor_id = get_or_create_visitor_id()
    user_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if user_ip and "," in user_ip:
        user_ip = user_ip.split(",")[0].strip()
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            usage = get_usage_status(conn, visitor_id, user_ip)
        finally:
            conn.close()
    except Exception as e:
        print(f"[new/admin pipeline] usage 조회 실패: {e}", flush=True)
        usage = None
    resp = make_response(
        render_template(
            "new.html",
            items=rows_ui,
            rows=rows_ui,
            count=len(rows_ui),
            err=None,
            status=status,
            source=source,
            q=query,
            deadline=deadline,
            recent=recent,
            has_ai_summary=has_ai_summary,
            has_recommend_label=has_recommend_label,
            has_attachments=has_attachments,
            category=category,
            tab=tab,
            fq=fq,
            summary=summary,
            source_labels=SOURCE_LABELS,
            top_clicked=top_clicked,
            usage=usage,
            today_visits=get_today_visit_count(),
            is_admin=is_admin,
        )
    )
    resp.set_cookie(
        "visitor_id",
        visitor_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/new", strict_slashes=False)
def new_announcements():
    """DB 기반 + start_date 최근 7일 이내만 표시하는 신규 공고 화면.

    `/` 와 달리 status 쿼리 기본값 없음(미지정 시 전체 상태). 이후 7일 필터 적용.
    """
    return _render_new_announcements_page(is_admin=False)


@app.route("/api/run", methods=["POST"])
def api_run_start():
    """크롤링/파이프라인 실행 시작. 이미 실행 중이면 409."""
    if not check_admin(request):
        return jsonify({"ok": False, "error": "admin key required"}), 403
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "").strip()
    if mode not in ("all", "jbexport", "bizinfo", "notify"):
        return jsonify({"ok": False, "error": "mode must be all|jbexport|bizinfo|notify"}), 400

    with RUN_LOCK:
        if RUN_STATE["running"]:
            return jsonify({"ok": False, "error": "already running"}), 409
        RUN_LOG.clear()
        RUN_STATE["running"] = True
        RUN_STATE["mode"] = mode
        RUN_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
        RUN_STATE["finished_at"] = None
        RUN_STATE["returncode"] = None
        RUN_STATE["pid"] = None

    _log_line(f"=== 실행 시작 mode={mode} ===")
    _run_pipeline_background(mode)
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    with RUN_LOCK:
        state = {
            "running": RUN_STATE["running"],
            "mode": RUN_STATE["mode"],
            "started_at": RUN_STATE["started_at"],
            "finished_at": RUN_STATE["finished_at"],
            "returncode": RUN_STATE["returncode"],
            "pid": RUN_STATE["pid"],
        }
        tail = list(RUN_LOG)[-50:]
    return jsonify({**state, "log_tail": tail})


@app.route("/api/run/logs", methods=["GET"])
def api_run_logs():
    with RUN_LOCK:
        lines = list(RUN_LOG)
    return jsonify({"logs": lines})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)