"""附件生成器抽象基类：新增附件类型只需实现 build() 并注册到 registry。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class AttachmentBuilder(ABC):
    key: str                        # URL标识
    title: str                      # 中文名
    description: str                # 前端提示
    business_types: list[str]       # 适用业务类型，如 ["supervision", "tis"]
    filename_pattern: str           # 如 "{project_name}_人员进退场横道图.docx"
    payload_model: type[BaseModel]  # Pydantic 输入契约类
    form_type: str = "table"        # 前端表单形态：table（行表）/ letter（字段表单）

    @abstractmethod
    def build(self, payload, project: dict) -> bytes:
        """接收已校验的 Pydantic model 实例 + 项目字典，返回 .docx 字节流。"""
        ...

    def filename(self, payload, project: dict) -> str:
        from ..files import safe_name
        return safe_name(self.filename_pattern.format(project_name=project.get("name", "未命名项目")))
