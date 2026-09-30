"""联合体协议书（P3 批次 4B）：复用段落引擎，重写为多方签署栏。

联合体投标协议书（#44）——正文用 LetterBuilder 的占位符段落机制（{{key}} → fill），
唯一差异是签署栏不是固定一方，而是「牵头人 + 逐家成员单位」各签一行。故子类复用
段落/字段派生/免责逻辑，仅重写 build() 按 payload 解析出的成员单位数量渲染多方签署栏。
成员单位以顿号/逗号/分号/换行分隔，填写几方便渲染几个签署块。
"""
from __future__ import annotations

import re

from pydantic import Field

from .letter_kit import (add_body, add_greeting, add_notice, add_sign_block,
                         add_title, fill, new_document, to_bytes)
from .letters import LetterBuilder, LetterPayload

_PARTY_SPLIT_RE = re.compile(r"[、，,；;\n]+")


class ConsortiumPayload(LetterPayload):
    lead_unit: str = Field(default="", max_length=200, description="牵头单位名称")
    lead_credit_code: str = Field(default="", max_length=64, description="牵头单位统一社会信用代码")
    member_units: str = Field(default="", max_length=500, description="成员单位名称（多个用、或逗号分隔）")
    work_division: str = Field(default="", max_length=500, description="各方工作分工与职责")
    profit_ratio: str = Field(default="", max_length=300, description="利益分配与风险承担方式")
    leader_liability: str = Field(default="", max_length=300, description="牵头人对外代表权限说明")

    def mapping(self, project):
        data = super().mapping(project)
        data.update(lead_unit=self.lead_unit, lead_credit_code=self.lead_credit_code,
                    member_units=self.member_units, work_division=self.work_division,
                    profit_ratio=self.profit_ratio, leader_liability=self.leader_liability)
        return data

    def parties(self) -> list[tuple[str, str]]:
        """牵头人 + 逐家成员单位，元素为 (角色标签, 单位名称)。"""
        members = [m.strip() for m in _PARTY_SPLIT_RE.split(self.member_units) if m.strip()]
        return [("牵头人", self.lead_unit)] + [("成员单位", m) for m in members]


class ConsortiumBuilder(LetterBuilder):
    key = "consortium-agreement"
    title = "联合体协议书"
    description = "明确联合体牵头人与各成员单位分工、连带责任与利益分配的共同投标协议"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_联合体协议书.docx"
    payload_model = ConsortiumPayload
    attachment_title = "联合体协议书"
    greeting = "致：{{tenderer_name}}"
    paragraphs = (
        "鉴于 {{project_name}}（招标人：{{tenderer_name}}）招标，下述各单位自愿组成联合体共同参加"
        "本项目投标，并就投标及中标后履约的有关事宜达成本协议：",
        "一、联合体构成\n牵头人：{{lead_unit}}（统一社会信用代码：{{lead_credit_code}}）。\n"
        "成员单位：{{member_units}}。",
        "二、工作分工\n{{work_division}}",
        "三、牵头人授权\n牵头人代表联合体各方负责投标及合同履行的全部对外事务，其签署的一切文件"
        "和处理的事务对各成员单位均具有约束力。{{leader_liability}}",
        "四、连带责任\n联合体各方对本项目投标及中标后合同履行承担连带责任。任何一方违约给对方或"
        "招标人造成损失的，由责任方承担，其余方依法承担连带责任。",
        "五、利益分配与风险承担\n{{profit_ratio}}",
        "六、本协议自各方签字盖章之日起生效，至本项目投标有效期届满及合同履行完毕后终止。"
        "联合体各方承诺不再以自己名义或参加其他联合体对本项目投标。",
    )
    # sign_lines 由 build() 按 parties() 动态生成，这里留空占位基类字段。
    sign_lines: tuple[str, ...] = ()

    def build(self, payload: ConsortiumPayload, project: dict) -> bytes:
        mapping = payload.mapping(project)
        doc = new_document()
        add_title(doc, self.attachment_title)
        if self.greeting:
            add_greeting(doc, fill(self.greeting, mapping))
        for paragraph in self.paragraphs:
            add_body(doc, fill(paragraph, mapping))
        sign_lines = []
        for role, name in payload.parties():
            sign_lines.append(f"{role}（盖章）：{name}")
            sign_lines.append("法定代表人或其委托代理人（签字）：＿＿＿＿＿＿＿")
        sign_lines.append(fill("日期：{{sign_date}}", mapping))
        add_sign_block(doc, sign_lines)
        add_notice(doc, self.notice)
        return to_bytes(doc)


__all__ = ["ConsortiumBuilder", "ConsortiumPayload"]
