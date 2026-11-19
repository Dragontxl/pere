"""环节6c-1：视频拼接与音频合并

将各镜头的视频片段按顺序拼接，再合并语音音频。
支持流拷贝拼接（-c copy，零重编码）和重编码拼接两种模式。
"""

import os
import re
import shutil
import subprocess
import tempfile
from .moviepy_compat import VideoFileClip, AudioFileClip, set_audio, subclip

# 系统 ffmpeg 和 ffprobe 路径
FFMPEG_EXE = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")

def _resolve_ffprobe() -> str | None:
    """解析 ffprobe 可执行文件路径，兼容 Windows(.exe) 和 Linux(无后缀)

    注意：imageio-ffmpeg 只提供 ffmpeg，不提供 ffprobe。GitHub Actions 的
    ubuntu-latest 镜像默认也没有安装 ffmpeg，所以这里可能返回 None。
    返回 None 时调用方必须退回 ffmpeg 解析，不能直接判定片段损坏。
    """
    # 优先用 shutil.which 在系统 PATH 中查找
    probed = shutil.which("ffprobe")
    if probed:
        return probed

    # 从 ffmpeg 路径推导（同目录，先试 ffprobe.exe 再试 ffprobe）
    ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
    for suffix in ("ffprobe.exe", "ffprobe"):
        candidate = os.path.join(ffmpeg_dir, suffix)
        if os.path.isfile(candidate):
            return candidate

    return None

FFPROBE_EXE = _resolve_ffprobe()


def _probe_clip_params(path: str) -> dict | None:
    """用 ffprobe 探测片段编码参数（pix_fmt/width/height）

    仅用于流拷贝一致性预检，探测失败返回 None。
    """
    if not FFPROBE_EXE:
        return None
    try:
        result = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt,width,height",
             "-of", "json", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10
        )
        if result.returncode != 0:
            return None
        import json
        stream = json.loads(result.stdout).get("streams", [{}])[0]
        return {
            "pix_fmt": stream.get("pix_fmt", ""),
            "width": int(stream.get("width", 0) or 0),
            "height": int(stream.get("height", 0) or 0),
        }
    except Exception:
        return None


def _normalize_clip_pix_fmt(path: str, target_pix_fmt: str) -> str:
    """将单个片段的像素格式归一化到目标格式（视频流重编码，音频直拷）

    仅在片段 pix_fmt 与目标不一致时调用。返回临时文件路径，调用方负责清理。
    使用快速预设，只重编码不匹配的少量片段，对整体拼接耗时影响很小。
    """
    tmp_out = tempfile.NamedTemporaryFile(
        suffix=".mp4", delete=False, encoding="utf-8"
    ).name
    cmd = [
        FFMPEG_EXE, "-y", "-i", path,
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", target_pix_fmt,
        "-c:a", "copy",
        "-movflags", "+faststart",
        tmp_out,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180
    )
    if result.returncode != 0 or not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)
        raise RuntimeError(
            f"pix_fmt 归一化失败: {os.path.basename(path)}: {result.stderr.strip()}"
        )
    return tmp_out


