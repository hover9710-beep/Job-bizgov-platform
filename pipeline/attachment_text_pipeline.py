# -*- coding: utf-8 -*-
"""첨부 파일(data/**/files) 순회 → data/text 에 .txt 저장.

Background-only attachment text extraction.
UI and mail should consume saved DB/text results, not call this module directly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.file_text_extract import extract_text

DEFAULT_ALLOWED = frozenset({".pdf", ".hwp", ".hwpx"})


def iter_files_roots(data_root: str = "data") -> List[Path]:
    """탐색 루트: data/jbexport/files, data/files, data/*/files (중복 제거)."""
    dr = (_ROOT / data_root).resolve() if not Path(data_root).is_absolute() else Path(data_root).resolve()
    roots: List[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        if not p.is_dir():
            return
        key = str(p.resolve())
        if key in seen:
            return
        seen.add(key)
        roots.append(p.resolve())

    add(dr / "jbexport" / "files")
    add(dr / "files")
    if dr.is_dir():
        for ch in sorted(dr.iterdir()):
            if ch.is_dir():
                add(ch / "files")
    return roots


def infer_source_for_path(file_path: Path, data_root: Path) -> str:
    """경로 기반 source 추론: jbexport / data/files/<src>/ / 기타 unknown."""
    try:
        rel = file_path.resolve().relative_to(data_root.resolve())
    except ValueError:
        parts = file_path.resolve().parts
        s = str(file_path).replace("\\", "/").lower()
        if "jbexport" in s:
            return "jbexport"
        return "unknown"
    parts = rel.parts
    if "jbexport" in parts:
        return "jbexport"
    if len(parts) >= 2 and parts[0] == "files":
        return parts[1] if parts[1] else "unknown"
    if len(parts) >= 2 and parts[1] == "files":
        return parts[0] if parts[0] else "unknown"
    return "unknown"


def iter_attachment_files(
    base_dir: str = "data/files",
    allowed_exts: Optional[Set[str]] = None,
) -> Iterator[Path]:
    """단일 base_dir 하위 순회 (하위 호환)."""
    exts = allowed_exts if allowed_exts is not None else set(DEFAULT_ALLOWED)
    exts_l = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    root = (_ROOT / base_dir).resolve() if not Path(base_dir).is_absolute() else Path(base_dir).resolve()
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts_l:
            yield p


def iter_all_attachment_files(
    data_root: str = "data",
    allowed_exts: Optional[Set[str]] = None,
) -> Iterator[Tuple[Path, Path]]:
    """(파일 경로, 해당 files 루트) 튜플 순회."""
    dr = (_ROOT / data_root).resolve() if not Path(data_root).is_absolute() else Path(data_root).resolve()
    for fr in iter_files_roots(data_root=data_root):
        for p in iter_attachment_files_from_root(fr, allowed_exts=allowed_exts):
            yield p, fr


def iter_attachment_files_from_root(
    files_root: Path,
    allowed_exts: Optional[Set[str]] = None,
) -> Iterator[Path]:
    exts = allowed_exts if allowed_exts is not None else set(DEFAULT_ALLOWED)
    exts_l = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    root = files_root.resolve()
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts_l:
            yield p


def build_text_output_path(
    file_path: Path,
    files_root: str | Path = "data/files",
    text_root: str = "data/text",
) -> Path:
    """files 루트 기준 상대 경로를 text_root 아래 .txt 로 매핑."""
    fp = file_path.resolve()
    fr = (
        (_ROOT / files_root).resolve()
        if isinstance(files_root, str) and not Path(files_root).is_absolute()
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
    files_root: str | Path = "data/files",
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
    base_dir: Optional[str] = None,
    limit: Optional[int] = None,
    overwrite: bool = False,
    allowed_exts: Optional[Set[str]] = None,
    data_root: str = "data",
    all_roots: bool = False,
) -> Dict[str, int]:
    """base_dir 단일 또는 all_roots 시 iter_files_roots 전체."""
    processed = ok_n = fail_n = skipped = 0

    if all_roots or base_dir is None:
        pairs = list(iter_all_attachment_files(data_root=data_root, allowed_exts=allowed_exts))
    else:
        fr = (_ROOT / base_dir).resolve() if not Path(base_dir).is_absolute() else Path(base_dir).resolve()
        pairs = [(p, fr) for p in iter_attachment_files_from_root(fr, allowed_exts=allowed_exts)]

    for fp, fr in pairs:
        if limit is not None and processed >= limit:
            break
        try:
            out_path = build_text_output_path(fp, files_root=fr, text_root="data/text")
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
        src = infer_source_for_path(fp, (_ROOT / data_root).resolve())
        res = process_one_file(fp, files_root=fr, text_root="data/text")
        ext = Path(res["file_path"]).suffix.lower().lstrip(".") or "?"
        if res["ok"]:
            ok_n += 1
            print(
                f"[extract] OK   {ext:<5} {res['chars']:>6} chars  [{src}] {res['file_path']}",
                flush=True,
            )
        else:
            fail_n += 1
            err = res.get("error") or ""
            print(
                f"[extract] FAIL {ext:<5}  error={err}  method={res.get('method','')}  [{src}]",
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
        default=None,
        help="단일 첨부 루트(미지정 시 data/jbexport/files + data/files + data/*/files 전부)",
    )
    parser.add_argument("--data-root", default="data", help="프로젝트 기준 data 디렉터리")
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
        data_root=args.data_root,
        all_roots=args.base_dir is None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
