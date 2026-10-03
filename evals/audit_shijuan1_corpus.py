"""Audit downloaded shijuan1 DOCX files and build a private intake shortlist."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "data" / "private_questions" / "shijuan1" / "manifest.json"
)
DEFAULT_JSON = (
    ROOT / "outputs" / "private_sources" / "shijuan1" / "corpus_audit.json"
)
DEFAULT_MARKDOWN = (
    ROOT / "outputs" / "private_sources" / "shijuan1" / "corpus_audit.md"
)
DEFAULT_SHORTLIST = (
    ROOT
    / "outputs"
    / "private_sources"
    / "shijuan1"
    / "intake_shortlist.json"
)

FAMILY_KEYWORDS = {
    "growth_rate": (
        "增长率",
        "平均增长",
        "月平均增长",
        "年平均增长",
        "下降率",
        "平均下降",
        "两次降价",
        "连续下降",
        "逐年递增",
        "逐月增长",
        "增长到",
    ),
    "profit_sales": (
        "利润",
        "销售",
        "售价",
        "进价",
        "销量",
        "每天获利",
        "日盈利",
    ),
    "geometry_area": (
        "面积",
        "长方形",
        "矩形",
        "篱笆",
        "花圃",
        "道路",
        "纸板",
        "阴影",
    ),
    "discriminant_parameter": (
        "判别式",
        "实数根",
        "两个相等",
        "两个不相等",
        "没有实数根",
        "有两个不相等",
        "有两个相等",
        "有两个实数根",
        "根的个数",
    ),
    "root_relation": (
        "根与系数",
        "两根之和",
        "两根之积",
        "方程的两根",
        "方程的两个根",
        "两个根的和",
        "两个根的积",
    ),
    "substitution": (
        "整体代入",
        "代数式的值",
        "求代数式",
        "已知一个根",
        "整体代换",
    ),
    "dynamic_geometry": (
        "点P",
        "点Q",
        "cm/s",
        "停止运动",
        "运动时间",
    ),
}

IMAGE_KEYWORDS = (
    "如图",
    "图中",
    "图1",
    "图2",
    "图①",
    "图②",
    "阴影部分",
    "网格",
    "坐标系中",
)

ANSWER_KEYWORDS = (
    "参考答案",
    "答案：",
    "答：",
    "解：",
    "解析：",
    "试题解答",
    "【答案】",
    "【解析】",
    "【详解】",
)

SOLUTION_SECTION_MARKERS = (
    "参考答案",
    "答案与解析",
    "试题解答",
    "答案详解",
)

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WORD_TEXT = f"{{{WORD_NAMESPACE}}}t"
MATH_TEXT = f"{{{MATH_NAMESPACE}}}t"
WORD_PARAGRAPH = f"{{{WORD_NAMESPACE}}}p"

QUESTION_START = re.compile(r"^\s*(\d{1,2})\s*[．.、]\s*")
OPTION_PATTERN = re.compile(r"(?:^|\s)[A-D][．.、]")
SUBQUESTION_PATTERN = re.compile(r"(?:（|\()([1-9])(?:）|\))")


@dataclass
class QuestionCandidate:
    id: str
    article_id: str
    category: str
    title: str
    year: int | None
    region: str
    article_url: str
    source_docx: list[str]
    families: list[str]
    question_number: str
    preview: str
    text_length: int
    has_answer: bool
    has_solution: bool
    requires_image: bool
    is_choice: bool
    subquestion_count: int
    source_count: int
    quality_score: int
    architecture_requirements: list[str]
    notes: list[str] = field(default_factory=list)


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(WORD_PARAGRAPH):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag in (WORD_TEXT, MATH_TEXT) and node.text:
                parts.append(node.text)
        text = html.unescape("".join(parts))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _split_question_blocks(text: str) -> list[tuple[str, str, bool]]:
    blocks: list[tuple[str, str, bool]] = []
    current_number = ""
    current_lines: list[str] = []
    in_solution_section = False

    def flush() -> None:
        nonlocal current_number, current_lines
        if current_number and current_lines:
            blocks.append((
                current_number,
                "\n".join(current_lines).strip(),
                in_solution_section,
            ))
        current_number = ""
        current_lines = []

    for line in text.splitlines():
        if any(marker in line for marker in SOLUTION_SECTION_MARKERS):
            flush()
            in_solution_section = True
            continue
        match = QUESTION_START.match(line)
        if match:
            flush()
            current_number = match.group(1)
            current_lines = [line[match.end():].strip()]
            continue
        if current_number:
            current_lines.append(line)
    flush()
    return blocks


def _dedupe_signature(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    normalized = normalized.replace("如图", "")
    return hashlib.sha1(normalized[:240].encode("utf-8")).hexdigest()


def _health_score(text: str, *, has_answer: bool, requires_image: bool) -> int:
    score = 0
    length = len(text)
    if 40 <= length <= 1200:
        score += 3
    if has_answer:
        score += 3
    if not requires_image:
        score += 2
    if OPTION_PATTERN.search(text):
        score += 1
    if SUBQUESTION_PATTERN.search(text):
        score += 2
    return score


def _architecture_requirements(families: set[str]) -> list[str]:
    requirements: list[str] = []
    if "growth_rate" in families:
        requirements.append("current_handler")
    if families & {
        "profit_sales",
        "discriminant_parameter",
        "root_relation",
        "substitution",
    }:
        requirements.append("next_handler")
    if "geometry_area" in families:
        requirements.append("geometry_model")
    if "dynamic_geometry" in families:
        requirements.append("visual_geometry_model")
    return requirements or ["unclassified"]


def _classify_families(text: str) -> list[str]:
    families: set[str] = set()
    equation_context = any(
        keyword in text
        for keyword in ("一元二次方程", "方程", "实数根", "根的判别式")
    )
    for family, keywords in FAMILY_KEYWORDS.items():
        if not any(keyword in text for keyword in keywords):
            continue
        if family == "growth_rate":
            compound_markers = (
                "平均增长",
                "月平均增长",
                "年平均增长",
                "平均下降",
                "两次降价",
                "连续下降",
                "逐年递增",
                "逐月增长",
                "增长到",
                "(1+x)",
                "(1-x)",
                "（1+x）",
                "（1-x）",
            )
            if not any(marker in text for marker in compound_markers):
                continue
        if family == "profit_sales":
            profit_context = any(
                keyword in text
                for keyword in ("利润", "盈利", "获利", "销售额")
            )
            sales_context = any(
                keyword in text
                for keyword in ("售价", "进价", "销量", "销售", "降价", "涨价")
            )
            if not (profit_context and sales_context):
                continue
        if family == "discriminant_parameter":
            explicit = (
                "判别式",
                "有两个不相等的",
                "有两个相等的",
                "有两个实数根",
                "没有实数根",
                "根的个数",
            )
            if not (any(marker in text for marker in explicit) and equation_context):
                continue
        if family == "geometry_area":
            modeling_context = any(
                keyword in text
                for keyword in (
                    "长为",
                    "宽为",
                    "围成",
                    "围栏",
                    "篱笆",
                    "花圃",
                    "道路",
                    "纸板",
                    "长方形",
                    "矩形",
                )
            )
            if not modeling_context:
                continue
            function_context = any(
                keyword in text
                for keyword in ("函数", "图象", "抛物线", "反比例", "坐标系")
            )
            structural_context = any(
                keyword in text
                for keyword in (
                    "长方形",
                    "矩形",
                    "围成",
                    "围栏",
                    "篱笆",
                    "花圃",
                    "道路",
                    "纸板",
                )
            )
            if function_context and not structural_context:
                continue
        if family == "dynamic_geometry":
            motion_context = any(
                keyword in text
                for keyword in ("cm/s", "厘米/秒", "运动时间", "停止运动")
            )
            if not motion_context:
                continue
        families.add(family)
    return sorted(families)


def _iter_docx(record: dict) -> list[Path]:
    extract_dir = record.get("extract_dir")
    if not extract_dir:
        return []
    root = ROOT / extract_dir
    if not root.exists():
        return []
    return sorted(root.rglob("*.docx"))


def _load_candidates(manifest_path: Path) -> tuple[list[dict], list[QuestionCandidate]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [
        item
        for item in payload.get("items") or []
        if item.get("status") == "downloaded"
    ]
    candidates: dict[str, QuestionCandidate] = {}
    for record in records:
        for docx in _iter_docx(record):
            try:
                text = _extract_docx_text(docx)
            except Exception:
                continue
            for number, block, solution_section in _split_question_blocks(text):
                if solution_section or not (30 <= len(block) <= 1600):
                    continue
                families = _classify_families(block)
                if not families:
                    continue
                requires_image = any(
                    keyword in block for keyword in IMAGE_KEYWORDS
                )
                has_answer = any(
                    keyword in block for keyword in ANSWER_KEYWORDS
                )
                has_solution = "解析" in block or "解：" in block
                is_choice = bool(OPTION_PATTERN.search(block))
                subquestion_count = len(
                    set(SUBQUESTION_PATTERN.findall(block))
                )
                signature = _dedupe_signature(block)
                article_id = str(record["article_id"])
                docx_relative = str(docx.relative_to(ROOT))
                score = _health_score(
                    block,
                    has_answer=has_answer,
                    requires_image=requires_image,
                )
                existing = candidates.get(signature)
                if existing:
                    if docx_relative not in existing.source_docx:
                        existing.source_docx.append(docx_relative)
                    existing.source_count = len(existing.source_docx)
                    existing.has_answer = existing.has_answer or has_answer
                    existing.has_solution = (
                        existing.has_solution or has_solution
                    )
                    existing.quality_score = max(
                        existing.quality_score,
                        score,
                    )
                    continue
                candidates[signature] = QuestionCandidate(
                    id=signature[:16],
                    article_id=article_id,
                    category=str(record["category"]),
                    title=str(record.get("title") or ""),
                    year=record.get("year"),
                    region=str(record.get("region") or ""),
                    article_url=str(record.get("article_url") or ""),
                    source_docx=[docx_relative],
                    families=families,
                    question_number=number,
                    preview=block[:800],
                    text_length=len(block),
                    has_answer=has_answer,
                    has_solution=has_solution,
                    requires_image=requires_image,
                    is_choice=is_choice,
                    subquestion_count=subquestion_count,
                    source_count=1,
                    quality_score=score,
                    architecture_requirements=_architecture_requirements(
                        set(families)
                    ),
                )
    return records, list(candidates.values())


def _select_shortlist(
    candidates: list[QuestionCandidate],
    *,
    per_family: int,
) -> list[QuestionCandidate]:
    selected: list[QuestionCandidate] = []
    seen: set[str] = set()
    for family in (
        "growth_rate",
        "profit_sales",
        "discriminant_parameter",
        "root_relation",
        "substitution",
        "geometry_area",
        "dynamic_geometry",
    ):
        family_items = [
            item
            for item in candidates
            if family in item.families
            and "geometry_model" not in item.architecture_requirements
            and "visual_geometry_model"
            not in item.architecture_requirements
        ]
        if family in {"geometry_area", "dynamic_geometry"}:
            family_items = [
                item for item in candidates if family in item.families
            ]
        family_items.sort(
            key=lambda item: (
                item.requires_image,
                not item.has_answer,
                -item.quality_score,
                item.text_length,
                item.id,
            )
        )
        used_articles: set[str] = set()
        picked = 0
        for item in family_items:
            if item.id in seen:
                continue
            if item.article_id in used_articles:
                continue
            selected.append(item)
            seen.add(item.id)
            used_articles.add(item.article_id)
            picked += 1
            if picked >= per_family:
                break
    return selected


def _write_markdown(
    path: Path,
    *,
    records: list[dict],
    candidates: list[QuestionCandidate],
    shortlist: list[QuestionCandidate],
) -> None:
    category_counts = Counter(item["category"] for item in records)
    family_counts = Counter(
        family for item in candidates for family in item.families
    )
    bucket_counts = Counter(
        requirement
        for item in candidates
        for requirement in item.architecture_requirements
    )
    lines = [
        "# shijuan1 私有语料审计",
        "",
        f"- 已下载题录：{len(records)}",
        f"- 去重候选题块：{len(candidates)}",
        f"- 首批候选队列：{len(shortlist)}",
        "",
        "## 分类分布",
        "",
        "| 分类 | 已下载 |",
        "|---|---:|",
    ]
    for category, count in category_counts.most_common():
        lines.append(f"| {category} | {count} |")
    lines.extend([
        "",
        "## 题型分布",
        "",
        "| 题型 | 候选题块 | 架构归属 |",
        "|---|---:|---|",
    ])
    bucket_for_family = {
        "growth_rate": "现有 handler",
        "profit_sales": "下一批 handler",
        "discriminant_parameter": "下一批 handler",
        "root_relation": "下一批 handler",
        "substitution": "下一批 handler",
        "geometry_area": "几何模型后置",
        "dynamic_geometry": "视觉/几何模型后置",
    }
    for family, count in family_counts.most_common():
        lines.append(
            f"| {family} | {count} | {bucket_for_family[family]} |"
        )
    lines.extend([
        "",
        "## 架构桶",
        "",
        "| 架构桶 | 数量 |",
        "|---|---:|",
    ])
    for bucket, count in bucket_counts.most_common():
        lines.append(f"| {bucket} | {count} |")
    lines.extend([
        "",
        "## 首批候选",
        "",
        "| 题块 | 年份/地区 | 题型 | 图片 | 答案 | 来源 |",
        "|---|---|---|---|---|---|",
    ])
    for item in shortlist:
        lines.append(
            f"| {item.id} | {item.year or ''} {item.region} | "
            f"{'、'.join(item.families)} | "
            f"{'是' if item.requires_image else '否'} | "
            f"{'是' if item.has_answer else '否'} | "
            f"{item.article_id} |"
        )
    lines.extend([
        "",
        "> 候选队列只代表文本和关键词层面可抽取，不代表答案正确、"
        "结构完整或系统已支持。进入题库前必须逐题复核。",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--shortlist", type=Path, default=DEFAULT_SHORTLIST)
    parser.add_argument("--per-family", type=int, default=40)
    args = parser.parse_args()

    records, candidates = _load_candidates(args.manifest)
    shortlist = _select_shortlist(
        candidates,
        per_family=max(0, args.per_family),
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(
            {
                "downloaded_records": len(records),
                "candidate_count": len(candidates),
                "shortlist_count": len(shortlist),
                "candidates": [asdict(item) for item in candidates],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.shortlist.write_text(
        json.dumps(
            {
                "selected": [asdict(item) for item in shortlist],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_markdown(
        args.markdown,
        records=records,
        candidates=candidates,
        shortlist=shortlist,
    )
    print(f"downloaded={len(records)} candidates={len(candidates)}")
    print(f"shortlist={len(shortlist)}")
    print(f"json={args.json}")
    print(f"shortlist_path={args.shortlist}")
    print(f"markdown={args.markdown}")


if __name__ == "__main__":
    main()
