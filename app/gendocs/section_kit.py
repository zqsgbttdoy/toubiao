"""章节类附件渲染引擎（P0 批次 1E）：多级标题 + 目录 + 编制指引 + 正文 + 分页。

监理大纲（14 章）、TIS 风险减量服务方案（11 章）等「章节类」附件共用本模块。
遵循报告「简单版直接复用 builtin.json 文本」的思路：章节正文的唯一数据源是
templates/builtin.json 中对应模板的 sections，生成器不重复维护正文。

正文里的占位符按可获取的项目数据解析：
- {{project.字段}} / {{fact.键}} / {{facts}} → 取自项目实体与其 facts（真实数据）
- {{materials}} / {{quote}} 等需 store/其他模块的 → 渲染为醒目的人工补充标记，
  恪守「资料须人工选用、权威报价以报价模块为准、本软件不伪造」的纪律。
底层页面 / 字体（宋体）/ 序列化仍复用 docx_kit，不重复造轮子。
"""
from __future__ import annotations

import json
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from ..core import ROOT, now
from .base import AttachmentBuilder
from .docx_kit import clean_text, new_document, to_bytes

_TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_BLACK = RGBColor(0x00, 0x00, 0x00)
_GRAY = RGBColor(0x59, 0x59, 0x59)
_GUIDANCE_PREFIXES = ("【本章要点】", "【评分对应】", "【说明】", "【提示】")
# 无法从 project 取得、需人工或他模块补全的占位符 → 明确提示，绝不臆造内容。
_MANUAL_TOKENS = {
    "materials": "【请结合资料库选用的证明资料逐条补充】",
    "quote": "【以「商务报价」模块的权威结论为准，本框架不代为填写】",
}
_builtin_cache: dict | None = None


def _builtin_entries() -> dict:
    """惰性加载 builtin.json，按模板 id 建索引（章节正文唯一数据源）。"""
    global _builtin_cache
    if _builtin_cache is None:
        data = json.loads((ROOT / "templates" / "builtin.json").read_text(encoding="utf-8"))
        _builtin_cache = {entry["id"]: entry for entry in data}
    return _builtin_cache


def load_sections(template_id: str) -> tuple[list[dict], str]:
    """返回 (sections 列表, 模板 source)。找不到时抛 ValueError 由调用方兜底。"""
    entry = _builtin_entries().get(template_id)
    if not entry:
        raise ValueError(f"builtin.json 中不存在模板：{template_id}")
    return entry.get("sections", []), entry.get("source", "")


def _facts_block(project: dict) -> str:
    facts = project.get("facts") or {}
    if not facts:
        return "【项目事实待补充：可在项目「已确认事实」中登记后重新生成】"
    lines = []
    for key, fact in facts.items():
        value = fact.get("value", "") if isinstance(fact, dict) else str(fact)
        confirmed = "已确认" if isinstance(fact, dict) and fact.get("confirmed") else "待确认"
        lines.append(f"· {key}：{value}（{confirmed}）")
    return "\n".join(lines)


def _resolve_token(expr: str, project: dict) -> str:
    expr = expr.strip()
    if expr in _MANUAL_TOKENS:
        return _MANUAL_TOKENS[expr]
    if expr.startswith("project."):
        return str(project.get(expr[len("project."):], "")).strip() or "【待补充】"
    if expr.startswith("fact."):
        key = expr[len("fact."):]
        fact = (project.get("facts") or {}).get(key)
        if isinstance(fact, dict):
            return str(fact.get("value", "")).strip() or f"【待确认：{key}】"
        return str(fact).strip() if fact else f"【待确认：{key}】"
    if expr == "facts":
        return _facts_block(project)
    return f"【待补充：{expr}】"  # 未知占位符显式暴露，避免 {{}} 残留误导


def resolve(text: str, project: dict) -> str:
    """把正文中的 {{...}} 占位符替换为可获取的项目数据或人工补充标记。"""
    return _TOKEN_RE.sub(lambda m: _resolve_token(m.group(1), project), text)


def _style_run(run, size_pt: float, *, bold=False, italic=False, color=None):
    run.font.name = "宋体"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    run._element.get_or_add_rPr()
    rpr = run._element.rPr
    if rpr.rFonts is None:
        rpr.get_or_add_rFonts()
    rpr.rFonts.set(qn("w:eastAsia"), "宋体")


