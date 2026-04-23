# -*- coding: utf-8 -*-
"""data/files 첨부를 순회해 data/text 에 .txt 로 저장."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Set

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.file_text_extract import extract_text

DEFAULT_ALLOWED = frozenset({".pdf", ".hwp", ".hwpx"})


def iter_attachment_files(
    base_dir: str = "data/files",
    allowed_exts: Optional[Set[str]] = None,
) -> Iterator[Path]:
    """base_dir 하위 전체 순회, 허용 확장자만."""
    exts = allowed_exts if allowed_exts is not None else set(DEFAULT_ALLOWED)
    exts_l = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    root = (_ROOT / base_dir).resolve() if not Path(base_dir).is_absolute() else Path(base_dir).resolve()
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts_l:
            yield p


def build_text_output_path(
    file_path: Path,
    files_root: str = "data/files",
    text_root: str = "data/text",
) -> Path:
    """files 기준 상대 경로를 text_root 아래 .txt 로 매핑."""
    fp = file_path.resolve()
    fr = (
        (_ROOT / files_root).resolve()
        if not Path(files_root).is_absolute()
        else Path(files_root).resolve()
    )
    tr = (
        (_ROOT / text_root).resolve()
        if not Path(text_root).is_absolute()
        else Path(text_root).resolve()
    )
    rel = fp.relative_to(fr)
    return tr / rel.with_suffix(".txt")


def process_one_file(
    file_path: Path,
    files_root: str = "data/files",
    text_root: str = "data/text",
) -> Dict[str, Any]:
    """extract_text 후 성공 시 .txt 저장."""
    fp = file_path.resolve()
    text_path = build_text_output_path(fp, files_root=files_root, text_root=text_root)
    result = extract_text(fp)
    ok = bool(result.get("ok"))
    text = str(result.get("text") or "")
    method = str(result.get("method") or "")
    err = result.get("error")

    if ok and text:
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(text, encoding="utf-8")

    return {
        "file_path": str(fp),
        "text_path": str(text_path),
        "ok": ok,
        "chars": len(text),
        "error": err if err is not None else "",
        "method": method,
    }


def run_attachment_text_pipeline(
    base_dir: str = "data/files",
    limit: Optional[int] = None,
    overwrite: bool = False,
    allowed_exts: Optional[Set[str]] = None,
) -> Dict[str, int]:
    processed = ok_n = fail_n = skipped = 0
    for fp in iter_attachment_files(base_dir=base_dir, allowed_exts=allowed_exts):
        if limit is not None and processed >= limit:
            break
        try:
            out_path = build_text_output_path(fp, files_root=base_dir, text_root="data/text")
        except ValueError:
            fail_n += 1
            processed += 1
            ext = fp.suffix.lower().lstrip(".") or "?"
            print(f"[extract] FAIL {ext}  error=path outside files_root {fp}", flush=True)
            continue

        if out_path.exists() and not overwrite:
            skipped += 1
            processed += 1
            continue

        processed += 1
        res = process_one_file(fp, files_root=base_dir, text_root="data/text")
        ext = Path(res["file_path"]).suffix.lower().lstrip(".") or "?"
        if res["ok"]:
            ok_n += 1
            print(
                f"[extract] OK   {ext:<5} {res['chars']:>6} chars   {res['file_path']}",
                flush=True,
            )
        else:
            fail_n += 1
            err = res.get("error") or ""
            print(
                f"[extract] FAIL {ext:<5}  error={err}  method={res.get('method','')}",
                flush=True,
            )

    print(
        f"[extract] summary: processed={processed} ok={ok_n} fail={fail_n} skipped={skipped}",
        flush=True,
    )
    return {
        "processed": processed,
        "ok": ok_n,
        "fail": fail_n,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="첨부 파일 → data/text .txt 추출")
    parser.add_argument(
        "--base-dir",
        default="data/files",
        help="첨부 루트 (프로젝트 루트 기준 상대 경로 가능)",
    )
    parser.add_argument("--limit", type=int, default=None, help="처리 상한")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 .txt 가 있어도 재추출",
    )
    args = parser.parse_args()
    run_attachment_text_pipeline(
        base_dir=args.base_dir,
        limit=args.limit,
        overwrite=args.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
