"""环节6c-1：视频拼接与音频合并

将各镜头的视频片段按顺序拼接，再合并语音音频。
支持流拷贝拼接（-c copy，零重编码）和重编码拼接两种模式。
"""

import os
import shutil
import subprocess
import tempfile
from .moviepy_compat import VideoFileClip, AudioFileClip, set_audio, subclip

# 系统 ffmpeg 和 ffprobe 路径
FFMPEG_EXE = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")

def _resolve_ffprobe() -> str:
    """解析 ffprobe 可执行文件路径，兼容 Windows(.exe) 和 Linux(无后缀)"""
    # 优先用 shutil.which 在系统 PATH 中查找
    probed = shutil.which("ffprobe")
    if probed:
        return probed

    # 从 ffmpeg 路径推导（同目录，先试 ffprobe.exe 再试 ffprobe）
    ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
    for suffix in ("ffprobe.exe", "ffprobe"):
        candidate = os.path.join(ffmpeg_dir, suffix)
        if os.path.exists(candidate):
            return candidate

    # 兜底：返回 "ffprobe"，让 subprocess 在 PATH 中查找
    return "ffprobe"

FFPROBE_EXE = _resolve_ffprobe()


def merge_clips_stream_copy(clip_paths: list, output_path: str) -> str:
    """流拷贝拼接视频片段（零重编码，速度极快）

    使用 ffmpeg concat demuxer + -c copy，直接将各片段的 H.264 码流
    拼接成完整视频，不解码、不重编码。要求所有片段编码参数一致
    （同 codec、分辨率、fps、pixel_format、profile、level）。

    拼接前会逐片检查 pix_fmt，参数不一致时主动抛出异常，
    避免流拷贝"成功"但产生静默颜色失真。

    Args:
        clip_paths: 视频片段路径列表（按顺序）
        output_path: 输出路径

    Returns:
        输出视频路径

    Raises:
        RuntimeError: 参数不一致或拼接失败时抛出（调用方可回退到重编码方案）
    """
    if not clip_paths:
        raise RuntimeError("没有视频片段可拼接")

    # 预检查：所有片段的 pix_fmt 必须一致，否则流拷贝会产生静默颜色失真
    pix_fmts = set()
    for path in clip_paths:
        try:
            result = subprocess.run(
                [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", path],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10
            )
            fmt = result.stdout.strip().rstrip(',')
            if fmt:
                pix_fmts.add(fmt)
        except Exception:
            # 检查失败的片段直接跳过流拷贝
            raise RuntimeError(f"流拷贝预检查失败: {path}")

    if len(pix_fmts) > 1:
        raise RuntimeError(f"片段编码参数不一致: {pix_fmts}，无法流拷贝拼接")

    # 创建 concat 列表文件（ffmpeg concat demuxer 格式）
    concat_list = []
    for path in clip_paths:
        abs_path = os.path.abspath(path)
        # Windows 路径含反斜杠，单引号包裹 + 转义
        safe_path = abs_path.replace("'", "'\\''")
        concat_list.append(f"file '{safe_path}'")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(concat_list))
        list_file = f.name

    try:
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=120
        )
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"流拷贝拼接失败: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("流拷贝拼接超时")
    except Exception as e:
        raise RuntimeError(f"流拷贝拼接异常: {e}")
    finally:
        # 清理临时列表文件
        if os.path.exists(list_file):
            os.unlink(list_file)

    return output_path


def _probe_clip_info(path: str) -> dict | None:
    """用 ffprobe 获取片段信息，损坏返回 None

    Returns:
        dict 含 nb_frames, duration, pix_fmt 等；损坏时返回 None
    """
    if not os.path.exists(path) or os.path.getsize(path) < 204_800:
        return None

    try:
        result = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
             "-count_frames", "-show_entries",
             "stream=nb_read_frames,duration,pix_fmt",
             "-of", "json", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15
        )
        if result.returncode != 0:
            return None

        import json
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        nb_frames = int(stream.get("nb_read_frames", "0"))
        duration = float(stream.get("duration", "0"))
        if nb_frames <= 0 or duration <= 0.1:
            return None

        return {
            "nb_frames": nb_frames,
            "duration": duration,
            "pix_fmt": stream.get("pix_fmt", ""),
        }
    except Exception:
        return None


