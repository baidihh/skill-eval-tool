"""Bounded ZIP exchange without extracting attacker-controlled paths to disk."""
import hashlib
import io
import json
from pathlib import PurePosixPath
import stat
import zipfile

MAX_FILE = 10 * 1024 * 1024
MAX_PACKAGE = 100 * 1024 * 1024
MAX_FILES = 1000


def safe_path(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name or ':' in name:
        raise ValueError('附件路径非法')
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('附件路径不得为绝对路径或越级路径')
    return name


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('清单包含重复字段：' + key)
        result[key] = value
    return result


def read_package(data):
    if len(data) > MAX_PACKAGE:
        raise ValueError('压缩包超过 100 MiB')
    files = {}; total = 0; seen = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_FILES:
                raise ValueError('ZIP 文件数量须为 1—1000')
            for info in infos:
                name = safe_path(info.filename)
                if name in seen:
                    raise ValueError('ZIP 存在重复路径：' + name)
                seen.add(name)
                mode = info.external_attr >> 16
                if info.flag_bits & 1:
                    raise ValueError('不支持加密 ZIP')
                if info.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise ValueError('ZIP 只允许普通文件，不允许目录或链接')
                if info.file_size > MAX_FILE:
                    raise ValueError('单文件超过 10 MiB')
                chunks = []; size = 0
                with archive.open(info) as source:
                    while True:
                        chunk = source.read(64 * 1024)
                        if not chunk:
                            break
                        size += len(chunk); total += len(chunk)
                        if size > MAX_FILE or total > MAX_PACKAGE:
                            raise ValueError('解压内容超过限制')
                        chunks.append(chunk)
                files[name] = b''.join(chunks)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('ZIP 损坏或压缩方式不支持') from exc
    if 'manifest.json' not in files:
        raise ValueError('ZIP 缺少 manifest.json')
    try:
        def invalid_constant(value):
            raise ValueError('清单包含非法数值：' + value)
        manifest = json.loads(files.pop('manifest.json').decode('utf-8'), object_pairs_hook=_reject_duplicates, parse_constant=invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('manifest.json 必须为 UTF-8 JSON') from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get('schema_version'), str):
        raise ValueError('清单缺少 schema_version')
    declared = {}
    entries = manifest.get('attachments', [])
    if not isinstance(entries, list):
        raise ValueError('附件清单必须为数组')
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('附件清单格式错误')
        name = safe_path(entry.get('path'))
        if name == 'manifest.json' or name in declared:
            raise ValueError('附件清单存在重复或保留路径')
        declared[name] = entry
    if set(declared) != set(files):
        raise ValueError('附件清单与 ZIP 文件不一致')
    for name, content in files.items():
        entry = declared[name]
        if entry.get('size') != len(content) or entry.get('sha256') != hashlib.sha256(content).hexdigest():
            raise ValueError('附件大小或哈希不匹配：' + name)
    return manifest, files


def write_package(manifest, files):
    manifest = dict(manifest)
    attachments = []
    for name, content in files.items():
        safe_path(name)
        if name == 'manifest.json' or not isinstance(content, bytes):
            raise ValueError('附件路径保留或内容不是字节')
        attachments.append({'path': name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(), 'purpose': 'evidence'})
    manifest['attachments'] = attachments
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        for name, content in files.items():
            archive.writestr(name, content)
    result = buffer.getvalue()
    read_package(result)
    return result
