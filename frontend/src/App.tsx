import { useEffect, useState } from 'react';
import {
  Alert, App as AntApp, Button, Card, Checkbox, Descriptions, Drawer, Empty, Form, Input,
  Modal, Popconfirm, Progress, Select, Space, Spin, Table, Tag, Tooltip,
} from 'antd';
import {
  AppstoreOutlined, ArrowLeftOutlined, ArrowRightOutlined, BulbOutlined, CheckCircleOutlined,
  CodeOutlined, CopyOutlined, DatabaseOutlined, DownloadOutlined, ExperimentOutlined,
  FileTextOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined, SafetyCertificateOutlined,
  SettingOutlined, SwapOutlined, UploadOutlined,
} from '@ant-design/icons';
import { api, op } from './api';
import ScorePanel from './ScorePanel';

type Item = Record<string, any>;

const labels: Record<string, string> = {
  demo: '演示', imported: '离线导入', live: '真实调用',
  draft: '草稿', published: '已发布', queued: '排队中', running: '运行中', cancel_requested: '取消中',
  awaiting_import: '等待导入', completed: '已完成', partial_failure: '部分失败', failed: '失败', cancelled: '已取消',
  passed: '通过', not_passed: '不通过', inconclusive: '未判定',
  pass: '通过', fail: '不通过', insufficient_evidence: '证据不足', not_applicable: '不适用',
  grading_error: '评分错误', data_error: '资料错误', succeeded: '执行成功',
  before: '修改前', after: '修改后', unknown: '未知', unconfigured: '未配置',
  improved: '改善', regressed: '退化', unchanged: '持平', incomparable: '不可比较',
};

