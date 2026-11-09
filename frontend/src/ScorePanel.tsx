import { Button } from 'antd';
import Radar from './Radar';

export default function ScorePanel({
  summary,
  gate,
  onDetail,
  compact = false,
}: {
  summary?: Record<string, any>;
  gate?: string;
  onDetail?: () => void;
  compact?: boolean;
}) {
  const value = summary?.composite_score?.value;
  const counted = summary?.composite_score?.dimensions_counted ?? 0;
  const gateText = gate === 'passed' ? '门禁通过' : gate === 'not_passed' ? '门禁不通过' : '未判定';
  return (
    <div className={`score-panel ${compact ? 'compact' : ''}`}>
      <div className="score-total">
        <span className="score-label">总综合得分</span>
        <div className="score-number">
          <strong>{value == null ? '—' : Number(value).toFixed(1)}</strong>
          <small>/ 100</small>
        </div>
        <em>展示用得分，不参与门禁</em>
      </div>
      <div className="score-divider" />
      <div className="score-radar">
        <Radar dimensions={summary?.dimensions || {}} size={compact ? 300 : 380} />
      </div>
      <div className="score-side">
        <div>
          <small>已判定维度</small>
          <b>{counted} / 6</b>
        </div>
        <div>
          <small>关键失败</small>
          <b>{summary?.critical_failures ?? 0} 项</b>
        </div>
        <div>
          <small>当前门禁</small>
          <span className={`gate-chip ${gate || 'inconclusive'}`}>{gateText}</span>
        </div>
        {onDetail && <Button type="link" onClick={onDetail}>查看详情</Button>}
      </div>
    </div>
  );
}
