# -*- coding: utf-8 -*-
"""바탕화면 BizGov_데일리.txt 누적 메모 갱신 (산출 7번 B안).

사용법:
  py scripts/update_daily_memo.py
      → docs/daily/<오늘>.md 첫 헤더 + 핵심 5줄 자동 추출, 오늘 블록 prepend

  py scripts/update_daily_memo.py --text "한 줄 핵심"
      → 명령행 직접 전달 (1줄 헤더 + 1줄 본문)

  py scripts/update_daily_memo.py -d 2026-05-08
      → 특정 날짜 명시 (default = today)

동작:
  1. C:\\Users\\custo\\OneDrive\\바탕 화면\\BizGov_데일리.txt 읽기 (UTF-8 BOM)
  2. [<날짜> <요일>] 블록이 이미 있으면 update (그 블록만 교체)
     없으면 헤더 [사용법] 다음에 prepend
  3. UTF-8 BOM 보존하여 다시 쓰기
  4. 옛 내용 그대로 유지 (누적)

옵션 우선순위:
  A. --text 명령행 → 가장 단순, 강제 사용
  B. docs/daily/<날짜>.md 첫 부분 자동 파싱 → default
  C. (B 실패 시) docs/LATEST.md 변경 이력 첫 항목
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # v1 root
TARGET = Path(r"C:\Users\custo\OneDrive\바탕 화면\BizGov_데일리.txt")

WEEKDAY_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
SEPARATOR = "=" * 41

HEADER_END_MARKER = "=========================================\n[사용법]"


def _read_target() -> str:
    """기존 파일 읽기 (BOM 제거)."""
    if not TARGET.exists():
        return ""
    raw = TARGET.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


def _write_target(content: str) -> None:
    """UTF-8 BOM 추가하여 쓰기."""
    data = b"\xef\xbb\xbf" + content.encode("utf-8")
    TARGET.write_bytes(data)


def _extract_from_daily_md(target_date: date) -> list[str]:
    """docs/daily/<YYYY-MM-DD>.md 에서 핵심 추출.

    파싱 룰:
    - 첫 # 제목: '—' 다음 부분만 (날짜 prefix 제거)
    - '## 한 줄 요약' 또는 첫 '## ' 섹션 본문 첫 5줄
    - 빈 줄 만나면 본문 종료
    - 표(`|`) / 코드블록(```) 제외
    """
    md_path = ROOT / "docs" / "daily" / f"{target_date.isoformat()}.md"
    if not md_path.is_file():
        return []
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    for line in lines:
        if line.startswith("# "):
            t = line[2:].strip()
            if "—" in t:
                t = t.split("—", 1)[1].strip()
            elif " - " in t:
                t = t.split(" - ", 1)[1].strip()
            title = t
            break

    # '## 한 줄 요약' 우선, 없으면 첫 '## '
    summary_idx = -1
    fallback_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("## ") and "한 줄 요약" in line:
            summary_idx = i
            break
        if fallback_idx < 0 and line.startswith("## "):
            fallback_idx = i
    start = summary_idx if summary_idx >= 0 else fallback_idx
    if start < 0:
        return [title] if title else []

    body: list[str] = []
    in_code = False
    saw_content = False
    for line in lines[start + 1 :]:
        if line.startswith("##"):
            break
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.strip().startswith("|"):
            continue  # 표 제외
        if not line.strip():
            if saw_content:
                break
            continue
        saw_content = True
        # markdown 강조 마크 제거 (** 만)
        clean = line.strip().replace("**", "")
        body.append(clean)
        if len(body) >= 5:
            break

    out: list[str] = []
    if title:
        out.append(title)
    out.extend(body)
    return out


def _extract_from_latest_md() -> list[str]:
    """docs/LATEST.md 변경 이력 첫 항목 (fallback)."""
    md_path = ROOT / "docs" / "LATEST.md"
    if not md_path.is_file():
        return []
    text = md_path.read_text(encoding="utf-8")
    # 변경 이력 표의 첫 데이터 행
    in_history = False
    for line in text.splitlines():
        if "변경 이력" in line or "변경이력" in line:
            in_history = True
            continue
        if in_history and line.startswith("|") and "|---" not in line and "일자" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[1]:
                return [cells[1]]
    return []


def _build_block(target_date: date, lines: list[str]) -> str:
    """블록 텍스트 생성: 구분선 + 헤더 + 본문 줄들. 끝에 빈 줄 1개 (다음 블록과 분리)."""
    weekday_str = WEEKDAY_KO[target_date.weekday()]
    header = f"[{target_date.isoformat()} {weekday_str}]"
    if lines:
        first = lines[0]
        rest = lines[1:]
    else:
        first = "(자동 추출 실패 — 수동 입력 필요)"
        rest = []

    out = [SEPARATOR, f"{header} {first}", SEPARATOR]
    for r in rest:
        # bullet 이미 있으면 그대로, 없으면 - prefix
        if r.startswith("- "):
            out.append(r)
        else:
            out.append(f"- {r}")
    return "\n".join(out) + "\n\n"


def _insert_block(content: str, new_block: str, target_date: date) -> str:
    """기존 content 에 new_block 삽입.

    - [<date> ...] 블록이 이미 있으면 → 그 블록만 교체
    - 없으면 → [사용법] 블록 다음(SEPARATOR 직전)에 prepend
    """
    iso = target_date.isoformat()
    sep = SEPARATOR

    # 기존 블록 찾기: 첫 SEPARATOR + [<iso> ...] 헤더 + 두번째 SEPARATOR + 본문 + 빈줄
    # lookahead 는 다음 SEPARATOR (다음 블록 시작) — flexible \n 한두 개
    pat = re.compile(
        rf"{re.escape(sep)}\n\[{re.escape(iso)} [^\]]+\][^\n]*\n{re.escape(sep)}\n(?:[^\n]*\n)*?(?={re.escape(sep)}\n)",
    )
    m = pat.search(content)
    if m:
        return content[: m.start()] + new_block + content[m.end():]

    # prepend — marker = '백업/git 무관 ...\n\n' (SEPARATOR 미포함, 옛 블록의 첫 SEPARATOR 보존)
    marker = "- 백업/git 무관 (바탕화면 메모만)\n\n"
    if marker in content:
        idx = content.index(marker) + len(marker)
        return content[:idx] + new_block + content[idx:]
    return content + new_block


def main() -> int:
    parser = argparse.ArgumentParser(description="BizGov_데일리.txt 갱신")
    parser.add_argument("-d", "--date", help="날짜 (YYYY-MM-DD), 기본 = 오늘")
    parser.add_argument("--text", help="명시 텍스트 (1줄 핵심)")
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"[error] invalid date: {args.date}", file=sys.stderr)
            return 1
    else:
        target_date = date.today()

    if args.text:
        lines = [args.text.strip()]
    else:
        lines = _extract_from_daily_md(target_date)
        if not lines:
            lines = _extract_from_latest_md()

    if not lines:
        print(
            f"[warning] 추출 실패. --text 명령행 전달 또는 "
            f"docs/daily/{target_date.isoformat()}.md 작성 후 재시도",
            file=sys.stderr,
        )

    new_block = _build_block(target_date, lines)
    existing = _read_target()
    if not existing:
        print("[error] BizGov_데일리.txt 가 없습니다. 초기 파일부터 작성하세요.", file=sys.stderr)
        return 1

    updated = _insert_block(existing, new_block, target_date)
    _write_target(updated)

    print(f"[ok] {target_date.isoformat()} {WEEKDAY_KO[target_date.weekday()]} 블록 갱신 완료")
    print(f"  target: {TARGET}")
    print(f"  source: {'--text' if args.text else 'docs/daily/<date>.md or LATEST.md fallback'}")
    print(f"  block lines: {len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
