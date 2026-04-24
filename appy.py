"""BizGovPlanner Flask app: UI reads persisted rows from biz.db.

DB-centered: request handlers do not run crawlers, remote attachment fetches, or on-demand text extraction.
Background collection: POST /api/run spawns subprocess run_all.py only.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

from flask import (
    Flask,
    flash,
    g,
    jsonify,
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

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

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
    filter_items,
    prepare_db_rows_for_ui,
    sqlite_row_to_item,
)

DB_PATH = BASE_DIR / "db" / "biz.db"
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
      - open     : display_status == '접수중'
      - closed   : display_status == '마감'
      - unknown  : 그 외(확인 필요 등)
      - urgent   : 접수중 중 end_date 가 오늘 ~ 오늘+3일(포함) 사이
    """
    today = date.today()
    limit = today + timedelta(days=3)
    total = len(items)
    open_n = closed_n = unknown_n = urgent_n = 0
    for it in items:
        st = (it.get("display_status") or "").strip()
        if st == "접수중":
            open_n += 1
            ed = _safe_parse_date(it.get("end_date"))
            if ed is not None and today <= ed <= limit:
                urgent_n += 1
        elif st == "마감":
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
    """UI 패널에서 run_all.py 를 --mode 와 함께 실행."""
    root = _project_root()
    if mode in ("all", "jbexport", "bizinfo"):
        return [
            sys.executable,
            os.path.join(str(root), "run_all.py"),
            "--mode",
            mode,
        ]
    raise ValueError(f"unknown mode: {mode}")


def _run_pipeline_background(mode: str) -> None:
    """서브프로세스를 백그라운드 스레드에서 실행하고 RUN_LOG 에 stdout 을 적재."""

    def worker() -> None:
        cmd = _build_command(mode)
        root = str(_project_root())
        _log_line(f"cwd={root}")
        _log_line("$ " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            _log_line(f"Popen 실패: {e}")
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
            _log_line(f"실행 중 오류: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            rc = -1

        with RUN_LOCK:
            RUN_STATE["running"] = False
            RUN_STATE["returncode"] = rc
            RUN_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _log_line(f"종료 코드: {rc}")

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


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    conn.commit()
    conn.close()


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
    # 기본값: status="접수중". status="전체" 는 필터 해제.
    status = (request.args.get("status") or "접수중").strip()
    source = (request.args.get("source") or "").strip()
    query = (request.args.get("q") or "").strip()

    status_filter = "" if status in ("", "전체") else status
    source_filter = "" if source in ("", "전체") else source.lower()

    sql = """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
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
    rows_ui = filter_items(rows_ui, status=status_filter, source=source_filter)
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
    return render_template(
        "new.html",
        items=rows_ui,
        rows=rows_ui,
        count=len(rows_ui),
        err=None,
        status=status,
        source=source,
        q=query,
        summary=summary,
        source_labels=SOURCE_LABELS,
    )


@app.route("/company", methods=["GET", "POST"])
def company():
    if request.method == "GET":
        return render_template("company.html")

    company_name = (request.form.get("company_name") or "").strip()
    if not company_name:
        flash("회사명은 필수입니다.", "danger")
        return render_template("company.html"), 400

    industry = (request.form.get("industry") or "").strip()
    region = (request.form.get("region") or "").strip()
    employee_count = (request.form.get("employee_count") or "").strip()
    revenue = (request.form.get("revenue") or "").strip()
    export_flag = (request.form.get("export_flag") or "").strip()

    db = get_db()
    db.execute(
        """
        INSERT INTO companies (company_name, industry, region, employee_count, revenue, export_flag)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (company_name, industry, region, employee_count, revenue, export_flag),
    )
    db.commit()
    flash("회사 정보가 저장되었습니다.", "success")
    return redirect(url_for("company"))


@app.route("/projects")
def projects_list():
    rows = get_db().execute(
        """
        SELECT id, title, organization, start_date, end_date, status, url, description,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
        FROM biz_projects
        ORDER BY COALESCE(end_date, '9999-12-31') DESC
        """
    ).fetchall()
    rows_ui = prepare_db_rows_for_ui(rows)
    if audit_ui_enabled():
        log_source_mismatch_and_parser(rows_ui[:10], label="GET /projects (목록 10)")
    return render_template("projects.html", rows=rows_ui)


@app.route("/project/<int:pid>")
def project_detail(pid):
    row = get_db().execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("projects_list"))

    ai_summary = row["ai_result"] if row["ai_result"] is not None else ""
    row_ui = normalize_display_item(_prepare_detail_row_for_template(row))
    if audit_ui_enabled():
        log_detail_consistency(
            get_db(),
            pid,
            prepare_row=_prepare_detail_row_for_template,
            normalize_item=normalize_display_item,
        )
    return render_template(
        "project_detail.html",
        row=row_ui,
        ai_summary=ai_summary,
    )


