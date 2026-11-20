/**
 * 流程图/结构图场景模板
 *
 * 以真实照片为全屏背景（Ken Burns 缓慢缩放），
 * 叠加玻璃态标题 + 流程步骤卡片。
 * steps 由 Python 端从解说文本切分而来；不足 2 条时只显示标题卡片，
 * 不再出现占位的「步骤一/二/三」。
 *
 * 动效：标题淡入缩放、步骤卡片弹性入场、连接线生长、首尾软转场。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');
const { easeOut, fadeOpacity, springScale, easeInOut } = require('./anim');

// 根据文本长度自适应字号
const fitFont = (len, base) => {
    if (len <= 10) return base;
    if (len <= 16) return Math.round(base * 0.82);
    if (len <= 24) return Math.round(base * 0.66);
    if (len <= 32) return Math.round(base * 0.52);
    return Math.round(base * 0.42);
};

const DiagramScene = (props) => {
    const frame = useCurrentFrame();
    const { fps, width } = useVideoConfig();
    const { text, steps = [], duration, background_image } = props;

    const headline = (text || '').trim();
    const stepList = Array.isArray(steps) ? steps.filter((s) => s && s.trim()) : [];
    const hasSteps = stepList.length >= 2;

    const bgUrl = background_image ? staticFile(background_image) : null;

    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.08;

    // 首尾软转场
    const globalOpacity = fadeOpacity(frame, totalFrames, fps * 0.4, fps * 0.4);

    const titleFont = fitFont(headline.length, hasSteps ? 56 : 96);

    // 标题卡片弹性入场
    const titleScale = springScale(frame, 0, fps);
    const titleOpacity = easeOut(frame, 0, fps * 0.4);

    // 步骤逐条入场
    const stepItemGap = fps * 0.5;
    const stepStart = fps * 1.0;

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
                <div style={{ textAlign: 'center', maxWidth: width * 0.8, width: '100%' }}>
                    {/* 标题卡片 */}
                    <div style={{
                        background: 'rgba(20, 22, 40, 0.62)',
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        borderRadius: '20px',
                        padding: '36px 48px',
                        boxShadow: '0 14px 48px rgba(0, 0, 0, 0.45)',
                        opacity: titleOpacity,
                        transform: `scale(${titleScale})`,
                    }}>
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
                    </div>

                    {/* 流程步骤（仅有真实步骤时显示） */}
                    {hasSteps && (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            marginTop: 36,
                        }}>
                            {stepList.map((step, i) => {
                                const stepFrame = stepStart + i * stepItemGap;
                                const stepScale = springScale(frame, stepFrame, fps);
                                const stepOpacity = easeOut(frame, stepFrame, stepFrame + fps * 0.3);

                                return (
                                    <React.Fragment key={i}>
                                        {/* 连接线（生长动画） */}
                                        {i < stepList.length - 1 && (
                                            <div style={{
                                                width: 2,
                                                height: `${28 * easeInOut(frame, stepFrame + fps * 0.3, stepFrame + fps * 0.6)}px`,
                                                backgroundColor: 'rgba(255, 255, 255, 0.22)',
                                                margin: '6px 0',
                                            }} />
                                        )}

                                        {/* 步骤卡片 */}
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            opacity: stepOpacity,
                                            transform: `scale(${stepScale})`,
                                            background: 'rgba(24, 26, 46, 0.78)',
                                            border: '1px solid rgba(255, 255, 255, 0.12)',
                                            borderRadius: '14px',
                                            padding: '14px 26px',
                                            boxShadow: '0 6px 24px rgba(0, 0, 0, 0.35)',
                                            minWidth: width * 0.4,
                                        }}>
                                            <div style={{
                                                width: 48,
                                                height: 48,
                                                borderRadius: '50%',
                                                background: `linear-gradient(135deg, hsl(${210 + i * 28}, 62%, 52%), hsl(${210 + i * 28}, 66%, 36%))`,
                                                display: 'flex',
                                                justifyContent: 'center',
                                                alignItems: 'center',
                                                color: '#fff',
                                                fontSize: 22,
                                                fontWeight: 'bold',
                                                flexShrink: 0,
                                                boxShadow: '0 2px 10px rgba(0, 0, 0, 0.3)',
                                                transform: `scale(${springScale(frame, stepFrame, fps)})`,
                                            }}>
                                                {i + 1}
                                            </div>
                                            <div style={{
                                                marginLeft: 20,
                                                fontSize: 30,
                                                color: '#eaeaea',
                                                textAlign: 'left',
                                                wordBreak: 'break-word',
                                                textShadow: '0 1px 4px rgba(0, 0, 0, 0.5)',
                                            }}>
                                                {step}
                                            </div>
                                        </div>
                                    </React.Fragment>
                                );
                            })}
                        </div>
                    )}
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

module.exports = DiagramScene;
module.exports.default = DiagramScene;
