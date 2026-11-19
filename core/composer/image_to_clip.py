"""环节6a：图片 → 视频片段（Ken Burns 动效）

将匹配的图片转换为带缩放/平移动效的视频片段，
避免静态图片的单调感。

性能优化：
- 预缩放图片一次，每帧只做裁切/粘贴，避免每帧对原图做 LANCZOS 缩放。
- 平移效果（pan）：预缩放到 base_scale，每帧零缩放，仅 paste（内存拷贝）。
- 缩放效果（zoom）：预缩放到 max_scale，每帧从预缩放图裁切窗口（最大 1.12×目标）
  再缩放，远小于从原图缩放。
"""

import os
import numpy as np
from PIL import Image
from .moviepy_compat import ImageClip, set_duration, fl


# Ken Burns 动效类型
EFFECTS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]


def image_to_clip(
    image_path: str,
    duration: float,
    output_path: str,
    scene_id: int = 0,
    visual_type: str = "landscape",
    resolution: tuple = (1920, 1080),
    fps: int = 24,
    codec: str = "libx264",
    audio_codec: str = "aac",
    preset: str = "fast",
    threads: int = 4
) -> str:
    """将图片转为带 Ken Burns 动效的视频片段

    根据场景序号选择动效方向，交替变化避免单调。

    Args:
        image_path: 图片路径
        duration: 片段时长（秒）
        output_path: 输出视频路径
        scene_id: 镜头序号（用于选择动效方向）
        visual_type: 视觉类型
        resolution: 输出分辨率 (宽, 高)
        fps: 帧率
        codec: 视频编码器
        audio_codec: 音频编码器
        preset: 编码预设
        threads: 编码线程数

    Returns:
        输出视频路径

    Raises:
        RuntimeError: 图片加载或视频写入失败时抛出
    """
    if not os.path.exists(image_path):
        raise RuntimeError(f"图片不存在: {image_path}")

    img = None
    prescaled = None
    clip = None
    try:
        img = Image.open(image_path).convert('RGB')
        target_w, target_h = resolution

        # 计算基础缩放：图片放大以覆盖目标分辨率，并留出移动空间
        base_scale = max(target_w / img.width, target_h / img.height) * 1.1
        max_scale = base_scale * 1.12  # 缩放效果的最大尺度

        # 根据 scene_id 选择动效类型，交替变化
        effect = EFFECTS[scene_id % len(EFFECTS)]

        # ── 预缩放：只做一次 LANCZOS 缩放，后续帧复用 ──
        is_zoom = effect in ("zoom_in", "zoom_out")
        prescale = max_scale if is_zoom else base_scale
        pre_w = max(1, int(img.width * prescale))
        pre_h = max(1, int(img.height * prescale))
        prescaled = img.resize((pre_w, pre_h), Image.LANCZOS)

        clip = set_duration(ImageClip(image_path), duration)

        if is_zoom:
            def make_frame(t):
                """缩放效果：从预缩放图裁切居中窗口，再缩放到目标分辨率"""
                progress = t / duration if duration > 0 else 0

                if effect == "zoom_in":
                    # scale: base_scale → max_scale，裁切窗口: 大 → 小
                    ratio = 1.12 / (1 + 0.12 * progress)
                else:  # zoom_out
                    # scale: max_scale → base_scale，裁切窗口: 小 → 大
                    ratio = 1.12 / (1.12 - 0.12 * progress)

                crop_w = max(1, int(target_w * ratio))
                crop_h = max(1, int(target_h * ratio))

                # 居中裁切
                cx_crop = (pre_w - crop_w) // 2
                cy_crop = (pre_h - crop_h) // 2

                cropped = prescaled.crop(
                    (cx_crop, cy_crop, cx_crop + crop_w, cy_crop + crop_h)
                )
                # 裁切窗口最大仅 1.12×目标尺寸，缩放开销很小
                frame_img = cropped.resize((target_w, target_h), Image.LANCZOS)
                return np.array(frame_img)
        else:
            def make_frame(t):
                """平移效果：直接从预缩放图粘贴到画布，零缩放"""
                progress = t / duration if duration > 0 else 0

                if effect == "pan_left":
                    cx = target_w * (0.6 - 0.1 * progress)
                    cy = target_h / 2
                elif effect == "pan_right":
                    cx = target_w * (0.4 + 0.1 * progress)
                    cy = target_h / 2
                elif effect == "pan_up":
                    cx = target_w / 2
                    cy = target_h * (0.6 - 0.1 * progress)
                else:  # pan_down
                    cx = target_w / 2
                    cy = target_h * (0.4 + 0.1 * progress)

                # 粘贴位置（与原实现一致，paste 自带裁剪，越界区域留黑）
                x = cx - pre_w / 2
                y = cy - pre_h / 2

                canvas = Image.new('RGB', (target_w, target_h), (0, 0, 0))
                canvas.paste(prescaled, (int(x), int(y)))
                return np.array(canvas)

        clip = fl(clip, make_frame)
        clip = set_duration(clip, duration)

        clip.write_videofile(
            output_path,
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            preset=preset,
            threads=threads,
            # 强制 yuv420p（有限范围），与 Remotion 片段一致，保证流拷贝拼接可用
            ffmpeg_params=['-pix_fmt', 'yuv420p', '-movflags', '+faststart']
        )
    except Exception as e:
        raise RuntimeError(f"图片转视频片段失败: {image_path} → {output_path}: {e}")
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass
        if prescaled is not None:
            try:
                prescaled.close()
            except Exception:
                pass
        if img is not None:
            try:
                img.close()
            except Exception:
                pass

    return output_path