@app.route("/detail/<int:pid>")
def detail(pid):
    row = get_db().execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()

    if row is None:
        flash("해당 공고를 찾을 수 없습니다.", "warning")
        return redirect(url_for("index"))

    row_ui = normalize_display_item(_prepare_detail_row_for_template(row))
    if audit_ui_enabled():
        log_detail_consistency(
            get_db(),
            pid,
            prepare_row=_prepare_detail_row_for_template,
            normalize_item=normalize_display_item,
        )
    return render_template(
        "detail.html",
        row=row_ui,
        back_href=url_for("index"),
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

    export_flag = str(company["export_flag"] or "").strip()
    if export_flag == "예":
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


def _recommend_data(
    db: Any, company_id: Optional[int] = None
) -> Tuple[Optional[Any], List[dict], str]:
    """
    추천 목록: recommendations 테이블이 있으면 우선 사용, 없으면 규칙 기반 즉시 계산(레거시).
    반환: (company_row | None, items, state)
    state: no_company | no_projects | ok
    """
    cnt = db.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"]
    if cnt == 0:
        return None, [], "no_company"

    if company_id is not None:
        company = db.execute(
            """
            SELECT id, company_name, industry, region, employee_count, revenue, export_flag, created_at
            FROM companies
            WHERE id = ?
            """,
            (int(company_id),),
        ).fetchone()
        if company is None:
            return None, [], "no_company"
    else:
        company = db.execute(
            """
            SELECT id, company_name, industry, region, employee_count, revenue, export_flag, created_at
            FROM companies
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

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
            sd = str(row["start_date"] or "").strip()
            ed = str(row["end_date"] or "").strip()
            period = f"{sd or '—'} ~ {ed or '—'}" if (sd or ed) else "—"
            return {
                "id": row["id"],
                "title": row["title"] or "",
                "organization": row["organization"] or "",
                "ministry": row["ministry"] or "",
                "executing_agency": row["executing_agency"] or "",
                "period": period,
                "score": int(row["score"] or 0),
                "reason": row["reason"] or "",
                "url": row["url"] or "",
                "pdf_path": None,
                "status": "",
            }

        return company, [_item_from_rec(r) for r in recs], "ok"

    projects = db.execute(
        """
        SELECT id, title, organization, ministry, executing_agency, start_date, end_date, status,
               description, pdf_path, url
        FROM biz_projects
        ORDER BY id DESC
        """
    ).fetchall()

    if not projects:
        return company, [], "no_projects"

    items: List[dict] = []
    for proj in projects:
        sc, rs = _calc_score(company, proj)
        sd = str(proj["start_date"] or "").strip()
        ed = str(proj["end_date"] or "").strip()
        if sd or ed:
            period = f"{sd or '—'} ~ {ed or '—'}"
        else:
            period = "—"
        reason_text = " / ".join(rs) if rs else "이번에 맞는 추천 조건이 없습니다."
        items.append(
            {
                "id": proj["id"],
                "title": proj["title"] or "",
                "organization": proj["organization"] or "",
                "ministry": str(proj["ministry"] or "")
                if "ministry" in proj.keys()
                else "",
                "executing_agency": str(proj["executing_agency"] or "")
                if "executing_agency" in proj.keys()
                else "",
                "period": period,
                "status": proj["status"] or "",
                "score": sc,
                "reason": reason_text,
                "pdf_path": (proj["pdf_path"] or "").strip() or None,
                "url": str(proj["url"] or ""),
            }
        )

    items.sort(key=lambda x: (-x["score"], x["id"]))
    return company, items, "ok"


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
        lines.append(f"   이유: {it['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@app.route("/recommend")
@app.route("/recommend/<int:company_id>")
def recommend(company_id: Optional[int] = None):
    db = get_db()
    company, items, state = _recommend_data(db, company_id=company_id)
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
        )
    if state == "no_projects":
        return render_template(
            "recommend.html",
            no_company=False,
            no_projects=True,
            company=company,
            items=[],
            company_id_param=company_id,
        )
    return render_template(
        "recommend.html",
        no_company=False,
        no_projects=False,
        company=company,
        items=items,
        company_id_param=company_id,
    )


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
    company, items, state = _recommend_data(db, company_id=cid)
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


@app.route("/new", strict_slashes=False)
def new_announcements():
    """DB 기반 + start_date 최근 7일 이내만 표시하는 신규 공고 화면.

    `/` 와 달리 status 쿼리 기본값 없음(미지정 시 전체 상태). 이후 7일 필터 적용.
    """
    status = request.args.get("status")
    if status is not None:
        status = status.strip()
    source = (request.args.get("source") or "").strip()
    query = (request.args.get("q") or "").strip()

    status_filter = "" if status in (None, "", "전체") else status
    source_filter = "" if source in ("", "전체") else source.lower()

    sql = """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path,
               ministry, executing_agency, source,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
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
    rows_ui = filter_items(rows_ui, status=status_filter, source=source_filter)

    today = date.today()
    cutoff = today - timedelta(days=7)
    rows_ui = [
        it
        for it in rows_ui
        if (sd := _safe_parse_date(it.get("start_date"))) is not None and sd >= cutoff
    ]

    summary = _compute_ui_summary(rows_ui)
    if audit_ui_enabled():
        log_source_mismatch_and_parser(rows_ui[:10], label="GET /new (목록 10)")
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
    return render_template(
        "new.html",
        items=rows_ui,
        rows=rows_ui,
        count=len(rows_ui),
        err=None,
        status=(status if status is not None else ""),
        source=source,
        q=query,
        summary=summary,
        source_labels=SOURCE_LABELS,
    )


@app.route("/api/run", methods=["POST"])
def api_run_start():
    """크롤링/파이프라인 실행 시작. 이미 실행 중이면 409."""
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "").strip()
    if mode not in ("all", "jbexport", "bizinfo"):
        return jsonify({"ok": False, "error": "mode must be all|jbexport|bizinfo"}), 400

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
    app.run(host="127.0.0.1", port=5000, debug=True)