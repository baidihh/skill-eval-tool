"""Render one fixed report revision as a self-contained, escaped HTML document."""
import html
import json

RESULT_LABELS={'pass':'通过','fail':'不通过','insufficient_evidence':'证据不足','not_applicable':'不适用'}
CONCLUSION_LABELS={'passed':'通过','not_passed':'不通过','inconclusive':'未判定'}
STATUS_LABELS={'completed':'已完成','partial_failure':'部分失败','failed':'失败','cancelled':'已取消','running':'运行中','queued':'排队中','draft':'草稿','awaiting_import':'等待导入'}
SOURCE_LABELS={'demo':'演示','imported':'离线导入','live':'真实调用'}


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def pretty(value):
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def pct(rate):
    if not isinstance(rate, dict) or rate.get('percent') is None:
        return '—'
    return '%s%%' % ('%.1f' % rate['percent'])


def fractions(rate):
    if not isinstance(rate, dict):
        return '—'
    return '%s / %s' % (rate.get('numerator', '—'), rate.get('denominator', '—'))


def render_html(report):
    summary = report.get('summary') or {}
    composite = summary.get('composite_score') or {}
    cases = report.get('cases') or []
    manifest = report.get('manifest') or {}
    usage = report.get('usage') or {}
    rev = report.get('revision_id') or report.get('id') or ''
    gate = report.get('gate')
    gate_text = {'passed': '门禁通过', 'not_passed': '门禁不通过', 'inconclusive': '门禁未判定'}.get(gate, '门禁%s' % (gate or '未知'))

    critical = []
    gaps = []
    for case in cases:
        for check in case.get('checks') or []:
            if check.get('critical') and check.get('result') == 'fail' and not check.get('error'):
                critical.append((case.get('case_id'), check.get('name') or check.get('id'), check.get('reason')))
        for evidence in case.get('evidence') or []:
            if evidence.get('state') not in ('parsed', 'acquired'):
                gaps.append((case.get('case_id'), evidence.get('state'), evidence.get('sha256')))

    dimensions = []
    for key, dim in sorted((summary.get('dimensions') or {}).items()):
        dimensions.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(dim.get('name') or key),
            esc('%.1f' % dim['score'] if dim.get('score') is not None else '—'),
            esc(dim.get('enabled', 0)), esc(dim.get('pass', 0)), esc(dim.get('fail', 0)),
            esc(dim.get('insufficient_evidence', 0)), esc(dim.get('not_applicable', 0))))

    case_html = []
    for case in cases:
        checks = []
        for check in case.get('checks') or []:
            refs = check.get('evidence_refs') or []
            checks.append('<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td class="mono">%s</td></tr>' % (
                esc(check.get('name') or check.get('id')),
                '<span class="flag">关键</span>' if check.get('critical') else '',
                esc(RESULT_LABELS.get(check.get('result'), check.get('result'))),
                '已复核' if check.get('reviewed') else '自动',
                esc(check.get('reason')),
                esc(', '.join(str(r.get('evidence_id', r) if isinstance(r, dict) else r) for r in refs) or '—')))
        attempts = []
        for attempt in case.get('attempts') or []:
            attempts.append('<tr><td>%s</td><td>%s</td><td>%s</td><td class="mono">%s</td><td>%s</td></tr>' % (
                esc(attempt.get('attempt_seq')), esc(attempt.get('status')), esc('主尝试' if attempt.get('is_primary') else '重试'),
                esc(attempt.get('external_run_id') or '—'), esc(attempt.get('created_at'))))
        reviews = []
        for event in case.get('review_history') or []:
            reviews.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(event.get('check_id')), esc(RESULT_LABELS.get(event.get('result'), event.get('result') or event.get('action'))),
                esc(event.get('reason')), esc(event.get('reviewer')), esc(event.get('created_at'))))
        evidence = []
        for item in case.get('evidence') or []:
            body = item.get('content')
            evidence.append('<div class="evidence"><div class="evidence-head"><span class="mono">%s</span><span>%s · %s</span></div><pre>%s</pre><small class="mono">SHA-256 %s</small></div>' % (
                esc(item.get('id')), esc(item.get('type')), esc(item.get('state')),
                esc(pretty(body) if not isinstance(body, str) else body), esc(item.get('sha256'))))
        case_html.append('''
<section class="case">
  <h3>%s <span class="pill %s">%s</span> %s</h3>
  <p class="meta">题目版本 %s · 执行状态 %s · 判分%s</p>
  <h4>任务输入</h4><pre>%s</pre>
  <h4>参考结果</h4><pre>%s</pre>
  <h4>实际结果</h4><pre>%s</pre>
  <h4>检查项</h4>
  <table><thead><tr><th>检查项</th><th>结论</th><th>来源</th><th>理由</th><th>证据引用</th></tr></thead><tbody>%s</tbody></table>
  <h4>执行尝试</h4>
  <table><thead><tr><th>序号</th><th>状态</th><th>角色</th><th>外部运行 ID</th><th>时间</th></tr></thead><tbody>%s</tbody></table>
  %s
  <h4>证据</h4>%s
</section>''' % (
            esc(case.get('case_id')), esc(case.get('conclusion')), esc(CONCLUSION_LABELS.get(case.get('conclusion'), case.get('conclusion'))),
            ''.join('<span class="tag">%s</span>' % esc(tag) for tag in case.get('tags') or []),
            esc(case.get('case_version')), esc(STATUS_LABELS.get(case.get('status'), case.get('status'))),
            '完整' if case.get('complete') else '存在缺口',
            esc(case.get('input')), esc(pretty(case.get('reference'))), esc(pretty(case.get('output'))),
            ''.join(checks), ''.join(attempts) or '<tr><td colspan="5">无记录</td></tr>',
            ('<h4>人工复核记录</h4><table><thead><tr><th>检查项</th><th>结论</th><th>理由</th><th>复核人</th><th>时间</th></tr></thead><tbody>%s</tbody></table>' % ''.join(reviews)) if reviews else '',
            ''.join(evidence) or '<p class="warn">未取得证据；不能视为核验通过。</p>'))

    critical_html = ''.join('<li><b>%s</b> · %s：%s</li>' % (esc(c), esc(n), esc(r)) for c, n, r in critical) or '<li>无有效关键失败。</li>'
    gaps_html = ''.join('<li>%s：证据状态 %s（%s）</li>' % (esc(c), esc(s), esc(h)) for c, s, h in gaps) or '<li>未发现缺失或不可解析的证据。</li>'
    usage_html = '<pre>%s</pre>' % esc(pretty(usage))
    manifest_html = '<pre>%s</pre>' % esc(pretty({key: manifest.get(key) for key in ('source', 'target_skill', 'model', 'verified', 'policy', 'judge', 'attempt_selection', 'dataset_hash')}))

    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · 评测报告</title>
