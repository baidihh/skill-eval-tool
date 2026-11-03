import copy
import tempfile
import unittest
from app.storage import Repository, DomainError
from app.service import Service
from app.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(self.tmp.name)
        service = Service(self.repo)
        service.seed()
        self.experiment = self.repo.experiments()[0]['id']
        self.ledger = Ledger(self.repo)

    def tearDown(self):
        self.repo.engine.dispose()
        self.tmp.cleanup()

    def call(self, key='check-1'):
        return self.ledger.reserve_call(self.experiment, 'RF01', 'judge', 'initial', 'vendor/account', key, {'task': key})

    def test_same_submission_reuses_call_and_conflicting_input_rejected(self):
        first = self.call()
        self.assertEqual(first['id'], self.call()['id'])
        with self.assertRaises(DomainError):
            self.ledger.reserve_call(self.experiment, 'RF01', 'judge', 'initial', 'vendor/account', 'check-1', {'task': 'changed'})

    def test_send_intent_survives_restart_and_one_retry_is_shared(self):
        call = self.call()
        sent = self.ledger.reserve_transport(call['id'], 'send1')
        self.assertEqual(sent['state'], 'send_intent')
        reopened = Ledger(self.repo)
        self.assertEqual(reopened.reserve_transport(call['id'], 'send1')['id'], sent['id'])
        with self.assertRaises(DomainError):
            reopened.reserve_transport(call['id'], 'send2')
        second = reopened.reserve_transport(call['id'], 'send2', recovery={'mode': 'judge_unknown_billable_retry'})
        self.assertEqual(second['seq'], 2)
        with self.assertRaises(DomainError):
            reopened.reserve_transport(call['id'], 'send3', recovery={'mode': 'judge_unknown_billable_retry'})
        snapshot = reopened.snapshot(self.experiment)
        self.assertEqual(snapshot['sent_or_unknown_requests'], 2)
        self.assertEqual(snapshot['unknown_usage_calls'], 1)

    def test_judge_initial_budget_six_calls_and_twelve_transports(self):
        for index in range(6):
            call = self.call('dimension-' + str(index))
            self.ledger.reserve_transport(call['id'], 'first')
            self.ledger.reserve_transport(call['id'], 'retry', recovery={'mode': 'judge_unknown_billable_retry'})
        with self.assertRaises(DomainError):
            self.call('dimension-7')
        self.assertEqual(self.ledger.snapshot(self.experiment)['sent_or_unknown_requests'], 12)

    def test_external_run_only_owned_once_and_safe_replay_no_new_execution(self):
        call = self.call()
        self.ledger.bind_external(call['id'], 'external-1')
        self.ledger.bind_external(call['id'], 'external-1')
        other = self.call('other')
        with self.assertRaises(DomainError):
            self.ledger.bind_external(other['id'], 'external-1')

    def test_usage_correction_replaces_item_and_snapshot_is_fixed(self):
        call = self.call()
        self.ledger.reserve_transport(call['id'], 'first')
        first = self.ledger.observe_usage(call['id'], 'invoice-item', 'event-1', {'amount': '1.20', 'currency': 'CNY', 'tokens': 30, 'basis': 'estimate'})
        snapshot = self.ledger.snapshot(self.experiment)
        saved = copy.deepcopy(snapshot)
        self.assertEqual(self.ledger.observe_usage(call['id'], 'invoice-item', 'event-1', {'amount': '1.20', 'currency': 'CNY', 'tokens': 30, 'basis': 'estimate'})['id'], first['id'])
        self.ledger.observe_usage(call['id'], 'invoice-item', 'event-2', {'amount': '1.00', 'currency': 'CNY', 'tokens': 30, 'basis': 'actual'})
        current = self.ledger.snapshot(self.experiment)
        self.assertEqual(current['amounts_by_currency']['CNY'], '1.00')
        self.assertEqual(current['tokens'], 30)
        self.assertEqual(saved, snapshot)
        self.assertEqual(self.ledger.snapshot(self.experiment, snapshot), snapshot)
        with self.assertRaises(DomainError):
            self.ledger.observe_usage(call['id'], 'invoice-item', 'event-2', {'amount': '3', 'currency': 'CNY'})

    def test_old_selection_excludes_new_calls_and_tokens_not_double_counted(self):
        call = self.call()
        self.ledger.reserve_transport(call['id'], 'first')
        self.ledger.observe_usage(call['id'], 'input-fee', 'input-event', {'amount':'0.2','currency':'CNY','tokens':30,'basis':'actual'})
        old = self.ledger.snapshot(self.experiment)
        self.ledger.observe_usage(call['id'], 'output-fee', 'output-event', {'amount':'0.5','currency':'CNY','tokens':30,'basis':'actual'})
        extra = self.call('another')
        self.ledger.reserve_transport(extra['id'], 'first')
        self.assertEqual(self.ledger.snapshot(self.experiment, old), old)
        current = self.ledger.snapshot(self.experiment)
        self.assertEqual(current['tokens'], 30)
        self.assertEqual(current['unknown_usage_calls'], 1)
        self.assertEqual(current['amounts_by_currency']['CNY'], '0.7')
