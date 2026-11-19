"""环节6d：固定片尾视频

在最终视频末尾追加一段固定片尾：
- 固定语音：「今天的分享就到这里，我们下次再会。」
- 固定图片：assets/outro/outro_landscape.jpg（横版）/
             assets/outro/outro_portrait.jpg（竖版）
  夕阳公路延伸向地平线，契合「下次再会」的收尾意境。
  图片已随仓库提交，本地缺失时自动从 Pexels 下载并保存复用。
- 带 Ken Burns 动效（缓慢推近），语音说完后留白收尾。

生成失败返回 None，绝不阻断主视频产出。
"""

import os
from pathlib import Path

from .image_to_clip import image_to_clip
from .tts_synthesis import synthesize_speech
from .video_merger import combine_audio_video

# 固定片尾语音
OUTRO_TEXT = "今天的分享就到这里，我们下次再会。"

# 项目根目录（core/composer 的上两级）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 片尾图片固定目录（图片随仓库提交，保证每次片尾一致）
OUTRO_IMAGE_DIR = _PROJECT_ROOT / "assets" / "outro"

# 本地片尾图片缺失时的 Pexels 下载关键词（固定，保证下载结果稳定）
OUTRO_PEXELS_KEYWORDS = ["sunset road horizon"]


def _resolve_outro_image(orientation: str, api_key: str | None) -> str | None:
    """获取片尾图片：优先本地固定图片，缺失时从 Pexels 下载

    Args:
        orientation: "landscape"（横版）或 "portrait"（竖版）
        api_key: Pexels API key（可为 None，下载器自动回退浏览器通道）

    Returns:
        片尾图片本地路径；获取失败返回 None
    """
    filename = f"outro_{orientation}.jpg"
    local_path = OUTRO_IMAGE_DIR / filename
    if local_path.exists():
        return str(local_path)

    # 本地缺失：从 Pexels 下载并保存到固定目录，后续复用
    try:
        OUTRO_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        from core.asset_matcher.pexels_downloader import download_pexels_images

        print(f"  📥 本地无片尾图片，从 Pexels 下载「{OUTRO_PEXELS_KEYWORDS[0]}」...")
        downloaded = download_pexels_images(
            keywords=OUTRO_PEXELS_KEYWORDS,
            output_dir=str(OUTRO_IMAGE_DIR),
            max_count=1,
            orientation=orientation,
            api_key=api_key,
        )
        if not downloaded:
            print("  ⚠️ 未下载到片尾图片")
            return None
        target = str(local_path)
        if downloaded[0] != target:
            os.replace(downloaded[0], target)
        return target
    except Exception as e:
        print(f"  ⚠️ 片尾图片获取失败: {e}")
        return None


def generate_outro_clip(
    work_dir,
    resolution: tuple,
    fps: int,
    codec: str,
    audio_codec: str,
    preset: str,
    threads: int,
    api_key: str | None = None,
    language: str = "zh",
    min_duration: float = 3.0,
    padding: float = 0.8,
) -> str | None:
    """生成固定片尾视频片段（含固定语音）

    流程：固定图片 → Ken Burns 动效视频 → 合并固定语音。
    片尾编码参数与主视频一致，可直接追加到片段列表末尾参与拼接。

    Args:
        work_dir: 工作目录（片尾中间文件输出目录）
        resolution: 输出分辨率 (宽, 高)，与主视频一致
        fps: 帧率，与主视频一致
        codec: 视频编码器，与主视频一致
        audio_codec: 音频编码器，与主视频一致
        preset: 编码预设，与主视频一致
        threads: 编码线程数
        api_key: Pexels API key（本地片尾图片缺失时下载用）
        language: 语音语言，"zh"（中文）或 "en"（英文）
        min_duration: 语音失败时片尾的最短时长（秒）
        padding: 语音时长之后的留白（秒），让语音说完后画面停留收尾

    Returns:
        片尾视频路径（可直接追加到主视频末尾）；失败返回 None
    """
    try:
        w, h = resolution
        orientation = "landscape" if w >= h else "portrait"

        # 1. 片尾图片（固定，横竖版各一）
        image_path = _resolve_outro_image(orientation, api_key)
        if not image_path:
            print("  ⚠️ 片尾图片不可用，跳过片尾视频")
            return None

        # 2. 固定语音合成
        audio_path = str(Path(work_dir) / "outro_audio.mp3")
        duration = synthesize_speech(OUTRO_TEXT, audio_path, language)
        if duration > 0:
            duration = duration + padding
            print(f"  🎙️ 片尾语音: {OUTRO_TEXT}（{duration:.1f}s，含留白）")
        else:
            # TTS 失败：纯视频片尾，固定时长
            duration = max(min_duration, padding)
            audio_path = None
            print(f"  ⚠️ 片尾语音合成失败，使用纯视频片尾（{duration:.1f}s）")

        # 3. 图片 → 带 Ken Burns 动效的视频片段
        # scene_id=0 固定为 zoom_in（缓慢推近），有聚焦收尾的仪式感
        video_path = str(Path(work_dir) / "outro_video.mp4")
        image_to_clip(
            image_path, duration, video_path,
            scene_id=0,
            visual_type=orientation,
            resolution=resolution,
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            preset=preset,
            threads=threads,
        )

        # 4. 合并语音（无语音时直接返回视频）
        if audio_path:
            final_path = str(Path(work_dir) / "outro_final.mp4")
            combine_audio_video(video_path, audio_path, final_path)
            # 清理中间文件
            if os.path.exists(video_path):
                os.unlink(video_path)
            return final_path

        return video_path
    except Exception as e:
        print(f"  ⚠️ 片尾视频生成失败（不影响主视频）: {e}")
        import traceback
        traceback.print_exc()
        return None
