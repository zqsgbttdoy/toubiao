"""脱敏预处理管道 - 发送前对敏感信息进行替换。

纪律：
- mappings（占位符→原文）仅本地留存用于人工核对，绝不随请求发送。
- level="standard" 面向本机模型；level="strict" 面向云端模型（is_cloud=True时强制），
  额外脱敏地址与项目名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 敏感信息识别正则
_PHONE_RE = re.compile(r'1[3-9]\d{9}|0\d{2,3}-?\d{7,8}')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_ID_CARD_RE = re.compile(r'\d{17}[\dXx]|\d{15}')
_CREDIT_CODE_RE = re.compile(r'[0-9A-Z]{18}')
_AMOUNT_RE = re.compile(r'(\d[\d,]*\.?\d*)\s*(万元|元|亿)')
_ADDRESS_RE = re.compile(r'([\u4e00-\u9fff]{2,}(省|市|区|县|镇|乡|村|路|街|道|号|栋|单元|室|楼)[\u4e00-\u9fff\d]*(号|楼|室|层|栋)?)+')
_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')


@dataclass
class RedactionResult:
    """脱敏结果"""
    text: str
    summary: dict = field(default_factory=dict)  # {"company_names": 2, "person_names": 3, ...}
    mappings: dict = field(default_factory=dict)  # 仅本地留存，绝不发送

    @property
    def masked_tokens(self) -> int:
        return sum(self.summary.values())


def _amount_to_bucket(match: re.Match) -> str:
    """金额→区间桶（保留量级信息供AI理解，隐去精确数值）"""
    try:
        num_str = match.group(1).replace(",", "")
        num = float(num_str)
        unit = match.group(2)
        if unit == "亿":
            return "[金额:亿级]"
        elif unit == "万元":
            if num < 50: return "[金额:50万以下]"
            elif num < 100: return "[金额:50万-100万]"
            elif num < 500: return "[金额:100万-500万]"
            elif num < 1000: return "[金额:500万-1000万]"
            else: return "[金额:1000万以上]"
        else:  # 元
            if num < 100000: return "[金额:10万以下]"
            elif num < 500000: return "[金额:10万-50万]"
            elif num < 1000000: return "[金额:50万-100万]"
            else: return "[金额:100万以上]"
    except (ValueError, IndexError):
        return "[金额:已脱敏]"


def redact_text(text: str, *,
                company_names: list[str] | None = None,
                person_names: list[str] | None = None,
                project_names: list[str] | None = None,
                level: str = "standard") -> RedactionResult:
    """
    对文本执行脱敏。

    level: "standard"(本地模型) | "strict"(云端模型，强制最严)
    company_names/person_names/project_names: 从项目facts与字段中提取的已知实体
    """
    summary: dict = {}
    mappings: dict = {}
    result = text

    # 1. 硬敏感（无论level都脱敏）
    # 电话
    phones = _PHONE_RE.findall(result)
    if phones:
        summary["phones"] = len(phones)
        for i, p in enumerate(dict.fromkeys(phones)):
            mappings[f"phone_{i}"] = p
        result = _PHONE_RE.sub("[已脱敏]", result)

    # 邮箱
    emails = _EMAIL_RE.findall(result)
    if emails:
        summary["emails"] = len(emails)
        for i, e in enumerate(dict.fromkeys(emails)):
            mappings[f"email_{i}"] = e
        result = _EMAIL_RE.sub("[已脱敏]", result)

    # 身份证
    ids = _ID_CARD_RE.findall(result)
    if ids:
        summary["id_cards"] = len(ids)
        result = _ID_CARD_RE.sub("[已脱敏]", result)

    # 统一社会信用代码
    codes = _CREDIT_CODE_RE.findall(result)
    if codes:
        summary["credit_codes"] = len(codes)
        result = _CREDIT_CODE_RE.sub("[已脱敏]", result)

    # 2. 标准脱敏（standard和strict都执行）
    # 金额→区间桶
    amounts = _AMOUNT_RE.findall(result)
    if amounts:
        summary["amounts"] = len(amounts)
        result = _AMOUNT_RE.sub(_amount_to_bucket, result)

    # 公司名（基于词典）
    if company_names:
        company_count = 0
        for i, name in enumerate(company_names):
            if name and name in result:
                company_count += result.count(name)
                role = f"[甲方{chr(65 + i)}]" if i < 3 else f"[单位{chr(65 + i)}]"
                mappings[f"company_{i}"] = name
                result = result.replace(name, role)
        if company_count:
            summary["company_names"] = company_count

    # 人名（基于词典）
    if person_names:
        person_count = 0
        for i, name in enumerate(person_names):
            if name and name in result:
                person_count += result.count(name)
                mappings[f"person_{i}"] = name
                result = result.replace(name, f"[人员{chr(65 + i)}]")
        if person_count:
            summary["person_names"] = person_count

    # 3. 严格模式额外脱敏（云端强制）
    if level == "strict":
        # 地址
        addresses = _ADDRESS_RE.findall(result)
        if addresses:
            summary["addresses"] = len(addresses)
            result = _ADDRESS_RE.sub("[区域已脱敏]", result)

        # 项目名
        if project_names:
            proj_count = 0
            for i, name in enumerate(project_names):
                if name and name in result:
                    proj_count += result.count(name)
                    mappings[f"project_{i}"] = name
                    result = result.replace(name, f"[项目{chr(65 + i)}]")
            if proj_count:
                summary["project_names"] = proj_count

    return RedactionResult(text=result, summary=summary, mappings=mappings)


def estimate_tokens(text: str) -> int:
    """启发式估算token数（中文≈1.5字符/token，英文≈4字符/token）"""
    chinese_chars = len(_CHINESE_RE.findall(text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)
