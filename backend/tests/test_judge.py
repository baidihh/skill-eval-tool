import unittest
from app.judge import validate_judge_output
from app.storage import DomainError
class JudgeTests(unittest.TestCase):
    def test_nonexistent_citation_rejected(self):
        with self.assertRaises(DomainError):validate_judge_output({'checks':[{'check_id':'x','result':'pass','reason':'ok','evidence_refs':[{'evidence_id':'fake'}]}]},[{'id':'x'}],[])
    def test_text_out_of_range_rejected(self):
        with self.assertRaises(DomainError):validate_judge_output({'checks':[{'check_id':'x','result':'pass','reason':'ok','evidence_refs':[{'evidence_id':'e','line_start':1,'line_end':8}]}]},[{'id':'x'}],[{'id':'e','state':'parsed','content':'one line'}])
    def test_valid_reference_accepted(self):
        value=validate_judge_output({'checks':[{'check_id':'x','result':'pass','reason':'verified','evidence_refs':[{'evidence_id':'e','json_path':'$.eligible'}]}]},[{'id':'x'}],[{'id':'e','state':'parsed','content':'{"eligible":true}'}])
        self.assertEqual(value.checks[0].result,'pass')
