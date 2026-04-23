# -*- coding: utf-8 -*-
"""첨부(PDF/HWP/HWPX)에서 텍스트 추출."""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Union

PathLike = Union[str, Path]


def guess_ext(path: PathLike) -> str:
    """소문자 확장자 반환 (예: `.pdf`)."""
    return Path(path).suffix.lower()


def clean_extracted_text(text: str) -> str:
    """\\r\\n 정리, 다중 공백·줄바꿈 축소, trim."""
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_text_from_pdf(path: PathLike) -> str:
    """pypdf로 페이지별 텍스트 추출 후 합침. 빈 페이지는 건너뜀."""
    from pypdf import PdfReader

    p = Path(path)
    reader = PdfReader(str(p))
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text()
        except Exception:
            continue
        if t and str(t).strip():
            parts.append(str(t).strip())
    return "\n\n".join(parts)


def extract_text_from_hwpx(path: PathLike) -> str:
    """ZIP(HWPX) 내 XML에서 태그 제거 후 텍스트만 수집."""
    p = Path(path)
    chunks: list[str] = []
    with zipfile.ZipFile(p, "r") as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".xml"):
                continue
            try:
                data = zf.read(name)
                root = ET.fromstring(data)
                txt = "".join(root.itertext())
                if txt.strip():
                    chunks.append(txt.strip())
            except Exception:
                continue
    return "\n\n".join(chunks)


def extract_text_from_hwp(path: PathLike) -> str:
    """바이너리 HWP는 미지원. 빈 문자열 반환 (method는 extract_text에서 지정)."""
    return ""


def extract_text(path: PathLike) -> Dict[str, Any]:
    """
    반환: {ok, ext, text, error, method}
    """
    p = Path(path)
    ext = guess_ext(p)
    out: Dict[str, Any] = {
        "ok": False,
        "ext": ext,
        "text": "",
        "error": None,
        "method": "",
    }

    if not p.is_file():
        out["error"] = "not a file"
        out["method"] = "skip"
        return out

    try:
        if ext == ".pdf":
            raw = extract_text_from_pdf(p)
            text = clean_extracted_text(raw)
            out["text"] = text
            out["ok"] = bool(text)
            out["method"] = "pypdf"
            if not text:
                out["error"] = "empty or unreadable pdf"
            return out

        if ext == ".hwpx":
            raw = extract_text_from_hwpx(p)
            text = clean_extracted_text(raw)
            out["text"] = text
            out["ok"] = bool(text)
            out["method"] = "hwpx-zip-xml"
            if not text:
                out["error"] = "no text in hwpx xml"
            return out

        if ext == ".hwp":
            extract_text_from_hwp(p)
            out["text"] = ""
            out["ok"] = False
            out["error"] = "HWP binary format not supported"
            out["method"] = "hwp-unsupported"
            return out

        out["error"] = f"unsupported extension: {ext}"
        out["method"] = "unsupported"
        return out

    except Exception as e:
        out["error"] = str(e)
        out["method"] = "error"
        return out
