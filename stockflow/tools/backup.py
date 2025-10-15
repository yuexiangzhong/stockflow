from pathlib import Path
import shutil, datetime, os, sys, json

def backup_project(config_path="config.yaml"):
    base = Path(".").resolve()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("backups")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"stockflow_backup_{stamp}.zip"
    includes = ["config.yaml", "infra/migrations", "data"]
    with shutil.make_archive(out.with_suffix(""), "zip", base_dir=base):
        pass  # 占位
    # 上面这一行会把整个工程打包，不够精细。改用临时汇集：
    tmp = base / f".backup_{stamp}"
    tmp.mkdir(parents=True)
    for p in includes:
        src = base / p
        if src.exists():
            dst = tmp / p
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    shutil.make_archive(out.with_suffix(""), "zip", root_dir=tmp)
    shutil.rmtree(tmp)
    print(f"✅ 备份完成：{out}")

if __name__ == "__main__":
    backup_project()
