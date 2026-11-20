/**
 * 数据可视化场景模板
 *
 * 以真实照片为全屏背景（Ken Burns 缓慢缩放），
 * 叠加玻璃态标题 + 动态生长的 SVG 图表。
 *
 * 图表形态：
 *   - 多个指标 → 柱状图（柱子从左到右依次生长，顶部带数值标签）
 *   - 单个百分比指标 → 环形进度（描边动画填充，中心大数字）
 *
 * 动效基于 templates/anim.js 的缓动插值，首尾带软转场。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, easeInOut, fadeOpacity, countUp } = require('./anim');

// 根据文本长度自适应字号
const fitFont = (len, base) => {
    if (len <= 10) return base;
    if (len <= 16) return Math.round(base * 0.82);
    if (len <= 24) return Math.round(base * 0.66);
    if (len <= 32) return Math.round(base * 0.52);
    return Math.round(base * 0.42);
};

const DataVisualScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width, height } = useVideoConfig();
    const { text, metrics = [], duration, background_image } = props;

    const headline = (text || '').trim();
    const metricList = Array.isArray(metrics)
        ? metrics.filter((m) => m && m.value)
        : [];
    const hasMetrics = metricList.length >= 1;

    const bgUrl = background_image ? staticFile(background_image) : null;

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.08;

    // 首尾软转场
    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    const titleFont = fitFont(headline.length, hasMetrics ? 50 : 96);

    // ── 环形进度（单个百分比指标）───────────────────────────
    const isPercentSingle = (
        metricList.length === 1 &&
        /[%％]/.test(String(metricList[0].value))
    );

    // 环形进度参数
    const ringRadius = 90;
    const ringCircumference = 2 * Math.PI * ringRadius;
    const percentNum = isPercentSingle
        ? parseFloat(String(metricList[0].value).replace(/[%％]/g, '')) || 0
        : 0;
    const ringStart = fps * 0.9;
    const ringProgress = easeInOut(frame, ringStart, ringStart + fps * 1.2);
    const ringDashOffset = ringCircumference * (1 - (percentNum / 100) * ringProgress);
    const ringDisplayNum = countUp(frame, ringStart, fps * 1.2, percentNum);

    // ── 柱状图参数 ──────────────────────────────────────────
    const barStart = fps * 0.9;
    const barItemGap = fps * 0.18;
    const maxValue = Math.max(
        ...metricList.map((m) => parseFloat(String(m.value).replace(/[^0-9.]/g, '')) || 0),
        1
    );

    // 图表区域尺寸
    const chartWidth = Math.min(width * 0.7, 960);
    const chartHeight = hasMetrics ? 360 : 0;
    const padding = { top: 70, right: 30, bottom: 60, left: 30 };

    const renderBars = () => {
        const innerW = chartWidth - padding.left - padding.right;
        const innerH = chartHeight - padding.top - padding.bottom;
        const slot = innerW / metricList.length;
        const barWidth = Math.min(slot * 0.5, 90);

        return metricList.map((m, i) => {
            const val = parseFloat(String(m.value).replace(/[^0-9.]/g, '')) || 0;
            const barStartFrame = barStart + i * barItemGap;
            const grow = easeOut(frame, barStartFrame, barStartFrame + fps * 0.6);
            const barHeight = (val / maxValue) * innerH * grow;
            const hue = 205 + i * 28;
            const cx = padding.left + slot * i + slot / 2;
            const x = cx - barWidth / 2;
            const y = padding.top + innerH - barHeight;
            const labelOpacity = easeOut(frame, barStartFrame + fps * 0.4, barStartFrame + fps * 0.7);
            const labelY = y - 14;

            return (
                <React.Fragment key={i}>
                    {/* 柱子 */}
                    <rect
                        x={x}
                        y={y}
                        width={barWidth}
                        height={Math.max(0, barHeight)}
                        rx={8}
                        fill={`linear-gradient(180deg, hsl(${hue}, 70%, 60%), hsl(${hue}, 65%, 42%))`}
                    />
                    {/* 顶部高亮条 */}
                    <rect
                        x={x}
                        y={y}
                        width={barWidth}
                        height={6}
                        rx={3}
                        fill={`hsl(${hue}, 80%, 72%)`}
                    />
                    {/* 数值标签 */}
                    <text
                        x={cx}
                        y={labelY}
                        textAnchor="middle"
                        fontSize={34}
                        fontWeight={700}
                        fill="#ffffff"
                        opacity={labelOpacity}
                        style={{ textShadow: '0 2px 10px rgba(0,0,0,0.6)' }}
                    >
                        {m.value}{m.unit ? ` ${m.unit}` : ''}
                    </text>
                </React.Fragment>
            );
        });
    };

    // 图表背景网格线（4 条横线）
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((p, i) => ({
        y: padding.top + (chartHeight - padding.top - padding.bottom) * p,
        opacity: 0.12,
    }));

    return (
        <AbsoluteFill style={{
            overflow: 'hidden',
            fontFamily: "'Microsoft YaHei', 'PingFang SC', Arial, sans-serif",
            opacity: globalOpacity,
        }}>
            {/* 背景照片 + Ken Burns 缩放 */}
            <div style={{
                position: 'absolute',
                inset: '-5%',
                backgroundImage: bgUrl ? `url(${bgUrl})` : undefined,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                transform: `scale(${bgScale})`,
                ...(!bgUrl && {
                    background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)',
                }),
            }} />

            {/* 半透明暗色遮罩 */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(0, 0, 0, 0.52)' }} />

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8%',
            }}>
                <div style={{
                    background: 'rgba(16, 19, 35, 0.72)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: '24px',
                    padding: '44px 56px',
                    boxShadow: '0 16px 56px rgba(0, 0, 0, 0.5)',
                    maxWidth: width * 0.86,
                    width: '100%',
                    textAlign: 'center',
                    opacity: easeOut(frame, 0, fps * 0.5),
                }}>
                    {/* 标题 */}
                    <div style={{
                        fontSize: titleFont,
                        fontWeight: 600,
                        color: '#f5f5f5',
                        lineHeight: 1.35,
                        wordBreak: 'break-word',
                        overflowWrap: 'anywhere',
                        textShadow: '0 2px 14px rgba(0, 0, 0, 0.6)',
                    }}>
                        {headline}
                    </div>

                    {/* 图表区域 */}
                    {hasMetrics && (
                        <div style={{ marginTop: 44 }}>
                            {isPercentSingle ? (
                                /* 环形进度 */
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                }}>
                                    <svg
                                        width={ringRadius * 2 + 40}
                                        height={ringRadius * 2 + 40}
                                        viewBox={`0 0 ${ringRadius * 2 + 40} ${ringRadius * 2 + 40}`}
                                    >
                                        {/* 轨道 */}
                                        <circle
                                            cx={ringRadius + 20}
                                            cy={ringRadius + 20}
                                            r={ringRadius}
                                            fill="none"
                                            stroke="rgba(255,255,255,0.15)"
                                            strokeWidth={14}
                                        />
                                        {/* 进度（旋转 -90° 从顶部开始） */}
                                        <circle
                                            cx={ringRadius + 20}
                                            cy={ringRadius + 20}
                                            r={ringRadius}
                                            fill="none"
                                            stroke="url(#ringGrad)"
                                            strokeWidth={14}
                                            strokeLinecap="round"
                                            strokeDasharray={ringCircumference}
                                            strokeDashoffset={ringDashOffset}
                                            transform={`rotate(-90 ${ringRadius + 20} ${ringRadius + 20})`}
                                        />
                                        <defs>
                                            <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
                                                <stop offset="0%" stopColor="#4f8cff" />
                                                <stop offset="100%" stopColor="#a06bff" />
                                            </linearGradient>
                                        </defs>
                                        {/* 中心数字 */}
                                        <text
                                            x={ringRadius + 20}
                                            y={ringRadius + 20}
                                            textAnchor="middle"
                                            dominantBaseline="central"
                                            fontSize={56}
                                            fontWeight={700}
                                            fill="#ffffff"
                                            style={{ textShadow: '0 2px 14px rgba(0,0,0,0.6)' }}
                                        >
                                            {ringDisplayNum}%
                                        </text>
                                    </svg>
                                </div>
                            ) : (
                                /* 柱状图 */
                                <svg
                                    width={chartWidth}
                                    height={chartHeight}
                                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                                >
                                    {/* 网格线 */}
                                    {gridLines.map((g, i) => (
                                        <line
                                            key={i}
                                            x1={padding.left}
                                            y1={g.y}
                                            x2={chartWidth - padding.right}
                                            y2={g.y}
                                            stroke="rgba(255,255,255,0.12)"
                                            strokeWidth={1}
                                        />
                                    ))}
                                    {renderBars()}
                                </svg>
                            )}
                        </div>
                    )}
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

module.exports = DataVisualScene;
module.exports.default = DataVisualScene;
