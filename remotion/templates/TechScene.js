/**
 * 科技风场景模板
 *
 * 暗色科技感视觉：背景照片叠加 SVG 网格 + 扫描光线，
 * 标题采用霓虹青紫渐变、逐字点亮，辅以数据坐标装饰。
 * 适合科技、数据、互联网类内容，与玻璃态卡片风格形成区隔。
 *
 * 动效：网格脉动、扫描线扫过、标题逐字高亮、首尾软转场。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, fadeOpacity, highlightIndex, easeInOut } = require('./anim');

const fitFont = (len, base) => {
    if (len <= 10) return base;
    if (len <= 16) return Math.round(base * 0.85);
    if (len <= 24) return Math.round(base * 0.7);
    if (len <= 32) return Math.round(base * 0.55);
    return Math.round(base * 0.45);
};

const TechScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width } = useVideoConfig();
    const { text, duration, background_image } = props;

    const headline = (text || '').trim();
    const chars = Array.from(headline);
    const bgUrl = background_image ? staticFile(background_image) : null;

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.06;

    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    // 网格脉动
    const gridOpacity = 0.06 + 0.04 * Math.sin((frame / fps) * Math.PI * 2);

    // 扫描线：从顶部扫到底部，循环
    const scanPeriod = fps * 4;
    const scanT = (frame % scanPeriod) / scanPeriod;
    const scanY = scanT * 100;

    // 标题逐字高亮
    const highlightStart = fps * 0.4;
    const charDuration = fps * 0.1;
    const hi = highlightIndex(headline, frame, highlightStart, charDuration);

    const titleFont = fitFont(headline.length, 84);

    return (
        <AbsoluteFill style={{
            overflow: 'hidden',
            fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Courier New', monospace",
            opacity: globalOpacity,
        }}>
            {/* 背景照片 */}
            <div style={{
                position: 'absolute',
                inset: '-5%',
                backgroundImage: bgUrl ? `url(${bgUrl})` : undefined,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                transform: `scale(${bgScale})`,
                ...(!bgUrl && {
                    background: 'linear-gradient(160deg, #0a0e1a 0%, #0d1326 50%, #060a14 100%)',
                }),
            }} />

            {/* 暗色遮罩 */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(5, 8, 16, 0.62)' }} />

            {/* 网格层 */}
            <svg
                position="absolute"
                width="100%"
                height="100%"
                viewBox={`0 0 ${width} 1080`}
                preserveAspectRatio="none"
                style={{ pointerEvents: 'none' }}
            >
                <defs>
                    <pattern id="techGrid" width={80} height={80} patternUnits="userSpaceOnUse">
                        <path d="M 80 0 L 0 0 0 80" fill="none" stroke="rgba(80,140,255,0.5)" strokeWidth={1} />
                    </pattern>
                </defs>
                <rect width="100%" height="100%" fill="url(#techGrid)" opacity={gridOpacity} />
                {/* 扫描线 */}
                <rect
                    x={0}
                    y={(1080 * scanY) / 100}
                    width="100%"
                    height={120}
                    fill="url(#scanGrad)"
                    opacity={0.35}
                />
                <defs>
                    <linearGradient id="scanGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="rgba(34,211,238,0)" />
                        <stop offset="50%" stopColor="rgba(34,211,238,0.5)" />
                        <stop offset="100%" stopColor="rgba(34,211,238,0)" />
                    </linearGradient>
                </defs>
            </svg>

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8%',
            }}>
                <div style={{
                    position: 'relative',
                    textAlign: 'center',
                    maxWidth: width * 0.82,
                }}>
                    {/* 顶部装饰标签 */}
                    <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 10,
                        padding: '8px 20px',
                        borderRadius: '999px',
                        background: 'rgba(34, 211, 238, 0.12)',
                        border: '1px solid rgba(34, 211, 238, 0.35)',
                        fontSize: 20,
                        color: '#22d3ee',
                        letterSpacing: '0.15em',
                        opacity: easeOut(frame, 0, fps * 0.4),
                        transform: `translateY(${(1 - easeOut(frame, 0, fps * 0.5)) * -16}px)`,
                        marginBottom: 40,
                    }}>
                        <span style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: '#22d3ee',
                            boxShadow: '0 0 12px #22d3ee',
                            animation: 'none',
                        }} />
                        DATA / TECH
                    </div>

                    {/* 主标题：霓虹渐变逐字点亮 */}
                    <div style={{
                        fontSize: titleFont,
                        fontWeight: 700,
                        lineHeight: 1.3,
                        letterSpacing: '0.04em',
                        wordBreak: 'break-word',
                        overflowWrap: 'anywhere',
                        display: 'flex',
                        flexWrap: 'wrap',
                        justifyContent: 'center',
                    }}>
                        {chars.map((ch, i) => {
                            const lit = i <= hi;
                            return (
                                <span
                                    key={i}
                                    style={{
                                        backgroundImage: lit
                                            ? 'linear-gradient(135deg, #22d3ee, #818cf8)'
                                            : 'none',
                                        WebkitBackgroundClip: lit ? 'text' : 'unset',
                                        WebkitTextFillColor: lit ? 'transparent' : 'rgba(200,220,255,0.25)',
                                        textShadow: lit
                                            ? '0 0 24px rgba(34,211,238,0.5)'
                                            : 'none',
                                    }}
                                >
                                    {ch === ' ' ? '\u00A0' : ch}
                                </span>
                            );
                        })}
                    </div>

                    {/* 底部数据装饰条 */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        marginTop: 44,
                        opacity: easeOut(frame, fps * 0.8, fps * 1.1),
                    }}>
                        <div style={{
                            height: 3,
                            width: `${easeInOut(frame, fps * 0.8, fps * 1.1) * 160}px`,
                            background: 'linear-gradient(90deg, #22d3ee, #818cf8)',
                            borderRadius: 2,
                        }} />
                        <span style={{
                            fontSize: 18,
                            color: 'rgba(130,170,230,0.7)',
                            fontFamily: "'Courier New', monospace",
                            letterSpacing: '0.2em',
                        }}>
                            [ 0x{Math.floor(frame / fps).toString(16).padStart(4, '0')} ]
                        </span>
                    </div>
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

module.exports = TechScene;
module.exports.default = TechScene;
