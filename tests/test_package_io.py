import importlib.util
import io
import json
from pathlib import Path
import stat
import unittest
import warnings
import zipfile

spec = importlib.util.spec_from_file_location('package_io', Path(__file__).resolve().parents[1] / 'package_io.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def raw_zip(entries):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries:
                archive.writestr(name, content)
    return stream.getvalue()


class PackageTests(unittest.TestCase):
    def test_package_roundtrip_preserves_bytes_and_hashes(self):
        payload = {'schema_version': '1.0', 'name': '固定报告'}
        encoded = module.write_package(payload, {'evidence/result.json': b'{"eligible":false}'})
        manifest, files = module.read_package(encoded)
        self.assertEqual(manifest['name'], '固定报告')
        self.assertEqual(files['evidence/result.json'], b'{"eligible":false}')

    def test_unsafe_paths_duplicates_and_symlinks_rejected(self):
        for path in ('../outside', '/absolute', 'folder/../outside', 'C:/outside', 'a\\b'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.read_package(raw_zip([(path, b'x')]))
        with self.assertRaisesRegex(ValueError, '重复路径'):
            module.read_package(raw_zip([('manifest.json', b'{}'), ('manifest.json', b'{}')]))
        link = zipfile.ZipInfo('link'); link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError, '链接'):
            module.read_package(raw_zip([(link, b'/outside')]))

    def test_hash_mismatch_and_oversized_actual_content_rejected(self):
        manifest = {'schema_version': '1.0', 'attachments': [{'path': 'x', 'size': 1, 'sha256': 'invalid'}]}
        with self.assertRaisesRegex(ValueError, '哈希'):
            module.read_package(raw_zip([('manifest.json', json.dumps(manifest)), ('x', b'x')]))
        with self.assertRaisesRegex(ValueError, '10 MiB'):
            module.read_package(raw_zip([('manifest.json', '{}'), ('x', b'x' * (module.MAX_FILE + 1))]))

    def test_undeclared_files_rejected(self):
        with self.assertRaisesRegex(ValueError, '清单'):
            module.read_package(raw_zip([('manifest.json', '{"schema_version":"1.0"}'), ('unlisted', 'x')]))


if __name__ == '__main__':
    unittest.main()
