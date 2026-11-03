import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('skill_lab_backup', Path(__file__).resolve().parents[1] / 'backup.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def test_backup_restore_keeps_database_and_content_and_stays_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root / 'data'; data.mkdir()
            (data / 'objects').mkdir()
            value = b'fixed evidence'
            content_hash = hashlib.sha256(value).hexdigest()
            (data / 'objects' / content_hash).write_bytes(value)
            (data / 'instance.json').write_text(json.dumps({'lineage_id': '4c4b3ee7-4f3c-432c-960e-b013f68a349a'}))
            db = sqlite3.connect(str(data / 'evaluation.db'))
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE example(value TEXT)')
            db.execute('INSERT INTO example VALUES (?)', ('immutable report',)); db.commit()
            with patch('subprocess.Popen') as popen:
                module.backup(data, root / 'snapshot')
                module.restore(root / 'snapshot', root / 'restored')
                popen.assert_not_called()
            restored = root / 'restored'
            self.assertTrue((restored / 'RESTORED_READ_ONLY').exists())
            self.assertEqual((restored / 'objects' / content_hash).read_bytes(), value)
            check = sqlite3.connect(str(restored / 'evaluation.db'))
            self.assertEqual(check.execute('SELECT value FROM example').fetchone()[0], 'immutable report')
            check.close(); db.close()
            self.assertFalse((data / 'maintenance.request').exists())
            self.assertFalse((data / 'maintenance').exists())

    def test_corrupted_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root / 'data'; data.mkdir(); (data / 'objects').mkdir()
            db = sqlite3.connect(str(data / 'evaluation.db')); db.execute('CREATE TABLE example(value TEXT)'); db.close()
            module.backup(data, root / 'snapshot')
            with (root / 'snapshot/evaluation.db').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, '哈希'):
                module.restore(root / 'snapshot', root / 'restored')
            self.assertFalse((root / 'restored').exists())


if __name__ == '__main__':
    unittest.main()
