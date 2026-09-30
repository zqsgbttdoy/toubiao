"""段落类附件生成器（P0 批次 1A）：投标函 / 各类证明书 / 承诺 / 委托书。

复用 letter_kit 引擎，每个附件 = 一份 Pydantic 输入契约 + 一段固定正文模板，
正文中的 {{key}} 由 payload.mapping(project) 提供的映射替换。
新增段落类附件只需再加一个 LetterBuilder 子类并注册到 registry。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base import AttachmentBuilder
from .checklist_kit import add_check_paragraph
from .letter_kit import (add_body, add_greeting, add_notice, add_sign_block,
                         add_title, fill, new_document, to_bytes)

# 所有段落类附件共用的落款提醒（强调线下签章，软件不生成电子签章）。
_DEFAULT_NOTICE = ("本文件由投标平台按项目信息自动生成，内容须由投标人逐项核对；"
                   "正式提交前请加盖公章、相关负责人签字后扫描或装订入投标文件。")


class LetterPayload(BaseModel):
    """段落类附件的公共输入字段；子类按需追加专属字段并在 mapping() 中合并。"""
    model_config = ConfigDict(extra="forbid")
    bidder_name: str = Field(default="", max_length=200, description="投标人名称")
    tenderer_name: str = Field(default="", max_length=200, description="招标人（委托方）名称")
    sign_date: str = Field(default="", max_length=50, description="落款日期，如 2026年10月1日")

    def mapping(self, project: dict) -> dict:
        return {
            "bidder_name": self.bidder_name,
            "tenderer_name": self.tenderer_name or project.get("client", ""),
            "project_name": project.get("name", "未命名项目"),
            "region": project.get("region", ""),
            "sign_date": self.sign_date,
        }


class LetterBuilder(AttachmentBuilder):
    """段落类附件生成器基类：标题 + 问候语 + 正文段落 + 签署栏 + 免责提示。"""
    form_type = "letter"
    payload_model = LetterPayload
    business_types = ["supervision", "tis"]
    attachment_title = "投标函"
    greeting = "致：{{tenderer_name}}"
    paragraphs: tuple[str, ...] = ()
    sign_lines: tuple[str, ...] = (
        "投标人（盖章）：{{bidder_name}}",
        "法定代表人（签字）：＿＿＿＿＿＿＿",
        "日期：{{sign_date}}",
    )
    notice = _DEFAULT_NOTICE

    def form_fields(self) -> list[dict]:
        """从 payload_model 自动派生前端字段表单定义，避免字段清单二次维护。"""
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

    def build(self, payload: LetterPayload, project: dict) -> bytes:
        mapping = payload.mapping(project)
        doc = new_document()
        add_title(doc, self.attachment_title)
        if self.greeting:
            add_greeting(doc, fill(self.greeting, mapping))
        for paragraph in self.paragraphs:
            add_body(doc, fill(paragraph, mapping))
        add_sign_block(doc, [fill(line, mapping) for line in self.sign_lines])
        add_notice(doc, self.notice)
        return to_bytes(doc)


# ─────────────────────────── 1. 投标函及附录 ───────────────────────────

class BidLetterPayload(LetterPayload):
    bid_price: str = Field(default="", max_length=100, description="投标总价（大写人民币）")
    duration: str = Field(default="", max_length=100, description="服务期限，如 365 日历天")

    def mapping(self, project):
        data = super().mapping(project)
        data.update(bid_price=self.bid_price, duration=self.duration)
        return data


class BidLetterBuilder(LetterBuilder):
    key = "bid-letter"
    title = "投标函及附录"
    description = "投标总报价、服务期限与响应承诺的致招标人函件"
    filename_pattern = "{project_name}_投标函.docx"
    payload_model = BidLetterPayload
    attachment_title = "投 标 函"
    paragraphs = (
        "1. 我方已仔细研究了{{project_name}}（招标人：{{tenderer_name}}）招标文件的全部内容"
        "（含澄清、修改及补遗文件），愿意按照招标文件规定的各项要求承担本项目的服务工作。",
        "2. 我方投标的服务费总报价为人民币（大写）{{bid_price}}，服务期限为{{duration}}。",
        "3. 我方承诺本投标文件在投标有效期内有效；若我方中标，将按招标文件规定提交履约担保并签订合同。",
        "4. 我方同意提供招标人按招标文件要求可能就本次投标提出的全部资料和数据，并保证其真实、准确、有效。",
        "5. 我方理解并同意，招标人并不一定接受最低报价的投标文件或收到的任何投标文件。",
    )
    sign_lines = (
        "投标人（盖章）：{{bidder_name}}",
        "法定代表人或其委托代理人（签字）：＿＿＿＿＿＿＿",
        "日期：{{sign_date}}",
    )


# ────────────────────── 2. 法定代表人身份证明书 ──────────────────────

class LegalRepIdPayload(LetterPayload):
    rep_name: str = Field(default="", max_length=50, description="法定代表人姓名")
    rep_gender: str = Field(default="", max_length=10, description="性别")
    rep_title: str = Field(default="", max_length=50, description="职务")
    rep_id_no: str = Field(default="", max_length=32, description="身份证号")
    credit_code: str = Field(default="", max_length=64, description="统一社会信用代码")

    def mapping(self, project):
        data = super().mapping(project)
        data.update(rep_name=self.rep_name, rep_gender=self.rep_gender,
                    rep_title=self.rep_title, rep_id_no=self.rep_id_no,
                    credit_code=self.credit_code)
        return data


class LegalRepIdBuilder(LetterBuilder):
    key = "legal-rep-id"
    title = "法定代表人身份证明书"
    description = "证明法定代表人身份及代表权，附身份证号与统一社会信用代码"
    filename_pattern = "{project_name}_法定代表人身份证明书.docx"
    payload_model = LegalRepIdPayload
    attachment_title = "法定代表人身份证明书"
    greeting = ""
    paragraphs = (
        "单位名称：{{bidder_name}}",
        "单位性质：有限责任公司\n地　　址：{{region}}\n统一社会信用代码：{{credit_code}}",
        "姓名：{{rep_name}}　　性别：{{rep_gender}}　　职务：{{rep_title}}　　身份证号：{{rep_id_no}}\n"
        "系 {{bidder_name}} 的法定代表人。特此证明。",
    )


# ────────────────────────── 3. 授权委托书 ──────────────────────────

class AuthorizationPayload(LetterPayload):
    rep_name: str = Field(default="", max_length=50, description="法定代表人姓名")
    rep_id_no: str = Field(default="", max_length=32, description="法定代表人身份证号")
    agent_name: str = Field(default="", max_length=50, description="被授权（代理）人姓名")
    agent_id_no: str = Field(default="", max_length=32, description="被授权人身份证号")
    credit_code: str = Field(default="", max_length=64, description="统一社会信用代码")

    def mapping(self, project):
        data = super().mapping(project)
        data.update(rep_name=self.rep_name, rep_id_no=self.rep_id_no,
                    agent_name=self.agent_name, agent_id_no=self.agent_id_no,
                    credit_code=self.credit_code)
        return data


class AuthorizationBuilder(LetterBuilder):
    key = "authorization-letter"
    title = "授权委托书"
    description = "法定代表人授权代理人办理投标相关事宜的委托书"
    filename_pattern = "{project_name}_授权委托书.docx"
    payload_model = AuthorizationPayload
    attachment_title = "授权委托书"
    greeting = "致：{{tenderer_name}}"
    paragraphs = (
        "本授权委托书声明：注册于{{region}}的 {{bidder_name}}（统一社会信用代码：{{credit_code}}）"
        "的法定代表人 {{rep_name}}（身份证号：{{rep_id_no}}），现授权委托 {{agent_name}}"
        "（身份证号：{{agent_id_no}}）为我方合法代理人。",
        "该代理人有权以我方名义办理 {{project_name}} 投标活动中的相关事宜，其在授权范围内所签署的一切"
        "文件及处理的一切事务，我方均予以承认并承担相应法律责任。",
        "代理人无转委托权。本授权委托书自签署之日起生效，至本项目投标有效期届满之日止。",
    )
    sign_lines = (
        "法定代表人（签字）：＿＿＿＿＿＿＿",
        "被授权代理人（签字）：＿＿＿＿＿＿＿",
        "投标人（盖章）：{{bidder_name}}",
        "日期：{{sign_date}}",
    )


# ──────────────────────── 4. 总监理工程师任命书 ────────────────────────

class ChiefSupervisorPayload(LetterPayload):
    chief_name: str = Field(default="", max_length=50, description="总监理工程师姓名")
    chief_reg_no: str = Field(default="", max_length=64, description="注册监理工程师证号")
    chief_title: str = Field(default="", max_length=50, description="技术职称")

    def mapping(self, project):
        data = super().mapping(project)
        data.update(chief_name=self.chief_name, chief_reg_no=self.chief_reg_no,
                    chief_title=self.chief_title)
        return data


class ChiefSupervisorBuilder(LetterBuilder):
    key = "chief-supervisor-appointment"
    title = "总监理工程师任命书"
    description = "任命注册监理工程师担任本项目总监理工程师（仅监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_总监任命书.docx"
    payload_model = ChiefSupervisorPayload
    attachment_title = "总监理工程师任命书"
    greeting = "致：{{tenderer_name}}"
    paragraphs = (
        "兹任命 {{chief_name}}（注册监理工程师证号：{{chief_reg_no}}，技术职称：{{chief_title}}）"
        "为 {{project_name}} 项目的总监理工程师，全面负责项目监理机构的组建及监理工作的组织实施，"
        "履行监理合同约定的各项职责。",
        "被任命人在任职期间应恪守职业道德，严格执行国家工程建设强制性标准与《建设工程监理规范》，"
        "对所承担项目的监理工作质量负总责。未经建设单位同意，任职期间不得随意更换。",
    )


# ──────────────────────── 5. TIS 机构独立性承诺函 ────────────────────────

class TisIndependenceBuilder(LetterBuilder):
    key = "tis-independence"
    title = "TIS 机构独立性承诺函"
    description = "承诺作为独立第三方开展 TIS 技术服务，与参建各方无隶属或利害关系"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS独立性承诺函.docx"
    payload_model = LetterPayload
    attachment_title = "TIS 机构独立性承诺函"
    greeting = "致：{{tenderer_name}}"
    paragraphs = (
        "我方 {{bidder_name}} 就参与 {{project_name}} 工程质量潜在缺陷保险（IDI）TIS 技术服务项目，"
        "郑重承诺如下：",
        "1. 我方为独立第三方技术服务机构，与本项目的建设单位、设计单位、施工单位、材料设备供应单位"
        "及保险机构之间均不存在隶属关系或其他可能影响独立判断的利害关系。",
        "2. 我方及我方从业人员不在本项目中兼任可能影响独立性、公正性的其他职务，不从事任何有损检查"
        "结论客观性的活动。",
        "3. 我方出具的风险识别、现场检查与报告结论，均以事实为依据、以技术标准和合同为准绳，独立、"
        "客观、公正，不受任何单位和个人的干涉；TIS 技术服务不代替监理、设计审查、法定检测及保险"
        "核保理赔结论。",
        "4. 如违反上述承诺，我方愿承担由此产生的一切法律责任，并接受相应处理。",
    )


# ─────────────────────────── 6. 信用承诺书 ───────────────────────────

class CreditCommitmentBuilder(LetterBuilder):
    key = "credit-commitment"
    title = "信用承诺书"
    description = "承诺资料真实、无重大违法及行贿记录、未被列入失信名单"
    filename_pattern = "{project_name}_信用承诺书.docx"
    payload_model = LetterPayload
    attachment_title = "信用承诺书"
    greeting = "致：{{tenderer_name}}"
    paragraphs = (
        "我方 {{bidder_name}} 自愿参与 {{project_name}} 的投标活动，现就信用事项郑重承诺如下：",
        "1. 严格遵守国家及项目所在地有关法律法规，秉持自愿、公平、诚实信用原则，自觉规范投标行为，"
        "不串通投标、不以他人名义投标或以其他方式弄虚作假。",
        "2. 保证所提交的资质、业绩、财务、人员等全部资料真实、合法、有效，无伪造、变造情形。",
        "3. 近三年内本单位及拟投入本项目的主要人员在经营活动中无重大违法记录、无行贿犯罪记录，"
        "未被工商行政管理机关列入严重违法失信名单、未被人民法院列入失信被执行人名单。",
        "4. 自愿接受行业主管部门及招标人依法实施的监督管理；如违背上述承诺，我方愿承担相应责任并"
        "接受失信联合惩戒。",
    )


# ──────────────────── 文本 + 勾选「声明」基类（P0 批次 1B） ────────────────────

class DeclarationBuilder(LetterBuilder):
    """在段落引擎基础上插入勾选项：标题 + 问候 + 引言 + ☑/□ 声明条款 + 结尾 + 签署栏。

    check_items 每项为 (展示文本, 布尔字段名)；布尔值取自 payload 对应字段。
    """
    intro: tuple[str, ...] = ()
    check_items: tuple[tuple[str, str], ...] = ()
    closing: str = ""

    def build(self, payload: LetterPayload, project: dict) -> bytes:
        mapping = payload.mapping(project)
        doc = new_document()
        add_title(doc, self.attachment_title)
        if self.greeting:
            add_greeting(doc, fill(self.greeting, mapping))
        for paragraph in self.intro:
            add_body(doc, fill(paragraph, mapping))
        for label, key in self.check_items:
            checked = bool(getattr(payload, key, False))
            add_check_paragraph(doc, fill(label, mapping), checked=checked)
        if self.closing:
            add_body(doc, fill(self.closing, mapping))
        add_sign_block(doc, [fill(line, mapping) for line in self.sign_lines])
        add_notice(doc, self.notice)
        return to_bytes(doc)
