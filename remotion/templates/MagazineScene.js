/**
 * 杂志排版风场景模板
 *
 * 杂志/出版视觉：大留白 + 超大标题 + 引文装饰，
 * 标题逐字升起，配序号与装饰线，营造金句/结论的庄重感。
 * 适合金句、结论、观点类内容，与玻璃态卡片/科技风/新闻风形成区隔。
 *
 * 动效：标题逐字升起、引文淡入、装饰线展开、首尾软转场。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, fadeOpacity, easeInOut } = require('./anim');

const fitFont = (len, base) => {
    if (len <= 8) return base;
    if (len <= 14) return Math.round(base * 0.8);
    if (len <= 22) return Math.round(base * 0.65);
    if (len <= 32) return Math.round(base * 0.5);
    return Math.round(base * 0.4);
};

const MagazineScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width } = useVideoConfig();
    const { text, duration, background_image } = props;

    const headline = (text || '').trim();
    const chars = Array.from(headline);
    const bgUrl = background_image ? staticFile(background_image) : null;

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.05;

    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    const titleFont = fitFont(headline.length, 120);

    // 标题逐字升起
    const charStart = fps * 0.5;
    const charDuration = fps * 0.1;

    // 引文（从文章派生的补充，无则用装饰）
    const subtitleOpacity = easeOut(frame, fps * 1.2, fps * 1.5);

    return (
        <AbsoluteFill style={{
            overflow: 'hidden',
            fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Source Han Serif SC', serif",
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
                    background: 'linear-gradient(160deg, #14120e 0%, #1e1a14 50%, #0d0c08 100%)',
                }),
            }} />

            {/* 暖色暗遮罩（杂志纸质感） */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(12, 10, 6, 0.5)' }} />

            {/* 左侧装饰竖线 */}
            <div style={{
                position: 'absolute',
                left: '6%',
                top: '18%',
                bottom: '18%',
                width: 2,
                background: 'linear-gradient(180deg, transparent, rgba(212,175,120,0.5), transparent)',
                opacity: easeOut(frame, fps * 0.3, fps * 0.7),
            }} />

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8% 0 14%',
            }}>
                <div style={{
                    position: 'relative',
                    textAlign: 'left',
                    maxWidth: width * 0.72,
                }}>
                    {/* 序号装饰 */}
                    <div style={{
                        fontSize: 28,
                        fontWeight: 700,
                        color: '#d4af78',
                        letterSpacing: '0.3em',
                        opacity: easeOut(frame, 0, fps * 0.4),
                        marginBottom: 32,
                        fontFamily: "'Courier New', monospace",
                    }}>
                        QUOTE / 01
                    </div>

                    {/* 超大引号装饰 */}
                    <div style={{
                        fontSize: 140,
                        lineHeight: 1,
                        color: 'rgba(212,175,120,0.25)',
                        fontFamily: "Georgia, serif",
                        opacity: easeOut(frame, fps * 0.2, fps * 0.6),
                        marginBottom: -10,
                    }}>
                        &ldquo;
                    </div>

                    {/* 主标题：逐字升起 */}
                    <div style={{
                        fontSize: titleFont,
                        fontWeight: 700,
                        color: '#f5f0e6',
                        lineHeight: 1.3,
                        letterSpacing: '0.02em',
                        wordBreak: 'break-word',
                        overflowWrap: 'anywhere',
                        display: 'flex',
                        flexWrap: 'wrap',
                    }}>
                        {chars.map((ch, i) => {
                            const charFrame = charStart + i * charDuration;
                            const t = easeOut(frame, charFrame, charFrame + fps * 0.25);
                            return (
                                <span
                                    key={i}
                                    style={{
                                        opacity: t,
                                        transform: `translateY(${(1 - t) * 40}px)`,
                                        display: 'inline-block',
                                    }}
                                >
                                    {ch === ' ' ? '\u00A0' : ch}
                                </span>
                            );
                        })}
                    </div>

                    {/* 装饰线 */}
                    <div style={{
                        width: `${easeInOut(frame, fps * 0.9, fps * 1.2) * 120}px`,
                        height: 2,
                        background: '#d4af78',
                        marginTop: 40,
                        opacity: easeOut(frame, fps * 0.9, fps * 1.2),
                    }} />

                    {/* 引文/副标题 */}
                    <div style={{
                        marginTop: 28,
                        fontSize: 30,
                        color: 'rgba(235,225,200,0.7)',
                        lineHeight: 1.6,
                        opacity: subtitleOpacity,
                        fontStyle: 'italic',
                    }}>
                        —— 深度解读
                    </div>
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

module.exports = MagazineScene;
module.exports.default = MagazineScene;
