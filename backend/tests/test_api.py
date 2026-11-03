import os
import tempfile
import unittest

DATA=tempfile.TemporaryDirectory();os.environ['EVAL_DATA_DIR']=DATA.name;os.environ['EVAL_SEED_DEMO']='0'
from fastapi.testclient import TestClient
from app.main import app,repo

class ApiTests(unittest.TestCase):
    def test_session_seed_import_and_fixed_exports(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/objects').status_code,401)
            csrf=client.get('/api/v1/session').json()['csrf_token'];headers={'X-CSRF-Token':csrf}
            self.assertEqual(client.post('/api/v1/demo/seed').status_code,403)
            self.assertEqual(client.post('/api/v1/demo/seed',headers=headers).status_code,200)
            obj=client.get('/api/v1/objects').json()[0];dataset=client.get('/api/v1/datasets').json()[0]
            payload={'schema_version':'1.0','name':'外部运行','object_id':obj['id'],'dataset_id':dataset['id'],'records':[{'case_id':'RF01','external_run_id':'test-external-1','attempt_seq':1,'status':'succeeded','output':{'eligible':True,'refund_cents':6000}}]}
            preview=client.post('/api/v1/imports',json=payload,headers=headers).json()
            imported=client.post('/api/v1/imports/'+preview['id']+'/confirm',json={'operation_id':'import-test'},headers=headers)
            self.assertEqual(imported.status_code,200,imported.text)
            again=client.post('/api/v1/imports/'+preview['id']+'/confirm',json={'operation_id':'import-test'},headers=headers)
            self.assertEqual(again.json()['id'],imported.json()['id'])
            from app.main import service
            service.process(imported.json()['id'])
            report=client.get('/api/v1/reports/'+imported.json()['id']).json()
            self.assertEqual(report['source'],'imported');self.assertEqual(report['summary']['total'],8)
            exported=client.get('/api/v1/reports/'+imported.json()['id']+'/revisions/'+report['id']+'/export?format=json')
            self.assertEqual(exported.json()['content_hash'],report['content_hash'])
            duplicate=client.post('/api/v1/imports/'+preview['id']+'/confirm',json={'operation_id':'different-op'},headers=headers)
            self.assertEqual(duplicate.json()['id'],imported.json()['id'])
    def test_reject_foreign_host_origin(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/session',headers={'host':'evil.example'}).status_code,403)
            self.assertEqual(client.get('/api/v1/session',headers={'origin':'https://evil.example'}).status_code,403)
    def test_archive_visibility_and_html_export(self):
        with TestClient(app) as client:
            csrf=client.get('/api/v1/session').json()['csrf_token'];headers={'X-CSRF-Token':csrf}
            client.post('/api/v1/demo/seed',headers=headers)
            obj=client.get('/api/v1/objects').json()[0]
            self.assertFalse(obj['archived'])
            archived=client.post('/api/v1/objects/'+obj['id']+'/archive',json={'operation_id':'api-archive-1'},headers=headers)
            self.assertEqual(archived.json()['archived'],True)
            self.assertNotIn(obj['id'],[x['id'] for x in client.get('/api/v1/objects').json()])
            self.assertIn(obj['id'],[x['id'] for x in client.get('/api/v1/objects?include_archived=true').json()])
            self.assertEqual(client.post('/api/v1/objects/'+obj['id']+'/unarchive',json={'operation_id':'api-unarchive-1'},headers=headers).json()['archived'],False)
            ex=next(x for x in client.get('/api/v1/experiments').json() if x['source']=='demo')
            report=client.get('/api/v1/reports/'+ex['id']).json()
            page=client.get('/api/v1/reports/'+ex['id']+'/revisions/'+report['id']+'/export?format=html')
            self.assertEqual(page.status_code,200);self.assertIn('text/html',page.headers['content-type'])
            self.assertIn('全样本通过占比',page.text);self.assertIn('逐题结果',page.text);self.assertIn(report['content_hash'],page.text)
            revisions=client.get('/api/v1/reports/'+ex['id']+'/revisions').json()
            self.assertTrue(revisions);self.assertIn('reason',revisions[0]);self.assertNotIn('cases',revisions[0])
    def test_report_zip_roundtrip_stays_imported_archive(self):
        with TestClient(app) as client:
            csrf=client.get('/api/v1/session').json()['csrf_token'];headers={'X-CSRF-Token':csrf}
            client.post('/api/v1/demo/seed',headers=headers)
            ex=next(x for x in client.get('/api/v1/experiments').json() if x['source']=='demo')
            report=client.get('/api/v1/reports/'+ex['id']).json()
            zipped=client.get('/api/v1/reports/'+ex['id']+'/revisions/'+report['id']+'/export.zip')
            self.assertEqual(zipped.status_code,200,zipped.text[:100] if zipped.status_code!=200 else '')
            preview=client.post('/api/v1/imports',content=zipped.content,headers={**headers,'Content-Type':'application/zip'})
            self.assertEqual(preview.status_code,200,preview.text)
            restored=client.post('/api/v1/imports/'+preview.json()['id']+'/confirm',json={'operation_id':'archive-1'},headers=headers)
            self.assertEqual(restored.status_code,200,restored.text)
            archive=restored.json();self.assertEqual(archive['source'],'imported');self.assertTrue(archive['read_only_archive'])
            new_report=client.get('/api/v1/reports/'+archive['id']).json()
            self.assertEqual(new_report['summary'],report['summary'])
            self.assertEqual(new_report['manifest']['archive_provenance']['original_hash'],report['content_hash'])
