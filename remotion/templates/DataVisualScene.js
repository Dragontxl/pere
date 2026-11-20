/**
 * 数据可视化场景模板
 *
 * 以真实照片为全屏背景（Ken Burns 缓慢缩放），
 * 叠加玻璃态标题 + 数据指标卡片。
 * metrics 由 Python 端从解说文本提取（数字+单位），
 * 不再伪造柱状图比例；没有指标时只显示标题卡片。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');

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

    // 背景 Ken Burns 缩放
    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.08;

    // 指标逐个淡入
    const itemDuration = fps * 0.6;
    const titleFont = fitFont(headline.length, hasMetrics ? 52 : 96);

    // 指标数值字号（按长度自适应）
    const metricValueFont = (v) => {
        const len = String(v).length;
        if (len <= 3) return 66;
        if (len <= 5) return 56;
        return 46;
    };

    return (
        <AbsoluteFill style={{
            overflow: 'hidden',
            fontFamily: "'Microsoft YaHei', 'PingFang SC', Arial, sans-serif",
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
                    background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f0f23 100%)',
                }),
            }} />

            {/* 半透明暗色遮罩 */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }} />

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8%',
            }}>
                <div style={{
                    background: 'rgba(18, 20, 38, 0.65)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: '24px',
                    padding: '44px 56px',
                    boxShadow: '0 12px 48px rgba(0, 0, 0, 0.45)',
                    maxWidth: width * 0.82,
                    width: '100%',
                    textAlign: 'center',
                    opacity: Math.min(frame / (fps * 0.5), 1),
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

                    {/* 数据指标卡片（仅有真实指标时显示） */}
                    {hasMetrics && (
                        <div style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            justifyContent: 'center',
                            gap: '24px 32px',
                            marginTop: 40,
                        }}>
                            {metricList.map((m, i) => {
                                const appear = Math.min(
                                    Math.max(frame - (i * itemDuration + fps * 0.4), 0) / (fps * 0.4),
                                    1
                                );
                                const hue = 205 + i * 30;
                                return (
                                    <div key={i} style={{
                                        minWidth: 260,
                                        padding: '24px 36px',
                                        borderRadius: '16px',
                                        background: `linear-gradient(160deg, hsla(${hue}, 60%, 30%, 0.75), hsla(${hue}, 55%, 18%, 0.75))`,
                                        border: `1px solid hsla(${hue}, 70%, 65%, 0.35)`,
                                        boxShadow: `0 6px 26px rgba(0, 0, 0, 0.35), 0 0 24px hsla(${hue}, 70%, 55%, 0.18)`,
                                        opacity: appear,
                                        transform: `translateY(${(1 - appear) * 22}px)`,
                                    }}>
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'baseline',
                                            justifyContent: 'center',
                                            gap: 8,
                                        }}>
                                            <span style={{
                                                fontSize: metricValueFont(m.value),
                                                fontWeight: 700,
                                                color: '#ffffff',
                                                lineHeight: 1,
                                                textShadow: '0 2px 12px rgba(0, 0, 0, 0.5)',
                                            }}>
                                                {m.value}
                                            </span>
                                            {m.unit && (
                                                <span style={{
                                                    fontSize: 26,
                                                    fontWeight: 500,
                                                    color: `hsl(${hue}, 80%, 80%)`,
                                                }}>
                                                    {m.unit}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

export default DataVisualScene;
