"""环节6b+：片段最终化（烧字幕 + 加音频）

将渲染好的纯视频片段，叠加字幕和对应音频段，输出带音轨和字幕的最终片段。
使用 ffmpeg 一次性完成字幕烧录和音频合并，避免对整条视频做全量重编码。

设计要点：
- 每个片段独立处理，编码量仅 5-10 秒，总编码量远小于全量重编码
- SRT 文件与输出片段同目录，用相对路径传给 subtitles 滤镜，避免路径转义问题
- 音频段从完整 narration.mp3 按时间偏移切取，保证解说与画面同步
"""

import os
import re
import shutil
import subprocess


def _resolve_ffmpeg():
    """解析 ffmpeg 路径

    优先级：IMAGEIO_FFMPEG_EXE 环境变量 > 系统 PATH > settings.json
    """
    env_ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE", "")
    if env_ffmpeg and os.path.exists(env_ffmpeg):
        return env_ffmpeg

    # 系统 PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # settings.json
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
            if _ffmpeg and os.path.exists(_ffmpeg):
                return _ffmpeg
    except Exception:
        pass

    return "ffmpeg"  # 最后兜底，依赖系统 PATH


# ffmpeg 路径
FFMPEG_EXE = _resolve_ffmpeg()


def _run_ffmpeg(cmd: list, timeout: int, cwd: str = None):
    """执行 ffmpeg 命令

    显式使用 UTF-8 解码：Windows 控制台默认 GBK，ffmpeg 输出 UTF-8，
    不指定 encoding 会在读取 stderr 时抛 UnicodeDecodeError。

    Args:
        cmd: 命令参数列表
        timeout: 超时秒数
        cwd: 工作目录（用于让滤镜里的文件路径不带盘符冒号）
    """
    return subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd
    )


def _err_tail(stderr: str, limit: int = 700) -> str:
    """取 stderr 尾部

    ffmpeg 的 stderr 开头是几百字节的版本/编译参数横幅，
    真正的错误信息总在最后几行，因此截取尾部。
    """
    text = (stderr or "").strip()
    return text[-limit:] if len(text) > limit else text

# 字幕样式（ASS force_style 格式）
# 注意：烧录纯 SRT 时 libass 使用默认脚本分辨率 384x288，所有数值会按
# video_height/288 缩放（1080p 即放大 3.75 倍）。因此：
#   FontSize=13 → 约 49px，MarginV=14 → 距底约 52px，Outline=1 → 约 3.8px
# 这样取值既能避免字幕盖住画面，也与分辨率无关（比例固定）。
SUBTITLE_STYLE = (
    "FontName=Microsoft YaHei,"
    "FontSize=13,"
    "PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,"
    "BorderStyle=1,"
    "Outline=1,"
    "Shadow=0,"
    "MarginV=14"
)


