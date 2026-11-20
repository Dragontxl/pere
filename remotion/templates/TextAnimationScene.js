/**
 * 文字动画场景模板
 *
 * 以真实照片为全屏背景（Ken Burns 缓慢缩放），
 * 叠加玻璃态标题卡片。标题采用逐字高亮（金句点亮）效果，
 * 卡片弹性缩放进场，首尾带软转场。
 * 仅显示简短标题（由 Python 端派生），不渲染画面描述文案，
 * 也不再显示整段解说（字幕另行烧录）。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, fadeOpacity, highlightIndex, springScale } = require('./anim');

// 根据文本长度自适应字号，避免长标题溢出
const fitFont = (len, base) => {
    if (len <= 10) return base;
    if (len <= 16) return Math.round(base * 0.82);
    if (len <= 24) return Math.round(base * 0.66);
    if (len <= 32) return Math.round(base * 0.52);
    return Math.round(base * 0.42);
};

const TextAnimationScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width } = useVideoConfig();
    const { text, duration, background_image } = props;

    const headline = (text || '').trim();
    const bgUrl = background_image ? staticFile(background_image) : null;
    const chars = Array.from(headline);

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.08;

    // 首尾软转场
    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    // 卡片弹性缩放进场
    const cardScale = springScale(frame, 0, fps);
    const cardOpacity = easeOut(frame, 0, fps * 0.4);

    // 逐字高亮：高亮到的字符索引，之前的字符亮，之后的暗
    const highlightStart = fps * 0.5;
    const charDuration = fps * 0.12;
    const hi = highlightIndex(headline, frame, highlightStart, charDuration);

    const fontSize = fitFont(headline.length, 96);

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
                    background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f0f23 100%)',
                }),
            }} />

            {/* 半透明暗色遮罩 */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(0, 0, 0, 0.48)' }} />

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8%',
            }}>
                <div style={{
                    background: 'rgba(20, 22, 40, 0.62)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: '24px',
                    padding: '48px 64px',
                    boxShadow: '0 16px 56px rgba(0, 0, 0, 0.5)',
                    maxWidth: width * 0.84,
                    textAlign: 'center',
                    opacity: cardOpacity,
                    transform: `scale(${cardScale})`,
                }}>
                    {/* 主标题：逐字高亮 */}
                    <div style={{
                        fontSize,
                        fontWeight: 600,
                        lineHeight: 1.35,
                        letterSpacing: '0.02em',
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
                                        color: lit ? '#ffffff' : 'rgba(245,245,245,0.35)',
                                        textShadow: lit
                                            ? '0 0 18px rgba(120,160,255,0.7), 0 2px 10px rgba(0,0,0,0.6)'
                                            : 'none',
                                        transition: 'none',
                                    }}
                                >
                                    {ch === ' ' ? '\u00A0' : ch}
                                </span>
                            );
                        })}
                    </div>

                    {/* 装饰线条（从中心展开） */}
                    <div style={{
                        width: `${easeOut(frame, fps * 0.9, fps * 1.3) * 200}px`,
                        height: 4,
                        background: 'linear-gradient(90deg, #4f8cff, #a06bff)',
                        margin: '32px auto 0',
                        borderRadius: 2,
                    }} />
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

module.exports = TextAnimationScene;
module.exports.default = TextAnimationScene;
