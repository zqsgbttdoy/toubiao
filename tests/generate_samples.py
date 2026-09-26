"""仅生成两个合成DOCX上传样本；不启动服务、不运行测试、不写业务数据。"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="生成明确标注为虚构的监理和TIS上传样本，不运行验证")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "fixtures", help="样本输出目录")
    args = parser.parse_args()
    from app.demo import synthetic_docx
    args.output.mkdir(parents=True, exist_ok=True)
    for business in ("supervision", "tis"):
        path = args.output / (business + "_fictional_sample.docx")
        path.write_bytes(synthetic_docx(business))
        print(f"已生成虚构样本：{path}")


if __name__ == "__main__":
    main()
