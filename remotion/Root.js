/**
 * Remotion 根入口
 *
 * 注册所有场景类型的 Composition，供 remotion render 使用。
 * 通过 --props 传入的场景参数动态设置 durationInFrames，
 * 避免固定 durationInFrames=120（仅5秒）导致长场景渲染失败。
 */

const React = require('react');
const { registerRoot, Composition } = require('remotion');

const DataVisualScene = require('./templates/DataVisualScene').default;
const TextAnimationScene = require('./templates/TextAnimationScene').default;
const DiagramScene = require('./templates/DiagramScene').default;

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
        </>
    );
});
