"""环节6b：语音合成

使用 TTS API（与 F:\\GO\\doc_ppt_video\\word2video 中的方案一致）
将文章全文合成为语音，返回音频时长用于后续视频时长对齐。

API 格式：
    POST http://ttv.yugongtxl.dpdns.org/v1/audio/speech
    Header: Authorization: Bearer <api_key>
    Body: {"input": text, "voice": voice, "speed": float, "pitch": float, "stream": false}
    Response: 原始 mp3 字节流
"""

import os

import requests
from .moviepy_compat import get_audio_duration

from ..utils import load_config


# 默认 TTS 配置（与 Go 项目保持一致）
DEFAULT_TTS_CONFIG = {
    "tts_api_url": "http://ttv.yugongtxl.dpdns.org/v1/audio/speech",
    "tts_api_key": "",
    "tts_voice": "",       # 空则根据语言自动选择
    "tts_speed": 1.0,
    "tts_pitch": 1.0,
}

# 任务级覆盖值（由 CLI 参数设置，仅影响本次进程）
# 优先级：CLI 覆盖 > 环境变量/settings.json > 默认值
_VOICE_OVERRIDE: str | None = None
_SPEED_OVERRIDE: float | None = None


def set_tts_overrides(voice: str | None = None, speed: float | None = None) -> None:
    """设置本次运行的 TTS 音色/语速覆盖值

    任务创建时用户选择的音色与语速通过 CLI 参数传入，在此覆盖
    settings.json / 环境变量中的全局配置。

    Args:
        voice: 音色名称，None 或空字符串表示沿用按语言自动选择的音色
        speed: 语速倍率，None 表示沿用配置值
    """
    global _VOICE_OVERRIDE, _SPEED_OVERRIDE
    _VOICE_OVERRIDE = (voice or "").strip() or None
    try:
        _SPEED_OVERRIDE = float(speed) if speed not in (None, "") else None
    except (TypeError, ValueError):
        _SPEED_OVERRIDE = None


def _get_tts_config() -> dict:
    """加载 TTS 配置

    优先级：环境变量 > settings.json > 默认值。
    空字符串不会覆盖默认值，避免 settings.json 中留空导致 TTS 不可用。

    Returns:
        TTS 配置字典
    """
    config = load_config("settings.json")
    tts_config = dict(DEFAULT_TTS_CONFIG)
    for key, value in config.items():
        if key.startswith("tts_") and value:  # 只使用非空值覆盖默认
            tts_config[key] = value

    # 环境变量兜底（GitHub Actions 通过 secrets 传入）
    env_url = os.environ.get("TTS_API_URL")
    if env_url:
        tts_config["tts_api_url"] = env_url
    env_key = os.environ.get("TTS_API_KEY")
    if env_key:
        tts_config["tts_api_key"] = env_key

    # 任务级覆盖（用户创建任务时选择的音色/语速）
    if _VOICE_OVERRIDE:
        tts_config["tts_voice"] = _VOICE_OVERRIDE
    if _SPEED_OVERRIDE is not None:
        tts_config["tts_speed"] = _SPEED_OVERRIDE

    return tts_config


def _select_voice(language: str) -> str:
    """根据全局语言选择音色

    文章语言在入口处统一确定（默认中文，可选英文），所有片段共用同一音色，
    避免逐段检测文本语言时数字/英文密集的短段被误判为英文。

    Args:
        language: 文章语言，"zh"（中文）或 "en"（英文）

    Returns:
        音色名称
    """
    if language == "en":
        return "en-US-EricNeural"
    return "zh-CN-YunjianNeural"


def _call_tts_api(text: str, output_path: str, tts_config: dict,
                   language: str = "zh") -> bool:
    """调用 TTS API 合成语音并保存

    带重试机制：API 偶发失败时自动重试，最多 3 次。

    Args:
        text: 要合成的文本
        output_path: 音频输出路径
        tts_config: TTS 配置字典
        language: 文章语言，"zh"（中文）或 "en"（英文），决定音色选择

    Returns:
        是否成功
    """
    import time

    global _VOICE_OVERRIDE

    voice = tts_config.get("tts_voice") or _select_voice(language)
    speed = float(tts_config.get("tts_speed", 1.0))
    # 防御：极端语速会被 TTS 服务拒绝，限制在合理区间
    speed = min(4.0, max(0.25, speed))
    pitch = float(tts_config.get("tts_pitch", 1.0))
    api_url = tts_config["tts_api_url"]
    api_key = tts_config["tts_api_key"]

    request_body = {
        "input": text,
        "voice": voice,
        "speed": speed,
        "pitch": pitch,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"  🎙️ 语音合成: 音色={voice}, 语速={speed}, 音调={pitch}")
            resp = requests.post(
                api_url,
                json=request_body,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()

            # 保存原始 mp3 字节流
            with open(output_path, "wb") as f:
                f.write(resp.content)

            print(f"  ✅ 语音合成完成: {output_path} ({len(resp.content) / 1024:.1f} KB)")
            return True
        except requests.exceptions.HTTPError as e:
            # 自定义音色可能不被服务端支持：回退到按语言选择的默认音色再试
            if (
                e.response is not None
                and e.response.status_code in (400, 404, 422)
                and voice != _select_voice(language)
            ):
                print(f"  ⚠️ 音色 {voice} 不可用，回退默认音色 {_select_voice(language)}")
                # 记住回退结果，避免后续每个片段都重复失败一次
                _VOICE_OVERRIDE = None
                voice = _select_voice(language)
                request_body["voice"] = voice
                continue
            if attempt < max_retries - 1:
                wait = 3 * (attempt + 1)
                print(f"  ⚠️ 语音合成失败（第 {attempt + 1} 次），{wait}秒后重试...")
                time.sleep(wait)
                continue
            print(f"❌ 语音合成失败: HTTP {e.response.status_code}")
            try:
                print(f"   响应: {e.response.text[:500]}")
            except Exception:
                pass
            return False
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 3 * (attempt + 1)
                print(f"  ⚠️ 语音合成失败（第 {attempt + 1} 次），{wait}秒后重试...")
                time.sleep(wait)
                continue
            print(f"❌ 语音合成失败: {e}")
            return False

    return False


def synthesize_speech(text: str, output_path: str, language: str = "zh") -> float:
    """合成语音并返回时长

    使用 TTS API 合成语音，通过 ffprobe 获取音频时长。
    接口与原 edge-tts 版本一致，调用方无需改动。

    Args:
        text: 要合成的文本
        output_path: 音频输出路径
        language: 文章语言，"zh"（中文，默认）或 "en"（英文），决定 TTS 音色

    Returns:
        音频时长（秒），失败返回 0
    """
    try:
        tts_config = _get_tts_config()

        # 确保输出目录存在
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # 调用 TTS API
        if not _call_tts_api(text, output_path, tts_config, language):
            return 0

        # 获取音频时长（ffprobe 优先，moviepy 兜底）
        duration = get_audio_duration(output_path)

        return duration
    except Exception as e:
        print(f"❌ 语音合成失败: {e}")
        return 0
