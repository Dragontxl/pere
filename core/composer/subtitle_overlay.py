"""环节6c-2：字幕叠加

根据各镜头的 on_screen_text 和分配的时长，
计算字幕时间轴，与画面一一对应。
"""

import os
from .moviepy_compat import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    create_text_clip,
    set_position,
    set_start,
    set_duration,
    set_audio,
    subclip,
)

from ..utils import is_chinese


# Windows 常见字体路径映射
_FONT_PATHS = {
    "SimHei": "C:/Windows/Fonts/simhei.ttf",
    "Arial": "C:/Windows/Fonts/arial.ttf",
    "Microsoft YaHei": "C:/Windows/Fonts/msyh.ttc",
}


def _resolve_font_path(font_name: str) -> str:
    """将字体名解析为实际字体文件路径

    moviepy 2.x 使用 PIL 渲染文本，需要字体文件路径而非字体名。
    优先使用已知映射，如果文件不存在则返回原始名称（PIL 会尝试自行解析）。

    Args:
        font_name: 字体名称

    Returns:
        字体文件路径或原始名称
    """
    if font_name in _FONT_PATHS:
        path = _FONT_PATHS[font_name]
        if os.path.exists(path):
            return path
    return font_name


def format_time(seconds: float) -> str:
    """格式化时间为 SRT 格式 HH:MM:SS,mmm

    Args:
        seconds: 秒数

    Returns:
        格式化的时间字符串
    """
    hours, rem = divmod(seconds, 3600)
    minutes, seconds_part = divmod(rem, 60)
    ms = int((seconds_part - int(seconds_part)) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds_part):02},{ms:03}"


def add_subtitles(
    video_path: str,
    scenes: list,
    output_path: str,
    audio_path: str = None,
    resolution: tuple = (1920, 1080),
    fps: int = 24,
    codec: str = "libx264",
    audio_codec: str = "aac",
    crf: int = 18
) -> str:
    """为视频添加字幕，可选合并音频（一步完成，减少全量重编码次数）

    字幕时间轴根据各镜头的时长计算，与画面一一对应。
    若提供 audio_path，则在叠加字幕的同时合并语音音频，
    避免先合并音频再叠加字幕的两次全量重编码。

    Args:
        video_path: 拼接后的视频路径（可无音频）
        scenes: 镜头列表（含 on_screen_text 和 duration）
        output_path: 输出路径
        audio_path: 语音音频路径，提供时在叠加字幕的同时合并音频
        resolution: 分辨率 (宽, 高)
        fps: 帧率
        codec: 视频编码器
        audio_codec: 音频编码器
        crf: 编码质量（18 为高质量）

    Returns:
        输出视频路径
    """
    video_clip = VideoFileClip(video_path)
    target_w, target_h = resolution

    # 获取音频：优先使用传入的语音文件，回退到视频自带音频
    audio_clip = None
    if audio_path:
        audio_clip = AudioFileClip(audio_path)
        # 音频比视频长则截取到视频时长
        if audio_clip.duration > video_clip.duration:
            audio_clip = subclip(audio_clip, 0, video_clip.duration)
        original_audio = audio_clip
    else:
        original_audio = video_clip.audio

    # 计算每个镜头的字幕时间
    start_time = 0.0
    subtitle_clips = []

    for scene in scenes:
        duration = scene.duration
        text = scene.on_screen_text.strip()

        if not text:
            start_time += duration
            continue

        # 根据语言选择字体
        font_name = 'SimHei' if is_chinese(text) else 'Arial'
        font = _resolve_font_path(font_name)
        fontsize = 40 if is_chinese(text) else 36

        txt_clip = create_text_clip(
            text,
            fontsize=fontsize,
            color='white',
            font=font,
            size=(int(target_w * 0.8), int(target_h * 0.12)),
            method='caption',
            align='center',
            stroke_color='black',
            stroke_width=1
        )
        txt_clip = set_position(txt_clip, ('center', target_h * 0.85))
        txt_clip = set_start(txt_clip, start_time)
        txt_clip = set_duration(txt_clip, duration)

        subtitle_clips.append(txt_clip)
        start_time += duration

    # 合成视频和字幕
    try:
        final_clip = CompositeVideoClip([video_clip] + subtitle_clips)
        # 显式恢复音频，避免 CompositeVideoClip 丢失音频轨道
        if original_audio is not None:
            final_clip = set_audio(final_clip, original_audio)

        final_clip.write_videofile(
            output_path,
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            threads=4,
            preset='fast',
            # 强制 yuv420p，与主视频片段像素格式一致，保证流拷贝拼接可用
            ffmpeg_params=['-pix_fmt', 'yuv420p', '-crf', str(crf), '-movflags', '+faststart']
        )
    except Exception as e:
        video_clip.close()
        if audio_clip is not None:
            try:
                audio_clip.close()
            except Exception:
                pass
        for clip in subtitle_clips:
            try:
                clip.close()
            except Exception:
                pass
        raise RuntimeError(f"字幕叠加失败: {e}")

    video_clip.close()
    if audio_clip is not None:
        try:
            audio_clip.close()
        except Exception:
            pass
    for clip in subtitle_clips:
        try:
            clip.close()
        except Exception:
            pass
    try:
        final_clip.close()
    except Exception:
        pass

    return output_path
