# -*- coding: utf-8 -*-
"""
Run the full pipeline in order (project root = cwd for each subprocess).

전체(--mode all):
  1) JBEXPORT: 상주 jbexport_proxy(:5001) + pipeline/jbexport_daily.py
  2) BIZINFO: connectors/connector_bizinfo.py
  2b) K-Startup: connectors/connector_kstartup.py
  3) filter_recommend → merge_sources → diff_new → merge_jb → update_db
  4) make_mail / 카카오 / mailer

부분(--mode jbexport|bizinfo): 해당 수집만 후 병합·DB(메일·카카오 없음).

옵션:
  --mode all|jbexport|bizinfo (기본 all)
  --test            : 중간 실패해도 이후 단계 시도·테스트 메일
  --skip-crawl      : 크롤 3종 스킵, 병합·알림만
  --only-mail       : make_mail → mailer 만
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

PY = sys.executable

LOG_DIR = ROOT / "logs"


def is_jbexport_proxy_alive(base_url="http://127.0.0.1:5001", timeout=2):
    try:
        with urllib.request.urlopen(base_url, timeout=timeout) as r:
            return True
    except Exception:
        return False


def _utf8_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


class _TeeWriter:
    """stdout/stderr 를 콘솔 + 파일 양쪽에 동시에 기록."""

    def __init__(self, original, log_file):
        self._orig = original
        self._log = log_file

    def write(self, data: str) -> int:
        try:
            self._orig.write(data)
        except Exception:
            pass
        try:
            self._log.write(data)
            self._log.flush()
        except Exception:
            pass
        return len(data) if data else 0

    def flush(self) -> None:
        try:
            self._orig.flush()
        except Exception:
            pass
        try:
            self._log.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._orig, name)


def _open_logfile():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d")
    path = LOG_DIR / f"run_all_{ts}.log"
    f = open(path, "a", encoding="utf-8")
    f.write(
        f"\n===== run_all start {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"pid={os.getpid()} argv={sys.argv!r} =====\n"
    )
    f.flush()
    return f, path


def _section(title: str) -> None:
    print("\n" + "=" * 60, flush=True)
    print(f"  {title}", flush=True)
    print("=" * 60 + "\n", flush=True)


def _run(cmd: list[str]) -> int:
    """서브프로세스 실행 + stdout/stderr 를 한 줄씩 부모 stdout(tee) 로 전달.

    Task Scheduler 환경에서 콘솔을 못 잡아도 run_all_*.log 에 모든 출력이 남는다.
    """
    print(f"$ {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
    proc.stdout.close()
    return proc.wait()


def _print_smtp_debug() -> None:
    print("==== SMTP DEBUG ====")
    print("SMTP_USER:", os.getenv("SMTP_USER"))
    print("SMTP_PASS:", bool(os.getenv("SMTP_PASS")))
    print("MAIL_TO:", os.getenv("MAIL_TO"))
    print("====================")


def _ensure_force_mail_body() -> None:
    """--test 모드에서 mail_body.txt 가 없을 때 최소 본문을 채워 넣는다."""
    out_file = ROOT / "data" / "mail" / "mail_body.txt"
    if out_file.is_file() and out_file.stat().st_size > 0:
        return
    out_file.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_file.write_text(
        "[run_all --test] 테스트 강제 발송\n"
        f"실행 시각: {today}\n"
        "이 메일은 스케줄러 발송 경로가 살아있는지 확인하기 위한 강제 테스트 메일입니다.\n",
        encoding="utf-8",
    )
    print(f"[run_all] --test: 비어있던 mail_body 를 강제 채움 → {out_file}", flush=True)


# ── 크롤·병합 단계 분리 ─────────────────────────────────────────────────────

def run_jbexport() -> int:
    """jbexport: 상주 프록시(:5001) 가동 여부 확인 후 jbexport_daily 수집."""
    _section("1) JBEXPORT daily collection")
    if not is_jbexport_proxy_alive():
        print(
            "[run_all] JBEXPORT proxy is not running on http://127.0.0.1:5001",
            flush=True,
        )
        return 1
    print("[run_all] JBEXPORT proxy OK: http://127.0.0.1:5001", flush=True)

    _section("1b) JBEXPORT jbexport_daily.py")
    return _run([PY, str(ROOT / "pipeline" / "jbexport_daily.py")])


def run_bizinfo() -> int:
    """bizinfo: connector_bizinfo 단일 실행."""
    _section("2) BIZINFO crawler")
    return _run([PY, str(ROOT / "connectors" / "connector_bizinfo.py")])


def run_kstartup() -> int:
    """kstartup: connector_kstartup 단일 실행."""
    _section("2b) K-Startup crawler")
    return _run([PY, str(ROOT / "connectors" / "connector_kstartup.py")])


def _post_merge_steps(args: argparse.Namespace) -> int:
    """merge / DB 반영 / 필터 (메일·카카오 제외)."""
    steps: list[tuple[str, list[str]]] = [
        (
            "3) Filter recommend",
            [PY, str(ROOT / "pipeline" / "filter_recommend.py")],
        ),
        (
            "4) Merge sources",
            [PY, str(ROOT / "pipeline" / "merge_sources.py")],
        ),
        (
            "4b) Diff new (merged/new.json)",
            [PY, str(ROOT / "pipeline" / "diff_new.py")],
        ),
        (
            "4c) Merge jb → all_jb.json",
            [PY, str(ROOT / "pipeline" / "merge_jb.py")],
        ),
        (
            "4d) Update DB (biz.db)",
            [PY, str(ROOT / "pipeline" / "update_db.py")],
        ),
    ]
    failures: list[tuple[str, int]] = []
    for title, cmd in steps:
        _section(title)
        rc = _run(cmd)
        if rc != 0:
            msg = f"[run_all] FAILED: {title} (exit {rc})"
            print(msg, flush=True)
            failures.append((title, rc))
            if not args.test:
                return rc
    if failures:
        print("\n[run_all] post-merge 일부 실패 (--test 계속):", flush=True)
        for t, rc in failures:
            print(f"  - {t} (exit {rc})", flush=True)
    return 0


def run_post_update_only(args: argparse.Namespace) -> int:
    """병합·DB·필터만 (알림 없음)."""
    return _post_merge_steps(args)


def _run_mail_chain(args: argparse.Namespace) -> int:
    """make_mail / 카카오 / mailer dry-run / 실발송."""
    mail_steps: list[tuple[str, list[str]]] = [
        ("5) Make mail body (mail_view)", [PY, "-m", "pipeline.mail_view"]),
        ("5a) Kakao token refresh", [PY, str(ROOT / "scripts" / "kakao_token_refresh.py")]),
        ("5b) Make Kakao body", [PY, str(ROOT / "pipeline" / "make_kakao.py")]),
        ("5c) Kakao notify (send)", [PY, str(ROOT / "kakao_notify.py")]),
        ("6) Mailer (dry-run)", [PY, str(ROOT / "mailer.py"), "--dry-run"]),
    ]
    NON_FATAL_STEPS = {
        "5a) Kakao token refresh",
        "5b) Make Kakao body",
        "5c) Kakao notify (send)",
    }
    failures: list[tuple[str, int]] = []

    for title, cmd in mail_steps:
        _section(title)
        if any("mailer.py" in str(p) for p in cmd):
            _print_smtp_debug()
        rc = _run(cmd)
        if rc != 0:
            msg = f"[run_all] FAILED: {title} (exit {rc})"
            print(msg, flush=True)
            failures.append((title, rc))
            if title in NON_FATAL_STEPS:
                print(f"[run_all] non-fatal: {title} 실패, 계속 진행", flush=True)
                continue
            if not args.test:
                return rc

    _section("7) Mailer (real send)")
    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_pass = (os.environ.get("SMTP_PASS") or "").strip()

    if args.test:
        _ensure_force_mail_body()

    if not smtp_user or not smtp_pass:
        print(
            "[run_all] Skipped: SMTP_USER and SMTP_PASS must both be set for real send.",
            flush=True,
        )
        print("  (mailer.py would exit 1 without them.)", flush=True)
        return 1 if not args.test else 0

    _print_smtp_debug()
    rc = _run([PY, str(ROOT / "mailer.py")])
    if rc != 0:
        print(f"[run_all] FAILED: 7) Mailer (real send) (exit {rc})", flush=True)
        if not args.test:
            return rc
        failures.append(("7) Mailer", rc))

    if failures:
        print("\n[run_all] 완료 (일부 스텝 실패):", flush=True)
        for t, rc in failures:
            print(f"  - {t} (exit {rc})", flush=True)
        return 0 if args.test else 1

    print("\nALL PIPELINE COMPLETED", flush=True)
    return 0


def run_post_update_and_notify(args: argparse.Namespace) -> int:
    """병합·DB 후 메일·카카오까지."""
    rc = _post_merge_steps(args)
    if rc != 0 and not args.test:
        return rc
    _section("4e) Attachment text extract")
    _run([PY, "-m", "pipeline.attachment_text_pipeline"])
    return _run_mail_chain(args)


def run_all(args: argparse.Namespace) -> int:
    """전체: jbexport → bizinfo → kstartup → 병합·알림."""
    if not args.skip_crawl:
        r = run_jbexport()
        if r != 0 and not args.test:
            return r
        r = run_bizinfo()
        if r != 0 and not args.test:
            return r
        r = run_kstartup()
        if r != 0 and not args.test:
            return r
    return run_post_update_and_notify(args)


def _only_mail_flow(args: argparse.Namespace) -> int:
    """--only-mail: make_mail → … → 실발송 만."""
    return _run_mail_chain(args)


def main() -> int:
    _utf8_stdio()

    parser = argparse.ArgumentParser(description="BizGovPlanner 전체 파이프라인")
    parser.add_argument("--test", action="store_true",
                        help="신규 0건이어도 mail_body 를 강제 채워 실제 메일 발송")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="크롤 단계 스킵(jbexport/bizinfo/kstartup), 병합·알림만")
    parser.add_argument("--only-mail", action="store_true",
                        help="크롤러/병합 전부 스킵, make_mail → mailer 만 실행")
    parser.add_argument(
        "--mode",
        choices=["all", "jbexport", "bizinfo"],
        default="all",
        help="실행 범위: all=전체, jbexport|bizinfo=해당 수집 후 병합·DB만(메일·카카오 없음)",
    )
    args = parser.parse_args()

    # ── 로그 파일 tee ──
    log_fp, log_path = _open_logfile()
    sys.stdout = _TeeWriter(sys.stdout, log_fp)
    sys.stderr = _TeeWriter(sys.stderr, log_fp)
    print(f"[run_all] log file: {log_path}", flush=True)

    code = 1
    try:
        if args.only_mail:
            code = _only_mail_flow(args)
        elif args.mode == "all":
            code = run_all(args)
        elif args.mode == "jbexport":
            code = run_jbexport()
            if code == 0 or args.test:
                code = run_post_update_only(args)
        elif args.mode == "bizinfo":
            code = run_bizinfo()
            if code == 0 or args.test:
                code = run_post_update_only(args)
        else:
            code = 1
        return code
    finally:
        try:
            log_fp.write(
                f"===== run_all end {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
            )
            log_fp.flush()
            log_fp.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