def format_srt_timestamp(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳 HH:MM:SS,mmm"""
    ms = int(seconds * 1000)
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def _wrap_subtitle(text: str, max_chars: int = 26) -> str:
    """把过长的字幕折成两行

    一个片段最长 52 字，一行显示会横跨整个画面、阅读吃力。
    这里在中间附近的标点处断行；找不到标点时按长度对半切。

    Args:
        text: 字幕文本
        max_chars: 单行最大字数（不超过则不折行）

    Returns:
        可能包含一个换行的字幕文本
    """
    text = (text or "").strip()
    if not text or "\n" in text or len(text) <= max_chars:
        return text

    mid = len(text) // 2
    best = -1
    for i, ch in enumerate(text):
        if ch not in "，、；：,;:":
            continue
        # 断点不能太靠两端，否则一侧只剩几个字
        if i < 8 or i > len(text) - 8:
            continue
        if best < 0 or abs(i - mid) < abs(best - mid):
            best = i

    if best >= 0:
        left = text[:best + 1].strip()
        right = text[best + 1:].strip()
        if left and right:
            return f"{left}\n{right}"

    return f"{text[:mid]}\n{text[mid:]}"


def generate_srt_file(text: str, duration: float, output_path: str) -> str:
    """生成单条字幕的 SRT 文件

    字幕从 0 显示到 duration，对应整个片段的时长。

    Args:
        text: 字幕文本
        duration: 片段时长（秒）
        output_path: SRT 文件输出路径

    Returns:
        SRT 文件路径
    """
    start = format_srt_timestamp(0)
    end = format_srt_timestamp(duration)
    content = f"1\n{start} --> {end}\n{_wrap_subtitle(text)}\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def get_clip_duration(clip_path: str) -> float:
    """获取视频片段时长（秒）

    使用 ffmpeg 解析，失败时返回 0。

    Args:
        clip_path: 视频文件路径

    Returns:
        时长（秒），失败返回 0
    """
    try:
        result = _run_ffmpeg([FFMPEG_EXE, "-i", clip_path], 10)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0


def extract_audio_segment(audio_path: str, offset: float, duration: float,
                          output_path: str) -> str:
    """从完整语音中切取指定时间段的音频段

    使用 ffmpeg -ss/-t 做输入端切取，速度快（不解码完整文件）。
    音频编码为 AAC 128k，与最终输出格式一致。

    Args:
        audio_path: 完整语音文件路径（narration.mp3）
        offset: 起始时间（秒）
        duration: 切取时长（秒）
        output_path: 音频段输出路径

    Returns:
        音频段文件路径

    Raises:
        RuntimeError: 切取失败时抛出
    """
    cmd = [
        FFMPEG_EXE, "-y",
        "-ss", str(offset),
        "-t", str(duration),
        "-i", audio_path,
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]
    result = _run_ffmpeg(cmd, 60)
    if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"音频切取失败: {_err_tail(result.stderr)}")
    return output_path


def finalize_clip(clip_path: str, audio_segment_path: str, subtitle_text: str,
                  output_path: str, crf: int = 18, enable_subtitle: bool = True) -> str:
    """将字幕和音频烧录到视频片段中

    一条 ffmpeg 命令完成：
    - 输入1：渲染好的纯视频片段
    - 输入2：该片段对应的音频段
    - 滤镜：subtitles 烧录字幕（enable_subtitle=True 时）
    - 编码：libx264 + aac

    Args:
        clip_path: 纯视频片段路径
        audio_segment_path: 音频段路径
        subtitle_text: 字幕文本
        output_path: 最终化片段输出路径
        crf: 编码质量（默认 18）
        enable_subtitle: 是否烧录字幕（默认 True，设为 False 则仅合并音频）

    Returns:
        最终化片段路径

    Raises:
        RuntimeError: 最终化失败时抛出
    """
    # 构建滤镜字符串（仅启用字幕时使用 subtitles 滤镜）
    clip_path = os.path.abspath(clip_path)
    audio_segment_path = os.path.abspath(audio_segment_path)
    output_path = os.path.abspath(output_path)
    work_cwd = None

    if enable_subtitle:
        # 生成 SRT 文件（与输出同目录）
        srt_path = os.path.splitext(output_path)[0] + ".srt"
        clip_duration = get_clip_duration(clip_path)

        generate_srt_file(subtitle_text, clip_duration if clip_duration > 0 else 0, srt_path)

        # 关键：ffmpeg 滤镜选项用 ':' 分隔，Windows 路径里的盘符冒号（F:）
        # 即使加单引号也会被二级解析拆开，导致 "No option name near ..."。
        # 解决方式：把工作目录切到 SRT 所在目录，滤镜里只传纯文件名，彻底消除冒号。
        work_cwd = os.path.dirname(srt_path)
        filter_str = (
            f"subtitles=filename='{os.path.basename(srt_path)}'"
            f":force_style='{SUBTITLE_STYLE}'"
        )
    else:
        filter_str = None  # 不使用视频滤镜

    try:
        cmd = [
            FFMPEG_EXE, "-y",
            "-i", clip_path,
            "-i", audio_segment_path,
        ]
        if filter_str:
            cmd.extend(["-vf", filter_str])
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", str(crf),
            # 强制统一像素格式：Remotion 渲染出来的是 yuvj420p（full range），
            # 图片片段是 yuv420p，pix_fmt 不一致会让流拷贝拼接预检失败、
            # 退回 MoviePy 全量重编码。在这里统一成 yuv420p（swscale 会正确
            # 做 full→limited 范围转换，颜色不偏），同时让 SPS 元数据一致。
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            # 每段首帧 DTS 归一化到 0：否则每段都从 -0.083s（B 帧延迟）开始，
            # concat 流拷贝时会在每个接缝处产生非单调 DTS 警告 + 时间轴漂移。
            "-avoid_negative_ts", "make_zero",
            output_path
        ])
        result = _run_ffmpeg(cmd, 120, cwd=work_cwd)
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"片段最终化失败: {_err_tail(result.stderr)}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("片段最终化超时")
    except Exception as e:
        raise RuntimeError(f"片段最终化异常: {e}")
    finally:
        # 清理 SRT 临时文件
        if enable_subtitle:
            srt_path = os.path.splitext(output_path)[0] + ".srt"
            if os.path.exists(srt_path):
                os.unlink(srt_path)

    return output_path


def add_silent_audio(clip_path: str, output_path: str, crf: int = 18) -> str:
    """给视频片段添加静音音轨（无音频素材时的兜底方案）

    使用 ffmpeg lavfi 的 anullsrc 生成静音音频，与视频合并。
    保证所有片段都有音轨，使流拷贝拼接的音频参数一致。

    Args:
        clip_path: 纯视频片段路径
        output_path: 输出路径
        crf: 编码质量（默认 18）

    Returns:
        带静音音轨的片段路径

    Raises:
        RuntimeError: 添加失败时抛出
    """
    try:
        cmd = [
            FFMPEG_EXE, "-y",
            "-i", clip_path,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", str(crf),
            # 与 finalize_clip 保持一致：统一 yuv420p，保证流拷贝拼接可用
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            # 与 finalize_clip 一致：首帧 DTS 归零，保证流拷贝拼接时间轴正确
            "-avoid_negative_ts", "make_zero",
            output_path
        ]
        result = _run_ffmpeg(cmd, 60)
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"静音音轨添加失败: {_err_tail(result.stderr)}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("静音音轨添加超时")
    except Exception as e:
        raise RuntimeError(f"静音音轨添加异常: {e}")

    return output_path


def mix_bgm(video_path: str, bgm_path: str, output_path: str,
            bgm_volume: float = 0.25) -> str:
    """将背景音乐与视频现有音轨混合（视频流零重编码）

    使用 -c:v copy 复制视频流，仅对音频做混合：
    - 解说音轨：保持原音量（1.0）
    - BGM 音轨：降低音量（默认 0.25）避免压过解说
    - amix 滤镜将两条音频混合为一条

    Args:
        video_path: 已含解说音轨的视频路径
        bgm_path: 背景音乐文件路径
        output_path: 混合后输出路径
        bgm_volume: BGM 音量比例（0-1，默认 0.25）

    Returns:
        混合后的视频路径

    Raises:
        RuntimeError: 混合失败时抛出
    """
    # 获取视频时长，用于截取 BGM
    video_duration = get_clip_duration(video_path)

    # 构建滤镜：解说保持原音量，BGM 降低音量后截取到视频时长，然后混合
    bgm_trim = video_duration if video_duration > 0 else "inf"
    filter_complex = (
        f"[0:a]volume=1.0[nar];"
        f"[1:a]volume={bgm_volume},atrim=0:{bgm_trim}[bgm];"
        f"[nar][bgm]amix=inputs=2:duration=first[aout]"
    )

    try:
        cmd = [
            FFMPEG_EXE, "-y",
            "-i", video_path,
            "-i", bgm_path,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",           # 视频流零重编码
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path
        ]
        result = _run_ffmpeg(cmd, 300)
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"BGM 混合失败: {_err_tail(result.stderr)}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("BGM 混合超时")
    except Exception as e:
        raise RuntimeError(f"BGM 混合异常: {e}")

    return output_path
