#!/usr/bin/env python3
"""기출·내신 자료(HWPX/HWP/PDF/TXT)에서 텍스트를 추출한다.

사용법:
    python extract_text.py 자료.hwpx [-o out.txt]

- .hwpx : python-hwpx로 본문 추출 (표 포함)
- .hwp  : pyhwp(hwp5txt) 시도 → 실패 시 olefile PrvText(미리보기, 앞부분만) 폴백
- .pdf  : pdftotext(있으면) → pypdf 폴백
- .txt/.md : 그대로 읽기
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def from_hwpx(path: Path) -> str:
    from hwpx.document import HwpxDocument
    doc = HwpxDocument.open(str(path))
    try:
        return doc.export_markdown()
    except Exception:
        return doc.export_text()


def from_hwp(path: Path) -> str:
    if shutil.which("hwp5txt"):
        r = subprocess.run(["hwp5txt", str(path)], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    try:
        from hwp5.hwp5txt import main  # noqa: F401  (pyhwp 설치 확인용)
    except ImportError:
        pass
    # 폴백: OLE 미리보기 텍스트 (문서 전체가 아닐 수 있음)
    try:
        import olefile
    except ImportError:
        sys.exit("HWP(구버전) 추출에는 pyhwp 또는 olefile이 필요합니다: "
                 "pip install pyhwp olefile --break-system-packages")
    ole = olefile.OleFileIO(str(path))
    if ole.exists("PrvText"):
        data = ole.openstream("PrvText").read()
        txt = data.decode("utf-16-le", errors="ignore")
        return "[주의: HWP 미리보기 텍스트라 문서 전체가 아닐 수 있습니다]\n" + txt
    sys.exit("이 HWP 파일에서 텍스트를 추출하지 못했습니다. hwpx로 다른 이름 저장 후 다시 시도하세요.")


def from_pdf(path: Path) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def extract(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".hwpx":
        return from_hwpx(path)
    if ext == ".hwp":
        return from_hwp(path)
    if ext == ".pdf":
        return from_pdf(path)
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    sys.exit(f"지원하지 않는 형식: {ext} (hwpx/hwp/pdf/txt 지원)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()
    text = extract(Path(args.input))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"저장: {args.output} ({len(text)}자)")
    else:
        print(text)


if __name__ == "__main__":
    main()
