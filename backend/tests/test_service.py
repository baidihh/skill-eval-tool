import copy
import json
import tempfile
import unittest
from app.storage import Repository,DomainError
from app.service import Service
from app.domain import canonical

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.repo=Repository(self.tmp.name);self.svc=Service(self.repo);self.svc.seed()
    def tearDown(self):self.repo.engine.dispose();self.tmp.cleanup()
    def test_demo_regression_and_immutable_review(self):
        experiments=self.repo.experiments();before=next(x for x in experiments if x['variant']=='before');after=next(x for x in experiments if x['variant']=='after')
        original=self.svc.report(before['id']);saved=canonical(original);case=next(x for x in original['cases'] if x['case_id']=='RF06')
        result=self.svc.compare({'left_experiment_id':before['id'],'right_experiment_id':after['id']})
        self.assertTrue(result['strict_eligible']);self.assertEqual(result['summary']['improved'],3)
        payload={'experiment_id':before['id'],'expected_revision_id':original['id'],'operation_id':'review1','case_id':'RF06','check_id':'correctness','result':'fail','reason':'确认第八天超过168小时','evidence_refs':[case['evidence'][0]['id']]}
        revised=self.svc.review(payload)
        self.assertNotEqual(revised['id'],original['id']);self.assertEqual(canonical(self.svc.report(before['id'],original['id'])),saved)
        self.assertEqual(self.svc.review(payload)['id'],revised['id'])
        with self.assertRaises(DomainError) as ctx:self.svc.review({**payload,'operation_id':'review2'})
        self.assertEqual(ctx.exception.status,409)
    def test_live_cannot_silently_demo(self):
        obj=self.repo.list('object')[0];ds=self.repo.list('dataset')[0]
        ex=self.svc.create_experiment({'name':'real','source':'live','object_id':obj['id'],'dataset_id':ds['id']})
        with self.assertRaises(DomainError) as ctx:self.svc.start(ex['id'])
        self.assertEqual(ctx.exception.code,'platform_unconfigured');self.assertEqual(self.repo.experiment(ex['id'])['status'],'draft')
    def test_immutable_storage_rejects_update(self):
        from sqlalchemy import text
        report=self.repo.list('report')[0]
        with self.assertRaises(Exception):
            with self.repo.write() as c:c.execute(text('UPDATE records SET payload="{}" WHERE id=:id'),{'id':report['id']})
    def test_import_atomic_conflict_and_no_double_experiment(self):
        obj=self.repo.list('object')[0];ds=self.repo.list('dataset')[0]
        payload={'schema_version':'1.0','name':'external','object_id':obj['id'],'dataset_id':ds['id'],'records':[{'case_id':'RF01','status':'succeeded','external_run_id':'run1','attempt_seq':1,'output':{'eligible':True,'refund_cents':6000}}]}
        from app.domain import digest
        preview={'content_hash':digest(payload),'payload':payload}
        before=len(self.repo.experiments())
        first=self.svc.confirm_import(preview,{'operation_id':'x'})
        second=self.svc.confirm_import(preview,{'operation_id':'y'})
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.repo.experiments()),before+1)
        changed=copy.deepcopy(payload);changed['records'][0]['output']['eligible']=False
        with self.assertRaises(DomainError):self.svc.confirm_import({'content_hash':digest(changed),'payload':changed},{'operation_id':'z'})
        self.assertEqual(len(self.repo.experiments()),before+1)
    def test_regrade_candidate_and_review_undo(self):
        ex=self.repo.experiments()[0];original=self.svc.report(ex['id']);case=original['cases'][0]
        candidate=self.svc.regrade(ex['id'],original['id'],'grade-candidate')
        self.assertEqual(self.repo.experiment(ex['id'])['current_revision_id'],original['id'])
        adopted=self.svc.adopt_grading(candidate['id'],{'expected_revision_id':original['id'],'operation_id':'adopt'})
        review=self.svc.review({'experiment_id':ex['id'],'expected_revision_id':adopted['id'],'operation_id':'review-undo','case_id':case['case_id'],'check_id':'completion','result':'pass','reason':'复核实际字段','evidence_refs':[case['evidence'][0]['id']]})
        undone=self.svc.undo_review({'experiment_id':ex['id'],'expected_revision_id':review['id'],'operation_id':'undo','case_id':case['case_id'],'check_id':'completion','reason':'恢复自动结论'})
        check=next(x for x in undone['cases'][0]['checks'] if x['id']=='completion')
        self.assertFalse(check['reviewed'])
    def test_missing_external_sequence_rejected(self):
        ds=self.repo.list('dataset')[0]
        with self.assertRaises(DomainError):self.svc.validate_records([{'case_id':'RF01','external_run_id':'r','status':'succeeded'}],ds)
    def test_invalid_evaluator_parameters_rejected(self):
        from app.service import validate_cases
        for check in ({'id':'x','type':'field_exists','fields':[]},{'id':'x','type':'equals','dimension':'unknown'},{'id':'x','type':'number_tolerance','tolerance':-1}):
            with self.assertRaises(DomainError):validate_cases([{'case_id':'one','input':'task','checks':[check]}])
    def test_object_archive_hides_and_blocks_new_experiments(self):
        obj=self.repo.list('object')[0];ds=self.repo.list('dataset')[0]
        self.svc.set_archive('object',obj['id'],'archive','archive-object')
        self.assertTrue(self.repo.archive_state('object',obj['id']))
        with self.assertRaises(DomainError) as ctx:self.svc.create_experiment({'name':'blocked','source':'demo','object_id':obj['id'],'dataset_id':ds['id']})
        self.assertEqual(ctx.exception.code,'object_archived')
        self.svc.set_archive('object',obj['id'],'unarchive','unarchive-object')
        self.assertFalse(self.repo.archive_state('object',obj['id']))
        created=self.svc.create_experiment({'name':'allowed','source':'demo','object_id':obj['id'],'dataset_id':ds['id']})
        self.assertEqual(created['status'],'draft')
    def test_experiment_archive_and_cancel_requested(self):
        obj=self.repo.list('object')[0];ds=self.repo.list('dataset')[0]
        ex=self.svc.create_experiment({'name':'cancel-me','source':'demo','object_id':obj['id'],'dataset_id':ds['id']})
        self.svc.start(ex['id'])
        with self.repo.write() as c:
            running=self.repo.experiment(ex['id'],c);running['status']='running';self.repo.update_experiment(c,running)
        requested=self.svc.cancel(ex['id'])
        self.assertEqual(requested['status'],'cancel_requested')
        self.svc.process(ex['id'])
        final=self.repo.experiment(ex['id'])
        self.assertEqual(final['status'],'cancelled');self.assertEqual(final['initial_terminal_status'],'cancelled')
        self.svc.set_archive('experiment',ex['id'],'archive','archive-experiment')
        self.assertTrue(self.repo.experiment(ex['id'])['archived_at'])
        self.assertNotIn(ex['id'],[x['id'] for x in self.repo.experiments()])
        self.assertIn(ex['id'],[x['id'] for x in self.repo.experiments(include_archived=True)])
    def test_publish_rejects_same_name_and_version_with_new_content(self):
        first=self.svc.create_dataset({'name':'回归集','version':'2.0','cases':[{'case_id':'A','input':'task','checks':[{'id':'c','type':'equals','path':'x','expected':1}]}]})
        self.svc.publish(first['id'])
        second=self.svc.create_dataset({'name':'回归集','version':'2.0','cases':[{'case_id':'A','input':'changed','checks':[{'id':'c','type':'equals','path':'x','expected':2}]}]})
        with self.assertRaises(DomainError) as ctx:self.svc.publish(second['id'])
        self.assertEqual(ctx.exception.code,'version_conflict')
    def test_object_version_rejects_same_label_with_other_content(self):
        obj=self.repo.list('object')[0]
        with self.assertRaises(DomainError) as ctx:self.svc.add_object_version(obj['id'],{'version':obj['versions'][-1]['version'],'content':'different'})
        self.assertEqual(ctx.exception.code,'version_conflict')
        updated=self.svc.add_object_version(obj['id'],{'version':'v9','content':'new content'})
        self.assertEqual(updated['parent_id'],obj['id'])
    def test_insights_group_failures_and_fixed_version_has_none(self):
        experiments=self.repo.experiments();before=next(x for x in experiments if x['variant']=='before');after=next(x for x in experiments if x['variant']=='after')
        result=self.svc.insights(before['id'])
        self.assertTrue(result['suggestions'])
        top=result['suggestions'][0]
        self.assertEqual(top['priority'],'P0');self.assertEqual(sorted(top['cases']),['RF05','RF06','RF07'])
        self.assertEqual(top['related_file'],'SKILL.md');self.assertEqual(top['related_line'],2);self.assertFalse(top['line_verified'])
        self.assertEqual(self.svc.insights(after['id'])['suggestions'],[])
    def test_report_summary_has_composite_score(self):
        ex=next(x for x in self.repo.experiments() if x['variant']=='before');summary=self.svc.report(ex['id'])['summary']
        self.assertEqual(summary['dimensions']['correctness']['score'],62.5)
        self.assertEqual(summary['composite_score']['dimensions_counted'],3)
        self.assertEqual(summary['composite_score']['value'],87.5)
    def test_html_report_is_readable_and_escaped(self):
        from app.report_export import render_html
        ex=self.repo.experiments()[0];report=copy.deepcopy(self.svc.report(ex['id']))
        report['cases'][0]['input']='<script>alert(1)</script>'
        page=render_html(report)
        self.assertIn('BASELINE-V1',page);self.assertIn('全样本通过占比',page)
        self.assertIn('执行尝试',page);self.assertIn('检查项',page)
        self.assertNotIn('<script>alert(1)</script>',page);self.assertIn('&lt;script&gt;',page)
    def test_compare_reports_pair_coverage_and_check_changes(self):
        experiments=self.repo.experiments();before=next(x for x in experiments if x['variant']=='before');after=next(x for x in experiments if x['variant']=='after')
        result=self.svc.compare({'left_experiment_id':before['id'],'right_experiment_id':after['id']})
        self.assertEqual(result['coverage']['paired'],8);self.assertEqual(result['coverage']['comparable'],8)
        changed=[pair for pair in result['pairs'] if pair['change']=='improved']
        self.assertTrue(all(any(check['change']=='changed' for check in pair['checks']) for pair in changed))
    def test_late_usage_does_not_mutate_old_report_or_double_charge(self):
        ex=self.repo.experiments()[0];original=self.svc.report(ex['id']);before=canonical(original)
        one=self.svc.observe_usage(ex['id'],{'operation_id':'usage1','charge_id':'fee1','amount':'1.25','currency':'CNY','token_count':100})
        self.assertEqual(one['usage']['known_cost'],1.25)
        corrected=self.svc.observe_usage(ex['id'],{'operation_id':'usage2','charge_id':'fee1','amount':'1.10','currency':'CNY','token_count':100})
        self.assertEqual(corrected['usage']['known_cost'],1.1)
        self.assertEqual(canonical(self.svc.report(ex['id'],original['id'])),before)
        self.assertEqual(self.svc.observe_usage(ex['id'],{'operation_id':'usage2','charge_id':'fee1','amount':'1.10','currency':'CNY','token_count':100})['id'],corrected['id'])
