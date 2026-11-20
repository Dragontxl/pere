/**
 * 共享动画工具
 *
 * 提供缓动插值、逐字高亮、首尾转场淡入淡出、缩放进场、数字滚动等
 * 动效基础，供各场景模板复用，避免每个模板各写一套线性动画。
 *
 * 所有函数均基于 Remotion 的 interpolate + Easing，返回纯数值，
 * 组件层据此设置 opacity / transform / 切片长度等。
 */

const { interpolate, Easing } = require('remotion');

/**
 * 缓入缓出插值：frame 在 [start, end] 内返回 0→1，区间外钳制
 * 适合卡片、遮罩等需要平滑起止的入场动画
 */
const easeInOut = (frame, start, end) => {
    return interpolate(frame, [start, end], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.inOut(Easing.cubic),
    });
};

/**
 * 缓出插值：快速达到目标后趋于平稳，适合元素入场（更自然）
 */
const easeOut = (frame, start, end) => {
    return interpolate(frame, [start, end], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.out(Easing.cubic),
    });
};

/**
 * 缓入插值：缓慢起步后加速，适合出场/淡出
 */
const easeIn = (frame, start, end) => {
    return interpolate(frame, [start, end], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.in(Easing.cubic),
    });
};

/**
 * 弹性缩放进场：从 scale 较小弹性恢复到 1，比线性缩放更有质感
 * 返回缩放系数（0.8 → 1 的弹性过程）
 */
const springScale = (frame, start, fps) => {
    const t = Math.max(0, frame - start);
    return interpolate(
        t,
        [0, fps * 0.6],
        [0.82, 1],
        {
            extrapolateRight: 'clamp',
            easing: Easing.out(Easing.back),
        }
    );
};

/**
 * 逐字显示：返回已显示的字符数，用于按字符切片渲染
 * charDuration：每个字符占用的帧数
 */
const typewriterCount = (text, frame, start, charDuration) => {
    const len = (text || '').length;
    if (len === 0) return 0;
    const elapsed = Math.max(0, frame - start);
    const shown = Math.floor(elapsed / charDuration);
    return Math.max(0, Math.min(shown, len));
};

/**
 * 逐字高亮：返回当前高亮到的字符索引（-1 表示尚未开始）
 * 用于金句逐字点亮效果
 */
const highlightIndex = (text, frame, start, charDuration) => {
    const len = (text || '').length;
    if (len === 0) return -1;
    const elapsed = Math.max(0, frame - start);
    return Math.min(Math.floor(elapsed / charDuration), len - 1);
};

/**
 * 首尾转场淡入淡出
 *
 * 入场：前 inFade 帧从 0 淡入到 1（缓出）
 * 出场：后 outFade 帧从 1 淡出到 0（缓入）
 * 返回整体透明度，实现片段间的软转场，无需拼接重编码
 *
 * @param frame 当前帧
 * @param totalFrames 片段总帧数
 * @param inFade 入场淡入帧数
 * @param outFade 出场淡出帧数
 */
const fadeOpacity = (frame, totalFrames, inFade, outFade) => {
    const inOp = interpolate(frame, [0, Math.max(1, inFade)], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.out(Easing.cubic),
    });
    const outStart = Math.max(0, totalFrames - Math.max(0, outFade));
    const outOp = interpolate(frame, [outStart, totalFrames], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.in(Easing.cubic),
    });
    return Math.min(inOp, outOp);
};

/**
 * 数字滚动：从 0 滚动到目标值，用于数据指标的动态计数
 * 返回当前显示值（保留原始格式的整数部分）
 */
const countUp = (frame, start, durationFrames, targetValue) => {
    const t = easeOut(frame, start, start + durationFrames);
    const num = Number(targetValue);
    if (Number.isNaN(num)) return targetValue;
    return Math.round(num * t);
};

/**
 * 滑入 + 淡入组合：返回 {opacity, translateY}
 * 用于卡片从下方滑入并淡入
 */
const slideUpFade = (frame, start, distance) => {
    const t = easeOut(frame, start, start + 0.5); // 0.5s 内完成
    return {
        opacity: t,
        translateY: (1 - t) * distance,
    };
};

module.exports = {
    easeInOut,
    easeOut,
    easeIn,
    springScale,
    typewriterCount,
    highlightIndex,
    fadeOpacity,
    countUp,
    slideUpFade,
};