def merge_clips_stream_copy(clip_paths: list, output_path: str) -> str:
    """流拷贝拼接视频片段（零重编码，速度极快）

    使用 ffmpeg concat demuxer + -c copy，直接将各片段的 H.264 码流
    拼接成完整视频，不解码、不重编码。要求所有片段编码参数一致
    （同 codec、分辨率、fps、pixel_format、profile、level）。

    拼接前会逐片探测编码参数；pix_fmt 不一致的片段会先归一化到多数
    片段使用的格式（默认 yuv420p），从而保证流拷贝始终可用，避免
    回退重编码。分辨率不一致时无法简单归一化，则回退重编码。

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

    # 预检查：探测所有片段编码参数
    if not FFPROBE_EXE:
        # 没有 ffprobe 就无法做一致性预检查，直接回退重编码（FFMPEG_EXE 一定可用）
        raise RuntimeError("未找到 ffprobe，跳过流拷贝，改用重编码拼接")

    params_list = []
    for path in clip_paths:
        p = _probe_clip_params(path)
        if p is None:
            raise RuntimeError(f"流拷贝预检查失败: {path}")
        params_list.append(p)

    # 目标像素格式：取出现次数最多的 pix_fmt，无则默认 yuv420p
    from collections import Counter
    pix_counter = Counter(p["pix_fmt"] for p in params_list if p["pix_fmt"])
    target_pix = pix_counter.most_common(1)[0][0] if pix_counter else "yuv420p"

    # 分辨率必须一致（pix_fmt 可归一化，但分辨率不一致无法简单归一化）
    dims = {(p["width"], p["height"]) for p in params_list}
    if len(dims) > 1:
        raise RuntimeError(f"片段分辨率不一致: {dims}，无法流拷贝拼接")

    # 将 pix_fmt 与目标不一致的片段归一化到目标格式
    normalized_paths = []
    normalized_files = []
    try:
        for path, p in zip(clip_paths, params_list):
            if p["pix_fmt"] and p["pix_fmt"] != target_pix:
                new_path = _normalize_clip_pix_fmt(path, target_pix)
                normalized_files.append(new_path)
                normalized_paths.append(new_path)
                print(f"  🔧 归一化像素格式: {os.path.basename(path)} "
                      f"{p['pix_fmt']} → {target_pix}")
            else:
                normalized_paths.append(path)
    except Exception:
        # 归一化失败：清理临时文件并抛出，由调用方回退重编码
        for f in normalized_files:
            if os.path.exists(f):
                os.unlink(f)
        raise

    # 创建 concat 列表文件（ffmpeg concat demuxer 格式）
    concat_list = []
    for path in normalized_paths:
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
        # 清理临时列表文件与归一化临时片段
        if os.path.exists(list_file):
            os.unlink(list_file)
        for f in normalized_files:
            if os.path.exists(f):
                os.unlink(f)

    return output_path


def _probe_with_ffmpeg(path: str) -> dict | None:
    """没有 ffprobe 时的兜底探测：用 ffmpeg -i 解析时长并确认存在视频流

    imageio-ffmpeg 只提供 ffmpeg，不提供 ffprobe，CI 上若未安装 ffmpeg
    就会落到这里。ffmpeg -i 在不输出文件时返回码为 1，因此不看 returncode。
    """
    try:
        result = subprocess.run(
            [FFMPEG_EXE, "-hide_banner", "-i", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30
        )
    except Exception:
        return None

    stderr = result.stderr or ""
    if "Video:" not in stderr:
        return None

    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if not m:
        return None
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if duration <= 0.1:
        return None

    return {"nb_frames": -1, "duration": duration, "pix_fmt": ""}


def _probe_clip_info(path: str) -> dict | None:
    """获取片段信息，损坏返回 None（ffprobe 缺失时自动退回 ffmpeg）

    Returns:
        dict 含 nb_frames, duration, pix_fmt 等；损坏时返回 None
    """
    if not os.path.exists(path) or os.path.getsize(path) < 204_800:
        return None

    if not FFPROBE_EXE:
        # 没有 ffprobe：必须走 ffmpeg 兜底，否则会把所有片段误判为损坏
        return _probe_with_ffmpeg(path)

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
    except FileNotFoundError:
        # ffprobe 路径不可执行（例如被删除）：退回 ffmpeg 探测
        return _probe_with_ffmpeg(path)
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
    if FFPROBE_EXE:
        print(f"  🔍 片段探测: {FFPROBE_EXE}")
    else:
        print("  ⚠️ 未找到 ffprobe，改用 ffmpeg 解析片段信息（CI 上建议安装 ffmpeg 以启用流拷贝拼接）")

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
            # 强制 yuv420p，与主视频片段像素格式一致，避免流拷贝拼接参数不一致
            ffmpeg_params=['-pix_fmt', 'yuv420p', '-movflags', '+faststart']
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
