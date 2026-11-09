const ORDER = [
  { key: 'robustness', label: '过程稳健度' },
  { key: 'skill_adherence', label: '技能遵循度' },
  { key: 'completion', label: '任务完成度' },
  { key: 'correctness', label: '结果正确性' },
  { key: 'evidence', label: '证据可靠性' },
  { key: 'constraints', label: '约束遵守度' },
];

const point = (index: number, radius: number, cx: number, cy: number) => {
  const angle = -Math.PI / 2 + (index * Math.PI) / 3;
  return [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius] as const;
};

export default function Radar({ dimensions = {}, size = 380 }: { dimensions?: Record<string, any>; size?: number }) {
  const width = size;
  const height = size * 0.82;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.33;
  const scores = ORDER.map((item) => {
    const dim = dimensions[item.key];
    return typeof dim?.score === 'number' ? Math.max(0, Math.min(100, dim.score)) : 0;
  });
  const data = scores.map((score, index) => point(index, (radius * score) / 100, cx, cy));
  const polygon = data.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

  return (
    <svg className="radar" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="六维能力雷达">
      {[0.25, 0.5, 0.75, 1].map((level) => (
        <polygon
          key={level}
          points={ORDER.map((_, index) => {
            const [x, y] = point(index, radius * level, cx, cy);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
          }).join(' ')}
          fill="none"
          stroke="#DFE5EF"
          strokeWidth="1"
        />
      ))}
      {ORDER.map((_, index) => {
        const [x, y] = point(index, radius, cx, cy);
        return <line key={index} x1={cx} y1={cy} x2={x} y2={y} stroke="#EAEDF1" strokeWidth="1" />;
      })}
      <polygon points={polygon} fill="rgba(22,100,255,0.18)" stroke="#1664FF" strokeWidth="2" strokeLinejoin="round" />
      {data.map(([x, y], index) => (
        <circle key={index} cx={x} cy={y} r="3.2" fill="#1664FF" />
      ))}
      {ORDER.map((item, index) => {
        const [x, y] = point(index, radius + 26, cx, cy);
        const enabled = dimensions[item.key]?.enabled;
        return (
          <text
            key={item.key}
            x={x}
            y={y}
            textAnchor={x < cx - 2 ? 'end' : x > cx + 2 ? 'start' : 'middle'}
            dominantBaseline="middle"
            className={`radar-label ${enabled ? '' : 'off'}`}
          >
            {item.label}
          </text>
        );
      })}
    </svg>
  );
}

export { ORDER as RADAR_ORDER };
