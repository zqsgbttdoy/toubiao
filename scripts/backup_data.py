"""投标平台数据一键备份：SQLite 一致性快照 + 全部附件 → ZIP + SHA-256 校验。

由 scripts/一键备份.bat 双击调用，也可命令行运行：
    .venv\\Scripts\\python.exe scripts\\backup_data.py

产物写入 data/backups/：
    toubiao_backup_<时间戳>.zip          —— 备份包（数据库快照 + blobs 附件 + 清单 + 恢复说明）
    toubiao_backup_<时间戳>.zip.sha256   —— 校验哈希与核对命令
每次运行都新建独立时间戳文件，绝不覆盖历史备份。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录（scripts 的上一级）
DB = ROOT / "data" / "database.sqlite3"
BLOBS = ROOT / "data" / "blobs"
OUT_DIR = ROOT / "data" / "backups"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="投标平台数据一致性备份")
    parser.add_argument("--output", type=Path, default=OUT_DIR, help="备份输出目录")
    args = parser.parse_args()

    if not DB.exists():
        print(f"[错误] 未找到数据库：{DB}")
        print("       请确认在本项目根目录的 data/ 下存在 database.sqlite3。")
        return 1

    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"toubiao_backup_{ts}.zip"

    blob_files = sorted(p for p in BLOBS.rglob("*") if p.is_file()) if BLOBS.exists() else []

    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "database.sqlite3"
        # 1) SQLite 官方备份 API 取一致性快照（自动合并 WAL，避免半截写入）
        src = sqlite3.connect(str(DB))
        dst = sqlite3.connect(str(snap))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

        chk = sqlite3.connect(str(snap))
        integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
        table_count = chk.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        chk.close()
        if integrity != "ok":
            print(f"[错误] 数据库快照自检失败：{integrity}，已中止，未写出备份。")
            return 2

        manifest = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "source_db": str(DB),
            "db_size_bytes": DB.stat().st_size,
            "snapshot_integrity": integrity,
            "table_count": table_count,
            "attachment_count": len(blob_files),
            "attachment_bytes": sum(p.stat().st_size for p in blob_files),
        }

        restore_readme = (
            "恢复步骤（务必在【停机】状态下操作，恢复前先把现有 data/ 另存一份以防万一）：\n"
            "  1) 关闭投标平台程序（确认没有在运行的 python/uvicorn 进程）。\n"
            "  2) 解压本 ZIP。\n"
            "  3) 把其中的 database.sqlite3 覆盖到项目 data/database.sqlite3。\n"
            "  4) 把其中的 blobs/ 整个目录覆盖到项目 data/blobs/。\n"
            "  5) 重新启动程序，核对项目与附件是否正常。\n"
            f"  ※ 校验：本包 SHA-256 应等于 {zip_path.name}.sha256 中记录的哈希。\n"
        )

        # 2) 打包 ZIP
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "database.sqlite3")
            for p in blob_files:
                z.write(p, "blobs/" + p.relative_to(BLOBS).as_posix())
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr("恢复说明.txt", restore_readme)

    # 3) 生成校验哈希文件
    digest = sha256(zip_path)
    sha_path = Path(str(zip_path) + ".sha256")
    sha_path.write_text(
        f"{digest}  {zip_path.name}\n"
        f"# 生成时间：{manifest['created']}\n"
        f"# 数据库快照自检：{integrity}（表数 {table_count}）；附件 {manifest['attachment_count']} 个\n"
        f"# 核对命令（PowerShell，在本备份目录运行）：\n"
        f"#   (Get-FileHash -Algorithm SHA256 '{zip_path.name}').Hash.ToLower()\n",
        encoding="utf-8",
    )

    # 4) 回读校验：ZIP 结构完好 + 重算哈希一致
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
    ok = (bad is None and sha256(zip_path) == digest)

    print("=" * 56)
    print("备份成功 ✅" if ok else "备份完成，但回读校验异常，请重跑一次 ⚠️")
    print("-" * 56)
    print(f"备份文件：{zip_path}")
    print(f"校验文件：{sha_path}")
    print(f"SHA-256：{digest}")
    print(f"大小：{zip_path.stat().st_size:,} 字节")
    print(f"数据库：{integrity}（{table_count} 张表）；本次包含附件 {manifest['attachment_count']} 个")
    print(f"备份目录中共有 {len(list(out_dir.glob('toubiao_backup_*.zip')))} 份历史备份")
    print("提示：请连同 .sha256 一起复制到 U 盘/网盘妥善保管；恢复只能在停机状态下进行。")
    print("=" * 56)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