const sourceText: Record<string, string> = { demo: '演示', imported: '离线导入', live: '真实调用' };
const tag = (s: string) => (
  <Tag color={['passed', 'pass', 'completed', 'published', 'succeeded'].includes(s) ? 'success'
    : ['not_passed', 'fail', 'failed', 'grading_error', 'data_error'].includes(s) ? 'error'
      : ['demo', 'partial_failure', 'inconclusive', 'insufficient_evidence'].includes(s) ? 'warning' : 'default'}>
    {labels[s] || s || '未知'}
  </Tag>
);
const short = (s?: string) => (s ? s.slice(0, 8) : '—');
const time = (s?: string) => (s ? new Date(s).toLocaleString('zh-CN', { hour12: false }) : '—');
const pct = (r: any) => (r?.percent == null ? '—' : `${Number(r.percent).toFixed(1)}%`);
const bytes = (n?: number) => (n == null ? '—' : n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MiB` : `${Math.round(n / 1024)} KiB`);
const json = (x: any) => JSON.stringify(x, null, 2);
const scoreOf = (summary?: Item) => summary?.composite_score?.value;

const initialCases = [{
  case_id: 'CASE-001', case_version: '1', input: '请完成业务任务，并遵守约定限制。',
  reference: { expected: '请填写权威参考结果' },
  checks: [{ id: 'result', name: '结果核对', dimension: 'correctness', type: 'equals', path: 'result', required: true, critical: true, expected: '请填写权威参考结果' }],
  tags: ['正常'],
}];

const MENU = [
  { label: '概览', items: [{ key: 'experiments', label: '评测实验', icon: <ExperimentOutlined /> }] },
  {
    label: '评测管理',
    items: [
      { key: 'insights', label: '评测洞察', icon: <BulbOutlined /> },
      { key: 'objects', label: '技能详情', icon: <AppstoreOutlined /> },
      { key: 'datasets', label: '评测集', icon: <DatabaseOutlined /> },
      { key: 'compare', label: '版本对比', icon: <SwapOutlined /> },
    ],
  },
  { label: '系统', items: [{ key: 'settings', label: '连接与设置', icon: <SettingOutlined /> }] },
];

function CodeView({ content, highlight }: { content: string; highlight?: number | null }) {
  return (
    <div className="code-view">
      {content.split('\n').map((line, index) => (
        <div key={index} className={`code-line ${highlight === index + 1 ? 'hl' : ''}`}>
          <span className="ln">{index + 1}</span>
          <span className="lc">{line || ' '}</span>
        </div>
      ))}
    </div>
  );
}

function MetaGrid({ items }: { items: { label: string; value: any }[] }) {
  return (
    <div className="info-grid">
      {items.map((item) => (
        <div className="info-item" key={item.label}>
          <span>{item.label}</span>
          <b>{item.value === null || item.value === undefined || item.value === '' ? '—' : item.value}</b>
        </div>
      ))}
    </div>
  );
}

function Section({ title, extra, children }: { title: string; extra?: any; children: any }) {
  return (
    <section className="section">
      <div className="section-head"><h3>{title}</h3>{extra}</div>
      {children}
    </section>
  );
}

export default function App() {
  const { message } = AntApp.useApp();
  const [page, setPage] = useState('experiments');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [objects, setObjects] = useState<Item[]>([]);
  const [datasets, setDatasets] = useState<Item[]>([]);
  const [experiments, setExperiments] = useState<Item[]>([]);
  const [settings, setSettings] = useState<Item>({});
  const [connections, setConnections] = useState<Item[]>([]);
  const [report, setReport] = useState<Item | null>(null);
  const [revisions, setRevisions] = useState<Item[]>([]);
  const [caseDetail, setCaseDetail] = useState<Item | null>(null);
  const [objectDetail, setObjectDetail] = useState<Item | null>(null);
  const [objectTab, setObjectTab] = useState('base');
  const [datasetDetail, setDatasetDetail] = useState<Item | null>(null);
  const [datasetCase, setDatasetCase] = useState<Item | null>(null);
  const [versionPreview, setVersionPreview] = useState<Item | null>(null);
  const [insights, setInsights] = useState<Item | null>(null);
  const [insightsId, setInsightsId] = useState<string>();
  const [showArchived, setShowArchived] = useState(false);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [reportFilter, setReportFilter] = useState('all');
  const [compareFilter, setCompareFilter] = useState('all');
  const [left, setLeft] = useState<string>();
  const [right, setRight] = useState<string>();
  const [leftRevision, setLeftRevision] = useState<string>();
  const [rightRevision, setRightRevision] = useState<string>();
  const [leftHistory, setLeftHistory] = useState<Item[]>([]);
  const [rightHistory, setRightHistory] = useState<Item[]>([]);
  const [comparison, setComparison] = useState<Item | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [objectOpen, setObjectOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [gradingOpen, setGradingOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState<Item | null>(null);
  const [undoCheck, setUndoCheck] = useState<Item | null>(null);
  const [undoReason, setUndoReason] = useState('');
  const [editingDataset, setEditingDataset] = useState<Item | null>(null);
  const [datasetName, setDatasetName] = useState('');
  const [datasetText, setDatasetText] = useState(json(initialCases));
  const [importText, setImportText] = useState('');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<Item | null>(null);
  const [gradingCandidates, setGradingCandidates] = useState<Item[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<string>();
  const [form] = Form.useForm();
  const [reviewForm] = Form.useForm();
  const [objectForm] = Form.useForm();
  const [versionForm] = Form.useForm();

  const formObjectId = Form.useWatch('object_id', form);
  const formDatasetId = Form.useWatch('dataset_id', form);

  async function refresh() {
    setError('');
    try {
      const results = await Promise.all([
        api('/objects?include_archived=1'), api('/datasets'), api('/experiments?include_archived=1'),
        api('/settings'), api('/connections'),
      ]);
      setObjects(results[0]); setDatasets(results[1]); setExperiments(results[2]);
      setSettings(results[3]); setConnections(results[4]);
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (!experiments.some((x) => ['queued', 'running', 'cancel_requested'].includes(x.status))) return;
    const timer = setInterval(() => { refresh(); if (report) openReport(report.experiment_id); }, 2000);
    return () => clearInterval(timer);
  }, [experiments, report?.experiment_id]);

  async function run(action: () => Promise<any>) {
    setBusy(true);
    try { await action(); await refresh(); } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function refreshRevisions(id: string) {
    try { setRevisions(await api(`/reports/${id}/revisions`)); } catch { setRevisions([]); }
  }

  async function openReport(id: string, rev = 'current') {
    setBusy(true);
    try {
      setReport(await api(`/reports/${id}/revisions/${rev}`));
      setPage('report'); setReportFilter('all'); await refreshRevisions(id);
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function exportReport(format: string) {
    if (!report) return;
    try {
      const path = format === 'zip' ? 'export.zip' : `export?format=${format}`;
      const response = await fetch(`/api/v1/reports/${report.experiment_id}/revisions/${report.revision_id}/${path}`);
      if (!response.ok) throw new Error('报告导出失败');
      const blob = await response.blob();
      const ext = format === 'zip' ? 'zip' : format === 'html' ? 'html' : 'json';
      const data: any = format === 'zip' ? blob : await blob.text();
      const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], { type: format === 'html' ? 'text/html' : 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = `${report.name}-${short(report.revision_id)}.${ext}`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e: any) { message.error(e.message); }
  }

  function navigate(key: string) {
    setQuery(''); setFilter('all');
    if (key === 'insights') { void openInsights(); return; }
    if (key !== 'report') setPage(key);
  }

  async function openInsights(id?: string) {
    const target = id || insightsId || experiments.find((x) => x.current_summary)?.id;
    setPage('insights');
    if (!target) { setInsights(null); return; }
    setInsightsId(target);
    try { setInsights(await api(`/experiments/${target}/insights`)); } catch (e: any) { message.error(e.message); }
  }

  function openCreate(objectId?: string) {
    form.resetFields();
    const published = datasets.find((x) => x.status === 'published');
    const pick = objectId || objects.find((x) => !x.archived)?.id;
    const versions = objects.find((x) => x.id === pick)?.versions || [];
    form.setFieldsValue({
      source: 'demo', variant: 'before', object_id: pick, dataset_id: published?.id,
      skill_version_id: versions[versions.length - 1]?.id,
    });
    setCreateOpen(true);
  }

  function openDatasetEditor(dataset?: Item) {
    setEditingDataset(dataset || null);
    setDatasetName(dataset?.name || '');
    setDatasetText(json(dataset?.cases || initialCases));
    setDatasetOpen(true);
  }

  function openImport() {
    setImportOpen(true); setImportPreview(null); setImportFile(null);
    setImportText(json({
      schema_version: '1.0', name: '外部执行导入',
      object_id: objects.find((x) => !x.archived)?.id || '',
      dataset_id: datasets.find((x) => x.status === 'published')?.id || '',
      records: [{
        case_id: datasets.find((x) => x.status === 'published')?.cases?.[0]?.case_id || 'CASE-001',
        external_run_id: 'external-run-001', attempt_seq: 1, status: 'succeeded',
        output: { result: '请替换为实际结果' },
      }],
    }));
  }

  async function saveExperiment() {
    const values = await form.validateFields();
    setBusy(true);
    try {
      const exp = await api('/experiments', values);
      await api(`/experiments/${exp.id}/start`, {});
      setCreateOpen(false);
      message.success('实验已创建并进入执行队列');
      await refresh();
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function saveDataset() {
    if (!datasetName.trim()) { message.error('请填写评测集名称'); return; }
    let cases;
    try { cases = JSON.parse(datasetText); } catch { message.error('题目 JSON 格式错误'); return; }
    if (!Array.isArray(cases) || !cases.length) { message.error('至少需要一道题'); return; }
    setBusy(true);
    try {
      const saved = await api(editingDataset ? `/datasets/${editingDataset.id}` : '/datasets', { name: datasetName, cases }, editingDataset ? 'PUT' : 'POST');
      setDatasetOpen(false); setDatasetDetail(saved); message.success('草稿已保存');
      await refresh();
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function saveObject() {
    const values = await objectForm.validateFields();
    setBusy(true);
    try {
      const created = await api('/objects', {
        name: values.name, description: values.description, version: values.version,
        content: values.content || '', expert: { expert_id: values.expert_id, model: values.model || null, system_prompt: values.system_prompt || null, verified: false },
      });
      setObjectOpen(false); setObjectDetail(created); setObjectTab('base');
      message.success('评测对象已登记'); await refresh();
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function saveVersion() {
    const values = await versionForm.validateFields();
    setBusy(true);
    try {
      const updated = await api(`/objects/${objectDetail!.id}/versions`, values);
      setObjectDetail(updated); setVersionOpen(false); message.success('新版本已登记，旧版本保持不变');
      await refresh();
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function toggleArchive(kind: 'objects' | 'experiments', item: Item) {
    const result = await api(`/${kind}/${item.id}/${item.archived || item.archived_at ? 'unarchive' : 'archive'}`, { operation_id: op() });
    if (kind === 'objects') setObjectDetail({ ...objectDetail, archived: result.archived });
    await refresh();
  }

  async function previewImport() {
    setBusy(true);
    try {
      if (importFile) setImportPreview(await api('/imports', importFile));
      else {
        let payload; try { payload = JSON.parse(importText); } catch { throw new Error('运行包 JSON 格式错误'); }
        setImportPreview(await api('/imports', payload));
      }
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function confirmImport() {
    setBusy(true);
    try {
      const created = await api(`/imports/${importPreview!.id}/confirm`, { operation_id: op() });
      setImportOpen(false); setImportPreview(null);
      message.success('已导入；离线评分正在执行');
      await refresh();
      void created;
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function submitReview() {
    const v = await reviewForm.validateFields();
    let refs;
    try { refs = JSON.parse(v.evidence_refs || '[]'); } catch { message.error('证据引用必须为 JSON 数组'); return; }
    setBusy(true);
    try {
      const next = await api('/reviews', {
        experiment_id: report!.experiment_id, expected_revision_id: report!.revision_id, operation_id: op(),
        case_id: reviewOpen!.case_id, check_id: reviewOpen!.id, result: v.result, reason: v.reason, evidence_refs: refs,
      });
      setReport(next); setCaseDetail(next.cases?.find((x: Item) => x.case_id === reviewOpen!.case_id) || null);
      setReviewOpen(null); await refreshRevisions(next.experiment_id); message.success('复核已保存为新报告修订');
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function submitUndo() {
    if (!undoReason.trim()) { message.error('请填写撤销理由'); return; }
    setBusy(true);
    try {
      const next = await api('/reviews/undo', {
        experiment_id: report!.experiment_id, expected_revision_id: report!.revision_id, operation_id: op(),
        case_id: undoCheck!.case_id, check_id: undoCheck!.id, reason: undoReason,
      });
      setReport(next); setCaseDetail(next.cases?.find((x: Item) => x.case_id === undoCheck!.case_id) || null);
      setUndoCheck(null); await refreshRevisions(next.experiment_id); message.success('已追加撤销记录');
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function createCandidate() {
    setBusy(true);
    try {
      const candidate = await api('/gradings', { experiment_id: report!.experiment_id, expected_revision_id: report!.revision_id, operation_id: op() });
      setGradingCandidates((prev) => [...prev, candidate]); setSelectedCandidate(candidate.id);
      message.success('候选判分已生成，当前报告未改变');
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  async function adoptCandidate() {
    setBusy(true);
    try {
      const next = await api(`/gradings/${selectedCandidate}/adopt`, { expected_revision_id: report!.revision_id, operation_id: op() });
      await openReport(next.experiment_id, next.revision_id); setGradingOpen(false);
      message.success('候选已采纳为新报告修订，人工结论保留');
    } catch (e: any) { message.error(e.message); } finally { setBusy(false); }
  }

  function copySuggestions() {
    if (!insights?.suggestions?.length) return;
    const text = insights.suggestions.map((s: Item) => `${s.priority} · ${s.title}\n${s.recommendation}\n关联 ${s.related_file || '未定位'}${s.related_line ? ':' + s.related_line : ''}；涉及 ${s.cases.join('、')}`).join('\n\n');
    navigator.clipboard?.writeText(text).then(() => message.success('调优建议已复制')).catch(() => message.warning('复制失败，请手动选择文本'));
  }

  const visibleExperiments = experiments.filter((x) => showArchived || !x.archived_at);
  const filteredExperiments = visibleExperiments.filter((x) => (filter === 'all' || x.source === filter) && (!query || `${x.name} ${x.id}`.toLowerCase().includes(query.toLowerCase())));
  const objectExperiments = objectDetail ? experiments.filter((x) => x.object_id === objectDetail.id) : [];
  const objectLatest = objectExperiments.find((x) => x.current_summary);
  const currentVersion = objectDetail?.versions?.[objectDetail.versions.length - 1];
  const reportExperiment = experiments.find((x) => x.id === report?.experiment_id);
  const reportDataset = datasets.find((x) => x.id === reportExperiment?.dataset_id);
  const pickedDataset = datasets.find((x) => x.id === formDatasetId);
  const modelDimensions = new Set((pickedDataset?.cases || []).flatMap((c: Item) => (c.checks || []).filter((k: Item) => k.type === 'model' && k.applicable !== false).map((k: Item) => k.dimension)));
  const callEstimate = (pickedDataset?.cases?.length || 0) * (1 + modelDimensions.size);
  const pageTitle = page === 'report' ? '评测报告' : page === 'insights' ? '评测洞察' : MENU.flatMap((g) => g.items).find((x) => x.key === page)?.label || '评测实验';

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-logo">S</span>
          <div><b>Skill Lab</b><small>技能评测工作台</small></div>
        </div>
        <div className="workspace-chip"><span>本</span><div>本地工作空间<small>仅本机访问</small></div></div>
        <nav>
          {MENU.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-label">{group.label}</div>
              {group.items.map((item) => (
                <button key={item.key} className={`nav-item ${(page === item.key || (page === 'report' && item.key === 'experiments')) ? 'active' : ''}`} onClick={() => navigate(item.key)}>
                  {item.icon}<span>{item.label}</span>{item.key === 'experiments' && <b>{visibleExperiments.length}</b>}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot"><SafetyCertificateOutlined /><span>固定版本 · 独立证据<br />可追溯的评测结论</span></div>
      </aside>

      <div className="main">
        <header className="topbar">
          <span>工作空间 <span className="crumb">/</span> {pageTitle}</span>
          <Space size={16}>
            <span className="local-status"><span className="dot" />本机服务</span>
            <a href="/docs" target="_blank" rel="noreferrer">API 文档 ↗</a>
          </Space>
        </header>
        <main>
          {error && <Alert className="mb" type="error" showIcon message="服务连接失败" description={error} action={<Button onClick={refresh}>重试</Button>} />}
          <Spin spinning={loading || busy}>
            {page === 'experiments' && (
              <>
                <div className="page-head">
                  <div><h1>评测实验</h1><p>用固定样本检验每一次 Skill 变更。</p></div>
                  <Space>
                    <Button icon={<UploadOutlined />} onClick={openImport}>导入运行包</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>发起评测</Button>
                  </Space>
                </div>
                {experiments.length === 0 && (
                  <Alert className="mb" type="info" showIcon message="从空白工作空间开始"
                    description="登记自己的 Skill 与评测集，或载入明确标记的退款演示夹具体验完整流程。"
                    action={<Button onClick={() => run(async () => { await api('/demo/seed', {}); message.success('演示夹具已载入'); })}>载入演示夹具</Button>} />
                )}
                <Card className="panel" title={<Space>全部实验 <span className="count">{filteredExperiments.length}</span></Space>}
                  extra={<Space wrap>
                    <Select value={filter} onChange={setFilter} style={{ width: 118 }} options={[{ value: 'all', label: '全部来源' }, { value: 'demo', label: '演示' }, { value: 'imported', label: '离线导入' }, { value: 'live', label: '真实调用' }]} />
                    <Checkbox checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)}>含已归档</Checkbox>
                    <Input.Search value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索实验名称" style={{ width: 190 }} />
                  </Space>}>
                  <Table rowKey="id" scroll={{ x: 1180 }} pagination={{ pageSize: 20, showSizeChanger: false }} dataSource={filteredExperiments} columns={[
                    {
                      title: '实验名称', dataIndex: 'name', width: 230,
                      render: (v: string, r: Item) => <div><button className="text-link" onClick={() => openReport(r.id)}>{v}</button><small className="secondary">{short(r.id)} · {time(r.created_at)}{r.archived_at ? ' · 已归档' : ''}</small></div>,
                    },
                    { title: '来源', dataIndex: 'source', width: 90, render: tag },
                    { title: '评测集', width: 150, render: (_: any, r: Item) => <span className="muted">{datasets.find((d) => d.id === r.dataset_id)?.name || '已发布版本'}</span> },
                    { title: 'Skill 版本', width: 100, render: (_: any, r: Item) => <Tag>{objects.flatMap((x) => x.versions || []).find((x) => x.id === r.skill_version_id)?.version || labels[r.variant] || '未知'}</Tag> },
                    {
                      title: '运行状态', dataIndex: 'status', width: 120,
                      render: (v: string, r: Item) => <Space direction="vertical" size={2}>{tag(v)}
                        {['running', 'queued', 'cancel_requested'].includes(v) && <small className="muted">{r.progress ? `已处理 ${r.progress.done}/${r.progress.total}` : v === 'queued' ? '等待后台任务' : '正在启动'}</small>}
                      </Space>,
                    },
                    {
                      title: '综合得分', width: 110,
                      render: (_: any, r: Item) => scoreOf(r.current_summary) == null
                        ? <span className="muted">未判定</span>
                        : <span><b className="table-score">{Number(scoreOf(r.current_summary)).toFixed(1)}</b><small className="score-unit"> / 100</small></span>,
                    },
                    { title: '报告修订', dataIndex: 'current_revision_id', width: 100, render: (v: string) => v ? <code>{short(v)}</code> : <span className="muted">尚未生成</span> },
                    {
                      title: '操作', width: 260,
                      render: (_: any, r: Item) => <Space wrap size={2}>
                        {r.current_revision_id && <Button size="small" type="link" onClick={() => openReport(r.id)}>报告</Button>}
                        {r.current_revision_id && <Button size="small" type="link" onClick={() => openInsights(r.id)}>洞察</Button>}
                        {r.status === 'draft' && <Button size="small" onClick={() => run(() => api(`/experiments/${r.id}/start`, {}))}>启动</Button>}
                        {['draft', 'awaiting_import', 'queued', 'running'].includes(r.status) && (
                          <Popconfirm title="取消实验？" description="停止提交新任务并保留已有结果；取消不代表外部操作已回滚。" onConfirm={() => run(() => api(`/experiments/${r.id}/cancel`, {}))}><Button size="small">取消</Button></Popconfirm>
                        )}
                        <Button size="small" onClick={() => run(() => api(`/experiments/${r.id}/copy`, {}))}>复制</Button>
                        <Popconfirm title={r.archived_at ? '恢复该实验？' : '归档该实验？'} description={r.archived_at ? '恢复后重新出现在默认列表。' : '归档只改变默认可见性，历史报告与证据仍可追溯。'} onConfirm={() => run(() => toggleArchive('experiments', r))}><Button size="small">{r.archived_at ? '恢复' : '归档'}</Button></Popconfirm>
                      </Space>,
                    },
                  ] as any} />
                </Card>
                <p className="page-foot">演示与离线记录用于联调，不替代真实平台调用验收。</p>
              </>
            )}

            {page === 'insights' && (
              <>
                <div className="page-head">
                  <div><h1>评测洞察</h1><p>把失败定位到具体检查项与 Skill 指令。</p></div>
                  <Space>
                    <Select style={{ width: 280 }} placeholder="选择实验" value={insightsId}
                      onChange={(v) => openInsights(v)}
                      options={experiments.filter((x) => x.current_revision_id).map((x) => ({ value: x.id, label: `${x.name} · ${sourceText[x.source] || x.source}` }))} />
                    <Button icon={<CopyOutlined />} disabled={!insights?.suggestions?.length} onClick={copySuggestions}>复制调优建议</Button>
                  </Space>
                </div>
                {!insights ? <Card className="panel"><Empty description="选择一份已生成的评测报告查看洞察" /></Card> : (
                  <Card className="panel">
                    <div className="insight-summary">
                      <div><span>固定修订</span><b>{short(insights.revision_id)}</b></div>
                      <div><span>已证实失败项</span><b>{insights.suggestions?.length || 0}</b></div>
                      <div><span>最高优先级</span><b>{insights.suggestions?.[0]?.priority || '—'}</b></div>
                      <div><span>涉及题目</span><b>{Array.from(new Set((insights.suggestions || []).flatMap((s: Item) => s.cases))).length}</b></div>
                    </div>
                    {insights.suggestions?.length ? (
                      <Table rowKey="id" pagination={false} dataSource={insights.suggestions} expandable={{
                        expandedRowRender: (r: Item) => (
                          <div>
                            <div className="reason-cases">涉及题目：{r.cases.map((c: string) => <Tag key={c}>{c}</Tag>)}</div>
                            <ul className="reason-list">{r.reasons.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
                          </div>
                        ),
                      }} columns={[
                        { title: '优先级', dataIndex: 'priority', width: 80, render: (v: string) => <span className={`priority ${v === 'P0' ? 'p0' : 'p1'}`}>{v}</span> },
                        { title: '调优项', dataIndex: 'title', width: 230, render: (v: string, r: Item) => <div><b>{v}</b><small className="secondary">{r.dimension} · 涉及 {r.case_count} 题</small></div> },
                        { title: '建议', dataIndex: 'recommendation' },
                        {
                          title: '关联文件', width: 150,
                          render: (_: any, r: Item) => r.related_file
                            ? <Space size={4} className="related-file"><code>{r.related_file}{r.related_line ? ':' + r.related_line : ''}</code><Tooltip title="行号为关键词定位结果，需人工确认"><Tag>待确认</Tag></Tooltip></Space>
                            : <span className="muted">未定位</span>,
                        },
                      ] as any} />
                    ) : <Empty description="该修订没有已证实的业务失败" />}
                    <p className="page-foot">{insights.note}</p>
                  </Card>
                )}
              </>
            )}

            {page === 'objects' && (
              !objectDetail ? (
                <>
                  <div className="page-head">
                    <div><h1>技能详情</h1><p>登记 Skill 版本与镜像专家，固定每次评测的起点。</p></div>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => { objectForm.resetFields(); setObjectOpen(true); }}>登记技能</Button>
                  </div>
                  <Card className="panel" extra={<Checkbox checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)}>含已归档</Checkbox>}>
                    <Table rowKey="id" scroll={{ x: 1080 }} pagination={{ pageSize: 20, showSizeChanger: false }} dataSource={objects.filter((x) => showArchived || !x.archived)} columns={[
                      {
                        title: '技能名称', dataIndex: 'name', width: 260,
                        render: (v: string, r: Item) => <div><button className="text-link" onClick={() => { setObjectDetail(r); setObjectTab('base'); }}>{v}</button><small className="secondary">{r.description || '尚未填写说明'}</small></div>,
                      },
                      { title: '当前版本', width: 110, render: (_: any, r: Item) => <Tag>{r.versions?.[r.versions.length - 1]?.version || '—'}</Tag> },
                      { title: '镜像专家', width: 160, render: (_: any, r: Item) => <span>{r.expert?.expert_id || '未登记'}</span> },
                      { title: '执行模型', width: 170, render: (_: any, r: Item) => <span>{r.expert?.model || '未知'}</span> },
                      { title: '实验数', width: 80, render: (_: any, r: Item) => experiments.filter((x) => x.object_id === r.id).length },
                      { title: '状态', width: 100, render: (_: any, r: Item) => r.archived ? <Tag>已归档</Tag> : <Tag color="success">可用</Tag> },
                      { title: '操作', width: 160, render: (_: any, r: Item) => <Space><Button type="link" onClick={() => { setObjectDetail(r); setObjectTab('base'); }}>查看</Button><Button type="link" onClick={() => openCreate(r.id)} disabled={r.archived}>发起评测</Button></Space> },
                    ] as any} />
                  </Card>
                </>
              ) : (
                <>
                  <div className="detail-head">
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setObjectDetail(null)}>返回</Button>
                    <h1>{objectDetail.name}</h1>
                    <span className="version-badge">{currentVersion?.version || 'v1'}</span>
                    {objectDetail.archived && <Tag>已归档</Tag>}
                    <div className="detail-actions">
                      <Popconfirm title={objectDetail.archived ? '恢复该评测对象？' : '归档该评测对象？'} description={objectDetail.archived ? '恢复后可用于创建新实验。' : '归档后不能创建新实验；历史实验仍可追溯。'} onConfirm={() => run(() => toggleArchive('objects', objectDetail))}>
                        <Button>{objectDetail.archived ? '恢复' : '归档'}</Button>
                      </Popconfirm>
                      <Button onClick={() => { versionForm.resetFields(); setVersionOpen(true); }}>登记新版本</Button>
                      <Button type="primary" icon={<PlusOutlined />} disabled={objectDetail.archived} onClick={() => openCreate(objectDetail.id)}>发起评测</Button>
                    </div>
                  </div>
                  <div className="tabs">
                    {[['base', '基本信息'], ['skill', '技能详情'], ['versions', '版本管理'], ['evaluation', '技能评测']].map(([key, label]) => (
                      <button key={key} className={`tab ${objectTab === key ? 'active' : ''}`} onClick={() => setObjectTab(key)}>{label}</button>
                    ))}
                  </div>

                  {objectTab === 'base' && (
                    <>
                      <Section title="技能元数据">
                        <MetaGrid items={[
                          { label: '技能名称/ID', value: objectDetail.target_skill || objectDetail.name },
                          { label: '版本', value: currentVersion?.version || '—' },
                          { label: '状态', value: objectDetail.archived ? '已归档' : '可用' },
                          { label: '描述', value: objectDetail.description },
                          { label: '所属项目', value: 'default' },
                          { label: '记录来源', value: sourceText[objectDetail.source] || objectDetail.source || '人工登记' },
                        ]} />
                      </Section>
                      <Section title="评测结论">
                        {objectLatest ? <ScorePanel summary={objectLatest.current_summary} gate={objectLatest.current_gate} onDetail={() => openReport(objectLatest.id)} />
                          : <Card className="panel empty-panel"><Empty description="尚无评测报告，发起一次评测后在这里查看结论" /></Card>}
                      </Section>
                      <Section title="其他信息">
                        <MetaGrid items={[
                          { label: '镜像专家', value: objectDetail.expert?.expert_id || '未登记' },
                          { label: '执行模型', value: objectDetail.expert?.model || '未知' },
                          { label: '配置核验', value: objectDetail.expert?.verified ? '已核验' : '人工登记/未核验' },
                          { label: '创建时间', value: time(objectDetail.created_at) },
                          { label: 'Skill 版本数', value: objectDetail.versions?.length || 0 },
                          { label: '关联实验', value: objectExperiments.length },
                        ]} />
                      </Section>
                      <Section title="关联评测实验" extra={<Button type="link" onClick={() => setObjectTab('evaluation')}>查看全部</Button>}>
                        <Table rowKey="id" pagination={false} dataSource={objectExperiments.slice(0, 6)} columns={[
                          { title: '实验', dataIndex: 'name', render: (v: string, r: Item) => <button className="text-link" onClick={() => openReport(r.id)}>{v}</button> },
                          { title: '来源', dataIndex: 'source', render: tag },
                          { title: '状态', dataIndex: 'status', render: tag },
                          { title: '综合得分', render: (_: any, r: Item) => scoreOf(r.current_summary) == null ? <span className="muted">未判定</span> : <b className="table-score">{Number(scoreOf(r.current_summary)).toFixed(1)}</b> },
                          { title: '时间', dataIndex: 'created_at', render: time },
                        ] as any} />
                      </Section>
                    </>
                  )}

                  {objectTab === 'skill' && currentVersion && (
                    <div className="skill-layout">
                      <div className="file-tree">
                        <div className="file-tree-title">项目文件</div>
                        <button className="file-item active"><FileTextOutlined /> SKILL.md</button>
                        <div className="file-tree-note">版本 {currentVersion.version}<br />内容哈希 {short(currentVersion.hash)}</div>
                      </div>
                      <div className="file-view">
                        <div className="file-bar"><Space><CodeOutlined />SKILL.md</Space><Tag>{currentVersion.trust || '未核验'}</Tag></div>
                        <CodeView content={currentVersion.content} />
                      </div>
                    </div>
                  )}

                  {objectTab === 'versions' && (
                    <Card className="panel">
                      <Table rowKey="id" pagination={false} dataSource={objectDetail.versions || []} columns={[
                        { title: '版本号', dataIndex: 'version' },
                        { title: '状态', render: (_: any, r: Item) => r.id === currentVersion?.id ? <Tag color="success">当前版本</Tag> : <Tag>历史版本</Tag> },
                        { title: '内容哈希', dataIndex: 'hash', render: (v: string) => <Tooltip title={v}><code>{short(v)}</code></Tooltip> },
                        { title: '可信度', dataIndex: 'trust', render: (v: string) => <Tag>{v || '未核验'}</Tag> },
                        { title: '操作', width: 100, render: (_: any, r: Item) => <Button type="link" onClick={() => setVersionPreview(r)}>查看</Button> },
                      ] as any} />
                    </Card>
                  )}

                  {objectTab === 'evaluation' && (
                    <Card className="panel" title="技能评测实验" extra={<Button type="primary" disabled={objectDetail.archived} onClick={() => openCreate(objectDetail.id)}>发起评测</Button>}>
                      <Table rowKey="id" scroll={{ x: 1000 }} pagination={{ pageSize: 10 }} dataSource={objectExperiments} columns={[
                        { title: '实验名称', dataIndex: 'name', width: 240, render: (v: string, r: Item) => <button className="text-link" onClick={() => openReport(r.id)}>{v}</button> },
                        { title: '来源', dataIndex: 'source', width: 90, render: tag },
                        { title: '状态', dataIndex: 'status', width: 100, render: tag },
                        { title: '综合得分', width: 110, render: (_: any, r: Item) => scoreOf(r.current_summary) == null ? <span className="muted">未判定</span> : <b className="table-score">{Number(scoreOf(r.current_summary)).toFixed(1)}</b> },
                        { title: '报告修订', dataIndex: 'current_revision_id', width: 100, render: (v: string) => v ? <code>{short(v)}</code> : <span className="muted">尚未生成</span> },
                        { title: '时间', dataIndex: 'created_at', width: 170, render: time },
                        { title: '操作', width: 130, render: (_: any, r: Item) => <Space><Button type="link" onClick={() => openReport(r.id)} disabled={!r.current_revision_id}>报告</Button><Button type="link" onClick={() => openInsights(r.id)} disabled={!r.current_revision_id}>洞察</Button></Space> },
                      ] as any} />
                    </Card>
                  )}
                </>
              )
            )}

            {page === 'datasets' && (
              !datasetDetail ? (
                <>
                  <div className="page-head">
                    <div><h1>评测集</h1><p>让真实任务、业务边界与历史失败成为可重复的基准。</p></div>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => openDatasetEditor()}>新建评测集</Button>
                  </div>
                  <Card className="panel" title="评测集与固定版本" extra={<Button icon={<DownloadOutlined />} onClick={() => {
                    const blob = new Blob([json(datasets)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'datasets.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
                  }}>导出清单</Button>}>
                    <Table rowKey="id" scroll={{ x: 920 }} pagination={{ pageSize: 20 }} dataSource={datasets} columns={[
                      { title: '评测集', dataIndex: 'name', width: 230, render: (v: string, r: Item) => <button className="text-link" onClick={() => setDatasetDetail(r)}>{v}</button> },
                      { title: '版本', dataIndex: 'version', width: 100, render: (v: any) => <code>{v || '草稿'}</code> },
                      { title: '题目数', width: 90, render: (_: any, r: Item) => r.cases?.length || 0 },
                      { title: '状态', dataIndex: 'status', width: 100, render: tag },
                      { title: '创建时间', dataIndex: 'created_at', width: 180, render: time },
                      {
                        title: '操作', width: 210,
                        render: (_: any, r: Item) => <Space>
                          <Button type="link" onClick={() => setDatasetDetail(r)}>查看</Button>
                          {r.status === 'draft' && <Button type="link" onClick={() => openDatasetEditor(r)}>编辑</Button>}
                          {r.status === 'draft' && <Popconfirm title="发布后本版本只读，确认发布？" onConfirm={() => run(async () => { const saved = await api(`/datasets/${r.id}/publish`, {}); setDatasetDetail(saved); })}><Button type="link">发布</Button></Popconfirm>}
                        </Space>,
                      },
                    ] as any} />
                  </Card>
                </>
              ) : (
                <>
                  <div className="detail-head">
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setDatasetDetail(null)}>返回</Button>
                    <h1>{datasetDetail.name}</h1>
                    <span className="version-badge">{datasetDetail.version || '草稿'}</span>
                    {tag(datasetDetail.status)}
                    <div className="detail-actions">
                      {datasetDetail.status === 'draft' && <Button onClick={() => openDatasetEditor(datasetDetail)}>编辑草稿</Button>}
                      {datasetDetail.status === 'draft' && <Popconfirm title="发布后本版本只读，确认发布？" onConfirm={() => run(async () => { const saved = await api(`/datasets/${datasetDetail.id}/publish`, {}); setDatasetDetail(saved); })}><Button type="primary">发布版本</Button></Popconfirm>}
                      <Button icon={<DownloadOutlined />} onClick={() => {
                        const blob = new Blob([json(datasetDetail)], { type: 'application/json' });
                        const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${datasetDetail.name}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
                      }}>导出 JSON</Button>
                    </div>
                  </div>
                  <Card className="panel">
                    <div className="dataset-meta"><span>共 {datasetDetail.cases?.length || 0} 道题</span><span>内容哈希 <code>{short(datasetDetail.content_hash)}</code></span><span>{datasetDetail.description || '未填写说明'}</span></div>
                    <Table rowKey="case_id" pagination={{ pageSize: 20 }} dataSource={datasetDetail.cases || []} columns={[
                      { title: '题目 ID', dataIndex: 'case_id', width: 130, render: (v: string) => <code>{v}</code> },
                      { title: '任务输入', dataIndex: 'input', ellipsis: true },
                      { title: '标签', dataIndex: 'tags', width: 180, render: (v: string[]) => <Space wrap size={2}>{v?.map((t) => <Tag key={t}>{t}</Tag>)}</Space> },
                      { title: '检查项', width: 90, render: (_: any, r: Item) => <span>{r.checks?.length || 0} 项</span> },
                      { title: '操作', width: 90, render: (_: any, r: Item) => <Button type="link" onClick={() => setDatasetCase(r)}>查看</Button> },
                    ] as any} />
                  </Card>
                </>
              )
            )}

            {page === 'compare' && (
              <>
                <div className="page-head"><div><h1>版本对比</h1><p>在相同条件下，逐题核对改善与退化。</p></div></div>
                <Card className="panel">
                  <div className="compare-select">
                    <Form.Item label="基线实验">
                      <Select placeholder="选择修改前实验" value={left} onChange={async (v) => { setLeft(v); setLeftRevision(undefined); try { setLeftHistory(await api(`/reports/${v}/revisions`)); } catch { setLeftHistory([]); } }}
                        options={experiments.filter((x) => x.current_revision_id).map((x) => ({ value: x.id, label: `${x.name} · ${labels[x.source]}` }))} />
                    </Form.Item>
                    <SwapOutlined className="swap-icon" />
                    <Form.Item label="候选实验">
                      <Select placeholder="选择修改后实验" value={right} onChange={async (v) => { setRight(v); setRightRevision(undefined); try { setRightHistory(await api(`/reports/${v}/revisions`)); } catch { setRightHistory([]); } }}
                        options={experiments.filter((x) => x.current_revision_id).map((x) => ({ value: x.id, label: `${x.name} · ${labels[x.source]}` }))} />
                    </Form.Item>
                    <Button type="primary" disabled={!left || !right || left === right} onClick={() => run(async () => setComparison(await api('/comparisons', { left_experiment_id: left, right_experiment_id: right, left_revision_id: leftRevision, right_revision_id: rightRevision })))}>开始对比 <ArrowRightOutlined /></Button>
                  </div>
                  <div className="compare-revisions">
                    <Space><span>基线修订</span><Select style={{ width: 230 }} value={leftRevision} placeholder="当前固定修订" allowClear onChange={setLeftRevision} options={leftHistory.map((x) => ({ value: x.revision_id, label: `${short(x.revision_id)} · ${x.reason || '报告'}` }))} /></Space>
                    <Space><span>候选修订</span><Select style={{ width: 230 }} value={rightRevision} placeholder="当前固定修订" allowClear onChange={setRightRevision} options={rightHistory.map((x) => ({ value: x.revision_id, label: `${short(x.revision_id)} · ${x.reason || '报告'}` }))} /></Space>
                  </div>
                </Card>
                {comparison && (
                  <div className="mt">
                    <Alert type={comparison.strict_eligible ? 'success' : 'warning'} showIcon
                      message={comparison.strict_eligible ? '满足严格版本对比条件' : '仅可描述性并排查看'}
                      description={!comparison.strict_eligible ? (comparison.blockers || []).map((x: any, i: number) => <div key={i}>{typeof x === 'string' ? x : json(x)}</div>) : '结论仅适用于本次固定样本，不代表生产表现必然相同。'} />
                    <Card className="panel mt" title="逐题变化" extra={<Space wrap><span className="muted">配对 {comparison.coverage?.paired ?? '—'} · 可比较 {comparison.coverage?.comparable ?? '—'} · 题目 {comparison.coverage?.left_case_count ?? '—'}/{comparison.coverage?.right_case_count ?? '—'}</span><Select value={compareFilter} onChange={setCompareFilter} style={{ width: 130 }} options={[{ value: 'all', label: '全部变化' }, { value: 'improved', label: '改善' }, { value: 'regressed', label: '退化' }, { value: 'unchanged', label: '持平' }, { value: 'incomparable', label: '不可比较' }]} /></Space>}>
                      <Table rowKey={(x: Item) => `${x.case_id}-${x.case_version}`} pagination={{ pageSize: 20 }}
                        dataSource={(comparison.pairs || []).filter((x: Item) => compareFilter === 'all' || x.change === compareFilter)}
                        expandable={{ expandedRowRender: (r: Item) => <div><Space wrap>{r.tags?.map((t: string) => <Tag key={t}>{t}</Tag>)}</Space><Table size="small" rowKey="id" pagination={false} className="mt" dataSource={r.checks || []} columns={[
                          { title: '检查项', render: (_: any, c: Item) => c.name || c.id },
                          { title: '基线', render: (_: any, c: Item) => tag(c.left) },
                          { title: '候选', render: (_: any, c: Item) => tag(c.right) },
                          { title: '变化', dataIndex: 'change', render: (v: string) => v === 'changed' ? '已变化' : '未变化' },
                        ] as any} /></div> }}
                        columns={[
                          { title: '题目 ID', dataIndex: 'case_id' },
                          { title: '基线', render: (_: any, r: Item) => tag(r.left || 'inconclusive') },
                          { title: '候选', render: (_: any, r: Item) => tag(r.right || 'inconclusive') },
                          { title: '变化', render: (_: any, r: Item) => <Space wrap><Tag>{labels[r.change] || r.change || '—'}</Tag>{r.descriptive_change && <Tooltip title="条件不满足严格对比，仅作描述性展示"><span className="muted">描述性 {labels[r.descriptive_change]}</span></Tooltip>}</Space> },
                        ] as any} />
                      <details><summary>配置差异与汇总</summary><pre className="json-view">{json({ differences: comparison.differences, summary: comparison.summary, coverage: comparison.coverage })}</pre></details>
                    </Card>
                  </div>
                )}
              </>
            )}

            {page === 'settings' && (
              <>
                <div className="page-head"><div><h1>连接与设置</h1><p>本地运行边界、平台能力与执行限额。</p></div></div>
                <Alert className="mb" showIcon type="warning" message="真实平台接入尚需核实" description="镜像专家由公司平台创建。本工具不会以演示数据替代真实调用，也不会自动执行生产绑定。" />
                <Card className="panel" title="平台连接">
                  <Table rowKey={(x: Item) => x.id || x.name} pagination={false} dataSource={connections} columns={[
                    { title: '连接', dataIndex: 'name' },
                    { title: '状态', render: (_: any, r: Item) => tag(r.status || 'unknown') },
                    { title: '说明', dataIndex: 'message' },
                    { title: '能力声明', render: (_: any, r: Item) => <code>{json(r.capabilities || {})}</code> },
                  ] as any} />
                </Card>
                <Card className="panel mt" title="运行限额与本地配置">
                  <MetaGrid items={[
                    { label: '运行模式', value: settings.mode },
                    { label: '本地身份', value: settings.identity },
                    { label: '题目数量', value: `1—${settings.limits?.max_cases ?? '—'} 题` },
                    { label: '单文件上限', value: bytes(settings.limits?.max_file_bytes) },
                    { label: '导入/导出包', value: `${bytes(settings.limits?.max_package_bytes)} / ${settings.limits?.max_files ?? '—'} 文件` },
                    { label: '并发', value: `执行 ${settings.limits?.execution_concurrency ?? '—'} · 评分 ${settings.limits?.grading_concurrency ?? '—'}` },
                    { label: '调用超时', value: `专家 ${settings.limits?.expert_timeout_seconds ?? '—'} 秒 · 裁判 ${settings.limits?.judge_timeout_seconds ?? '—'} 秒` },
                    { label: '技术重试', value: `最多 ${settings.limits?.technical_retries ?? '—'} 次` },
                    { label: '对象存储', value: `${settings.storage?.object_count ?? '—'} 个对象 · ${bytes(settings.storage?.bytes)}` },
                  ]} />
                  <Alert className="mt" type="info" showIcon message="备份与恢复由本机命令执行" description="备份会短暂停止 API 与 worker，并在写屏障下生成 SQLite 快照和对象清单；恢复副本默认只读，不启动外部调用。凭证不进入备份。" />
                </Card>
              </>
            )}

            {page === 'report' && report && (
              <>
                <div className="report-head">
                  <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setPage('experiments')}>实验列表</Button>
                  <h1>{report.name}</h1>
                  {tag(report.source)}{tag(report.status)}
                  <span className="version-badge">修订 {short(report.revision_id)}</span>
                  <div className="detail-actions">
                    {revisions.length > 0 && <Select value={report.revision_id} style={{ width: 170 }} onChange={(v) => openReport(report.experiment_id, v)} options={revisions.map((x) => ({ value: x.revision_id, label: `修订 ${short(x.revision_id)} · ${x.reason || '报告'}` }))} />}
                    <Button icon={<DownloadOutlined />} onClick={() => exportReport('html')}>HTML 报告</Button>
                    <Button onClick={() => exportReport('json')}>JSON</Button>
                    <Button onClick={() => exportReport('zip')}>证据 ZIP</Button>
                    <Button onClick={() => { setSelectedCandidate(undefined); setGradingOpen(true); }}>重新评分</Button>
                  </div>
                </div>
                <Card className="panel report-card">
                  <div className="report-title-row">
                    <div><h2>评测报告</h2><p className="page-sub">BASELINE-V1 · 本次固定样本。技术运行状态与业务结论独立。</p></div>
                    <Space>
                      <Button icon={<HistoryOutlined />} onClick={() => openInsights(report.experiment_id)}>查看洞察</Button>
                    </Space>
                  </div>
                  <ScorePanel summary={report.summary} gate={report.gate} />
                  <Section title="效率与成本">
                    <div className="metrics">
                      <div className="metric"><span>执行成功题数</span><b>{report.summary?.execution_success_rate?.numerator ?? '—'}<small> / {report.summary?.execution_success_rate?.denominator ?? '—'} 题</small></b></div>
                      <div className="metric"><span>已判定题通过率</span><b>{pct(report.summary?.determined_pass_rate)}</b></div>
                      <div className="metric"><span>完整判分覆盖率</span><b>{pct(report.summary?.complete_coverage)}</b></div>
                      <div className="metric"><span>已知消耗</span><b>{report.usage?.known_cost == null ? '未记录' : `${report.usage.known_cost} ${report.usage.currency || ''}`}</b></div>
                    </div>
                  </Section>
                  <Section title="实验基本信息">
                    <MetaGrid items={[
                      { label: '评测集', value: reportDataset?.name || '已发布版本' },
                      { label: '评测集版本', value: reportDataset?.version || '—' },
                      { label: '运行来源', value: sourceText[report.source] || report.source },
                      { label: '执行模型', value: report.manifest?.model || '未核验' },
                      { label: '评分模型', value: report.manifest?.judge?.mode || '内置规则' },
                      { label: '尝试选择', value: report.manifest?.attempt_selection || '—' },
                      { label: '开始时间', value: time(reportExperiment?.created_at) },
                      { label: '报告生成', value: time(report.created_at) },
                      { label: '配置核验', value: report.manifest?.verified ? '已核验' : '人工登记/未核验' },
                    ]} />
                  </Section>
                  <Section title="分维度表现">
                    <Table rowKey="key" pagination={false} dataSource={Object.entries(report.summary?.dimensions || {}).map(([key, d]: any) => ({ key, ...d }))} columns={[
                      { title: '维度', dataIndex: 'name', render: (v: string, r: Item) => <Space><b>{v}</b><Tag>{r.enabled ? '已启用' : '未启用'}</Tag></Space> },
                      { title: '得分', dataIndex: 'score', width: 100, render: (v: number | null) => v == null ? <span className="muted">未判定</span> : <b className="table-score">{Number(v).toFixed(1)}</b> },
                      { title: '通过 / 不通过', width: 150, render: (_: any, r: Item) => <span>{r.pass} / {r.fail}</span> },
                      { title: '证据不足', dataIndex: 'insufficient_evidence', width: 100 },
                      { title: '评价', width: 130, render: (_: any, r: Item) => !r.enabled ? <span className="muted">未配置检查</span> : r.score == null ? <span className="muted">尚无判定</span> : <Tag color={r.score >= 90 ? 'success' : r.score >= 70 ? 'warning' : 'error'}>{r.score >= 90 ? '表现稳定' : r.score >= 70 ? '需要关注' : '存在明显缺口'}</Tag> },
                    ] as any} />
                  </Section>
                  <Section title="逐题结果" extra={<Select value={reportFilter} onChange={setReportFilter} style={{ width: 140 }} options={[{ value: 'all', label: '全部结论' }, { value: 'passed', label: '通过' }, { value: 'not_passed', label: '不通过' }, { value: 'inconclusive', label: '未判定' }]} />}>
                    <Table rowKey="case_id" scroll={{ x: 980 }} pagination={{ pageSize: 20 }} dataSource={(report.cases || []).filter((x: Item) => reportFilter === 'all' || x.conclusion === reportFilter)} columns={[
                      { title: '题目 ID', dataIndex: 'case_id', width: 110, render: (v: string, r: Item) => <button className="text-link mono" onClick={() => setCaseDetail(r)}>{v}</button> },
                      { title: '任务输入', dataIndex: 'input', width: 300, ellipsis: true },
                      { title: '标签', dataIndex: 'tags', width: 160, render: (v: string[]) => <Space wrap size={2}>{v?.map((t) => <Tag key={t}>{t}</Tag>)}</Space> },
                      { title: '业务结论', dataIndex: 'conclusion', width: 100, render: tag },
                      {
                        title: '检查项', width: 120,
                        render: (_: any, r: Item) => {
                          const required = (r.checks || []).filter((c: Item) => c.required && c.applicable !== false);
                          return <span>{required.filter((c: Item) => c.result === 'pass').length} / {required.length} 通过</span>;
                        },
                      },
                      { title: '判分完整', dataIndex: 'complete', width: 100, render: (v: boolean) => v ? <span className="success"><CheckCircleOutlined /> 完整</span> : <span className="muted">存在缺口</span> },
                      { title: '操作', width: 90, render: (_: any, r: Item) => <Button type="link" onClick={() => setCaseDetail(r)}>查看</Button> },
                    ] as any} />
                  </Section>
                  <Section title="消耗与费用（该修订观察快照）">
                    <Alert type="info" showIcon message="未知消耗不记为零；本页固定于当前报告修订，后到费用只进入新修订。" />
                    <pre className="json-view mt">{json({ usage: report.usage, ledger_snapshot: report.ledger_snapshot })}</pre>
                  </Section>
                </Card>
              </>
            )}
          </Spin>
          <footer>Skill Lab <span>·</span> 可追溯的评测，可信赖的变更 <span className="footer-right">LOCAL WORKSPACE / v0.2</span></footer>
        </main>
      </div>

      <Drawer width={560} title="发起评测" open={createOpen} onClose={() => setCreateOpen(false)}
        footer={<Space style={{ float: 'right' }}><Button onClick={() => setCreateOpen(false)}>取消</Button><Button type="primary" loading={busy} onClick={saveExperiment}>创建并运行</Button></Space>}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="实验名称" rules={[{ required: true }]}><Input placeholder="例如：退款审核 v2 回归" /></Form.Item>
          <Form.Item name="source" label="运行来源" rules={[{ required: true }]}>
            <Select options={[{ value: 'demo', label: '演示 · 验收夹具' }, { value: 'live', label: '真实调用 · 公司镜像专家' }]} />
          </Form.Item>
          <Form.Item name="object_id" label="技能" rules={[{ required: true }]}>
            <Select options={objects.filter((x) => !x.archived).map((x) => ({ value: x.id, label: x.name }))} />
          </Form.Item>
          <Form.Item name="dataset_id" label="评测集" rules={[{ required: true }]}>
            <Select options={datasets.filter((x) => x.status === 'published').map((x) => ({ value: x.id, label: `${x.name} · ${x.version}` }))} />
          </Form.Item>
          <Form.Item name="skill_version_id" label="固定 Skill 版本" rules={[{ required: true }]}>
            <Select options={(objects.find((x) => x.id === formObjectId)?.versions || []).map((x: Item) => ({ value: x.id, label: `${x.version} · ${short(x.hash)}` }))} />
          </Form.Item>
          <Form.Item name="variant" label="演示夹具行为" extra="仅演示来源使用此项生成夹具结果；离线运行使用导入记录。">
            <Select options={[{ value: 'before', label: '错误期限 15 天' }, { value: 'after', label: '修复期限 7 天' }]} />
          </Form.Item>
          <Alert type={formObjectId && formDatasetId ? 'info' : 'warning'} showIcon
            message={`预计最多 ${callEstimate} 次调用`}
            description={pickedDataset ? `固定 ${pickedDataset.cases?.length || 0} 题；每题 1 次执行，模型裁判维度 ${modelDimensions.size} 个。技术重试最多 1 次。` : '请选择已发布评测集后查看调用上限。'} />
          <Alert className="mt" type="warning" showIcon message="平台能力未确认时，服务端会拒绝真实启动。演示来源全程标记，不计为真实调用验收。" />
        </Form>
      </Drawer>

      <Drawer width={760} title={editingDataset ? '编辑评测集草稿' : '新建评测集'} open={datasetOpen} onClose={() => setDatasetOpen(false)}
        footer={<Space style={{ float: 'right' }}><Button onClick={() => setDatasetOpen(false)}>取消</Button><Button type="primary" loading={busy} onClick={saveDataset}>保存草稿</Button></Space>}>
        <p className="muted">执行资料和裁判资料分别声明；参考答案不会作为专家输入。发布后本版本只读。</p>
        <Input className="mb" value={datasetName} onChange={(e) => setDatasetName(e.target.value)} placeholder="评测集名称" />
        <Input.TextArea className="code-input" rows={20} value={datasetText} onChange={(e) => setDatasetText(e.target.value)} />
      </Drawer>

      <Drawer width={560} title="登记技能" open={objectOpen} onClose={() => setObjectOpen(false)}
        footer={<Space style={{ float: 'right' }}><Button onClick={() => setObjectOpen(false)}>取消</Button><Button type="primary" loading={busy} onClick={saveObject}>登记</Button></Space>}>
        <Form form={objectForm} layout="vertical">
          <Form.Item name="name" label="Skill 名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="说明"><Input /></Form.Item>
          <Space align="start">
            <Form.Item name="expert_id" label="镜像专家 ID"><Input /></Form.Item>
            <Form.Item name="model" label="已配置模型"><Input placeholder="未知则留空" /></Form.Item>
            <Form.Item name="version" label="版本" rules={[{ required: true }]}><Input /></Form.Item>
          </Space>
          <Form.Item name="system_prompt" label="专家系统提示词"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="content" label="SKILL.md 快照"><Input.TextArea rows={8} /></Form.Item>
          <Alert type="info" message="人工登记不会自动成为平台已核验配置。" />
        </Form>
      </Drawer>

      <Drawer width={680} title="登记新 Skill 版本" open={versionOpen} onClose={() => setVersionOpen(false)}
        footer={<Space style={{ float: 'right' }}><Button onClick={() => setVersionOpen(false)}>取消</Button><Button type="primary" loading={busy} onClick={saveVersion}>登记</Button></Space>}>
        <Form form={versionForm} layout="vertical">
          <Form.Item name="version" label="版本名称" rules={[{ required: true }]}><Input placeholder="例如 v2" /></Form.Item>
          <Form.Item name="content" label="SKILL.md 内容" rules={[{ required: true }]}><Input.TextArea rows={18} className="code-input" /></Form.Item>
        </Form>
      </Drawer>

      <Drawer width={700} title="导入外部执行记录" open={importOpen} onClose={() => setImportOpen(false)}
        footer={<Space style={{ float: 'right' }}><Button onClick={() => setImportOpen(false)}>取消</Button>{importPreview ? <Button type="primary" loading={busy} onClick={confirmImport}>确认导入并评分</Button> : <Button type="primary" loading={busy} onClick={previewImport}>校验与预览</Button>}</Space>}>
        <Alert type="info" showIcon className="mb" message="来源固定为离线导入，不能声明为本工具真实调用。" />
        {importPreview ? (
          <>
            <Descriptions bordered size="small" column={1} items={Object.entries(importPreview.preview || {}).map(([key, value]) => ({ key, label: key, children: String(value) }))} />
            <Button className="mt" onClick={() => setImportPreview(null)}>返回修改</Button>
          </>
        ) : (
          <>
            <p className="muted">选择标准 JSON / ZIP 运行包，或粘贴 JSON。支持回导只读报告归档；先校验预览，再确认入库。</p>
            <input type="file" accept=".json,.zip,application/json,application/zip" onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const isZip = file.name.toLowerCase().endsWith('.zip');
              if (file.size > (isZip ? 100 : 10) * 1024 * 1024) { message.error(isZip ? 'ZIP 不可超过 100 MiB' : 'JSON 不可超过 10 MiB'); return; }
              setImportFile(isZip ? file : null);
              if (!isZip) setImportText(await file.text());
            }} />
            {importFile && <Alert type="success" className="mt" message={`已选择 ZIP：${importFile.name}`} description="服务器将核对清单、路径、内容哈希和限额；校验成功后才能确认导入。" />}
            <Input.TextArea disabled={!!importFile} className="code-input mt" rows={18} value={importText} onChange={(e) => setImportText(e.target.value)} />
          </>
        )}
      </Drawer>

      <Drawer width={900} title={caseDetail ? `题目 ${caseDetail.case_id} · 证据与判分` : ''} open={!!caseDetail} onClose={() => setCaseDetail(null)}>
        {caseDetail && (
          <>
            <Space wrap>{tag(caseDetail.conclusion)}<Tag>执行 {labels[caseDetail.status] || caseDetail.status}</Tag>{caseDetail.grading_error && <Tag color="error">评分错误</Tag>}{caseDetail.data_error && <Tag color="error">资料错误</Tag>}<span className="muted">当前报告修订 {short(report?.revision_id)}</span></Space>
            <h3>任务输入</h3><div className="evidence-text">{caseDetail.input}</div>
            <h3>参考结果</h3><pre className="json-view">{json(caseDetail.reference)}</pre>
            <h3>实际结果</h3>{caseDetail.output == null ? <Alert type="warning" showIcon message="没有可核对的实际产物" description="缺少产物或解析失败时不能判为通过。" /> : <pre className="json-view">{json(caseDetail.output)}</pre>}
            <h3>执行尝试</h3>
            <Table size="small" rowKey="id" pagination={false} dataSource={caseDetail.attempts || []} columns={[
              { title: '序号', dataIndex: 'attempt_seq' },
              { title: '状态', dataIndex: 'status', render: (v: string) => tag(v) },
              { title: '角色', render: (_: any, r: Item) => r.is_primary ? '主尝试' : '恢复结果' },
              { title: '外部运行 ID', dataIndex: 'external_run_id', render: (v: string) => v ? <code>{v}</code> : <span className="muted">未知</span> },
              { title: '时间', dataIndex: 'created_at', render: time },
            ] as any} />
            <h3>检查项</h3>
            {caseDetail.checks?.map((check: Item) => (
              <div className="check-card" key={check.id}>
                <div className="check-head">
                  <strong>{check.name}</strong>{tag(check.result)}{check.critical && <Tag color="red">关键</Tag>}{check.error && tag(check.error)}
                  <span className="muted">{report?.summary?.dimensions?.[check.dimension]?.name || check.dimension}</span>
                  {check.reviewed && <Tag color="cyan">已人工复核</Tag>}
                  {check.manual_required && !check.reviewed && <Tag color="orange">待人工确认</Tag>}
                </div>
                <p>{check.reason || '没有评分理由'}</p>
                <div className="check-foot">
                  <span className="muted">证据：{check.evidence_refs?.map((x: any) => typeof x === 'string' ? short(x) : short(x.evidence_id || x.id)).join('、') || '无'}</span>
                  {check.result !== 'not_applicable' && <Button size="small" onClick={() => { setReviewOpen({ ...check, case_id: caseDetail.case_id }); reviewForm.setFieldsValue({ result: check.result, reason: '', evidence_refs: json(check.evidence_refs || []) }); }}>人工复核</Button>}
                  {check.reviewed && <Button size="small" onClick={() => { setUndoCheck({ ...check, case_id: caseDetail.case_id }); setUndoReason(''); }}>撤销复核</Button>}
                </div>
              </div>
            ))}
            <h3>复核记录</h3>
            {caseDetail.review_history?.length ? <Table size="small" rowKey="id" pagination={false} dataSource={caseDetail.review_history} columns={[
              { title: '检查项', dataIndex: 'check_id' },
              { title: '结论/动作', render: (_: any, r: Item) => r.action === 'undo' ? '撤销' : tag(r.result) },
              { title: '理由', dataIndex: 'reason' },
              { title: '复核人', dataIndex: 'reviewer' },
              { title: '时间', dataIndex: 'created_at', render: time },
            ] as any} /> : <p className="muted">尚无人工复核；原始自动判分保持只读。</p>}
            <h3>实际证据</h3>
            {caseDetail.evidence?.length ? caseDetail.evidence.map((e: Item) => (
              <Card key={e.id} size="small" className="mb" title={<Space><code>{short(e.id)}</code><Tag>{e.type}</Tag>{tag(e.state)}</Space>}>
                <pre className="json-view">{typeof e.content === 'string' ? e.content : json(e.content)}</pre>
                <small className="secondary mono">SHA-256 {e.sha256}</small>
              </Card>
            )) : <Empty description="未取得证据，不能视为核验通过" />}
          </>
        )}
      </Drawer>

      <Drawer width={760} title={datasetCase ? `题目 ${datasetCase.case_id}` : ''} open={!!datasetCase} onClose={() => setDatasetCase(null)}>
        {datasetCase && (
          <>
            <Space wrap>{datasetCase.tags?.map((t: string) => <Tag key={t}>{t}</Tag>)}<Tag>版本 {datasetCase.case_version}</Tag></Space>
            <h3>任务输入</h3><div className="evidence-text">{datasetCase.input}</div>
            <h3>执行资料（专家可见）</h3>
            {datasetCase.execution_materials?.length ? datasetCase.execution_materials.map((m: Item, i: number) => <Card key={i} size="small" className="mb" title={m.name}><pre className="json-view">{m.text || json(m)}</pre></Card>) : <p className="muted">未声明执行资料</p>}
            <h3>裁判资料（仅评分可见）</h3>
            {datasetCase.judge_materials?.length ? datasetCase.judge_materials.map((m: Item, i: number) => <Card key={i} size="small" className="mb" title={m.name}><pre className="json-view">{m.text || json(m)}</pre></Card>) : <p className="muted">未声明裁判资料</p>}
            <h3>参考结果</h3><pre className="json-view">{json(datasetCase.reference)}</pre>
            <h3>检查项</h3>
            <Table size="small" rowKey="id" pagination={false} dataSource={datasetCase.checks || []} columns={[
              { title: '检查项', dataIndex: 'name' },
              { title: '维度', dataIndex: 'dimension' },
              { title: '类型', dataIndex: 'type' },
              { title: '必选', dataIndex: 'required', render: (v: boolean) => v ? '是' : '否' },
              { title: '关键', dataIndex: 'critical', render: (v: boolean) => v ? '是' : '否' },
            ] as any} />
          </>
        )}
      </Drawer>

      <Drawer width={760} title={versionPreview ? `SKILL.md · ${versionPreview.version}` : ''} open={!!versionPreview} onClose={() => setVersionPreview(null)}>
        {versionPreview && <><div className="file-bar"><Space><FileTextOutlined />SKILL.md</Space><Tag>{versionPreview.version}</Tag></div><CodeView content={versionPreview.content} /></>}
      </Drawer>

      <Modal title="人工复核检查项" open={!!reviewOpen} onCancel={() => setReviewOpen(null)} confirmLoading={busy} onOk={submitReview}>
        <Alert type="info" showIcon className="mb" message="原始判分保持只读，复核会生成新修订。缺少必要证据不能改为通过。" />
        <Form form={reviewForm} layout="vertical">
          <Form.Item name="result" label="复核结论" rules={[{ required: true }]}><Select options={['pass', 'fail', 'insufficient_evidence'].map((x) => ({ value: x, label: labels[x] }))} /></Form.Item>
          <Form.Item name="reason" label="复核理由" rules={[{ required: true, message: '必须填写理由' }]}><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="evidence_refs" label="证据引用（JSON 数组）" rules={[{ required: true }]}><Input.TextArea rows={3} className="code-input" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="撤销人工复核" open={!!undoCheck} onCancel={() => setUndoCheck(null)} confirmLoading={busy} onOk={submitUndo}>
        <Alert type="info" className="mb" message="仅撤销所选检查的最近一次复核，其他检查保持不变，并生成新报告修订。" />
        <Input.TextArea rows={3} placeholder="撤销理由（必填）" value={undoReason} onChange={(e) => setUndoReason(e.target.value)} />
      </Modal>

      <Modal width={900} title="对固定产物重新评分" open={gradingOpen} onCancel={() => setGradingOpen(false)}
        footer={<Space><Button onClick={() => setGradingOpen(false)}>关闭</Button><Button loading={busy} onClick={createCandidate}>生成规则判分候选</Button><Button type="primary" loading={busy} disabled={!selectedCandidate} onClick={adoptCandidate}>采纳候选</Button></Space>}>
        <Alert className="mb" type="info" showIcon message="重评使用已有产物，不再次调用专家。" description="先生成候选查看结果，再显式采纳。原报告与人工复核保持可追溯。" />
        <Select className="mb" style={{ width: '100%' }} placeholder="选择本次会话生成的候选" value={selectedCandidate} onChange={setSelectedCandidate}
          options={gradingCandidates.filter((x) => x.experiment_id === report?.experiment_id).map((x) => ({ value: x.id, label: `候选 ${short(x.id)} · 基于 ${short(x.base_revision_id)} · ${time(x.created_at)}` }))} />
        {selectedCandidate && <Table size="small" rowKey="case_id" pagination={{ pageSize: 8 }} dataSource={gradingCandidates.find((x) => x.id === selectedCandidate)?.cases || []} columns={[
          { title: '题目', dataIndex: 'case_id' },
          { title: '候选检查结果', render: (_: any, r: Item) => <Space wrap>{r.checks?.map((c: Item) => <Tooltip key={c.id} title={c.reason}><span>{c.name} {tag(c.result)}{c.reviewed && <Tag color="cyan">人工保留</Tag>}</span></Tooltip>)}</Space> },
        ] as any} />}
      </Modal>
    </div>
  );
}
