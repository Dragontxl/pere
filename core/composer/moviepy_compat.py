"""moviepy 版本兼容层

自动适配 moviepy 1.x (moviepy.editor) 和 2.x (moviepy) 的 API 差异。

v1.x → v2.x 主要变化：
- 导入路径：moviepy.editor → moviepy
- 方法名：set_duration → with_duration, set_start → with_start,
  set_position → with_position, set_audio → with_audio
- subclip → subclipped
- TextClip 参数顺序：font 变为首参，需用 text= 关键字传文本
"""

import os
import shutil

# 在导入 moviepy 之前设置 IMAGEIO_FFMPEG_EXE 环境变量
# imageio_ffmpeg 不查系统 PATH，只找自己捆绑的二进制，
# 如果不设置此变量，导入 moviepy 时会抛 RuntimeError
# 优先级：环境变量 > 系统 PATH > settings.json 配置
if "IMAGEIO_FFMPEG_EXE" not in os.environ:
    _ffmpeg = shutil.which("ffmpeg")
    if not _ffmpeg:
        # 尝试从 settings.json 读取配置
        try:
            import json
            _settings_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "config", "settings.json"
            )
            if os.path.exists(_settings_path):
                with open(_settings_path, "r", encoding="utf-8") as f:
                    _cfg = json.load(f)
                _ffmpeg = _cfg.get("ffmpeg_path", "")
        except Exception:
            pass
    if _ffmpeg:
        os.environ["IMAGEIO_FFMPEG_EXE"] = _ffmpeg

try:
    # moviepy 1.x
    from moviepy.editor import (
        ImageClip,
        VideoFileClip,
        AudioFileClip,
        TextClip,
        CompositeVideoClip,
        concatenate_videoclips,
    )
    MOVIEPY_V2 = False
except ImportError:
    # moviepy 2.x
    from moviepy import (
        ImageClip,
        VideoFileClip,
        AudioFileClip,
        TextClip,
        CompositeVideoClip,
        concatenate_videoclips,
    )
    MOVIEPY_V2 = True


# ============================================================
# TextClip 兼容
# ============================================================

def create_text_clip(text: str, **kwargs):
    """创建 TextClip，自动适配 v1/v2 参数差异

    v1.x: TextClip(text, fontsize=40, ...)  首参为 text
    v2.x: TextClip(font, text, ...)         首参为 font，需用 text= 关键字

    调用方按 v1.x 风格传参（fontsize/align），本函数自动转换。

    Args:
        text: 文本内容
        **kwargs: TextClip 参数

    Returns:
        TextClip 实例
    """
    if MOVIEPY_V2:
        if "fontsize" in kwargs:
            kwargs["font_size"] = kwargs.pop("fontsize")
        if "align" in kwargs:
            kwargs["text_align"] = kwargs.pop("align")
        return TextClip(text=text, **kwargs)
    return TextClip(text, **kwargs)


# ============================================================
# 方法兼容包装（set_* → with_*）
# ============================================================

def set_duration(clip, duration):
    """设置片段时长（兼容 v1.x set_duration / v2.x with_duration）"""
    if MOVIEPY_V2:
        return clip.with_duration(duration)
    return clip.set_duration(duration)


def set_start(clip, start):
    """设置片段起始时间（兼容 v1.x set_start / v2.x with_start）"""
    if MOVIEPY_V2:
        return clip.with_start(start)
    return clip.set_start(start)


def set_position(clip, position):
    """设置片段位置（兼容 v1.x set_position / v2.x with_position）"""
    if MOVIEPY_V2:
        return clip.with_position(position)
    return clip.set_position(position)


def set_audio(clip, audio):
    """设置片段音频（兼容 v1.x set_audio / v2.x with_audio）"""
    if MOVIEPY_V2:
        return clip.with_audio(audio)
    return clip.set_audio(audio)


def subclip(clip, start, end=None):
    """截取片段子区间（兼容 v1.x subclip / v2.x subclipped）"""
    if MOVIEPY_V2:
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def fl(clip, func):
    """应用帧变换（兼容 v1.x fl / v2.x transform）

    v1.x: clip.fl(func)  func(t) -> frame
    v2.x: clip.transform(func)  func(clip, t) -> frame

    本包装器将 v1.x 风格的 func(t) 适配为 v2.x 的 func(clip, t)。

    Args:
        clip: 视频片段
        func: 帧变换函数，签名为 func(t) -> numpy.array

    Returns:
        变换后的片段
    """
    if MOVIEPY_V2:
        return clip.transform(lambda c, t: func(t))
    return clip.fl(func)


# ============================================================
# 音频时长获取
# ============================================================

def get_audio_duration(audio_path: str) -> float:
    """获取音频时长

    优先使用 ffprobe，失败时回退 moviepy。

    Args:
        audio_path: 音频文件路径

    Returns:
        音频时长（秒）
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe", "-i", audio_path,
                "-show_entries", "format=duration",
                "-v", "quiet",
                "-of", "csv=p=0",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    # ffprobe 失败，回退 moviepy
    clip = AudioFileClip(audio_path)
    duration = clip.duration
    clip.close()
    return duration
