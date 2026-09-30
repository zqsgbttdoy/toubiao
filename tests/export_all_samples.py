r"""批量导出全部已注册模板的样例 docx，供人工「格式复核」。

用法（在项目根目录）：
    .venv\Scripts\python.exe -m tests.export_all_samples
    # 或指定输出目录：
    .venv\Scripts\python.exe -m tests.export_all_samples --output "docs/格式复核样例_全量"

说明：内容用「通用样例载荷」自动填充（必填字段=示例值，其余走默认），目的是复现**版式结构**
——页面方向、列宽与表头、序号列、勾选/ select 映射、金额千分位、横道/柱状底纹、履历与层级版式、
三签栏、多方签署栏等，供肉眼核对格式是否符合投标要求；正式数据请在软件界面中录入后生成。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from app.gendocs import registry
from tests._genall_helpers import sample_payload

_UNSAFE = re.compile(r'[\\/:*?"<>|\s]+')


def _safe(title: str) -> str:
    return _UNSAFE.sub("", title)[:40] or "附件"


def main():
    parser = argparse.ArgumentParser(description="导出全部模板样例 docx 供格式复核")
    parser.add_argument("--output", type=Path,
                        default=Path("docs/格式复核样例_全量"), help="样例输出目录")
    args = parser.parse_args()
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)

    project = {
        "name": "【样例】某房建工程监理项目",
        "business_type": "supervision",
        "client": "虚构建设单位",
        "region": "示例地区",
        "deadline": "2027-12-31T17:00:00+08:00",
        "facts": {},
    }

    index = {}
    for i, builder in enumerate(registry._BUILDERS, 1):
        payload = sample_payload(builder.payload_model)
        raw = builder.build(payload, project)
        filename = f"{i:02d}_{_safe(builder.title)}.docx"
        (out / filename).write_bytes(raw)
        index[builder.key] = (i, builder.title, filename, builder.form_type)
        print(f"[{i:02d}] {filename}  ({builder.form_type})")

    # 附带一份索引清单（txt，避免依赖 markdown 渲染）
    lines = ["序号  模板标识  版式类型  文件名", "-" * 60]
    for key, (i, title, fn, ft) in sorted(index.items(), key=lambda kv: kv[1][0]):
        lines.append(f"{i:>2}   {key:<26} {ft:<9} {fn}")
    lines.insert(1, f"共 {len(index)} 个模板；输出目录：{out.resolve()}")
    (out / "_索引.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n完成：共 {len(index)} 个样例，已写入 {out.resolve()}")


if __name__ == "__main__":
    main()