def add_cover(doc, title: str, project: dict, source_note: str):
    """封面：文档标题 + 项目信息 + 编制依据/免责说明。"""
    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.paragraph_format.space_before = Pt(24)
    heading.paragraph_format.space_after = Pt(12)
    _style_run(heading.add_run(clean_text(title)), 22, bold=True)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _style_run(sub.add_run(clean_text(f"项目：{project.get('name', '未命名项目')}")), 12)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _style_run(meta.add_run(f"委托方：{project.get('client') or '未填写'}　地区：{project.get('region') or '未填写'}　生成时间：{now()}"),
               9, color=_GRAY)

    if source_note:
        note = doc.add_paragraph()
        _style_run(note.add_run("编制依据：" + clean_text(source_note)), 9, italic=True, color=_GRAY)


def add_toc(doc, sections: list[dict]):
    """静态目录：逐章列出标题（Word 内可用导航窗格进一步跳转）。"""
    toc_title = doc.add_paragraph()
    toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    toc_title.paragraph_format.space_after = Pt(8)
    _style_run(toc_title.add_run("目　录"), 16, bold=True)
    for section in sections:
        line = doc.add_paragraph()
        line.paragraph_format.space_after = Pt(2)
        _style_run(line.add_run(clean_text(section.get("title", ""))), 11)


def add_chapter(doc, section: dict, project: dict, *, include_guidance: bool):
    """一个章节：Heading 1 标题（进入 Word 大纲级别） + 指引/正文逐行渲染。"""
    heading = doc.add_heading(level=1)
    _style_run(heading.add_run(clean_text(section.get("title", ""))), 15, bold=True, color=_BLACK)

    body = resolve(section.get("body", ""), project)
    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        is_guidance = line.startswith(_GUIDANCE_PREFIXES)
        if is_guidance and not include_guidance:
            continue
        paragraph = doc.add_paragraph()
        fmt = paragraph.paragraph_format
        fmt.line_spacing = 1.4
        fmt.space_after = Pt(4)
        if is_guidance:
            fmt.left_indent = Pt(12)
            _style_run(paragraph.add_run(clean_text(line)), 10.5, italic=True, color=_GRAY)
        else:
            fmt.first_line_indent = Pt(24)
            _style_run(paragraph.add_run(clean_text(line)), 12)


def _page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


class SectionBuilder(AttachmentBuilder):
    """章节类附件生成器基类：子类声明 template_id / 标题 / 业务类型即可。"""
    form_type = "sections"
    payload_model = None            # 由子类提供（见 sections.py）
    template_id = ""                # 对应 builtin.json 模板 id
    doc_title = "技术建议书"
    include_toc_default = True
    include_guidance_default = True

    def form_fields(self) -> list[dict]:
        fields = []
        for name, info in self.payload_model.model_fields.items():
            max_length = getattr(info, "max_length", None)
            if not max_length:
                for meta in info.metadata:
                    max_length = getattr(meta, "max_length", None)
                    if max_length:
                        break
            is_bool = info.annotation is bool
            fields.append({
                "key": name,
                "label": info.description or name,
                "required": bool(info.is_required()),
                "type": "bool" if is_bool else "text",
                "max_length": 200 if is_bool else (int(max_length) if max_length else 200),
            })
        return fields

    def build(self, payload, project: dict) -> bytes:
        doc = new_document()
        try:
            sections, source_note = load_sections(self.template_id)
        except ValueError:
            sections, source_note = [], ""

        title = getattr(payload, "title", "") or self.doc_title
        include_toc = getattr(payload, "include_toc", self.include_toc_default)
        include_guidance = getattr(payload, "include_guidance", self.include_guidance_default)

        add_cover(doc, title, project, source_note)
        if include_toc and sections:
            _page_break(doc)
            add_toc(doc, sections)
        for index, section in enumerate(sections):
            _page_break(doc)
            add_chapter(doc, section, project, include_guidance=include_guidance)
        if not sections:
            add_chapter(doc, {"title": title, "body": "【未找到标准章节框架，请人工编制正文内容】"},
                        project, include_guidance=True)
        return to_bytes(doc)


__all__ = ["SectionBuilder", "load_sections", "resolve", "add_cover", "add_toc",
           "add_chapter"]