def merge_clips(clip_paths: list, output_path: str, preset: str = "veryfast") -> str:
    """拼接视频片段

    优先使用流拷贝拼接（-c copy，零重编码，秒级完成），
    如果片段编码参数不兼容或存在损坏片段，则回退到
    ffmpeg concat demuxer 重编码（流式处理，不会 OOM）。

    损坏片段自动跳过，不中断整体拼接。

    Args:
        clip_paths: 视频片段路径列表（按顺序）
        output_path: 输出路径
        preset: 编码预设，默认 veryfast（仅回退重编码时使用）

    Returns:
        输出视频路径

    Raises:
        RuntimeError: 所有片段均加载失败或拼接失败时抛出
    """
    # 预检所有片段，过滤损坏的
    valid_clips = []
    skipped = []
    for path in clip_paths:
        info = _probe_clip_info(path)
        if info:
            valid_clips.append(path)
        else:
            skipped.append(path)
            print(f"  ⚠️ 片段损坏或无效，跳过: {os.path.basename(path)}")

    if not valid_clips:
        raise RuntimeError("所有视频片段均无效或损坏，无法拼接")

    if skipped:
        print(f"  ⚠️ 跳过 {len(skipped)} 个损坏片段，拼接 {len(valid_clips)} 个有效片段")

    # 先尝试流拷贝拼接（零重编码，速度极快）
    try:
        print(f"  ⚡ 尝试流拷贝拼接（零重编码）...")
        merge_clips_stream_copy(valid_clips, output_path)
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ 流拷贝拼接完成（{file_size:.1f} MB，未重编码）")
        return output_path
    except Exception as e:
        print(f"  ⚠️ 流拷贝拼接失败，回退到 ffmpeg 重编码拼接: {e}")
        print(f"  🔄 使用 ffmpeg concat demuxer 重编码（preset={preset}）...")

    # ffmpeg concat demuxer 重编码：流式处理，不一次性加载所有片段到内存
    concat_list = []
    for path in valid_clips:
        abs_path = os.path.abspath(path)
        safe_path = abs_path.replace("'", "'\\''")
        concat_list.append(f"file '{safe_path}'")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(concat_list))
        list_file = f.name

    try:
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264",
            "-preset", preset,
            "-c:a", "aac",
            "-threads", "4",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=600  # 10 分钟超时（重编码 175 个片段可能需要较长时间）
        )
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"ffmpeg 重编码拼接失败: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg 重编码拼接超时（10分钟）")
    except Exception as e:
        raise RuntimeError(f"ffmpeg 重编码拼接异常: {e}")
    finally:
        if os.path.exists(list_file):
            os.unlink(list_file)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✅ ffmpeg 重编码拼接完成（{file_size:.1f} MB，{len(valid_clips)} 个片段）")
    return output_path


def combine_audio_video(video_path: str, audio_path: str, output_path: str) -> str:
    """将语音合并到视频上

    音频比视频长则截取，短则保持（视频末尾静音）。

    Args:
        video_path: 视频路径
        audio_path: 音频路径
        output_path: 输出路径

    Returns:
        输出视频路径

    Raises:
        RuntimeError: 视频或音频加载失败时抛出
    """
    video_clip = None
    audio_clip = None
    try:
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)

        # 音频比视频长则截取到视频时长
        if audio_clip.duration > video_clip.duration:
            audio_clip = subclip(audio_clip, 0, video_clip.duration)

        final_clip = set_audio(video_clip, audio_clip)
        final_clip.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            ffmpeg_params=['-movflags', '+faststart']
        )
    except Exception as e:
        raise RuntimeError(f"音视频合并失败: {e}")
    finally:
        if video_clip is not None:
            try:
                video_clip.close()
            except Exception:
                pass
        if audio_clip is not None:
            try:
                audio_clip.close()
            except Exception:
                pass

    return output_path
