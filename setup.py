#!/usr/bin/env python3
"""Install the pinned local application dependencies and build its frontend."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="安装 Skill Lab 本机依赖并构建页面")
    parser.add_argument("--skip-install", action="store_true", help="依赖已安装时仅构建前端")
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        parser.error("需要 Python 3.9 或更新版本")
    npm = shutil.which("npm")
    if not npm:
        parser.error("未找到 npm；请安装 Node.js 22 或更新的受支持版本")
    env_dir = ROOT / "backend" / ".venv"
    interpreter = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not args.skip_install:
        if not interpreter.exists():
            venv.EnvBuilder(with_pip=True).create(env_dir)
        requirements = ROOT / "backend/requirements.lock.txt"
        if not requirements.exists():
            requirements = ROOT / "backend/requirements.txt"
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(requirements)], check=True)
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    print("准备完成。运行 python3 start.py 启动本机服务。")


if __name__ == "__main__":
    main()
