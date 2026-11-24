"""环节6c-1：视频拼接与音频合并

将各镜头的视频片段按顺序拼接，再合并语音音频。
支持视频流拷贝拼接（-c:v copy 视频零重编码 + -c:a aac 音频重编码）
和全量重编码拼接两种模式。
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
    """用 ffprobe 探测片段编码参数（pix_fmt/width/height/duration）

    仅用于流拷贝一致性预检，探测失败返回 None。
    """
    if not FFPROBE_EXE:
        return None
    try:
        result = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt,width,height:format=duration",
             "-of", "json", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10
        )
        if result.returncode != 0:
            return None
        import json
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        duration = float(data.get("format", {}).get("duration", 0) or 0)
        return {
            "pix_fmt": stream.get("pix_fmt", ""),
            "width": int(stream.get("width", 0) or 0),
            "height": int(stream.get("height", 0) or 0),
            "duration": duration,
        }
    except Exception:
        return None


def _normalize_clip_pix_fmt(path: str, target_pix_fmt: str) -> str:
    """将单个片段的像素格式归一化到目标格式（视频流重编码，音频直拷）

    仅在片段 pix_fmt 与目标不一致时调用。返回临时文件路径，调用方负责清理。
    使用快速预设，只重编码不匹配的少量片段，对整体拼接耗时影响很小。
    """
    tmp_out = tempfile.NamedTemporaryFile(
        suffix=".mp4", delete=False
    ).name
    cmd = [
        FFMPEG_EXE, "-y", "-i", path,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", target_pix_fmt,
        "-c:a", "copy",
        # 首帧 DTS 归零，避免 concat 流拷贝时接缝处时间戳异常
        "-avoid_negative_ts", "make_zero",
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


def _validate_concat_output(output_path: str, expected_durations: list) -> bool:
    """校验拼接产出的视频文件是否真正可解码（非仅容器元数据正常）

    纯 -c copy 拼接可能产出 ffmpeg 返回 0 但内容损坏的文件：
    容器元数据（时长/码率）正常，但实际数据流无法解码（尤其音频流）。
    此函数探测输出文件并验证：
    1. 视频流和音频流均存在
    2. 输出时长接近输入片段时长之和（容差 15%）
    3. 尝试解码末尾帧，确认末尾内容可访问

    Args:
        output_path: 拼接输出文件路径
        expected_durations: 各输入片段的时长列表（用于对比）

    Returns:
        True 表示校验通过；False 表示文件损坏，应回退重编码
    """
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 204_800:
        return False

    # 1. 探测输出文件的流信息与时长
    if FFPROBE_EXE:
        try:
            result = subprocess.run(
                [FFPROBE_EXE, "-v", "error", "-show_entries",
                 "format=duration:stream=codec_type,codec_name",
                 "-of", "json", output_path],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15
            )
            if result.returncode != 0:
                print("  [WARN] 拼接校验失败: ffprobe 无法读取输出文件")
                return False

            import json
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            if not has_video or not has_audio:
                print(f"  [WARN] 拼接校验失败: 缺少流 video={has_video} audio={has_audio}")
                return False

            out_duration = float(data.get("format", {}).get("duration", "0"))
            expected = sum(expected_durations) if expected_durations else out_duration
            if expected > 0.1 and abs(out_duration - expected) / expected > 0.15:
                print(
                    f"  [WARN] 拼接校验失败: 输出时长 {out_duration:.1f}s，"
                    f"预期 {expected:.1f}s（偏差 {abs(out_duration - expected) / expected:.0%}）"
                )
                return False
        except Exception as e:
            print(f"  [WARN] 拼接校验失败: 探测输出异常 {e}")
            return False
    else:
        # 无 ffprobe：用 ffmpeg 兜底探测
        try:
            result = subprocess.run(
                [FFMPEG_EXE, "-hide_banner", "-i", output_path],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30
            )
            stderr = result.stderr or ""
            if "Video:" not in stderr or "Audio:" not in stderr:
                return False
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
            if not m:
                return False
            out_duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            expected = sum(expected_durations) if expected_durations else out_duration
            if expected > 0.1 and abs(out_duration - expected) / expected > 0.15:
                return False
        except Exception:
            return False

    # 2. 尝试解码末尾帧，确认末尾内容可访问（关键：片尾在末尾，损坏时无法读取）
    try:
        probe_frame = output_path + ".validate.jpg"
        r = subprocess.run(
            [FFMPEG_EXE, "-y", "-ss", "0", "-i", output_path,
             "-f", "image2", "-frames:v", "1", "-q:v", "5", probe_frame],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30
        )
        ok_start = os.path.exists(probe_frame) and os.path.getsize(probe_frame) > 0
        # 清理探针帧
        if os.path.exists(probe_frame):
            os.unlink(probe_frame)

        # 解码末尾帧（取输出时长 - 1 秒）
        probe_frame2 = output_path + ".validate_end.jpg"
        seek_t = out_duration - 1 if out_duration > 2 else out_duration // 2
        r2 = subprocess.run(
            [FFMPEG_EXE, "-y", "-ss", str(seek_t), "-i", output_path,
             "-f", "image2", "-frames:v", "1", "-q:v", "5", probe_frame2],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30
        )
        ok_end = os.path.exists(probe_frame2) and os.path.getsize(probe_frame2) > 0
        if os.path.exists(probe_frame2):
            os.unlink(probe_frame2)

        if not (ok_start and ok_end):
            print(f"  [WARN] 拼接校验失败: 帧解码 ok_start={ok_start} ok_end={ok_end}")
        return ok_start and ok_end
    except Exception as e:
        print(f"  [WARN] 拼接校验失败: 帧解码异常 {e}")
        return False


def merge_clips_stream_copy(clip_paths: list, output_path: str) -> str:
    """视频流拷贝拼接（视频零重编码 + 音频重编码，速度极快）

    使用 ffmpeg concat demuxer，视频流 -c:v copy 直接拼接 H.264 码流
    （不解码、不重编码），音频流 -c:a aac 统一重编码为兼容的 AAC。

    纯 -c copy 盲拼在各片段音频编码参数（采样率/声道/编码器）不一致时
    会产出损坏文件：容器元数据正常但实际数据流无法解码，播放器中途
    中断，末尾片段（如片尾）不可见。改为视频流拷贝 + 音频重编码，
    既保留视频零重编码的快速拼接，又确保音频兼容性。

    拼接前会逐片探测编码参数；pix_fmt 不一致的片段会先归一化到目标
    格式（yuv420p）。拼接后校验输出文件可解码性，损坏则回退重编码。
    分辨率不一致时无法简单归一化，则回退重编码。

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

    # 目标像素格式固定为 yuv420p（有限范围），与 Remotion 渲染、各写片段路径一致，
    # 保证所有片段最终收敛到唯一规范格式，流拷贝拼接始终可用。
    target_pix = "yuv420p"

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
                print(f"  [NORM] 归一化像素格式: {os.path.basename(path)} "
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
        # 视频流拷贝（零重编码），音频重编码为 AAC（128k）
        # 不同片段的 AAC 音频参数（采样率/声道/编码器）可能不一致，
        # 纯 -c copy 盲拼会导致音频流损坏（播放器中途中断、末尾片段不可见）。
        # 视频流 -c:v copy 保持无损快速拼接，仅音频重编码确保兼容性。
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
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

        # 拼接后校验：探测输出文件，确认视频流和音频流均可正常解码
        # 纯 -c copy 拼接可能产出容器正常但内容损坏的文件（ffmpeg 返回 0 但数据无效）
        expected_durations = [p["duration"] for p in params_list]
        validated = _validate_concat_output(output_path, expected_durations)
        if not validated:
            # 直接 MP4 拷贝校验不通过时，先尝试 MPEG-TS 中转：
            # TS 对时间戳/参数集变化更宽容，常能把 300+ 片段的拷贝拼接救回来，
            # 避免直接回退到整片全量重编码（超长视频要十几分钟）。
            print("  [RETRY] 直接 MP4 拷贝校验未通过，尝试 MPEG-TS 中转重试流拷贝...")
            ts_path = output_path + ".concat.ts"
            try:
                ts_cmd = [
                    FFMPEG_EXE, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_file,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k",
                    "-f", "mpegts",
                    ts_path,
                ]
                ts_result = subprocess.run(
                    ts_cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180
                )
                if ts_result.returncode != 0 or not os.path.exists(ts_path) or os.path.getsize(ts_path) == 0:
                    raise RuntimeError(f"TS 中转拼接失败: {ts_result.stderr.strip()[-500:]}")
                remux_cmd = [
                    FFMPEG_EXE, "-y", "-i", ts_path,
                    "-c", "copy", "-bsf:a", "aac_adtstoasc",
                    "-movflags", "+faststart",
                    output_path,
                ]
                remux = subprocess.run(
                    remux_cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180
                )
                if remux.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    raise RuntimeError(f"TS 中转重封装失败: {remux.stderr.strip()[-500:]}")
                validated = _validate_concat_output(output_path, expected_durations)
            finally:
                if os.path.exists(ts_path):
                    os.unlink(ts_path)

        if not validated:
            raise RuntimeError("流拷贝拼接产出损坏文件，回退重编码拼接")
    except subprocess.TimeoutExpired:
        raise RuntimeError("流拷贝拼接超时")
    except RuntimeError:
        # 校验失败或拼接失败：清理已产出的损坏文件，由调用方回退重编码
        if os.path.exists(output_path):
            os.unlink(output_path)
        raise
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


# 片段最小字节数：纯色/文字卡这类低码率片段可能只有几十 KB，
# 不能用 200KB 之类的阈值判定损坏（会把合法片段误删，导致成片缺段）。
_MIN_CLIP_BYTES = 4096


def _count_clip_frames(path: str) -> int:
    """精确统计视频帧数（-count_frames 会完整解码，较慢，仅在元数据缺帧数时用）"""
    import json
    try:
        result = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
             "-count_frames", "-show_entries", "stream=nb_read_frames",
             "-of", "json", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180
        )
        if result.returncode != 0:
            return 0
        data = json.loads(result.stdout)
        streams = data.get("streams") or []
        return int(streams[0].get("nb_read_frames") or 0) if streams else 0
    except Exception:
        return 0


