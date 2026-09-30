"""履历版式附件生成器（P1 批次 2D）：复用 resume_kit，仅声明字段清单。

监理人员简历表（#19，混合 多段+表）——每人渲染为一张边框式简历表单，
字段由 fields 元数据单一驱动「前端采集」与「表单渲染」，多人自动分页。
新增人员简历类附件只需再加一个 ResumeBuilder 子类并注册到 registry。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .resume_kit import ResumeBuilder


class ResumeRow(BaseModel):
    """单个人员的简历字段（主要经历支持换行多条）。"""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50, description="姓名")
    gender: str = Field(default="", max_length=10, description="性别")
    age: str = Field(default="", max_length=10, description="年龄")
    title_level: str = Field(default="", max_length=50, description="技术职称")
    qualification: str = Field(default="", max_length=100, description="注册执业资格")
    education: str = Field(default="", max_length=30, description="学历")
    major: str = Field(default="", max_length=50, description="所学专业")
    years: int | None = Field(default=None, ge=0, le=60, description="从业年限")
    project_role: str = Field(default="", max_length=50, description="拟任岗位")
    certs: str = Field(default="", max_length=200, description="资格证书及编号")
    experience: str = Field(default="", max_length=2000, description="主要监理经历（可换行分条）")


class ResumePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ResumeRow] = Field(min_length=1, max_length=50)
    title: str = Field(default="", max_length=200)


class SupervisorResumeBuilder(ResumeBuilder):
    key = "supervisor-resume"
    title = "监理人员简历表"
    description = "一人一表的表格式监理人员简历，含职称、执业资格、从业年限与主要经历"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_监理人员简历表.docx"
    payload_model = ResumePayload
    default_title = "监理人员简历表"
    experience_label = "主要监理经历"
    fields = (
        ("姓名", "name", 1, "text", 50),
        ("性别", "gender", 1, "text", 10),
        ("年龄", "age", 1, "text", 10),
        ("技术职称", "title_level", 1, "text", 50),
        ("注册执业资格", "qualification", 2, "text", 100),
        ("学历", "education", 1, "text", 30),
        ("所学专业", "major", 1, "text", 50),
        ("从业年限", "years", 1, "number", 0),
        ("拟任岗位", "project_role", 1, "text", 50),
        ("资格证书及编号", "certs", 2, "text", 200),
    )


__all__ = ["SupervisorResumeBuilder", "ResumeRow", "ResumePayload"]