<style>
:root{color:#223838;background:#f4f5f0}
body{margin:0;font:14px/1.75 "PingFang SC","Microsoft YaHei",sans-serif;background:#f4f5f0;color:#223838}
main{max-width:1080px;margin:0 auto;padding:36px 28px 60px}
h1{font:600 27px Georgia,"Songti SC",serif;margin:0 0 8px;letter-spacing:-.4px}
h2{font-size:16px;margin:34px 0 12px;border-left:3px solid #6b9d78;padding-left:10px}
h3{font-size:14px;margin:0 0 6px}
h4{font-size:12px;color:#5d7465;margin:18px 0 6px;letter-spacing:.4px}
p{margin:8px 0}
.meta{color:#7c8c80;font-size:11px;margin:0 0 10px}
header{border-bottom:1px solid #dfe5da;padding-bottom:18px;margin-bottom:8px}
.tag,.pill,.flag{display:inline-block;font-size:10px;padding:1px 7px;border-radius:4px;margin-left:6px;vertical-align:middle}
.tag{background:#eef2ea;color:#5d7465}
.flag{background:#f6e4d8;color:#9a5c39;margin-right:6px}
.pill{background:#eef2ea;color:#46624f}.pill.passed{background:#e4f0dd;color:#3f7334}.pill.not_passed{background:#f7e3de;color:#a34f3c}.pill.inconclusive{background:#f6eedc;color:#96702f}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}
.card{background:#fff;border:1px solid #e0e6da;border-radius:8px;padding:15px 17px}
.card span{font-size:10px;color:#7e8f82;display:block}
.card b{font:400 25px Georgia,serif;display:block;margin:7px 0 3px;color:#1c4439}
.card small{font-size:10px;color:#98a398}
.gate{background:#f8f0e7;border:1px solid #eadcc8;border-radius:8px;padding:18px 22px;margin:16px 0}
.gate.passed{background:#eaf4e5;border-color:#d6e6ca}
.gate h2{border:0;padding:0;margin:0 0 6px;font-size:19px}
.gate p{color:#8b7d66;font-size:11px;margin:0}
table{width:100%%;border-collapse:collapse;font-size:11px;background:#fff;border:1px solid #e3e8df;border-radius:6px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #edf0e8;vertical-align:top}
th{background:#f6f8f3;font-weight:500;color:#65796c;font-size:10px}
tr:last-child td{border-bottom:0}
pre{white-space:pre-wrap;word-break:break-word;background:#f6f8f3;border:1px solid #e6ebe1;border-radius:6px;padding:12px;font:11px/1.8 "SFMono-Regular",Consolas,monospace;margin:0 0 6px}
.case{background:#fff;border:1px solid #e0e6da;border-radius:8px;padding:18px 20px;margin:14px 0}
.evidence{border:1px solid #e6ebe1;border-radius:6px;padding:10px;margin:10px 0;background:#fbfcf9}
.evidence-head{display:flex;justify-content:space-between;gap:10px;font-size:10px;color:#76887b;margin-bottom:6px}
.mono{font-family:"SFMono-Regular",Consolas,monospace;font-size:10px}
.warn{color:#a34f3c;font-size:11px}
ul.plain{padding-left:20px;font-size:11px}
footer{margin-top:38px;border-top:1px solid #dfe5da;padding-top:14px;color:#8d9a8f;font-size:10px}
@media print{body{background:#fff}main{max-width:none;padding:0}.case,.card,table{break-inside:avoid}}
</style></head><body><main>
<header>
<div class="mono">SKILL LAB · 固定修订报告</div>
<h1>%s</h1>
<p class="meta">来源 %s · 运行状态 %s · 修订 <span class="mono">%s</span> · 生成 %s</p>
</header>
<div class="gate %s"><h2>%s</h2><p>总综合得分 <b>%s</b> / 100（展示用，不参与门禁）。BASELINE-V1 · 本次固定样本。技术运行状态与业务结论独立；失败与缺失项不从分母中移除。该修订内容与费用快照不随后到数据改变。</p></div>
<div class="cards">
<div class="card"><span>全样本通过占比</span><b>%s</b><small>%s 题</small></div>
<div class="card"><span>已判定题通过率</span><b>%s</b><small>%s 题</small></div>
<div class="card"><span>完整判分覆盖率</span><b>%s</b><small>%s 题</small></div>
<div class="card"><span>已判定覆盖率</span><b>%s</b><small>%s 题</small></div>
</div>
<h2>关键失败与证据缺口</h2>
<p><b>有效关键失败</b></p><ul class="plain">%s</ul>
<p><b>证据缺口</b></p><ul class="plain">%s</ul>
<h2>维度结果</h2>
<table><thead><tr><th>维度</th><th>得分</th><th>启用</th><th>通过</th><th>不通过</th><th>证据不足</th><th>不适用</th></tr></thead><tbody>%s</tbody></table>
<h2>逐题结果</h2>
%s
<h2>消耗与费用（该修订观察快照）</h2>
%s
<h2>固定配置摘要</h2>
%s
<footer>
<p>报告修订 <span class="mono">%s</span> · 内容哈希 <span class="mono">%s</span></p>
<p>本报告仅说明本次固定样本表现，不代表生产效果或稳定因果提升。演示与导入记录不能替代真实平台调用验收。凭证与未授权字段不进入导出。</p>
</footer>
</main></body></html>''' % (
        esc(report.get('name')), esc(report.get('name')), esc(SOURCE_LABELS.get(report.get('source'), report.get('source'))),
        esc(STATUS_LABELS.get(report.get('status'), report.get('status'))), esc(rev), esc(report.get('created_at')),
        'passed' if gate == 'passed' else '', esc(gate_text),
        '%.1f' % composite['value'] if composite.get('value') is not None else '—',
        pct(summary.get('all_sample_pass_rate')), esc(fractions(summary.get('all_sample_pass_rate'))),
        pct(summary.get('determined_pass_rate')), esc(fractions(summary.get('determined_pass_rate'))),
        pct(summary.get('complete_coverage')), esc(fractions(summary.get('complete_coverage'))),
        pct(summary.get('determined_coverage')), esc(fractions(summary.get('determined_coverage'))),
        critical_html, gaps_html, ''.join(dimensions) or '<tr><td colspan="6">无维度数据</td></tr>',
        ''.join(case_html) or '<p class="warn">该修订没有题目结果。</p>', usage_html, manifest_html,
        esc(rev), esc(report.get('content_hash')))
