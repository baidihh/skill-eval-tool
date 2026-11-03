#!/usr/bin/env python3
"""Consistent local backup; restore is offline-only until explicit takeover."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'backup-manifest.json').read_text())
    if manifest.get('status') != 'complete' or manifest.get('schema_version') != 'backup-v1':
        raise ValueError('备份清单版本或完成状态不正确')
    for name, expected in manifest['files'].items():
        candidate = folder / name
        path = candidate.resolve()
        if not path.is_relative_to(folder) or not path.is_file() or candidate.is_symlink():
            raise ValueError('备份文件缺失或路径非法：' + name)
        if sha(path) != expected:
            raise ValueError('文件哈希不匹配：' + name)
    db = sqlite3.connect('file:' + str(folder / 'evaluation.db') + '?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite 完整性检查失败')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite 外键检查失败')
    finally:
        db.close()
    return manifest


def backup(data_dir, destination):
    data_dir, destination = Path(data_dir).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(data_dir):
        raise ValueError('备份目标须不存在且位于数据目录外')
    if not (data_dir / 'evaluation.db').is_file():
        raise ValueError('找不到 evaluation.db')
    request, ack, maintenance = [data_dir / n for n in ('maintenance.request', 'maintenance.ack', 'maintenance')]
    with request.open('x') as stream:
        stream.write(str(os.getpid()))
    local_lock = open(data_dir / '.launcher.lock', 'a+')
    owns_offline = False
    temp = None
    try:
        try:
            fcntl.flock(local_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owns_offline = True
        except BlockingIOError:
            deadline = time.monotonic() + 25
            while not ack.exists() and time.monotonic() < deadline:
                time.sleep(0.2)
            if not ack.exists():
                raise ValueError('启动器未确认停止 API/worker，未生成备份')
        maintenance.write_text('backup')
        with open(data_dir / 'write.lock', 'a+') as barrier:
            fcntl.flock(barrier, fcntl.LOCK_EX)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix='.skill-lab-backup-', dir=str(destination.parent)))
            source = sqlite3.connect(str(data_dir / 'evaluation.db'))
            target = sqlite3.connect(str(temp / 'evaluation.db'))
            try:
                source.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
            finally:
                target.close(); source.close()
            (temp / 'objects').mkdir()
            # Copy all immutable objects (a conservative superset of current references).
            for path in (data_dir / 'objects').iterdir():
                if path.name.endswith('.tmp'):
                    continue
                if path.is_symlink() or not path.is_file() or len(path.name) != 64 or sha(path) != path.name:
                    raise ValueError('对象文件损坏或非法：' + path.name)
                shutil.copyfile(path, temp / 'objects' / path.name)
            for name in ('instance.json', 'deletion-manifest.json'):
                if (data_dir / name).is_file():
                    shutil.copyfile(data_dir / name, temp / name)
            if not (temp / 'instance.json').exists():
                (temp / 'instance.json').write_text(json.dumps({'lineage_id': str(uuid.uuid4())}))
            files = {str(p.relative_to(temp)): sha(p) for p in temp.rglob('*') if p.is_file()}
            manifest = {'schema_version': 'backup-v1', 'status': 'complete', 'app_version': '0.1.0', 'created_at': time.time(), 'files': files, 'credentials_included': False}
            (temp / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2))
            verify(temp)
            os.replace(str(temp), str(destination))
            temp = None
    finally:
        if temp is not None:
            shutil.rmtree(temp)
        maintenance.unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        if owns_offline:
            ack.unlink(missing_ok=True)
        local_lock.close()
    return destination


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    verify(source)
    if destination.exists():
        raise ValueError('恢复目标必须不存在')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.skill-lab-restore-', dir=str(destination.parent)))
    try:
        manifest = json.loads((source / 'backup-manifest.json').read_text())
        for name in manifest['files']:
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, path)
        shutil.copyfile(source / 'backup-manifest.json', temp / 'backup-manifest.json')
        verify(temp)
        (temp / 'RESTORED_READ_ONLY').write_text('仅离线验证；显式接管前禁止启动 API/worker。跨机器原实例需人工确认停机。')
        os.replace(str(temp), str(destination))
    except Exception:
        shutil.rmtree(temp)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description='Skill Lab 一致性备份与离线恢复')
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('backup'); b.add_argument('destination', type=Path); b.add_argument('--data-dir', type=Path, default=ROOT / '.data')
    v = sub.add_parser('verify'); v.add_argument('source', type=Path)
    r = sub.add_parser('restore'); r.add_argument('source', type=Path); r.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            print('备份完成：', backup(args.data_dir, args.destination))
        elif args.command == 'restore':
            print('已恢复至离线验证副本，未启动任何外部调用：', restore(args.source, args.destination))
        else:
            print('备份校验通过：', verify(args.source)['schema_version'])
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, '操作失败：%s\n' % error)


if __name__ == '__main__':
    main()
