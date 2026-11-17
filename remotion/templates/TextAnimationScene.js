/**
 * 文字动画场景模板
 *
 * 以真实照片为全屏背景（Ken Burns 缓慢缩放），
 * 叠加玻璃态标题卡片。仅显示简短标题（由 Python 端派生），
 * 不渲染画面描述文案，也不再显示整段解说（字幕另行烧录）。
 * 参数通过 props.json 传入。
 */

const React = require('react');
const { AbsoluteFill, useCurrentFrame, useVideoConfig, staticFile } = require('remotion');

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
    const { fps, width, height } = useVideoConfig();
    const { text, duration, background_image } = props;

    const headline = (text || '').trim();
    const bgUrl = background_image ? staticFile(background_image) : null;

    // 背景 Ken Burns 缩放
    const totalFrames = Math.max(1, (duration || 5) * fps);
    const bgProgress = Math.min(frame / totalFrames, 1);
    const bgScale = 1 + bgProgress * 0.08;

    // 动画阶段
    const fadeIn = Math.min(frame / (fps * 0.5), 1);
    const slideIn = Math.min(frame / (fps * 1), 1);

    const fontSize = fitFont(headline.length, 96);

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
                    boxShadow: '0 12px 48px rgba(0, 0, 0, 0.45)',
                    maxWidth: width * 0.84,
                    textAlign: 'center',
                    opacity: fadeIn,
                    transform: `translateY(${(1 - slideIn) * 40}px)`,
                }}>
                    {/* 主标题（自动缩放，自动换行） */}
                    <div style={{
                        fontSize,
                        fontWeight: 600,
                        color: '#f5f5f5',
                        lineHeight: 1.35,
                        letterSpacing: '0.02em',
                        wordBreak: 'break-word',
                        overflowWrap: 'anywhere',
                        textShadow: '0 2px 18px rgba(0, 0, 0, 0.65)',
                    }}>
                        {headline}
                    </div>

                    {/* 装饰线条 */}
                    <div style={{
                        width: 200 * Math.min((fadeIn - 0.2) / 0.4, 1),
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

export default TextAnimationScene;
