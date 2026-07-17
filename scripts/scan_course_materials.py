#!/usr/bin/env python3
"""Inventory course materials without indexing uncertain files."""

import argparse
import csv
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

try:
    from pypdf import PdfReader
except ImportError:  # The scan remains useful before optional parsers are installed.
    PdfReader = None

logging.getLogger("pypdf").setLevel(logging.ERROR)


SUPPORTED = {".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown"}
MATERIAL_TYPES = {
    "教材": ("教材", "教程", "课本"),
    "讲义": ("讲义", "复习", "知识点", "整理", "笔记"),
    "PPT": ("ppt", "课件"),
    "实验": ("实验", "实训"),
    "题库": ("题库", "试题", "模拟题", "真题", "练习题", "简答题", "选择题"),
    "大纲": ("大纲", "提纲"),
    "补充阅读": ("阅读", "论文", "文献"),
}
COURSE_RULES = (
    ("programming_python", "programming", ("python", "py程序")),
    ("math_calculus", "math", ("高等数学", "微积分", "calculus")),
    ("math_linear_algebra", "math", ("线性代数", "linear algebra")),
    ("math_probability_statistics", "math", ("概率论", "数理统计", "概率统计")),
    ("politics_maogai", "politics", ("毛概", "毛泽东思想", "中特理论")),
    ("politics_modern_history", "politics", ("近现代史", "现代史纲要")),
    ("politics_xi_thought", "politics", ("习近平新时代", "习思想", "新思想概论")),
)
SUSPICIOUS_SOURCE_MARKERS = ("z-library", "anna's archive", "annas archive")
FIELDS = [
    "document_id", "absolute_path", "relative_path", "filename", "format", "size_bytes",
    "sha256", "domain", "course_id", "material_type", "book_title", "version_year",
    "is_duplicate", "duplicate_of", "is_scanned_pdf", "is_parseable", "needs_ocr",
    "suggested_parser", "suggested_workspace", "classification_confidence",
    "needs_manual_review", "manual_review_reason", "import_status", "failure_reason",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(path: Path) -> Tuple[str, str, float, bool, str]:
    text = str(path).lower()
    matches = []
    for course_id, domain, keywords in COURSE_RULES:
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        if score:
            matches.append((score, course_id, domain))
    if not matches:
        return "unknown", "", 0.0, True, "文件名和目录无法可靠确定课程"
    matches.sort(reverse=True)
    best = matches[0]
    tied = [item for item in matches if item[0] == best[0]]
    if len(tied) > 1:
        return "unknown", "", 0.35, True, "同时命中多个课程规则"
    confidence = 0.95 if best[0] >= 2 else 0.82
    return best[2], best[1], confidence, False, ""


def material_type(path: Path) -> str:
    text = path.name.lower()
    if path.suffix.lower() == ".pptx":
        return "PPT"
    for category, keywords in MATERIAL_TYPES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "未知"


def inspect_pdf(path: Path) -> Tuple[bool, bool, bool, str, str]:
    if PdfReader is None:
        return False, False, False, "pypdf", "未安装 pypdf，无法判断 PDF 是否含文本层"
    try:
        reader = PdfReader(str(path))
        sample_pages = reader.pages[: min(6, len(reader.pages))]
        extracted = "".join((page.extract_text() or "") for page in sample_pages).strip()
        scanned = len(extracted) < max(80, len(sample_pages) * 25)
        return scanned, True, scanned, "OCR(PyMuPDF+macOS Vision)" if scanned else "pypdf", ""
    except Exception as exc:
        return False, False, False, "pypdf", str(exc)[:300]


def inspect_file(path: Path) -> Tuple[bool, bool, bool, str, str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return inspect_pdf(path)
    if suffix in {".txt", ".md", ".markdown"}:
        try:
            path.read_text(encoding="utf-8")
            return False, True, False, "utf-8 text", ""
        except UnicodeDecodeError:
            return False, True, False, "charset-normalizer + text", ""
        except Exception as exc:
            return False, False, False, "text", str(exc)[:300]
    if suffix == ".docx":
        return False, True, False, "python-docx", ""
    if suffix == ".pptx":
        return False, True, False, "python-pptx", ""
    return False, False, False, "unsupported", "文件类型不在允许导入列表"


def prior_statuses(manifest_path: Path) -> Dict[str, dict]:
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {item["sha256"]: item for item in data.get("documents", []) if item.get("sha256")}
    except Exception:
        return {}


def scan(root: Path, output_dir: Path) -> dict:
    root = root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "course_material_manifest.json"
    previous = prior_statuses(manifest_path)
    documents = []
    first_by_hash: Dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.name.startswith(".")):
        digest = sha256_file(path)
        suffix = path.suffix.lower()
        domain, course_id, confidence, review, review_reason = classify(path)
        scanned, parseable, needs_ocr, parser, failure = inspect_file(path)
        duplicate_of = first_by_hash.get(digest, "")
        first_by_hash.setdefault(digest, str(path.relative_to(root)))
        lower_name = path.name.lower()
        if any(marker in lower_name for marker in SUSPICIOUS_SOURCE_MARKERS):
            review = True
            review_reason = "文件名显示来源或授权状态需人工核实"
        if suffix not in SUPPORTED:
            review = True
            review_reason = review_reason or "不支持的文件类型"
        year_match = re.search(r"(?:19|20)\d{2}", path.name)
        old = previous.get(digest, {})
        status = old.get("import_status", "pending_review")
        if review or duplicate_of or not parseable:
            status = "needs_manual_review" if not duplicate_of else "duplicate"
        document_id = "doc_" + digest[:20]
        documents.append({
            "document_id": document_id,
            "absolute_path": str(path),
            "relative_path": str(path.relative_to(root)),
            "filename": path.name,
            "format": suffix.lstrip(".") or "unknown",
            "size_bytes": path.stat().st_size,
            "sha256": digest,
            "domain": domain,
            "course_id": course_id,
            "material_type": material_type(path),
            "book_title": path.stem,
            "version_year": year_match.group(0) if year_match else "",
            "is_duplicate": bool(duplicate_of),
            "duplicate_of": duplicate_of,
            "is_scanned_pdf": scanned,
            "is_parseable": parseable,
            "needs_ocr": needs_ocr,
            "suggested_parser": parser,
            "suggested_workspace": course_id,
            "classification_confidence": confidence,
            "needs_manual_review": review,
            "manual_review_reason": review_reason,
            "import_status": status,
            "failure_reason": failure,
        })
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "document_count": len(documents),
        "documents": documents,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "course_material_inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(documents)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描教材并生成课程清单，不自动导入")
    parser.add_argument("--root", default="/Users/dhang/Documents/rag")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "data"))
    args = parser.parse_args()
    result = scan(Path(args.root), Path(args.output))
    review_count = sum(bool(item["needs_manual_review"]) for item in result["documents"])
    duplicate_count = sum(bool(item["is_duplicate"]) for item in result["documents"])
    print(json.dumps({"documents": result["document_count"], "needs_manual_review": review_count, "duplicates": duplicate_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
