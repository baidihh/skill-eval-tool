"""Persist accounting before network I/O. This module never performs HTTP requests.

Transport rows represent conservative send intent: crashing before a response does
not release their budget. Usage observations are append-only replacements of one
supplier fee item, never an incremental amount to add to the preceding version.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import text
from .domain import canonical, digest
from .storage import DomainError, uid, now


class Ledger:
    def __init__(self, repository):
        self.repo = repository

    def _call(self, connection, call_id):
        row = connection.execute(text('SELECT * FROM ledger_calls WHERE id=:id'), {'id': call_id}).mappings().first()
        if not row:
            raise DomainError('call_not_found', '逻辑调用不存在', 404)
        return dict(row)

    def reserve_call(self, experiment_id, case_id, kind, batch_id, namespace, submit_key, frozen_request):
        if kind not in ('expert', 'judge') or not all(isinstance(v, str) and v.strip() for v in (case_id, batch_id, namespace, submit_key)):
            raise DomainError('invalid_call', '调用类型、批次、题目及供应商幂等键不能为空')
        request_hash = digest(frozen_request)
        with self.repo.write() as c:
            self.repo.experiment(experiment_id, c)
            row = c.execute(text('SELECT * FROM ledger_calls WHERE namespace=:namespace AND submit_key=:submit_key'), {'namespace': namespace, 'submit_key': submit_key}).mappings().first()
            if row:
                result = dict(row)
                if result['request_hash'] != request_hash or any(result[key] != value for key, value in [('experiment_id', experiment_id), ('case_id', case_id), ('kind', kind), ('batch_id', batch_id)]):
                    raise DomainError('call_conflict', '相同幂等键不能变更请求或逻辑归属', 409)
                return result
            count = c.execute(text('SELECT count(*) FROM ledger_calls WHERE experiment_id=:exp AND case_id=:case AND kind=:kind AND batch_id=:batch'), {'exp': experiment_id, 'case': case_id, 'kind': kind, 'batch': batch_id}).scalar_one()
            maximum = 6 if kind == 'judge' else 1
            if count >= maximum:
                raise DomainError('logical_call_budget', '本批次逻辑调用额度已耗尽')
            result = dict(id=uid(), experiment_id=experiment_id, case_id=case_id, kind=kind, batch_id=batch_id, namespace=namespace, submit_key=submit_key, request_hash=request_hash, created_at=now())
            c.execute(text('INSERT INTO ledger_calls VALUES(:id,:experiment_id,:case_id,:kind,:batch_id,:namespace,:submit_key,:request_hash,:created_at)'), result)
            self.repo.event(c, experiment_id, 'logical_call_reserved', {'call_id': result['id'], 'kind': kind, 'batch_id': batch_id})
            return result

    def reserve_transport(self, call_id, operation_id, recovery=None):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise DomainError('missing_operation', '传输操作标识不能为空')
        recovery = recovery or {}
        with self.repo.write() as c:
            call = self._call(c, call_id)
            existing = c.execute(text('SELECT * FROM ledger_transports WHERE call_id=:call AND operation_id=:op'), {'call': call_id, 'op': operation_id}).mappings().first()
            if existing:
                result = dict(existing)
                if json.loads(result['recovery']) != recovery:
                    raise DomainError('transport_conflict', '同一传输操作内容冲突', 409)
                return result
            count = c.execute(text('SELECT count(*) FROM ledger_transports WHERE call_id=:call'), {'call': call_id}).scalar_one()
            if count >= 2:
                raise DomainError('retry_budget', '本逻辑调用技术恢复额度已耗尽')
            if count:
                mode = recovery.get('mode')
                if mode == 'safe_idempotent_replay':
                    expiry = recovery.get('valid_until')
                    try:
                        parsed = datetime.fromisoformat(expiry)
                        valid = parsed.tzinfo is not None and parsed > datetime.now(timezone.utc)
                    except (ValueError, TypeError):
                        valid = False
                    if not valid or recovery.get('guaranteed_same_execution') is not True:
                        raise DomainError('unsafe_replay', '供应商幂等保证缺失或有效期已过，禁止重发')
                elif mode == 'judge_unknown_billable_retry' and call['kind'] == 'judge':
                    pass
                else:
                    raise DomainError('unsafe_replay', '未知执行不能自动重提；必须提供有效幂等保证或显式裁判计费重试')
            elif recovery:
                raise DomainError('invalid_recovery', '首次请求不应携带技术重试声明')
            total = c.execute(text('''SELECT count(*) FROM ledger_transports t JOIN ledger_calls l ON l.id=t.call_id
                WHERE l.experiment_id=:exp AND l.case_id=:case AND l.kind=:kind AND l.batch_id=:batch'''), {'exp': call['experiment_id'], 'case': call['case_id'], 'kind': call['kind'], 'batch': call['batch_id']}).scalar_one()
            if total >= (12 if call['kind'] == 'judge' else 2):
                raise DomainError('transport_budget', '本题本批次实际请求额度已耗尽')
            result = dict(id=uid(), call_id=call_id, seq=count + 1, operation_id=operation_id, request_hash=call['request_hash'], state='send_intent', recovery=canonical(recovery), created_at=now())
            c.execute(text('INSERT INTO ledger_transports VALUES(:id,:call_id,:seq,:operation_id,:request_hash,:state,:recovery,:created_at)'), result)
            self.repo.event(c, call['experiment_id'], 'transport_reserved', {'call_id': call_id, 'transport_id': result['id'], 'seq': result['seq']})
            return result

    def bind_external(self, call_id, external_run_id):
        if not isinstance(external_run_id, str) or not external_run_id.strip():
            raise DomainError('missing_external_run', '外部执行标识不能为空')
        with self.repo.write() as c:
            call = self._call(c, call_id)
            found = c.execute(text('SELECT * FROM ledger_external_runs WHERE (namespace=:ns AND external_run_id=:ext) OR call_id=:call'), {'ns': call['namespace'], 'ext': external_run_id, 'call': call_id}).mappings().all()
            if found:
                if len(found) == 1 and found[0]['call_id'] == call_id and found[0]['external_run_id'] == external_run_id:
                    return dict(found[0])
                raise DomainError('external_ownership_conflict', '一个外部执行只能归属一个逻辑调用', 409)
            c.execute(text('INSERT INTO ledger_external_runs VALUES(:namespace,:external_run_id,:call_id)'), {'namespace': call['namespace'], 'external_run_id': external_run_id, 'call_id': call_id})
            self.repo.event(c, call['experiment_id'], 'external_run_bound', {'call_id': call_id, 'external_run_id': external_run_id})
            return {'namespace': call['namespace'], 'external_run_id': external_run_id, 'call_id': call_id}

    def observe_usage(self, call_id, item_id, supplier_event_id, payload):
        if not all(isinstance(v, str) and v.strip() for v in (item_id, supplier_event_id)):
            raise DomainError('invalid_usage', '供应商费用项与事件标识不能为空')
        data = dict(payload)
        amount = data.get('amount')
        if amount is not None:
            try:
                number = Decimal(str(amount))
                if not number.is_finite() or number < 0:
                    raise ValueError()
            except (InvalidOperation, ValueError):
                raise DomainError('invalid_usage', '费用必须为有限非负数')
            if not isinstance(data.get('currency'), str) or not data['currency'].strip():
                raise DomainError('invalid_usage', '已知费用必须提供币种')
            data['amount'] = str(number)
        tokens = data.get('tokens')
        if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0):
            raise DomainError('invalid_usage', 'Token 必须为非负整数或未知')
        if data.get('basis') not in ('estimate', 'actual', 'unknown'):
            raise DomainError('invalid_usage', '费用依据必须是 estimate、actual 或 unknown')
        content_hash = digest(data)
        with self.repo.write() as c:
            call = self._call(c, call_id)
            found = c.execute(text('SELECT * FROM usage_observations WHERE namespace=:ns AND supplier_event_id=:event'), {'ns': call['namespace'], 'event': supplier_event_id}).mappings().first()
            if found:
                if found['call_id'] != call_id or found['item_id'] != item_id or found['content_hash'] != content_hash:
                    raise DomainError('usage_conflict', '供应商同一账单事件内容冲突', 409)
                return dict(found)
            previous = c.execute(text('SELECT call_id,version FROM usage_observations WHERE namespace=:ns AND item_id=:item ORDER BY version DESC LIMIT 1'), {'ns': call['namespace'], 'item': item_id}).first()
            if previous and previous[0] != call_id:
                raise DomainError('usage_ownership_conflict', '同一费用项不能重复归属其他调用', 409)
            result = dict(id=uid(), namespace=call['namespace'], item_id=item_id, version=previous[1] + 1 if previous else 1, supplier_event_id=supplier_event_id, call_id=call_id, payload=canonical(data), content_hash=content_hash, created_at=now())
            c.execute(text('INSERT INTO usage_observations VALUES(:id,:namespace,:item_id,:version,:supplier_event_id,:call_id,:payload,:content_hash,:created_at)'), result)
            self.repo.event(c, call['experiment_id'], 'usage_observed', {'observation_id': result['id'], 'call_id': call_id})
            return result

    def snapshot(self, experiment_id, selection=None):
        """Return a materialized immutable value; persist this in a report revision.

        Pass the complete returned value as selection to reconstruct its original
        call/transport/usage coverage even when later observations have arrived.
        """
        with self.repo.engine.connect() as c:
            calls = [dict(row) for row in c.execute(text('SELECT * FROM ledger_calls WHERE experiment_id=:id ORDER BY id'), {'id': experiment_id}).mappings()]
            transports = [dict(row) for row in c.execute(text('SELECT t.* FROM ledger_transports t JOIN ledger_calls l ON l.id=t.call_id WHERE l.experiment_id=:id ORDER BY t.id'), {'id': experiment_id}).mappings()]
            observations = [dict(row) for row in c.execute(text('SELECT u.* FROM usage_observations u JOIN ledger_calls l ON l.id=u.call_id WHERE l.experiment_id=:id ORDER BY u.version'), {'id': experiment_id}).mappings()]
        if selection is not None:
            if not isinstance(selection, dict):
                raise DomainError('invalid_selection', '重建费用快照需要完整选择清单')
            for key, rows in [('call_ids', calls), ('transport_ids', transports), ('observation_ids', observations)]:
                wanted = set(selection.get(key, []))
                if not wanted <= {row['id'] for row in rows}:
                    raise DomainError('invalid_selection', '快照选择引用不存在或不属于该实验')
                rows[:] = [row for row in rows if row['id'] in wanted]
        latest = {}
        for row in observations:
            latest[(row['namespace'], row['item_id'])] = row
        selected = list(latest.values())
        totals = {}; token_observations = {}; known_calls = set(); bases = set()
        for row in selected:
            data = json.loads(row['payload'])
            if data.get('amount') is not None:
                currency = data['currency']; totals[currency] = totals.get(currency, Decimal(0)) + Decimal(data['amount'])
                known_calls.add(row['call_id'])
            if data.get('tokens') is not None:
                # Token counts describe a logical call, unlike independently
                # billable supplier fee items. Do not duplicate tokens if a
                # provider splits one call into multiple invoice line items.
                previous = token_observations.get(row['call_id'])
                if previous is None or row['created_at'] > previous[0]:
                    token_observations[row['call_id']] = (row['created_at'], data['tokens'])
            bases.add(data['basis'])
        call_ids = {row['id'] for row in calls}
        if not {row['call_id'] for row in selected + transports} <= call_ids:
            raise DomainError('invalid_selection', '快照调用引用不完整')
        result = {'schema_version': 'usage-ledger-v1', 'call_ids': sorted(call_ids), 'transport_ids': sorted(row['id'] for row in transports), 'observation_ids': sorted(row['id'] for row in selected), 'logical_calls': len(calls), 'sent_or_unknown_requests': len(transports), 'known_usage_calls': len(known_calls), 'unknown_usage_calls': len(calls) - len(known_calls), 'amounts_by_currency': {key: str(value) for key, value in sorted(totals.items())}, 'tokens': sum(value[1] for value in token_observations.values()) if token_observations else None, 'token_calls_covered': len(token_observations), 'bases': sorted(bases)}
        return result
