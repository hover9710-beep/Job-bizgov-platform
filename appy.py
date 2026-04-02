import os
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from ai_analyzer import analyze_project
from pdf_generator import create_pdf
from mailer import send_email as do_send

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db" / "biz.db"
REPORTS_DIR = BASE_DIR / "reports"


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
    conn.commit()
    conn.close()


@app.teardown_appcontext
def close_db(_error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.route("/")
def index():
    status = (request.args.get("status") or "").strip()
    query = (request.args.get("q") or "").strip()

    sql = """
        SELECT id, title, organization, start_date, end_date, status, url, description, ai_result, pdf_path
        FROM biz_projects
        WHERE 1=1
    """
    params = []

    if status:
        sql += " AND status = ?"
        params.append(status)

    if query:
        sql += " AND (title LIKE ? OR organization LIKE ? OR description LIKE ?)"
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q])

    sql += " ORDER BY id DESC"

    rows = get_db().execute(sql, params).fetchall()
    return render_template("index.html", rows=rows, status=status, q=query)


@app.route("/detail/<int:pid>")
def detail(pid):
    row = get_db().execute(
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

    return render_template("detail.html", row=row)


@app.route("/analyze/<int:pid>")
def analyze(pid):
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

    ai_result = analyze_project(row["title"], row["description"] or "")
    pdf_full_path = create_pdf(row["title"], ai_result)
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


if __name__ == "__main__":
    _init_db()
    app.run(debug=True)