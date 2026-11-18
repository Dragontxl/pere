"""图文+Remotion 自动视频生成系统 — 主流程编排入口

完整流程：文章 → 分镜 → 素材匹配 → Remotion分析 → 综合决策 → 合成输出

用法：
    交互模式（本地）:  python main.py
    非交互模式（CI）:  python main.py --article-file article.txt
    指定输出目录:      python main.py --article-file article.txt --output-dir ./output
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from zhipuai import ZhipuAI

from core.utils import load_config, ensure_dir, clean_filename, is_chinese
from core.article_input import (
    get_article_from_ai,
    get_article_from_file,
    select_and_get_article,
)
from core.scene_generator import generate_scenes, generate_scenes_from_chunks, Scene
from core.article_chunker import split_into_chunks
from core.asset_matcher.pexels_downloader import download_pexels_images, _create_driver, PexelsSession
from core.asset_matcher.multimodal_reviewer import MultimodalReviewer
from core.remotion_analyzer import analyze_scenes
from core.decision_engine import decide_scenes, SceneDecision
from core.composer.image_to_clip import image_to_clip
from core.composer.tts_synthesis import synthesize_speech
from core.composer.video_merger import merge_clips
from core.composer.subtitle_overlay import add_subtitles
from core.composer.clip_finalizer import (
    finalize_clip,
    add_silent_audio,
    mix_bgm,
)


def _translate_keywords(keywords: list, client, model: str) -> list:
    """将中文关键词翻译为英文（Pexels 以英文搜索效果最佳）

    检测每个关键词是否含中文，含中文的批量调用 Agnes 翻译为英文，
    纯英文关键词直接保留。翻译失败时回退为原始关键词。

    Args:
        keywords: 原始关键词列表
        client: Agnes 客户端
        model: 模型名称

    Returns:
        翻译后的关键词列表（保持原始顺序）
    """
    import re

    # 分离中文和英文关键词，记录原始位置
    need_translate = []  # [(original_index, keyword)]
    result = [None] * len(keywords)

    for i, kw in enumerate(keywords):
        kw = kw.strip()
        if is_chinese(kw):
            need_translate.append((i, kw))
        else:
            result[i] = kw

    if not need_translate:
        return keywords

    # 批量翻译所有中文关键词
    try:
        kw_list = "\n".join(f"{i+1}. {kw}" for i, (_, kw) in enumerate(need_translate))
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "请将以下关键词逐个翻译为英文，保持编号，只输出翻译结果。\n"
                        "格式：\n1. translation1\n2. translation2\n\n"
                        f"关键词：\n{kw_list}"
                    ),
                }
            ],
            temperature=0.1,
        )
        lines = resp.choices[0].message.content.strip().split('\n')
        translated_count = 0
        for line in lines:
            line = line.strip()
            m = re.match(r'^(\d+)\.\s*(.+)$', line)
            if m:
                local_idx = int(m.group(1)) - 1
                if local_idx < len(need_translate):
                    result[need_translate[local_idx][0]] = m.group(2).strip()
                    translated_count += 1

        # 翻译失败的回退为原始词
        for i, kw in need_translate:
            if result[i] is None:
                result[i] = kw
                print(f"    ⚠️ 关键词未翻译，使用原文: {kw}")

        print(f"  🌐 已翻译 {translated_count} 个中文关键词为英文")
    except Exception as e:
        print(f"  ⚠️ 关键词翻译失败，使用原始关键词: {e}")
        for i, kw in need_translate:
            result[i] = kw

    return result


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="图文+Remotion 自动视频生成系统")
    parser.add_argument(
        "--article-file",
        type=str,
        default=None,
        help="文章文件路径（提供则跳过交互，适合 CI 模式）"
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="话题要求（使用智能体生成文章，适合 CI 模式）"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="输出目录（默认使用 assets/ 下的时间戳子目录）"
    )
    parser.add_argument(
        "--skip-remotion",
        action="store_true",
        help="跳过 Remotion，所有镜头使用图片实现"
    )
    parser.add_argument(
        "--orientation",
        type=str,
        choices=["landscape", "portrait"],
        default=None,
        help="图片方向：landscape（横屏，默认）或 portrait（竖屏），覆盖配置文件"
    )
    parser.add_argument(
        "--no-subtitle",
        action="store_true",
        help="不添加字幕（默认每条 clip 都会烧录字幕）"
    )
    parser.add_argument(
        "--bgm",
        type=str,
        default=None,
        help="背景音乐文件路径（默认不添加 BGM，提供后将在拼接后混合）"
    )
    parser.add_argument(
        "--language",
        type=str,
        choices=["zh", "en"],
        default=None,
        help="文章语言：zh（中文，默认）或 en（英文），决定 TTS 音色选择"
    )
    parser.add_argument(
        "--rerender-clips",
        type=str,
        default=None,
        help="重新渲染指定场景的片段并重新拼接，如 --rerender-clips 3,7,12 或 --rerender-clips 3-7"
    )
    parser.add_argument(
        "--rerender-image",
        action="append",
        default=None,
        help="替换指定场景的素材图片，格式 scene_id:path，可重复。如 --rerender-image 5:/path/img.jpg"
    )
    parser.add_argument(
        "--rerender-type",
        action="append",
        default=None,
        help="修改指定场景的视觉类型，格式 scene_id:type，可重复。如 --rerender-type 8:data_visual"
    )
    # CI / 平台集成参数
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="任务ID（CI 模式，用于回调和 R2 存储路径）"
    )
    parser.add_argument(
        "--article-source",
        type=str,
        choices=["ai_generated", "pasted", "uploaded"],
        default=None,
        help="文章来源：ai_generated / pasted / uploaded"
    )
    parser.add_argument(
        "--start-phase",
        type=str,
        choices=["SCENE_GEN", "ASSET_MATCH", "REMOTION_RENDER", "TTS_COMPOSE"],
        default=None,
        help="起始阶段（CI 模式，控制从哪个环节开始执行）"
    )
    parser.add_argument(
        "--end-phase",
        type=str,
        choices=["SCENE_GEN", "ASSET_MATCH", "REMOTION_RENDER", "TTS_COMPOSE"],
        default=None,
        help="结束阶段（CI 模式，控制执行到哪个环节）"
    )
    parser.add_argument(
        "--callback-url",
        type=str,
        default=None,
        help="回调通知地址（CI 模式，阶段进度/完成/失败时 POST 通知）"
    )
    parser.add_argument(
        "--callback-secret",
        type=str,
        default=None,
        help="回调签名密钥（与后端 CALLBACK_SECRET 一致，用于 HMAC-SHA256 签名）"
    )
    parser.add_argument(
        "--r2-prefix",
        type=str,
        default=None,
        help="R2 存储前缀（CI 模式，中间产物和最终视频的 R2 路径前缀）"
    )
    parser.add_argument(
        "--r2-bucket",
        type=str,
        default=None,
        help="R2 桶名称（CI 模式，上传中间产物时使用）"
    )
    parser.add_argument(
        "--r2-access-key-id",
        type=str,
        default=None,
        help="R2 Access Key ID"
    )
    parser.add_argument(
        "--r2-secret-access-key",
        type=str,
        default=None,
        help="R2 Secret Access Key"
    )
    parser.add_argument(
        "--r2-endpoint",
        type=str,
        default=None,
        help="R2 Endpoint URL"
    )
    return parser.parse_args()


def setup_environment(config: dict, render_params: dict) -> tuple:
    """初始化环境：配置 ImageMagick、创建工作目录

    Args:
        config: 全局配置
        render_params: 渲染参数

    Returns:
        (work_dir, temp_dir)
    """
    # 配置 ImageMagick（TextClip 依赖）
    img_magick = config.get("imagemagick_path", "")
    if img_magick:
        from moviepy.config import change_settings
        change_settings({"IMAGEMAGICK_BINARY": img_magick})

    # 创建工作目录
    if not args.output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        assets_dir = config.get("assets_dir", "assets")
        work_dir = Path(assets_dir) / timestamp
    else:
        work_dir = Path(args.output_dir)

    work_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = work_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    return work_dir, temp_dir


# ── CI 回调与 R2 上传 ──────────────────────────────────────────────────

_PHASE_ORDER = ["SCENE_GEN", "ASSET_MATCH", "REMOTION_RENDER", "TTS_COMPOSE"]


def get_phase_range(start_phase: str | None, end_phase: str | None) -> tuple[int, int]:
    """返回 (start_idx, end_idx)，覆盖从 SCENE_GEN 到 TTS_COMPOSE"""
    start = _PHASE_ORDER.index(start_phase) if start_phase and start_phase in _PHASE_ORDER else 0
    end = _PHASE_ORDER.index(end_phase) if end_phase and end_phase in _PHASE_ORDER else 3
    if end < start:
        end = start
    return start, end


def send_callback(
    payload: dict,
    callback_url: str | None,
    callback_secret: str | None,
) -> bool:
    """向后端发送 HMAC-SHA256 签名的回调通知

    Args:
        payload: 回调数据（task_id、phase、status 等）
        callback_url: 后端回调地址
        callback_secret: HMAC 签名密钥

    Returns:
        是否成功发送
    """
    if not callback_url or not callback_secret:
        return False

    try:
        import hmac
        import hashlib
        import urllib.request

        body = json.dumps(payload, ensure_ascii=False)
        body_bytes = body.encode("utf-8")

        signature = hmac.new(
            callback_secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).digest()
        signature_b64 = base64.b64encode(signature).decode("ascii")

        req = urllib.request.Request(
            callback_url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Callback-Signature": signature_b64,
                # Cloudflare blocks the default urllib User-Agent (Error 1010)
                "User-Agent": "pexel-remotion-pipeline/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                print(f"  📡 回调已发送: {body}")
                return True
            else:
                print(f"  ⚠️ 回调非2xx响应: {resp.status}")
                return False
    except Exception as e:
        print(f"  ⚠️ 回调发送失败: {e}")
        return False


def upload_to_r2(
    local_path: str,
    r2_key: str,
    r2_bucket: str | None,
    r2_access_key_id: str | None,
    r2_secret_access_key: str | None,
    r2_endpoint: str | None,
) -> bool:
    """将本地文件上传到 R2（使用 wrangler CLI）

    Args:
        local_path: 本地文件路径
        r2_key: R2 对象键
        r2_bucket: R2 桶名
        r2_access_key_id: Access Key ID
        r2_secret_access_key: Secret Access Key
        r2_endpoint: R2 Endpoint URL

    Returns:
        是否成功
    """
    if not (r2_bucket and r2_access_key_id and r2_secret_access_key and r2_endpoint):
        print(f"  ⚠️ R2 配置不完整，跳过上传: {local_path}")
        return False

    if not os.path.exists(local_path):
        print(f"  ⚠️ 文件不存在，跳过上传: {local_path}")
        return False

    try:
        # 使用 wrangler CLI 上传到 R2（wrangler 4 语法：对象路径用位置参数）
        result = subprocess.run(
            ["npx", "--yes", "wrangler", "r2", "object", "put",
             f"{r2_bucket}/{r2_key}",
             "--file", local_path,
             "--remote"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print(f"  📤 R2 上传成功: {r2_key}")
            return True
        else:
            print(f"  ⚠️ wrangler r2 put 失败: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"  ⚠️ wrangler CLI 不可用，跳过 R2 上传: {local_path}")
        return False
    except Exception as e:
        print(f"  ⚠️ R2 上传失败 {r2_key}: {e}")
        return False


def save_phase_artifact(
    artifact_path: str,
    task_id: str | None,
    r2_prefix: str | None,
    r2_config: dict | None,
) -> bool:
    """保存阶段产物到 R2（如果配置了 R2）"""
    if not task_id or not r2_prefix or not r2_config:
        return False

    if not os.path.exists(artifact_path):
        return False

    filename = os.path.basename(artifact_path)
    r2_key = f"{r2_prefix}/{filename}"
    return upload_to_r2(
        artifact_path, r2_key,
        r2_config.get("bucket"),
        r2_config.get("access_key_id"),
        r2_config.get("secret_access_key"),
        r2_config.get("endpoint"),
    )


def load_phase_artifact(
    artifact_name: str,
    work_dir: Path,
    task_id: str | None,
    r2_prefix: str | None,
    r2_config: dict | None,
) -> Path | None:
    """加载阶段产物：优先从本地 work_dir 读取，如果不存在则从 R2 下载

    Args:
        artifact_name: 产物文件名（如 scenes.json）
        work_dir: 本地工作目录
        task_id: 任务ID
        r2_prefix: R2 前缀
        r2_config: R2 配置

    Returns:
        本地文件路径，或 None（如果无法获取）
    """
    local_path = work_dir / artifact_name
    if local_path.exists():
        return local_path

    # 尝试从 R2 下载
    if task_id and r2_prefix and r2_config:
        try:
            r2_key = f"{r2_prefix}/{artifact_name}"
            import urllib.request

            endpoint = r2_config["endpoint"].rstrip("/")
            bucket = r2_config["bucket"]
            access_key = r2_config["access_key_id"]
            secret_key = r2_config["secret_access_key"]

            # 使用 wrangler CLI 下载（wrangler 4 语法：对象路径用位置参数）
            result = subprocess.run(
                ["npx", "--yes", "wrangler", "r2", "object", "get",
                 f"{bucket}/{r2_key}",
                 "--file", str(local_path),
                 "--remote"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and local_path.exists():
                print(f"  📥 从 R2 下载产物: {r2_key}")
                return local_path
            else:
                print(f"  ⚠️ R2 下载失败: {r2_key} - {result.stderr}")
        except Exception as e:
            print(f"  ⚠️ R2 下载异常: {e}")

    return None


def download_clips_from_r2(
    work_dir: Path,
    task_id: str | None,
    r2_prefix: str | None,
    r2_config: dict | None,
) -> int:
    """从 R2 下载已有的 final_clip 片段到工作目录，用于片段缓存复用

    在重渲染或从后续阶段开始执行时，将之前生成的片段从 R2 下载到本地，
    避免重复渲染未改变的片段。

    Args:
        work_dir: 本地工作目录
        task_id: 任务ID
        r2_prefix: R2 前缀
        r2_config: R2 配置

    Returns:
        成功下载的片段数量
    """
    if not task_id or not r2_prefix or not r2_config:
        return 0

    try:
        # 列出 R2 下所有 final_clip_*.mp4 文件
        endpoint = r2_config["endpoint"].rstrip("/")
        bucket = r2_config["bucket"]
        access_key = r2_config["access_key_id"]
        secret_key = r2_config["secret_access_key"]

        downloaded = 0
        cursor: str | None = None

        while True:
            options = {"prefix": f"{r2_prefix}/final_clip_", "limit": 1000}
            if cursor:
                options["cursor"] = cursor

            import urllib.request
            import json as _json

            # 使用 AWS Signature V4 签名请求 R2（兼容 S3 API）
            # 简化方案：使用 wrangler CLI 列出对象
            list_cmd = [
                "npx", "--yes", "wrangler", "r2", "object", "list",
                f"{bucket}/{r2_prefix}/",
                "--remote",
            ]
            result = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                print(f"  ⚠️ R2 列出对象失败: {result.stderr}")
                return 0

            # wrangler r2 object list 输出为 JSON
            try:
                objects = _json.loads(result.stdout)
                if not isinstance(objects, list):
                    return 0
            except (json.JSONDecodeError, ValueError):
                return 0

            clip_files = [
                obj for obj in objects
                if isinstance(obj, dict) and obj.get("key", "").endswith(".mp4")
                and "final_clip_" in obj.get("key", "")
            ]

            for obj in clip_files:
                clip_key = obj["key"]
                local_path = work_dir / os.path.basename(clip_key)

                if local_path.exists():
                    continue  # 已存在，跳过

                download_cmd = [
                    "npx", "--yes", "wrangler", "r2", "object", "get",
                    f"{bucket}/{clip_key}",
                    "--file", str(local_path),
                    "--remote",
                ]
                dl_result = subprocess.run(
                    download_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if dl_result.returncode == 0 and local_path.exists():
                    downloaded += 1
                    print(f"  📥 下载缓存片段: {os.path.basename(clip_key)}")
                else:
                    print(f"  ⚠️ 下载缓存片段失败: {clip_key} - {dl_result.stderr}")

            break  # wrangler list 不支持分页游标，一次性获取

        return downloaded
    except Exception as e:
        print(f"  ⚠️ 下载缓存片段异常: {e}")
        return 0


def save_clip_to_r2(
    clip_path: str,
    r2_key: str,
    r2_config: dict | None,
) -> bool:
    """将单个视频片段上传到 R2，供后续重渲染或阶段执行时缓存复用

    Args:
        clip_path: 本地片段路径
        r2_key: R2 对象键
        r2_config: R2 配置

    Returns:
        是否成功
    """
    if not r2_config:
        return False

    if not os.path.exists(clip_path):
        return False

    return upload_to_r2(
        clip_path, r2_key,
        r2_config["bucket"],
        r2_config["access_key_id"],
        r2_config["secret_access_key"],
        r2_config["endpoint"],
    )


def get_article(client, config: dict, model: str) -> str:
    """获取文章，根据参数选择方式

    Args:
        client: 智谱AI客户端
        config: 全局配置
        model: 模型名称

    Returns:
        文章内容
    """
    if args.article_file:
        print(f"📖 从文件读取文章: {args.article_file}")
        return get_article_from_file(args.article_file)
    elif args.topic:
        print(f"📖 智能体生成文章，话题: {args.topic}")
        return get_article_from_ai(client, args.topic, model)
    else:
        print("📖 启动交互式文章输入...")
        return select_and_get_article(client, model)


def download_and_match(scenes: list, zhipu_client, config: dict, temp_dir: Path, work_dir: Path, agnes_client=None, model: str = "agnes-3.0-flash", progress_cb=None) -> dict:
    """环节3：为每个镜头下载候选图片并做匹配分析

    Args:
        scenes: 镜头列表
        zhipu_client: 智谱AI客户端（多模态评审用）
        config: 全局配置
        temp_dir: 临时目录
        work_dir: 工作目录
        agnes_client: Agnes客户端（用于中文关键词翻译为英文）
        model: Agnes模型名称
        progress_cb: 进度回调函数，签名 (phase, message, processed, total)

    Returns:
        {scene_id: [{"path":..., "score":...}, ...]}
    """
    # 初始化 CLIP 匹配器（延迟导入，torch 未安装时优雅降级）
    clip_model_name = config.get("clip_model", "openai/clip-vit-base-patch32")
    clip_matcher = None
    try:
        from core.asset_matcher.clip_matcher import CLIPMatcher
        clip_matcher = CLIPMatcher(model_name=clip_model_name)
    except Exception as e:
        print(f"⚠️ CLIP 模型加载失败: {e}")
        print("   将跳过相似度匹配，使用下载的第一张图片")

    # 初始化多模态精评器（如果可用）
    reviewer = None
    if zhipu_client is not None and not args.skip_remotion:
        try:
            multimodal_model = config.get("multimodal_model_name", "glm-4.1v-thinking-flash")
            multimodal_concurrency = config.get("multimodal_concurrency", 5)
            reviewer = MultimodalReviewer(zhipu_client, model=multimodal_model, concurrency=multimodal_concurrency)
            print(f"✅ 多模态精评器已就绪（模型: {multimodal_model}, 并发: {multimodal_concurrency}）")
        except Exception as e:
            print(f"⚠️ 多模态精评器不可用: {e}")
    elif args.skip_remotion:
        print("⏭️ 已跳过多模态精评")

    max_images = config.get("max_download_images", 5)
    chromedriver_path = config.get("chromedriver_path", "")

    # 图片方向：CLI 参数优先，其次配置文件，默认横屏
    image_orientation = args.orientation or config.get("image_orientation", "landscape")
    print(f"📐 图片方向: {image_orientation}（每镜头下载 {max_images} 张）")

    match_results = {}

    # 创建共享 Pexels 会话，所有镜头复用（避免每镜头新建 Chrome 的开销）
    # 会话被反爬拦截时会自动重建 Chrome
    session = PexelsSession(
        chromedriver_path if chromedriver_path else None,
        page_load_timeout=30,
    )
    try:
        session.driver
        print(f"✅ Selenium 会话已创建，所有镜头共享")
    except Exception as e:
        print(f"⚠️ Selenium 会话创建失败，将在首次搜索时重试: {e}")

    try:
        for scene in scenes:
            print(f"\n  ── 镜头 {scene.scene_id} ──")
            print(f"  描述: {scene.visual_description}")

            # 下载候选图片（复用共享会话）
            image_dir = temp_dir / f"scene_{scene.scene_id}"
            image_dir.mkdir(parents=True, exist_ok=True)

            # 下载候选图片前，将中文关键词翻译为英文（Pexels 英文搜索效果更好）
            search_kws = scene.search_keywords
            if agnes_client is not None and search_kws:
                search_kws = _translate_keywords(search_kws, agnes_client, model)

            image_paths = download_pexels_images(
                keywords=search_kws,
                output_dir=str(image_dir),
                max_count=max_images,
                driver_path=chromedriver_path if chromedriver_path else None,
                orientation=image_orientation,
                session=session,
                api_key=config.get("pexels_api_key")
            )

            if not image_paths:
                print(f"    ❌ 未下载到图片，跳过匹配")
                match_results[scene.scene_id] = []
                continue

            # CLIP 匹配
            if clip_matcher:
                matches = clip_matcher.match(scene.visual_description, image_paths)
                best = matches[0]
                print(f"    ✅ CLIP 最佳匹配: 分数 {best['score']:.3f}")

                # 多模态精评（对 CLIP 初筛前 3 张做精评）
                if reviewer and len(matches) > 1:
                    top_candidates = matches[:3]
                    top_paths = [m["path"] for m in top_candidates]
                    reviews = reviewer.review(scene.visual_description, top_paths)
                    if reviews:
                        best_reviewed = reviews[0]
                        print(f"    ✅ 多模态精评: 分数 {best_reviewed['score']}/100")
                        # 用精评结果替换 CLIP 结果
                        matches = reviews + matches[3:]
                        matches.sort(key=lambda x: x.get("score", 0), reverse=True)
            else:
                matches = [{"path": image_paths[0], "score": 0.0}]
                print(f"    ⚠️ 使用第一张图片（无 CLIP 匹配）")

            match_results[scene.scene_id] = matches

            # 报告逐镜头进度
            if progress_cb:
                progress_cb("ASSET_MATCH", f"镜头 {scene.scene_id} 素材匹配完成", scene.scene_id, len(scenes))

    finally:
        # 关闭共享 Selenium 会话
        try:
            session.close()
            print(f"\n✅ Selenium 会话已关闭")
        except Exception:
            pass

    return match_results


def _derive_headline(text: str, max_len: int = 16) -> str:
    """从解说文本中提取简短标题，用于 Remotion 画面展示

    解说文本通常是 30-60 字的完整句子，直接当大标题会严重溢出。
    这里取第一句、优先在标点处断开，控制在 max_len 字以内。

    Args:
        text: 解说文本（on_screen_text）
        max_len: 标题最大字数

    Returns:
        简短标题
    """
    import re
    text = (text or "").strip().strip('“”"「」\' ')
    if not text:
        return ""
    # 取第一句
    first = re.split(r'[。！？；!?;\n]', text)[0].strip()
    if not first:
        first = text
    if len(first) <= max_len:
        return first
    # 优先在逗号/顿号/冒号处断开
    for part in re.split(r'[，,、：:]', first):
        part = part.strip()
        if 0 < len(part) <= max_len:
            return part
    # 最后硬截断
    return first[:max_len] + "…"


def _derive_steps(text: str, max_steps: int = 4, max_len: int = 14) -> list:
    """从解说文本提取流程步骤，用于 DiagramScene

    按句号/逗号/顿号切分，保留长度合理的短句作为步骤。
    不足 2 条时返回空列表（模板将只显示标题卡片，避免占位假步骤）。

    Args:
        text: 解说文本
        max_steps: 最多步骤数
        max_len: 每步最大字数

    Returns:
        步骤字符串列表（可能为空）
    """
    import re
    text = (text or "").strip()
    if not text:
        return []
    chunks = re.split(r'[。！？；!?;\n，,、：:—]', text)
    steps = []
    # 标题由第一句派生，同一句不应再作为步骤重复出现
    headline = _derive_headline(text)
    for c in chunks:
        c = c.strip().strip('—-"“”')
        if 2 <= len(c) <= max_len and c != headline and c not in steps:
            steps.append(c)
        if len(steps) >= max_steps:
            break
    return steps if len(steps) >= 2 else []


def _derive_metrics(text: str, max_items: int = 4) -> list:
    """从解说文本提取数据指标（数字+单位），用于 DataVisualScene

    只提取「数字 + 可选单位」组成的指标，避免伪造柱状图比例。
    没有任何数字时返回空列表（模板将只显示标题卡片）。

    Args:
        text: 解说文本
        max_items: 最多指标数

    Returns:
        [{"value": "5572", "unit": "家"}, ...]
    """
    import re
    text = (text or "").strip()
    if not text:
        return []
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*(万亿|亿元|万元|亿|万|%|％|家|人|元|倍)?', text)
    metrics = []
    seen = set()
    for num, unit in matches:
        unit = unit.replace('％', '%')
        key = (num, unit)
        if key in seen:
            continue
        seen.add(key)
        metrics.append({"value": num, "unit": unit})
        if len(metrics) >= max_items:
            break
    # 只有一个指标时也展示（例如「净利润同比增长 8.5%」），
    # 空列表会让整个镜头退化成纯标题卡，信息量太低
    return metrics if len(metrics) >= 1 else []


def render_remotion_scene(scene, duration, output_path, config: dict, render_params: dict, background_image=None, seg_idx=0):
    """渲染 Remotion 编码视频片段

    通过 subprocess 调用 Node.js 渲染脚本，传入场景参数。
    渲染失败时返回 None，调用方使用图片兜底。

    Args:
        scene: 镜头对象
        duration: 片段时长
        output_path: 输出路径
        config: 全局配置
        render_params: 渲染参数
        background_image: 背景图片路径，提供给 Remotion 模板作为全屏背景，
            消除 Remotion 片段与图片片段的风格割裂
        seg_idx: 段序号（同场景拆分多段时区分临时文件名，默认 0）

    Returns:
        视频路径或 None（渲染失败时）
    """
    remotion_dir = Path(__file__).parent / "remotion"
    render_script = remotion_dir / "render.js"

    if not render_script.exists():
        print(f"    ⚠️ Remotion 渲染脚本不存在: {render_script}")
        return None

    # 段号后缀：同场景多段并行渲染时区分临时文件，避免互相覆盖/删除
    seg_suffix = f"_{seg_idx}" if seg_idx else ""

    # 将输出路径转为绝对路径，避免 Node.js 在 remotion/ 子目录中找不到文件
    output_path = str(Path(output_path).resolve())

    # 复制背景图片到 Remotion public 目录（staticFile 仅能访问 public/ 下的文件）
    bg_filename = None
    bg_public_path = None
    if background_image and os.path.exists(background_image):
        public_dir = remotion_dir / "public"
        public_dir.mkdir(parents=True, exist_ok=True)
        bg_filename = f"bg_{scene.scene_id}{seg_suffix}.jpg"
        bg_public_path = public_dir / bg_filename
        shutil.copy2(background_image, str(bg_public_path))

    # 构建 props.json —— 写入 remotion/ 目录内，传相对文件名给 render.js
    # Remotion CLI 会将 --props 路径相对于其 cwd（remotion/）解析，
    # 写在外部目录会导致路径多拼一层 remotion\ 前缀，ENOENT 失败
    # 从解说文本派生画面展示内容
    # - headline：简短标题（避免整段解说溢出）
    # - steps：流程图步骤（真实切分，非占位）
    # - metrics：数据指标（真实数字，非伪造柱状图）
    headline = _derive_headline(scene.on_screen_text) or " "
    steps = _derive_steps(scene.on_screen_text)
    metrics = _derive_metrics(scene.on_screen_text)

    props = {
        "text": headline,
        "steps": steps,
        "metrics": metrics,
        "duration": duration,
        "width": render_params["resolution_width"],
        "height": render_params["resolution_height"],
        "fps": render_params["fps"],
        "background_image": bg_filename,
    }

    props_path = remotion_dir / f"props_scene_{scene.scene_id}{seg_suffix}.json"
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False, indent=2)

    # 构建渲染命令 —— 传相对文件名，避免 Remotion CLI 路径解析问题
    cmd = [
        "node",
        str(render_script),
        "--scene", scene.visual_type,
        "--props", props_path.name,
        "--output", str(output_path),
    ]

    try:
        print(f"    🎬 渲染 Remotion: {scene.visual_type} ({duration:.1f}s)")
        if bg_filename:
            print(f"    🖼️ 背景图片: {bg_filename}")
        result = subprocess.run(
            cmd,
            cwd=str(remotion_dir),
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=300
        )

        if result.returncode == 0 and os.path.exists(output_path):
            print(f"    ✅ Remotion 渲染完成")
            return str(output_path)
        else:
            print(f"    ⚠️ Remotion 渲染失败: {result.stderr.strip()}")
            return None
    except subprocess.TimeoutExpired:
        print(f"    ⚠️ Remotion 渲染超时")
        return None
    except Exception as e:
        print(f"    ⚠️ Remotion 渲染异常: {e}")
        return None
    finally:
        # 清理 props 临时文件
        if props_path.exists():
            props_path.unlink()
        # 清理背景图片（public 目录中的临时文件）
        if bg_public_path and bg_public_path.exists():
            bg_public_path.unlink()


def _finalize_scene_clip(scene, clip_path, final_clip_path,
                          audio_segment_path, subtitle_text, crf,
                          enable_subtitle=True):
    """最终化单个片段：烧字幕 + 加音频，失败时逐级兜底

    三级兜底策略：
    1. 有音频段：finalize_clip（烧字幕+加音频，或仅加音频）
    2. 音频失败：add_silent_audio（加静音音轨，保证流拷贝音频参数一致）
    3. 都失败：复制原始片段（无音频，最后兜底）

    Args:
        scene: 镜头对象
        clip_path: 渲染好的纯视频片段路径
        final_clip_path: 最终化片段输出路径
        audio_segment_path: 音频段路径（None 表示无音频）
        subtitle_text: 字幕文本
        crf: 编码质量
        enable_subtitle: 是否烧录字幕（默认 True）

    Returns:
        (scene, final_clip_path) 或 None（clip_path 不存在时）
    """
    if not os.path.exists(clip_path):
        return None

    # 1. 有音频段：烧字幕 + 加音频（或仅加音频）
    if audio_segment_path and os.path.exists(audio_segment_path):
        try:
            finalize_clip(str(clip_path), audio_segment_path, subtitle_text,
                          str(final_clip_path), crf, enable_subtitle=enable_subtitle)
            if enable_subtitle:
                print(f"    ✅ 字幕+音频已烧录")
            else:
                print(f"    ✅ 音频已合并（字幕已禁用）")
            return scene, str(final_clip_path)
        except Exception as e:
            print(f"    ⚠️ 字幕+音频烧录失败，尝试静音音轨兜底: {e}")

    # 2. 兜底：加静音音轨（保证流拷贝拼接的音频参数一致）
    try:
        add_silent_audio(str(clip_path), str(final_clip_path), crf)
        print(f"    ⚠️ 已添加静音音轨（无字幕）")
        return scene, str(final_clip_path)
    except Exception as e:
        print(f"    ❌ 静音音轨添加失败: {e}")

    # 3. 最后兜底：复制原始片段（无音频）
    try:
        shutil.copy2(str(clip_path), str(final_clip_path))
        print(f"    ⚠️ 使用原始片段（无音频无字幕）")
        return scene, str(final_clip_path)
    except Exception as e:
        print(f"    ❌ 片段复制失败: {e}")
        return None


def _render_single_scene(
    scene, decision, match_results,
    config, render_params, work_dir,
    resolution, fps, codec, audio_codec, preset, threads,
    skip_remotion,
    audio_segment_path=None, subtitle_text="",
    enable_subtitle=True,
    seg_idx=0,
    seg_duration=0
):
    """渲染单个场景的视频片段（含 Remotion、图片兜底、字幕+音频最终化）

    供并行渲染调用，封装了 Remotion 渲染、图片 Ken Burns 兜底、
    以及字幕烧录+音频合并的完整逻辑。

    一个场景可能因语音超长被拆成多段（seg_idx > 0），此时 clip 文件名
    带段号后缀，视频时长用该段自身时长（seg_duration），避免各段都按
    全长渲染导致音画不匹配。

    Args:
        scene: 镜头对象
        decision: 决策对象
        match_results: 匹配结果
        config: 全局配置
        render_params: 渲染参数
        work_dir: 工作目录
        resolution: 分辨率
        fps: 帧率
        codec: 编码器
        audio_codec: 音频编码器
        preset: 编码预设
        threads: 编码线程数
        skip_remotion: 是否跳过 Remotion
        audio_segment_path: 该段对应的音频段路径（用于最终化）
        subtitle_text: 该段的字幕文本（用于最终化）
        enable_subtitle: 是否烧录字幕（默认 True，设为 False 则仅合并音频）
        seg_idx: 段序号（同一场景拆分多段时区分，默认 0）
        seg_duration: 该段视频时长（秒，<=0 时回退到 scene.duration）

    Returns:
        (scene, final_clip_path) 或 None（渲染失败时）
    """
    seg_suffix = f"_{seg_idx}" if seg_idx else ""
    clip_path = work_dir / f"clip_{scene.scene_id}{seg_suffix}.mp4"
    final_clip_path = work_dir / f"final_clip_{scene.scene_id}{seg_suffix}.mp4"
    crf = render_params.get("crf", 18)
    # 段时长：拆分场景用段自身时长，非拆分或合成失败时回退到场景总时长
    if seg_duration <= 0:
        seg_duration = scene.duration

    # 片段缓存：如果最终片段已存在（从之前的渲染或 R2 下载），直接复用
    # 避免重复渲染未改变的场景，节省时间和 API 调用
    if final_clip_path.exists() and final_clip_path.stat().st_size > 0:
        print(f"  ♻️ 镜头 {scene.scene_id} 段{seg_idx}: 复用已缓存片段")
        return scene, str(final_clip_path)

    # 选取背景图片：优先用决策的 asset_path，回退到匹配结果第一张
    # Remotion 片段将以此照片为背景，消除与图片片段的风格割裂
    bg_image = decision.asset_path
    if not bg_image:
        matches = match_results.get(scene.scene_id, [])
        if matches:
            bg_image = matches[0]["path"]

    # Remotion 渲染
    if decision.implementation == "remotion" and not skip_remotion:
        result = render_remotion_scene(
            scene, seg_duration, str(clip_path), config, render_params,
            background_image=bg_image, seg_idx=seg_idx
        )
        if result:
            return _finalize_scene_clip(
                scene, clip_path, final_clip_path,
                audio_segment_path, subtitle_text, crf,
                enable_subtitle
            )

    # 图片 + Ken Burns 动效（Remotion 兜底 / 图片场景正常处理）
    asset_path = decision.asset_path
    if not asset_path:
        matches = match_results.get(scene.scene_id, [])
        if matches:
            asset_path = matches[0]["path"]

    if asset_path:
        try:
            image_to_clip(
                image_path=asset_path,
                duration=seg_duration,
                output_path=str(clip_path),
                scene_id=scene.scene_id,
                visual_type=scene.visual_type,
                resolution=resolution,
                fps=fps,
                codec=codec,
                audio_codec=audio_codec,
                preset=preset,
                threads=threads
            )
            return _finalize_scene_clip(
                scene, clip_path, final_clip_path,
                audio_segment_path, subtitle_text, crf,
                enable_subtitle
            )
        except Exception as e:
            print(f"  ❌ 镜头 {scene.scene_id}: 图片片段生成失败: {e}")

    # 兜底1：无素材时用 Remotion 文字卡，保证解说和字幕不断档
    if not skip_remotion:
        print(f"  ⚠️ 镜头 {scene.scene_id}: 无可用素材，改用文字卡兜底")
        result = render_remotion_scene(
            scene, seg_duration, str(clip_path), config, render_params,
            background_image=None, seg_idx=seg_idx
        )
        if result:
            return _finalize_scene_clip(
                scene, clip_path, final_clip_path,
                audio_segment_path, subtitle_text, crf,
                enable_subtitle
            )

    # 兜底2：纯色底图（走与图片片段完全相同的编码路径，保证拼接参数一致）
    try:
        from PIL import Image
        color_png = work_dir / f"color_{scene.scene_id}.png"
        Image.new("RGB", tuple(resolution), (18, 20, 38)).save(str(color_png))
        image_to_clip(
            image_path=str(color_png),
            duration=seg_duration,
            output_path=str(clip_path),
            scene_id=scene.scene_id,
            visual_type=scene.visual_type,
            resolution=resolution,
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            preset=preset,
            threads=threads
        )
        color_png.unlink(missing_ok=True)
        return _finalize_scene_clip(
            scene, clip_path, final_clip_path,
            audio_segment_path, subtitle_text, crf,
            enable_subtitle
        )
    except Exception as e:
        print(f"  ❌ 镜头 {scene.scene_id}: 纯色兜底也失败了: {e}")

    return None


def _split_text_balanced(text: str) -> list:
    """把文本在标点处拆成两段，尽量均匀

    用于 TTS 音频超过时长上限时拆分场景，保证每段语音完整不截断。
    优先在中文标点（。！？；，、）处断开，避免在词中硬拆。

    Args:
        text: 要拆分的文本

    Returns:
        两段文本的列表；拆不开时返回原文本单段
    """
    if len(text) < 16:
        return [text]

    target = len(text) // 2
    # 标点优先级（强标点处断开更自然）
    punct_order = ["。", "！", "？", "；", "，", "、"]
    best_pos = -1
    best_dist = float("inf")
    best_priority = len(punct_order)
    for priority, ch in enumerate(punct_order):
        pos = text.find(ch)
        while pos != -1:
            dist = abs(pos - target)
            if dist < best_dist or (dist == best_dist and priority < best_priority):
                best_dist = dist
                best_pos = pos
                best_priority = priority
            pos = text.find(ch, pos + 1)

    if 0 < best_pos < len(text) - 1:
        return [text[:best_pos + 1], text[best_pos + 1:]]

    # 没有合适标点，按字符数硬拆
    mid = len(text) // 2
    return [text[:mid], text[mid:]]


def _tts_split(text, tag, work_dir, max_duration, language, depth=0):
    """递归 TTS：文本超长时在标点处拆分，保证每段音频 ≤ 上限

    先对整段文本合成语音并测时长，超限则在标点处拆成两段分别合成，
    递归处理直到每段音频 ≤ max_duration。这样每段的语音都完整，
    不会被时长上限截断。

    正常流程和重渲染流程共用此函数，保证拆分逻辑一致。

    Args:
        text: 要合成的文本
        tag: 文件名标识（scene_id，拆分后追加后缀）
        work_dir: 工作目录（音频文件保存于此）
        max_duration: 单段音频时长上限（秒）
        language: 文章语言，"zh" 或 "en"，决定 TTS 音色
        depth: 递归深度（防无限拆分）

    Returns:
        [(seg_path, dur, text), ...]
    """
    seg_path = str(work_dir / f"audio_seg_{tag}_{depth}.mp3")
    dur = synthesize_speech(text, seg_path, language=language)
    if dur <= max_duration:
        return [(seg_path, dur, text)]
    # 超长：尝试拆分
    if depth >= 3 or len(text) < 16:
        print(f"  ⏱️ {tag} 语音 {dur:.1f}s 超 {max_duration:.0f}s，"
              f"文本无法再拆分，截断至上限")
        return [(seg_path, dur, text)]
    parts = _split_text_balanced(text)
    if len(parts) <= 1:
        print(f"  ⏱️ {tag} 语音 {dur:.1f}s 超限，文本无法再拆分，截断至上限")
        return [(seg_path, dur, text)]
    # 拆分后删除原始超长音频，改用拆分段
    try:
        os.unlink(seg_path)
    except OSError:
        pass
    segments = []
    for i, part in enumerate(parts):
        segments.extend(_tts_split(part, f"{tag}_{i}", work_dir, max_duration,
                                   language, depth + 1))
    return segments


def _tts_one(scene, work_dir, max_duration, language):
    """为单个场景合成语音，超长时自动拆分

    返回 (scene, segments)，segments 为 [(seg_path, dur, text), ...]。
    正常流程和重渲染流程共用此函数。

    Args:
        scene: 镜头对象
        work_dir: 工作目录
        max_duration: 单段音频时长上限（秒）
        language: 文章语言

    Returns:
        (scene, [(seg_path, dur, text), ...])
    """
    text = scene.on_screen_text or ""
    segments = _tts_split(text, scene.scene_id, work_dir, max_duration, language)
    total_dur = sum(d for _, d, _ in segments)
    if total_dur <= 0:
        # 合成失败：按字数估算时长，片段走静音音轨兜底
        total_dur = max(2.0, min(max_duration, len(text) / 5.2))
    scene.duration = total_dur
    return scene, segments


def _parse_scene_ids(spec: str) -> set:
    """解析场景 ID 列表，支持逗号分隔和范围

    Args:
        spec: 场景 ID 字符串，如 "3,7,12" 或 "3-7" 或 "3,5-8,12"

    Returns:
        场景 ID 集合
    """
    ids = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            start_id = int(start.strip())
            end_id = int(end.strip())
            ids.update(range(start_id, end_id + 1))
        else:
            ids.add(int(part))
    return ids


def _collect_final_clips(work_dir) -> list:
    """收集所有 final_clip 文件，按 (scene_id, seg_idx) 排序

    用于重渲染后重新拼接全部片段。文件命名规则：
    - final_clip_{scene_id}.mp4        （单段场景，seg_idx=0）
    - final_clip_{scene_id}_{seg}.mp4  （多段场景，seg_idx>0）

    Args:
        work_dir: 工作目录

    Returns:
        按场景顺序、段顺序排列的 clip 路径列表
    """
    clips = []
    for f in work_dir.glob("final_clip_*.mp4"):
        name = f.name
        base = name[len("final_clip_"):-len(".mp4")]
        if "_" in base:
            scene_str, seg_str = base.rsplit("_", 1)
            if seg_str.isdigit():
                scene_id = int(scene_str)
                seg_idx = int(seg_str)
                clips.append((scene_id, seg_idx, str(f)))
                continue
        # 无段号后缀，seg_idx=0
        try:
            scene_id = int(base)
            clips.append((scene_id, 0, str(f)))
        except ValueError:
            continue

    clips.sort(key=lambda x: (x[0], x[1]))
    return [c[2] for c in clips]


def rerender_clips(work_dir, config: dict, render_params: dict, args) -> str:
    """重新渲染指定场景的片段并重新拼接

    从已有工作目录加载中间产物（scenes.json / decisions.json / match_results.json），
    对用户指定的场景重新 TTS + 渲染，其他场景保持原样，最后重新拼接全部片段。

    支持两种使用方式：
    1. 仅重渲染（不换素材）：--rerender-clips 3,7,12
    2. 重渲染 + 修改素材：--rerender-clips 5 --rerender-image 5:/path/img.jpg
       或修改视觉类型：--rerender-clips 8 --rerender-type 8:data_visual

    Args:
        work_dir: 已有工作目录（含 scenes.json / decisions.json / match_results.json）
        config: 全局配置
        render_params: 渲染参数
        args: 命令行参数（rerender_clips / rerender_image / rerender_type / language 等）

    Returns:
        最终视频路径
    """
    work_dir = Path(work_dir)

    # 加载中间产物
    scenes_path = work_dir / "scenes.json"
    decisions_path = work_dir / "decisions.json"
    match_path = work_dir / "match_results.json"

    if not scenes_path.exists():
        print(f"❌ 未找到分镜文件: {scenes_path}")
        print(f"   请先运行完整管线生成中间产物，或用 --output-dir 指定正确的工作目录")
        raise FileNotFoundError(f"分镜文件不存在: {scenes_path}")

    # 解析 scenes.json → Scene 对象
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes_data = json.load(f)
    scenes = [Scene(**s) for s in scenes_data["scenes"]]

    # 解析 decisions.json → SceneDecision 对象
    with open(decisions_path, "r", encoding="utf-8") as f:
        decisions_data = json.load(f)
    decisions = [SceneDecision(**d) for d in decisions_data]

    # 解析 match_results.json
    with open(match_path, "r", encoding="utf-8") as f:
        match_results = json.load(f)

    # 从 R2 下载已有的缓存片段（非目标场景的片段），避免在 CI 中丢失
    if args.r2_bucket and args.r2_access_key_id and args.r2_secret_access_key and args.r2_endpoint and args.r2_prefix:
        r2_config = {
            "bucket": args.r2_bucket,
            "access_key_id": args.r2_access_key_id,
            "secret_access_key": args.r2_secret_access_key,
            "endpoint": args.r2_endpoint,
        }
        cached = download_clips_from_r2(work_dir, args.task_id, args.r2_prefix, r2_config)
        if cached > 0:
            print(f"📥 从 R2 下载 {cached} 个缓存片段（非目标场景将复用）")

    # 解析目标场景 ID
    target_ids = _parse_scene_ids(args.rerender_clips)
    print(f"🔁 重新渲染场景: {sorted(target_ids)}（共 {len(target_ids)} 个）")

    # 应用用户修改：替换素材图片
    if args.rerender_image:
        for spec in args.rerender_image:
            if ":" not in spec:
                print(f"  ⚠️ 忽略无效格式 --rerender-image {spec}（应为 scene_id:path）")
                continue
            scene_id_str, image_path = spec.split(":", 1)
            try:
                sid = int(scene_id_str)
            except ValueError:
                print(f"  ⚠️ 忽略无效场景 ID: {scene_id_str}")
                continue
            for dec in decisions:
                if dec.scene_id == sid:
                    dec.asset_path = image_path
                    print(f"  🖼️ 场景 {sid}: 素材替换为 {image_path}")
                    break
            else:
                print(f"  ⚠️ 未找到场景 {sid}，跳过图片替换")

    # 应用用户修改：修改视觉类型
    if args.rerender_type:
        for spec in args.rerender_type:
            if ":" not in spec:
                print(f"  ⚠️ 忽略无效格式 --rerender-type {spec}（应为 scene_id:type）")
                continue
            scene_id_str, visual_type = spec.split(":", 1)
            try:
                sid = int(scene_id_str)
            except ValueError:
                print(f"  ⚠️ 忽略无效场景 ID: {scene_id_str}")
                continue
            for scene in scenes:
                if scene.scene_id == sid:
                    old_type = scene.visual_type
                    scene.visual_type = visual_type
                    print(f"  🎨 场景 {sid}: 视觉类型 {old_type} → {visual_type}")
                    break
            else:
                print(f"  ⚠️ 未找到场景 {sid}，跳过类型修改")

    # 筛选目标场景和决策
    target_scenes = [s for s in scenes if s.scene_id in target_ids]
    target_decisions = [d for d in decisions if d.scene_id in target_ids]

    if not target_scenes:
        print(f"❌ 目标场景均不在分镜范围内（共 {len(scenes)} 个场景）")
        raise ValueError(f"目标场景无效: {sorted(target_ids)}")

    # 删除目标场景的旧片段（避免拆分段数变化时旧文件残留）
    print("\n🧹 清理目标场景的旧片段...")
    for scene_id in target_ids:
        # 精确匹配：final_clip_{scene_id}.mp4（单段）和 final_clip_{scene_id}_*.mp4（多段）
        # 不能用 final_clip_{scene_id}*.mp4 —— 否则 scene_id=3 会误匹配 scene 30-39
        old_clips = list(work_dir.glob(f"final_clip_{scene_id}.mp4"))
        old_clips += list(work_dir.glob(f"final_clip_{scene_id}_*.mp4"))
        for old in old_clips:
            old.unlink()
            print(f"  🗑️ 删除旧片段: {old.name}")

    # 重新 TTS 目标场景
    language = args.language or config.get("tts_language", "zh")
    MAX_SCENE_DURATION = 10.0
    print(f"\n🎙️ 重新合成语音（语言: {language}）...")
    audio_segments = {}
    for scene in target_scenes:
        segments = _tts_split(
            scene.on_screen_text, scene.scene_id,
            work_dir, MAX_SCENE_DURATION, language,
        )
        audio_segments[scene.scene_id] = segments
        total_dur = sum(d for _, d, _ in segments)
        scene.duration = total_dur
        seg_info = " + ".join(f"{d:.1f}s" for _, d, _ in segments)
        print(f"  ✅ 场景 {scene.scene_id}: {len(segments)} 段（{seg_info}）")

    # 渲染目标场景
    resolution = (render_params["resolution_width"], render_params["resolution_height"])
    fps = render_params["fps"]
    codec = render_params["codec"]
    audio_codec = render_params["audio_codec"]
    preset = render_params["preset"]
    threads = render_params["threads"]
    per_worker_threads = max(1, threads // 3)
    enable_subtitle = not args.no_subtitle

    print(f"\n🎬 重新渲染 {len(target_scenes)} 个场景...")
    results_by_scene = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for scene, decision in zip(target_scenes, target_decisions):
            segs = audio_segments.get(scene.scene_id, [])
            if not segs:
                future = pool.submit(
                    _render_single_scene,
                    scene, decision, match_results,
                    config, render_params, work_dir,
                    resolution, fps, codec, audio_codec, preset, per_worker_threads,
                    args.skip_remotion,
                    None, scene.on_screen_text or "",
                    enable_subtitle, 0, scene.duration,
                )
                futures[future] = (scene, 0)
            else:
                for seg_idx, (audio_seg, seg_dur, seg_subtitle) in enumerate(segs):
                    future = pool.submit(
                        _render_single_scene,
                        scene, decision, match_results,
                        config, render_params, work_dir,
                        resolution, fps, codec, audio_codec, preset, per_worker_threads,
                        args.skip_remotion,
                        audio_seg, seg_subtitle,
                        enable_subtitle, seg_idx, seg_dur,
                    )
                    futures[future] = (scene, seg_idx)

        for future in as_completed(futures):
            scene, seg_idx = futures[future]
            try:
                result = future.result()
                if result:
                    rendered_scene, clip_path = result
                    results_by_scene[(scene.scene_id, seg_idx)] = (rendered_scene, clip_path)
            except Exception as e:
                print(f"  ❌ 场景 {scene.scene_id} 段{seg_idx}: 渲染失败: {e}")

    # 报告渲染结果
    success_count = len(results_by_scene)
    expected_count = sum(
        len(audio_segments.get(s.scene_id, [])) if audio_segments.get(s.scene_id) else 1
        for s in target_scenes
    )
    if success_count < expected_count:
        print(f"  ⚠️ 渲染完成 {success_count}/{expected_count} 段，部分片段可能未更新")
    else:
        print(f"  ✅ 全部 {success_count} 段渲染完成")

    # 将新渲染的片段上传到 R2 供后续缓存复用
    if args.r2_bucket and args.r2_access_key_id and args.r2_secret_access_key and args.r2_endpoint and args.r2_prefix:
        r2_config = {
            "bucket": args.r2_bucket,
            "access_key_id": args.r2_access_key_id,
            "secret_access_key": args.r2_secret_access_key,
            "endpoint": args.r2_endpoint,
        }
        for (scene_id, seg_idx), (_, clip_path) in results_by_scene.items():
            if clip_path and os.path.exists(clip_path):
                r2_clip_key = f"{args.r2_prefix}/{os.path.basename(clip_path)}"
                save_clip_to_r2(clip_path, r2_clip_key, r2_config)

    # 清理音频段临时文件
    for segments in audio_segments.values():
        for seg_path, _, _ in segments:
            if os.path.exists(seg_path):
                os.unlink(seg_path)

    # 重新拼接：收集所有 final_clip（含未重渲染的旧片段 + 新渲染的片段）
    print(f"\n📋 重新拼接最终视频...")
    clip_paths = _collect_final_clips(work_dir)

    if not clip_paths:
        print("❌ 没有可用的视频片段，无法拼接")
        raise RuntimeError("没有可用的视频片段")

    final_output = work_dir / "final_output.mp4"
    merge_clips(clip_paths, str(final_output))
    print(f"  ✅ 拼接完成（{len(clip_paths)} 个片段）")

    return str(final_output)


def compose_video(
    scenes: list,
    decisions: list,
    match_results: dict,
    config: dict,
    render_params: dict,
    work_dir: Path,
    progress_cb=None,
    r2_prefix: str | None = None,
    r2_config: dict | None = None,
    task_id: str | None = None,
) -> str:
    """环节6：合成最终视频

    Args:
        scenes: 镜头列表（duration 由逐镜头语音时长决定）
        decisions: 镜头决策列表
        match_results: 匹配结果
        config: 全局配置
        render_params: 渲染参数
        work_dir: 工作目录
        progress_cb: 进度回调函数，签名 (phase, message, processed, total)
        r2_prefix: R2 前缀（用于保存片段到 R2 供缓存复用）
        r2_config: R2 配置
        task_id: 任务ID

    Returns:
        最终视频路径
    """
    resolution = (render_params["resolution_width"], render_params["resolution_height"])
    fps = render_params["fps"]
    codec = render_params["codec"]
    audio_codec = render_params["audio_codec"]
    preset = render_params["preset"]
    threads = render_params["threads"]
    crf = render_params["crf"]

    # 6a. 逐镜头语音合成（音画天然对齐）
    # 每个镜头只合成自己那段解说，镜头时长 = 实测语音时长（上限 10 秒）。
    # 不再「先合成全文、再按比例把总时长摊给各镜头」——那套做法一旦分镜
    # 没有覆盖全文（LLM 曾把 6210 字只切成 8 个镜头），就会丢掉绝大部分解说。
    print("\n🎙️ 逐镜头合成语音...")
    MAX_SCENE_DURATION = 10.0
    audio_segments = {}  # {scene_id: [(seg_path, dur, subtitle_text), ...]}

    if scenes:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_tts_one, s, work_dir, MAX_SCENE_DURATION, args.language)
                for s in scenes
            ]
            done = 0
            for future in as_completed(futures):
                try:
                    scene, segments = future.result()
                except Exception as e:
                    print(f"  ⚠️ 语音合成异常: {e}")
                    continue
                done += 1
                audio_segments[scene.scene_id] = segments
                if len(segments) > 1:
                    seg_info = " + ".join(f"{d:.1f}s" for _, d, _ in segments)
                    print(f"  🔀 镜头 {scene.scene_id} 语音超长，拆分为 "
                          f"{len(segments)} 段（{seg_info}）")
                elif segments and segments[0][1] <= 0:
                    print(f"  ⚠️ 镜头 {scene.scene_id} 语音合成失败，"
                          f"按 {scene.duration:.1f}s 渲染（无解说音轨）")

                if progress_cb:
                    progress_cb("TTS_COMPOSE", f"镜头 {scene.scene_id} 语音合成完成", done, len(scenes))

                if done % 10 == 0 or done == len(scenes):
                    print(f"  🎙️ 语音进度 {done}/{len(scenes)}")

    total_video_duration = sum(s.duration for s in scenes)
    total_clips = sum(len(segs) for segs in audio_segments.values())
    print(f"  ✅ 视频总时长 {total_video_duration:.1f}s（{len(scenes)} 个镜头，{total_clips} 个片段）")


    # 6b. 生成各镜头视频片段（并行渲染，4vCPU 限 3 并发）
    print("\n🎬 生成视频片段...")
    clip_paths = []
    successful_scenes = []  # 仅包含成功生成片段的场景，用于字幕时间轴对齐

    # 4vCPU 资源限制：3 并发平衡内存（Chrome ~500MB/实例）和 CPU（ffmpeg 编码）
    # Ken Burns 每 worker 线程数降为 1，避免 3×4=12 线程过度订阅 4 核
    per_worker_threads = max(1, threads // 3)

    results_by_scene = {}  # {(scene_id, seg_idx): (scene, clip_path)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for scene, decision in zip(scenes, decisions):
            segs = audio_segments.get(scene.scene_id, [])
            enable_subtitle = not args.no_subtitle
            if not segs:
                # 无音频段（合成异常）：按单段渲染，走静音兜底
                future = pool.submit(
                    _render_single_scene,
                    scene, decision, match_results,
                    config, render_params, work_dir,
                    resolution, fps, codec, audio_codec, preset, per_worker_threads,
                    args.skip_remotion,
                    None, scene.on_screen_text or "",
                    enable_subtitle, 0,
                    scene.duration
                )
                futures[future] = (scene, 0)
            else:
                for seg_idx, (audio_seg, seg_dur, seg_subtitle) in enumerate(segs):
                    future = pool.submit(
                        _render_single_scene,
                        scene, decision, match_results,
                        config, render_params, work_dir,
                        resolution, fps, codec, audio_codec, preset, per_worker_threads,
                        args.skip_remotion,
                        audio_seg, seg_subtitle,
                        enable_subtitle, seg_idx,
                        seg_dur
                    )
                    futures[future] = (scene, seg_idx)

        for future in as_completed(futures):
            scene, seg_idx = futures[future]
            try:
                result = future.result()
                if result:
                    rendered_scene, clip_path = result
                    results_by_scene[(scene.scene_id, seg_idx)] = (rendered_scene, clip_path)

                    # 保存片段到 R2 供缓存复用
                    if clip_path and r2_prefix and r2_config and task_id:
                        r2_clip_key = f"{r2_prefix}/{os.path.basename(clip_path)}"
                        save_clip_to_r2(clip_path, r2_clip_key, r2_config)

                    if progress_cb:
                        rendered_count = len(results_by_scene)
                        total_expected = sum(
                            len(segs) if segs else 1
                            for segs in audio_segments.values()
                        )
                        progress_cb(
                            "TTS_COMPOSE",
                            f"镜头 {rendered_scene.scene_id} 段{seg_idx} 渲染完成",
                            rendered_count,
                            total_expected,
                        )
            except Exception as e:
                print(f"  ❌ 镜头 {scene.scene_id} 段{seg_idx}: 渲染失败: {e}")
                if progress_cb:
                    progress_cb("TTS_COMPOSE", f"镜头 {scene.scene_id} 段{seg_idx} 渲染失败", 0, len(scenes))

    # 按场景顺序、段顺序排列，确保拼接顺序正确
    for scene in scenes:
        segs = audio_segments.get(scene.scene_id, [])
        if not segs:
            if (scene.scene_id, 0) in results_by_scene:
                rendered_scene, clip_path = results_by_scene[(scene.scene_id, 0)]
                clip_paths.append(clip_path)
                successful_scenes.append(rendered_scene)
                print(f"  ✅ 镜头 {rendered_scene.scene_id}: 片段已生成")
        else:
            for seg_idx in range(len(segs)):
                if (scene.scene_id, seg_idx) in results_by_scene:
                    rendered_scene, clip_path = results_by_scene[(scene.scene_id, seg_idx)]
                    clip_paths.append(clip_path)
                    successful_scenes.append(rendered_scene)
                    total = len(segs)
                    print(f"  ✅ 镜头 {rendered_scene.scene_id} "
                          f"段{seg_idx + 1}/{total}: 片段已生成")

    if not clip_paths:
        print("❌ 没有可用的视频片段，无法合成")
        raise RuntimeError("没有可用的视频片段")

    # 6c. 流拷贝拼接（所有片段已含音频+字幕，零重编码）
    # 每个片段在渲染阶段已烧录字幕+合并音频，直接拼接码流即可
    print("\n📋 流拷贝拼接最终视频...")
    final_output = work_dir / "final_output.mp4"
    merge_clips(clip_paths, str(final_output))

    # 可选：混合背景音乐（视频流零重编码，仅音频处理）
    # BGM 默认不添加，提供 --bgm 参数时才执行
    if args.bgm and os.path.exists(args.bgm):
        print(f"\n🎵 混合背景音乐: {args.bgm}")
        bgm_output = work_dir / "final_with_bgm.mp4"
        mix_bgm(str(final_output), args.bgm, str(bgm_output))
        final_output = bgm_output
        # 删除无 BGM 的中间文件
        old_output = work_dir / "final_output.mp4"
        if old_output.exists():
            old_output.unlink()
        print(f"  ✅ BGM 混合完成（视频流零重编码）")
    elif args.bgm:
        print(f"\n⚠️ BGM 文件不存在，跳过: {args.bgm}")

    # 清理音频段临时文件
    for segments in audio_segments.values():
        for seg_path, _, _ in segments:
            if os.path.exists(seg_path):
                os.unlink(seg_path)

    return str(final_output)


def cleanup(temp_dir: Path):
    """清理临时文件"""
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\n🗑️ 已清理临时目录: {temp_dir}")


def main():
    global args
    args = parse_args()

    # Windows 控制台默认 GBK 编码，重新配置为 UTF-8 以支持 emoji 输出
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    # 加载配置
    config = load_config("settings.json")
    render_params = load_config("render_params.json")

    # Pexels API Key：settings.json 优先，环境变量兜底（GitHub Actions 用）
    if not config.get("pexels_api_key"):
        config["pexels_api_key"] = os.environ.get("PEXELS_API_KEY", "")

    # 文章语言：CLI 参数 > settings.json > 默认中文
    if args.language is None:
        args.language = config.get("tts_language", "zh")
    print(f"🌐 文章语言: {args.language}（{'中文' if args.language == 'zh' else '英文'}）")

    model = config.get("model_name", "agnes-3.0-flash")

    # 初始化 Agnes 客户端（文本生成：文章、分镜）
    # settings.json 优先，环境变量兜底（GitHub Actions 用）
    agnes_api_key = config.get("agnes_api_key", "")
    if not agnes_api_key:
        agnes_api_key = os.environ.get("AGNES_API_KEY", "")
    agnes_base_url = config.get("agnes_api_base_url", "https://apihub.agnes-ai.com/v1")
    if not agnes_api_key:
        print("❌ 未配置 Agnes API Key，请在 config/settings.json 中设置 agnes_api_key")
        sys.exit(1)

    from core.agnes_client import AgnesClient
    client = AgnesClient(base_url=agnes_base_url, api_key=agnes_api_key, timeout=180)

    # 初始化智谱AI客户端（多模态评审）
    zhipu_api_key = config.get("zhipu_api_key", "")
    if not zhipu_api_key:
        zhipu_api_key = os.environ.get("ZHIPU_API_KEY", "")
    if not zhipu_api_key:
        print("⚠️ 未配置智谱AI API Key，多模态精评将不可用")
        zhipu_client = None
    else:
        zhipu_client = ZhipuAI(api_key=zhipu_api_key)

    print("=" * 60)
    print("  图文+Remotion 自动视频生成系统")
    print("=" * 60)

    # 初始化环境
    work_dir, temp_dir = setup_environment(config, render_params)
    print(f"📁 工作目录: {work_dir}")

    # 重渲染模式：跳过完整管线，直接重渲染指定场景
    if args.rerender_clips:
        try:
            final_output = rerender_clips(work_dir, config, render_params, args)

            # 上传最终视频到 R2
            if final_output and args.r2_bucket and args.r2_access_key_id and args.r2_secret_access_key and args.r2_endpoint and args.r2_prefix:
                r2_config = {
                    "bucket": args.r2_bucket,
                    "access_key_id": args.r2_access_key_id,
                    "secret_access_key": args.r2_secret_access_key,
                    "endpoint": args.r2_endpoint,
                }
                r2_video_key = f"{args.r2_prefix}/final_output.mp4"
                upload_to_r2(
                    final_output, r2_video_key,
                    r2_config["bucket"],
                    r2_config["access_key_id"],
                    r2_config["secret_access_key"],
                    r2_config["endpoint"],
                )

            # 发送完成回调
            if args.task_id:
                send_callback(
                    {
                        "task_id": args.task_id,
                        "phase": "TTS_COMPOSE",
                        "status": "completed",
                        "message": "重渲染完成",
                        "final_video_key": f"{args.r2_prefix}/final_output.mp4" if (args.r2_bucket and args.r2_prefix) else "final_output.mp4",
                        "final_video_url": f"{args.r2_prefix}/final_output.mp4" if (args.r2_bucket and args.r2_prefix) else None,
                    },
                    args.callback_url,
                    args.callback_secret,
                )

            print(f"\n{'=' * 60}")
            print(f"✅ 重渲染完成！")
            print(f"📁 输出文件: {final_output}")
            print(f"{'=' * 60}")
        except Exception as e:
            print(f"\n❌ 重渲染失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        return

    try:
        # ── CI 平台集成 ───────────────────────────────────────────────
        start_idx, end_idx = get_phase_range(args.start_phase, args.end_phase)
        start_phase_name = _PHASE_ORDER[start_idx]
        end_phase_name = _PHASE_ORDER[end_idx]

        r2_config = None
        if args.r2_bucket and args.r2_access_key_id and args.r2_secret_access_key and args.r2_endpoint:
            r2_config = {
                "bucket": args.r2_bucket,
                "access_key_id": args.r2_access_key_id,
                "secret_access_key": args.r2_secret_access_key,
                "endpoint": args.r2_endpoint,
            }

        def _cb_progress(phase: str, message: str, processed: int = 0, total: int = 0):
            send_callback(
                {
                    "task_id": args.task_id,
                    "phase": phase,
                    "status": "processing",
                    "message": message,
                    "processed_count": processed,
                    "total_count": total,
                },
                args.callback_url,
                args.callback_secret,
            )

        def _cb_phase_done(phase: str):
            send_callback(
                {
                    "task_id": args.task_id,
                    "phase": phase,
                    "status": "completed",
                    "message": f"Phase {phase} completed",
                    "processed_count": 1,
                    "total_count": 1,
                },
                args.callback_url,
                args.callback_secret,
            )

        print(f"\n📋 执行阶段: {start_phase_name} → {end_phase_name} ({start_idx}-{end_idx})")
        if args.task_id:
            print(f"🆔 任务ID: {args.task_id}")
        if r2_config:
            print(f"☁️ R2 存储: {args.r2_prefix}")

        # ══════════════════════════════════════════════════════════════
        # Phase 0: SCENE_GEN — 文章 → 分镜
        # ══════════════════════════════════════════════════════════════
        scenes = None
        if start_idx <= 0:
            _cb_progress(start_phase_name, "开始生成文章和分镜")
            # 环节1：获取文章
            print("\n[1/6] 获取文章...")
            if args.article_file:
                article = get_article_from_file(args.article_file)
                print(f"✅ 从文件读取文章，共 {len(article)} 字")
            elif args.article_source == "ai_generated" or args.topic:
                topic = args.topic or "生成一篇适合视频口播的文章"
                article = get_article_from_ai(client, topic, model)
                print(f"✅ AI 生成文章，共 {len(article)} 字")
            else:
                article = get_article(client, config, model)
                if not article or not article.strip():
                    print("❌ 未获取到文章内容")
                    sys.exit(1)
                print(f"✅ 文章已获取，共 {len(article)} 字")

            # 保存文章
            article_path = work_dir / "article.txt"
            with open(article_path, "w", encoding="utf-8") as f:
                f.write(article)
            save_phase_artifact(str(article_path), args.task_id, args.r2_prefix, r2_config)

            # 环节2：文章切块 + LLM 分镜
            print("\n[2/6] 切分文章并生成分镜...")
            chunks = split_into_chunks(article)
            if not chunks:
                print("❌ 文章切块失败，内容为空")
                sys.exit(1)
            total_chars = sum(len(c) for c in chunks)
            print(f"✅ 文章切成 {len(chunks)} 个解说片段"
                  f"（约 {total_chars} 字，预计 {total_chars / 5.2 / 60:.1f} 分钟）")

            scenes = generate_scenes_from_chunks(chunks, client, model)
            print(f"✅ 生成 {len(scenes)} 个镜头")

            _cb_progress("SCENE_GEN", f"已生成 {len(scenes)} 个分镜镜头", len(scenes), len(scenes))

            # 保存分镜
            scenes_path = work_dir / "scenes.json"
            with open(scenes_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"scenes": [s.to_dict() for s in scenes]},
                    f, ensure_ascii=False, indent=2
                )
            save_phase_artifact(str(scenes_path), args.task_id, args.r2_prefix, r2_config)

            _cb_phase_done("SCENE_GEN")

        else:
            # 从 R2 或本地加载分镜
            scenes_path = load_phase_artifact(
                "scenes.json", work_dir, args.task_id, args.r2_prefix, r2_config
            )
            if scenes_path:
                with open(scenes_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from core.scene_generator import Scene
                scenes = [Scene.from_dict(s) for s in data.get("scenes", [])]
                print(f"✅ 从产物加载 {len(scenes)} 个镜头")
            else:
                print("❌ 无法加载 scenes.json，请确保 SCENE_GEN 阶段已完成")
                sys.exit(1)

        # ══════════════════════════════════════════════════════════════
        # Phase 1: ASSET_MATCH — 分镜 → 素材匹配结果
        # ══════════════════════════════════════════════════════════════
        match_results = None
        if start_idx <= 1:
            _cb_progress("ASSET_MATCH", "开始下载并匹配图片素材")
            # 环节3：素材下载与匹配
            print("\n[3/6] 下载并匹配图片素材...")
            match_results = download_and_match(
                scenes, zhipu_client, config, temp_dir, work_dir,
                progress_cb=_cb_progress
            )

            # 保存匹配结果
            match_path = work_dir / "match_results.json"
            with open(match_path, "w", encoding="utf-8") as f:
                json.dump(match_results, f, ensure_ascii=False, indent=2)
            save_phase_artifact(str(match_path), args.task_id, args.r2_prefix, r2_config)

            _cb_phase_done("ASSET_MATCH")

        else:
            match_path = load_phase_artifact(
                "match_results.json", work_dir, args.task_id, args.r2_prefix, r2_config
            )
            if match_path:
                with open(match_path, "r", encoding="utf-8") as f:
                    match_results = json.load(f)
                print(f"✅ 从产物加载匹配结果（{len(match_results)} 个镜头）")
            else:
                print("❌ 无法加载 match_results.json，请确保 ASSET_MATCH 阶段已完成")
                sys.exit(1)

        # ══════════════════════════════════════════════════════════════
        # Phase 2: REMOTION_RENDER — 匹配结果 → 综合决策
        # ══════════════════════════════════════════════════════════════
        decisions = None
        if start_idx <= 2:
            _cb_progress("REMOTION_RENDER", "开始分析 Remotion 适用性和综合决策")
            # 环节4：Remotion 适用性分析
            print("\n[4/6] 分析 Remotion 适用性...")
            remotion_decisions = analyze_scenes(scenes)
            remotion_count = sum(1 for d in remotion_decisions if d.use_remotion)
            print(f"✅ {remotion_count} 个镜头适合 Remotion，{len(scenes) - remotion_count} 个使用图片")

            # 环节5：综合决策
            print("\n[5/6] 综合决策...")
            score_threshold = config.get("match_score_threshold", 0.25)
            decisions = decide_scenes(scenes, match_results, remotion_decisions, score_threshold)

            for dec in decisions:
                print(f"  镜头 {dec.scene_id}: {dec.implementation} — {dec.reason}")

            _cb_progress("REMOTION_RENDER", f"已分析 {len(decisions)} 个镜头的 Remotion 适用性", len(decisions), len(decisions))

            # 保存决策
            decisions_path = work_dir / "decisions.json"
            with open(decisions_path, "w", encoding="utf-8") as f:
                json.dump(
                    [{
                        "scene_id": d.scene_id,
                        "implementation": d.implementation,
                        "asset_path": d.asset_path,
                        "match_score": d.match_score,
                        "reason": d.reason
                    } for d in decisions],
                    f, ensure_ascii=False, indent=2
                )
            save_phase_artifact(str(decisions_path), args.task_id, args.r2_prefix, r2_config)

            _cb_phase_done("REMOTION_RENDER")

        else:
            decisions_path = load_phase_artifact(
                "decisions.json", work_dir, args.task_id, args.r2_prefix, r2_config
            )
            if decisions_path:
                with open(decisions_path, "r", encoding="utf-8") as f:
                    dec_data = json.load(f)
                from core.decision_engine import SceneDecision
                decisions = [SceneDecision.from_dict(d) for d in dec_data]
                print(f"✅ 从产物加载 {len(decisions)} 个决策")
            else:
                print("❌ 无法加载 decisions.json，请确保 REMOTION_RENDER 阶段已完成")
                sys.exit(1)

        # ══════════════════════════════════════════════════════════════
        # Phase 3: TTS_COMPOSE — 决策 → 最终视频
        # ══════════════════════════════════════════════════════════════
        final_output = None
        if start_idx <= 3:
            _cb_progress("TTS_COMPOSE", "开始合成语音和视频")

            # 下载已有的缓存片段（从 R2），避免重复渲染
            if r2_config and args.task_id and args.r2_prefix:
                cached = download_clips_from_r2(
                    work_dir, args.task_id, args.r2_prefix, r2_config
                )
                if cached > 0:
                    print(f"  ♻️ 从 R2 下载 {cached} 个缓存片段，将复用")

            # 环节6：合成视频
            print("\n[6/6] 合成视频...")
            final_output = compose_video(
                scenes, decisions, match_results,
                config, render_params, work_dir,
                progress_cb=_cb_progress,
                r2_prefix=args.r2_prefix,
                r2_config=r2_config,
                task_id=args.task_id,
            )

            # 上传最终视频到 R2
            if final_output and r2_config:
                r2_video_key = f"{args.r2_prefix}/final_output.mp4"
                upload_to_r2(
                    final_output, r2_video_key,
                    r2_config["bucket"],
                    r2_config["access_key_id"],
                    r2_config["secret_access_key"],
                    r2_config["endpoint"],
                )

            _cb_phase_done("TTS_COMPOSE")

            # 发送完成回调（含最终视频信息）
            if final_output:
                send_callback(
                    {
                        "task_id": args.task_id,
                        "phase": "TTS_COMPOSE",
                        "status": "completed",
                        "message": "视频生成完成",
                        "final_video_key": f"{args.r2_prefix}/final_output.mp4" if r2_config else "final_output.mp4",
                        "final_video_url": f"{args.r2_prefix}/final_output.mp4" if r2_config else None,
                    },
                    args.callback_url,
                    args.callback_secret,
                )

        # 保留临时目录中的图片素材，供后续 --rerender-clips 重渲染使用
        # 如需清理可手动删除 temp 目录，或修改 work_dir
        print(f"\n📁 临时素材保留在 {temp_dir}（供 --rerender-clips 重渲染使用）")

        if final_output:
            print(f"\n{'=' * 60}")
            print(f"✅ 视频生成完成！")
            print(f"📁 输出文件: {final_output}")
            print(f"{'=' * 60}")
        elif end_idx < 3:
            print(f"\n{'=' * 60}")
            print(f"✅ 阶段执行完成（{end_phase_name}）")
            print(f"📁 产物已保存到 R2/工作目录")
            print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()

        # 发送错误回调
        if args.task_id:
            send_callback(
                {
                    "task_id": args.task_id,
                    "phase": args.start_phase or "SCENE_GEN",
                    "status": "failed",
                    "error": str(e),
                },
                args.callback_url,
                args.callback_secret,
            )

        cleanup(temp_dir)
        sys.exit(1)


if __name__ == "__main__":
    main()
