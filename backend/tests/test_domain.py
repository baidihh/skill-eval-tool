import unittest
from app.domain import summarize, compare_manifests

class DomainTests(unittest.TestCase):
    def test_mixed_sample_denominators(self):
        cases=[]
        for i in range(10):
            cases.append({'case_id':str(i),'status':'succeeded' if i < 8 else 'failed','checks':[{'id':'x','dimension':'correctness','required':True,'critical':True,'result':'pass' if i<6 else 'fail' if i<8 else 'insufficient_evidence','reason':'fixture','evidence_refs':['e']}], 'grading_error': i == 9})
        summary,gate=summarize(cases)
        self.assertEqual(summary['all_sample_pass_rate']['percent'],60.0)
        self.assertEqual(summary['determined_pass_rate']['percent'],75.0)
        self.assertEqual(summary['complete_coverage']['percent'],80.0)
        self.assertEqual(summary['composite_score']['value'],75.0)
        self.assertEqual(summary['dimensions']['correctness']['score'],75.0)
        self.assertEqual(gate,'not_passed')
    def test_compare_allows_only_target_package_change(self):
        a={'source':'demo','target_skill':'refund-review','skills':[{'name':'refund-review','hash':'before'}],'model':'fixture-v1','system_prompt':'fixed','verified':True,'dataset_hash':'x','policy':'baseline-v1', **{k:{'state':'not_applicable'} for k in ('generation_parameters','tools','environment','memory','initial_state','judge','limits','attempt_selection','evaluation_time','authoritative_policy_hash','trigger_mode')}}
        b={**a,'skills':[{'name':'refund-review','hash':'after'}]}
        self.assertEqual(compare_manifests(a,b),[])
        b['model']='changed'
        self.assertTrue(compare_manifests(a,b))

class GateSafetyTests(unittest.TestCase):
    def test_required_manual_result_not_effective_before_review(self):
        cases=[{'case_id':'x','status':'succeeded','checks':[{'id':'j','dimension':'correctness','required':True,'critical':True,'result':'fail','manual_required':True,'reviewed':False}]}]
        summary,gate=summarize(cases)
        self.assertEqual(gate,'inconclusive');self.assertEqual(summary['critical_failures'],0)
    def test_missing_behavior_fields_block_even_if_equal(self):
        a={'source':'demo','target_skill':'s','skills':[{'name':'s','hash':'v1'}],'model':'x','system_prompt':'p','verified':True,'dataset_hash':'a','policy':'b'}
        self.assertTrue(compare_manifests(a,a))
