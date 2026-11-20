/**
 * Remotion 根入口
 *
 * 注册所有场景类型的 Composition，供 remotion render 使用。
 * 通过 --props 传入的场景参数动态设置 durationInFrames，
 * 避免固定 durationInFrames=120（仅5秒）导致长场景渲染失败。
 *
 * 场景类型：
 *   - data-visual：数据可视化（SVG 图表）
 *   - text-animation：文字动画（逐字高亮）
 *   - diagram：流程图/结构图
 *   - tech：科技风（网格扫描 + 霓虹标题）
 *   - news：新闻播报风（标签条 + 字幕条）
 *   - magazine：杂志排版风（大留白 + 超大标题）
 */

const React = require('react');
const { registerRoot, Composition } = require('remotion');

const DataVisualScene = require('./templates/DataVisualScene').default;
const TextAnimationScene = require('./templates/TextAnimationScene').default;
const DiagramScene = require('./templates/DiagramScene').default;
const TechScene = require('./templates/TechScene').default;
const NewsScene = require('./templates/NewsScene').default;
const MagazineScene = require('./templates/MagazineScene').default;

// 通用 calculateMetadata：根据 props 动态设置时长和分辨率
function dynamicMetadata({ props }) {
    return {
        durationInFrames: Math.round(props.duration * props.fps),
        fps: props.fps,
        width: props.width,
        height: props.height,
    };
}

registerRoot(() => {
    return (
        <>
            <Composition
                id="data-visual"
                component={DataVisualScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
            <Composition
                id="text-animation"
                component={TextAnimationScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
            <Composition
                id="diagram"
                component={DiagramScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
            <Composition
                id="tech"
                component={TechScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
            <Composition
                id="news"
                component={NewsScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
            <Composition
                id="magazine"
                component={MagazineScene}
                durationInFrames={120}
                fps={24}
                width={1920}
                height={1080}
                calculateMetadata={dynamicMetadata}
            />
        </>
    );
});