def _probe_clip_info(path: str) -> dict | None:
    """获取片段信息，损坏返回 None（ffprobe 缺失时自动退回 ffmpeg）

    先用元数据读取时长/帧数（毫秒级），只有元数据缺帧数时才用
    -count_frames 精确统计。之前对全部 300+ 片段逐个 -count_frames
    完整解码，光预检就要好几分钟。

    Returns:
        dict 含 nb_frames, duration, pix_fmt 等；损坏时返回 None
    """
    if not os.path.exists(path) or os.path.getsize(path) < _MIN_CLIP_BYTES:
        return None

    if not FFPROBE_EXE:
        # 没有 ffprobe：必须走 ffmpeg 兜底，否则会把所有片段误判为损坏
        return _probe_with_ffmpeg(path)

    try:
        result = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_frames,duration,pix_fmt",
             "-of", "json", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15
        )
        if result.returncode != 0:
            return None

        import json
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        duration = float(stream.get("duration") or 0)
        if duration <= 0.1:
            return None
        nb_frames = int(stream.get("nb_frames") or 0)
        if nb_frames <= 0:
            nb_frames = _count_clip_frames(path)
        if nb_frames <= 0:
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

    优先使用视频流拷贝拼接（-c:v copy 视频零重编码 + -c:a aac 音频重编码，
    秒级完成），如果片段编码参数不兼容或存在损坏片段，则回退到
    ffmpeg concat demuxer 全量重编码（流式处理，不会 OOM）。

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
        print(f"  [INFO] 片段探测: {FFPROBE_EXE}")
    else:
        print("  [WARN] 未找到 ffprobe，改用 ffmpeg 解析片段信息（CI 上建议安装 ffmpeg 以启用流拷贝拼接）")

    # 预检所有片段，过滤损坏的
    valid_clips = []
    skipped = []
    total_duration = 0.0
    for path in clip_paths:
        info = _probe_clip_info(path)
        if info:
            valid_clips.append(path)
            total_duration += float(info.get("duration") or 0)
        else:
            skipped.append(path)
            print(f"  [WARN] 片段损坏或无效，跳过: {os.path.basename(path)}")

    if not valid_clips:
        raise RuntimeError("所有视频片段均无效或损坏，无法拼接")

    if skipped:
        print(f"  [WARN] 跳过 {len(skipped)} 个损坏片段，拼接 {len(valid_clips)} 个有效片段")

    # 先尝试视频流拷贝拼接（视频零重编码 + 音频重编码，速度极快）
    try:
        print(f"  [TRY] 尝试视频流拷贝拼接（视频零重编码 + 音频重编码）...")
        merge_clips_stream_copy(valid_clips, output_path)
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  [OK] 流拷贝拼接完成（{file_size:.1f} MB，视频未重编码）")
        return output_path
    except Exception as e:
        print(f"  [WARN] 流拷贝拼接失败，回退到 ffmpeg 重编码拼接: {e}")
        print(f"  [FALLBACK] 使用 ffmpeg concat demuxer 重编码（preset={preset}）...")

    # ffmpeg concat demuxer 重编码：流式处理，不一次性加载所有片段到内存
    concat_list = []
    for path in valid_clips:
        abs_path = os.path.abspath(path)
        safe_path = abs_path.replace("'", "'\\''")
        concat_list.append(f"file '{safe_path}'")

    # 超时按总时长自适应：4 线程 veryfast 大约 3~5x 实时速度。
    # 之前硬编码 600s，在 300+ 片段 / 三十分钟以上的长视频上必然误超时
    # （Run 45324299443：330 个片段、全量重编码 10 分钟没跑完直接失败）。
    total_minutes = total_duration / 60
    encode_timeout = min(2400, max(900, int(total_duration * 1.5) + 120))
    print(
        f"  [TIME] 输入总时长约 {total_minutes:.1f} 分钟，"
        f"重编码超时上限 {encode_timeout // 60} 分钟"
    )

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
            "-threads", "0",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=encode_timeout
        )
        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"ffmpeg 重编码拼接失败: {result.stderr.strip()}")

        # 重编码后校验：-shortest 已截断时长至实际内容长度，
        # 主要确认末尾帧可访问。不传 clip_durations 做时长对比，
        # 因源片段元数据时长可能不准确（正是本次问题的根因）。
        validated = _validate_concat_output(output_path, [])
        if not validated:
            raise RuntimeError("ffmpeg 重编码拼接产出损坏文件（末尾帧不可访问）")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg 重编码拼接超时（{encode_timeout // 60}分钟）")
    except Exception as e:
        raise RuntimeError(f"ffmpeg 重编码拼接异常: {e}")
    finally:
        if os.path.exists(list_file):
            os.unlink(list_file)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [OK] ffmpeg 重编码拼接完成（{file_size:.1f} MB，{len(valid_clips)} 个片段）")
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
