/**
 * 新闻播报风场景模板
 *
 * 新闻节目视觉：顶部红色标签条滑入，居中大标题淡入，
 * 底部深色字幕条从下方展开展示要点（如有 steps）。
 * 适合流程、机制、资讯类内容，与玻璃态卡片/科技风形成区隔。
 *
 * 动效：标签滑入、标题淡入缩放、字幕条展开、首尾软转场。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, fadeOpacity, springScale, slideUpFade } = require('./anim');

const fitFont = (len, base) => {
    if (len <= 10) return base;
    if (len <= 16) return Math.round(base * 0.85);
    if (len <= 24) return Math.round(base * 0.7);
    if (len <= 32) return Math.round(base * 0.55);
    return Math.round(base * 0.45);
};

const NewsScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width } = useVideoConfig();
    const { text, steps = [], duration, background_image } = props;

    const headline = (text || '').trim();
    const stepList = Array.isArray(steps) ? steps.filter((s) => s && s.trim()) : [];
    const hasSteps = stepList.length >= 1;
    const bgUrl = background_image ? staticFile(background_image) : null;

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.06;

    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    const titleFont = fitFont(headline.length, hasSteps ? 62 : 88);

    // 顶部标签滑入
    const tagSlide = slideUpFade(frame, 0, 20);
    // 标题淡入缩放
    const titleScale = springScale(frame, fps * 0.2, fps);
    const titleOpacity = easeOut(frame, fps * 0.2, fps * 0.6);
    // 底部字幕条展开
    const barExpand = easeOut(frame, fps * 0.7, fps * 1.0);

    return (
        <AbsoluteFill style={{
            overflow: 'hidden',
            fontFamily: "'Microsoft YaHei', 'PingFang SC', Arial, sans-serif",
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
                    background: 'linear-gradient(160deg, #1a1a1a 0%, #241a1a 50%, #0f0f0f 100%)',
                }),
            }} />

            {/* 偏暖暗色遮罩（新闻感） */}
            <AbsoluteFill style={{ backgroundColor: 'rgba(15, 12, 10, 0.55)' }} />

            {/* 顶部标签条 */}
            <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '28px 0',
                opacity: tagSlide.opacity,
                transform: `translateY(${tagSlide.translateY}px)`,
            }}>
                <div style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '10px 28px',
                    background: 'linear-gradient(90deg, #d32f2f, #b71c1c)',
                    borderRadius: '6px',
                    fontSize: 22,
                    fontWeight: 700,
                    color: '#fff',
                    letterSpacing: '0.2em',
                    boxShadow: '0 6px 20px rgba(211,47,47,0.4)',
                }}>
                    <span style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background: '#fff',
                        animation: 'none',
                    }} />
                    焦点资讯
                </div>
            </div>

            {/* 内容层 */}
            <AbsoluteFill style={{
                justifyContent: 'center',
                alignItems: 'center',
                padding: '0 8%',
            }}>
                <div style={{
                    textAlign: 'center',
                    maxWidth: width * 0.84,
                    width: '100%',
                }}>
                    {/* 大标题 */}
                    <div style={{
                        fontSize: titleFont,
                        fontWeight: 700,
                        color: '#ffffff',
                        lineHeight: 1.35,
                        wordBreak: 'break-word',
                        overflowWrap: 'anywhere',
                        opacity: titleOpacity,
                        transform: `scale(${titleScale})`,
                        textShadow: '0 4px 24px rgba(0, 0, 0, 0.7)',
                    }}>
                        {headline}
                    </div>

                    {/* 红色分隔线 */}
                    <div style={{
                        width: `${easeOut(frame, fps * 0.4, fps * 0.7) * 120}px`,
                        height: 4,
                        background: 'linear-gradient(90deg, #d32f2f, transparent)',
                        margin: '32px auto 0',
                        borderRadius: 2,
                    }} />
                </div>
            </AbsoluteFill>

            {/* 底部字幕条 */}
            {hasSteps && (
                <div style={{
                    position: 'absolute',
                    bottom: 0,
                    left: 0,
                    right: 0,
                    background: 'rgba(10, 8, 6, 0.82)',
                    borderTop: '3px solid #d32f2f',
                    padding: '24px 8% 32px',
                    transform: `translateY(${(1 - barExpand) * 100}px)`,
                    opacity: barExpand,
                }}>
                    <div style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        justifyContent: 'center',
                        gap: '14px 32px',
                        maxWidth: width * 0.88,
                        margin: '0 auto',
                    }}>
                        {stepList.slice(0, 3).map((step, i) => {
                            const appear = easeOut(
                                frame,
                                fps * 0.8 + i * fps * 0.3,
                                fps * 1.0 + i * fps * 0.3
                            );
                            return (
                                <div
                                    key={i}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 10,
                                        opacity: appear,
                                        transform: `translateY(${(1 - appear) * 12}px)`,
                                    }}
                                >
                                    <span style={{
                                        color: '#d32f2f',
                                        fontWeight: 700,
                                        fontSize: 24,
                                        flexShrink: 0,
                                    }}>
                                        {String(i + 1).padStart(2, '0')}
                                    </span>
                                    <span style={{
                                        color: '#e8e8e8',
                                        fontSize: 26,
                                        textShadow: '0 1px 4px rgba(0,0,0,0.5)',
                                    }}>
                                        {step}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </AbsoluteFill>
    );
};

module.exports = NewsScene;
module.exports.default = NewsScene;
