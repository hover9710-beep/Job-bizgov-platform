# -*- coding: utf-8 -*-
"""
Run the full pipeline in order (project root = cwd for each subprocess).

1) JBEXPORT: connectors/connectors_jbexport/jbexport_proxy.py (Flask — background for pipeline duration)
2) BIZINFO: connectors/connector_bizinfo.py
3) filter_recommend
4) merge_sources → data/merged/all_sites.json (+ history)
4b) diff_new → data/merged/new.json
5) make_mail (data/mail/mail_body.txt)
5a) kakao token refresh (scripts/kakao_token_refresh.py)
5b) make_kakao (data/kakao/kakao_body.txt)
5c) kakao_notify (data/kakao/kakao_body.txt → Kakao Memo API)
6) mailer --dry-run
7) mailer (real send)

옵션:
  --test            : 신규 공고 0건이거나 mail_body.txt 없음이어도 강제로 메일 발송.
                      (이번 실행이 "스케줄러에서 진짜 실행됐는지" 확인용)
  --skip-crawl      : 1~3단계(크롤링/필터) 스킵, 기존 JSON 재사용.
  --only-mail       : 크롤러와 병합을 전부 건너뛰고 make_mail → mailer 만 실행.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

PY = sys.executable

PROXY_SCRIPT = ROOT / "connectors" / "connectors_jbexport" / "jbexport_proxy.py"
LOG_DIR = ROOT / "logs"


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


def main() -> int:
    _utf8_stdio()

    parser = argparse.ArgumentParser(description="BizGovPlanner 전체 파이프라인")
    parser.add_argument("--test", action="store_true",
                        help="신규 0건이어도 mail_body 를 강제 채워 실제 메일 발송")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="1~3단계 스킵, 기존 JSON 재사용")
    parser.add_argument("--only-mail", action="store_true",
                        help="크롤러/병합 전부 스킵, make_mail → mailer 만 실행")
    args = parser.parse_args()

    # ── 로그 파일 tee ──
    log_fp, log_path = _open_logfile()
    sys.stdout = _TeeWriter(sys.stdout, log_fp)
    sys.stderr = _TeeWriter(sys.stderr, log_fp)
    print(f"[run_all] log file: {log_path}", flush=True)

    proc = None
    try:
        if not args.only_mail:
            _section("1) JBEXPORT crawler (jbexport_proxy — background)")
            if not PROXY_SCRIPT.is_file():
                print(f"[run_all] Missing script: {PROXY_SCRIPT}", flush=True)
                return 1

            proxy_cmd = [PY, str(PROXY_SCRIPT)]
            print("[run_all] Starting Flask proxy in background (required for local jbexport API).",
                  flush=True)
            print(f"$ {' '.join(proxy_cmd)}", flush=True)
            proc = subprocess.Popen(proxy_cmd, cwd=str(ROOT))
            time.sleep(0.2)
            if proc.poll() is not None:
                print(f"[run_all] JBEXPORT proxy exited immediately (code {proc.returncode}).",
                      flush=True)
                return proc.returncode if proc.returncode is not None else 1
            time.sleep(2)
            if proc.poll() is not None:
                print(f"[run_all] JBEXPORT proxy stopped (code {proc.returncode}).", flush=True)
                return proc.returncode if proc.returncode is not None else 1

        # ── 파이프라인 스텝 정의 ──
        pre_mail_steps: list[tuple[str, list[str]]] = []
        if not args.only_mail:
            if not args.skip_crawl:
                pre_mail_steps.append((
                    "2) BIZINFO crawler",
                    [PY, str(ROOT / "connectors" / "connector_bizinfo.py")],
                ))
                pre_mail_steps.append((
                    "3) Filter recommend",
                    [PY, str(ROOT / "pipeline" / "filter_recommend.py")],
                ))
            pre_mail_steps.append((
                "4) Merge sources",
                [PY, str(ROOT / "pipeline" / "merge_sources.py")],
            ))
            pre_mail_steps.append((
                "4b) Diff new (merged/new.json)",
                [PY, str(ROOT / "pipeline" / "diff_new.py")],
            ))

        mail_steps: list[tuple[str, list[str]]] = [
            # mail_view: DB → period_text + infer_status 기반 본문 생성 (새 뷰 계층).
            ("5) Make mail body (mail_view)", [PY, "-m", "pipeline.mail_view"]),
            # 카카오 access_token 은 24h 만료 — refresh 가능한 환경이면 매일 갱신.
            ("5a) Kakao token refresh", [PY, str(ROOT / "scripts" / "kakao_token_refresh.py")]),
            ("5b) Make Kakao body", [PY, str(ROOT / "pipeline" / "make_kakao.py")]),
            # 카카오 발송 — 실패해도 메일 발송은 계속 진행 (아래 non-fatal 처리).
            ("5c) Kakao notify (send)", [PY, str(ROOT / "kakao_notify.py")]),
            ("6) Mailer (dry-run)", [PY, str(ROOT / "mailer.py"), "--dry-run"]),
        ]

        # 카카오 관련 단계는 실패해도 메일 발송을 멈추지 않는다 (best-effort).
        NON_FATAL_STEPS = {
            "5a) Kakao token refresh",
            "5b) Make Kakao body",
            "5c) Kakao notify (send)",
        }

        # --test 가 아니면, 중간 스텝 하나라도 실패하면 즉시 리턴.
        # --test 면, 모든 스텝을 실행하되 실패해도 발송 단계까지 진행.
        failures: list[tuple[str, int]] = []

        for title, cmd in pre_mail_steps + mail_steps:
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

        # 7) Real mail send
        _section("7) Mailer (real send)")
        smtp_user = (os.environ.get("SMTP_USER") or "").strip()
        smtp_pass = (os.environ.get("SMTP_PASS") or "").strip()

        if args.test:
            _ensure_force_mail_body()

        if not smtp_user or not smtp_pass:
            print("[run_all] Skipped: SMTP_USER and SMTP_PASS must both be set for real send.",
                  flush=True)
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
            # --test 에선 non-zero 스텝이 있어도 0 반환 (스케줄러 탐지용)
            return 0 if args.test else 1

        print("\nALL PIPELINE COMPLETED", flush=True)
        return 0
    finally:
        if proc is not None:
            print("\n[run_all] Stopping JBEXPORT proxy...", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
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
