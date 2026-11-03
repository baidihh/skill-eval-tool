#!/usr/bin/env python3
"""Supervise a loopback API and a single persistent worker."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="启动 Skill Lab 本机网页及后台评分任务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".data")
    parser.add_argument("--no-worker", action="store_true", help="只读调试时不启动后台任务；不等同于离线恢复验证")
    parser.add_argument("--takeover", action="store_true", help="显式接管已验证恢复副本；须确认其他机器原实例已停止")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024—65535 之间")
    if sys.platform == "win32":
        parser.error("当前启动器使用 POSIX 文件锁，支持 macOS/Linux；Windows 尚未适配")
    import fcntl
    interpreter = ROOT / "backend/.venv/bin/python"
    if not interpreter.exists():
        parser.error("未找到虚拟环境；请先运行 python3 setup.py")
    if not (ROOT / "frontend/dist/index.html").exists():
        parser.error("未找到前端构建；请先运行 python3 setup.py")
    data_dir = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / 'RESTORED_READ_ONLY').exists() and not args.takeover:
        parser.error('恢复副本默认仅供离线验证；确认原实例已停机后使用 --takeover')
    if (data_dir / 'maintenance.request').exists():
        parser.error('数据目录正在备份维护，请等待维护结束')
    # Hold the directory lock before reading/creating its identity.
    directory_lock = open(data_dir / ".launcher.lock", "a+")
    try:
        fcntl.flock(directory_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("该数据目录已有启动器运行")
    identity_path = data_dir / "instance.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
    else:
        identity = {"lineage_id": str(uuid.uuid4())}
        identity_path.write_text(json.dumps(identity), encoding="utf-8")
    lineage = str(uuid.UUID(identity["lineage_id"]))
    # Cloned data with the same identity cannot execute twice on this machine.
    lock_root = Path(tempfile.gettempdir()) / ("skill-lab-%s-locks" % os.getuid())
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lineage_lock = open(lock_root / (lineage + ".lock"), "a+")
    try:
        fcntl.flock(lineage_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("同一实例谱系已在本机运行；恢复副本不能同时接管")
    if args.takeover:
        (data_dir / 'RESTORED_READ_ONLY').unlink(missing_ok=True)
    env = os.environ.copy()
    env.update(EVAL_DATA_DIR=str(data_dir), EVAL_FRONTEND_DIR=str(ROOT / "frontend/dist"), EVAL_PORT=str(args.port), PYTHONPATH=os.pathsep.join([str(ROOT / "backend"), str(ROOT)]))
    children = []
    stopping = False

    def stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        api = subprocess.Popen([str(interpreter), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)], cwd=ROOT / "backend", env=env)
        children.append(api)
        worker = None
        if not args.no_worker:
            worker = subprocess.Popen([str(interpreter), "-m", "app.worker"], cwd=ROOT / "backend", env=env)
            children.append(worker)
        print("\nSkill Lab: http://127.0.0.1:%s\n数据目录: %s\n按 Ctrl+C 停止服务。" % (args.port, data_dir), flush=True)
        restart_times = []
        while not stopping:
            if (data_dir / 'maintenance.request').exists():
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                for child in children:
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                (data_dir / 'maintenance.ack').write_text(str(os.getpid()))
                while (data_dir / 'maintenance.request').exists() and not stopping:
                    time.sleep(0.2)
                (data_dir / 'maintenance.ack').unlink(missing_ok=True)
                if stopping:
                    break
                api = subprocess.Popen([str(interpreter), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(args.port)], cwd=ROOT / 'backend', env=env)
                children.append(api)
                if not args.no_worker:
                    worker = subprocess.Popen([str(interpreter), '-m', 'app.worker'], cwd=ROOT / 'backend', env=env)
                    children.append(worker)
                continue
            if api.poll() is not None:
                raise RuntimeError("API 进程已退出，退出码 %s" % api.returncode)
            if worker is not None and worker.poll() is not None:
                now = time.monotonic()
                restart_times = [t for t in restart_times if now - t < 60]
                if len(restart_times) >= 3:
                    raise RuntimeError("worker 在一分钟内连续退出，已停止自动重启，请检查错误")
                restart_times.append(now)
                print("后台进程退出，正在恢复持久任务…", flush=True)
                worker = subprocess.Popen([str(interpreter), "-m", "app.worker"], cwd=ROOT / "backend", env=env)
                children.append(worker)
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        lineage_lock.close()
        directory_lock.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print("启动失败：%s" % exc, file=sys.stderr)
        sys.exit(1)
