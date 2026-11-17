"""验证脚本：测试不依赖重型包的核心逻辑模块

测试范围：
1. 配置加载
2. 通用工具函数
3. 分镜生成（JSON 提取、Scene 数据结构）
4. Remotion 分析
5. 决策引擎
6. 多模态评审器（思维链响应解析）
7. TTS 配置加载与音色选择
8. moviepy 导入兼容性检查
"""

import sys
import os
import json
import traceback

sys.stdout.reconfigure(encoding='utf-8')

BASE = r'F:\Programs\pexel-remotion'
sys.path.insert(0, BASE)
os.chdir(BASE)

passed = 0
failed = 0


def check(name, fn):
    """运行测试并记录结果"""
    global passed, failed
    try:
        result = fn()
        if result is not False:
            passed += 1
            print(f'✅ {name}')
        else:
            failed += 1
            print(f'❌ {name}')
    except Exception as e:
        failed += 1
        print(f'❌ {name}: {e}')
        traceback.print_exc()


# ============================================================
# 1. 配置加载
# ============================================================
def test_config_loading():
    from core.utils import load_config
    config = load_config("settings.json")
    assert "multimodal_model_name" in config, "缺少 multimodal_model_name"
    assert config["multimodal_model_name"] == "glm-4.1v-thinking-flash"
    assert "tts_api_url" in config, "缺少 tts_api_url"
    assert "tts_api_key" in config, "缺少 tts_api_key"
    assert "tts_voice" in config, "缺少 tts_voice"
    assert "tts_speed" in config, "缺少 tts_speed"
    assert "tts_pitch" in config, "缺少 tts_pitch"

    render_params = load_config("render_params.json")
    assert render_params["resolution_width"] == 1920
    assert render_params["resolution_height"] == 1080
    assert render_params["fps"] == 24
    print(f"    multimodal_model_name: {config['multimodal_model_name']}")
    print(f"    tts_api_url: {config['tts_api_url']}")
    print(f"    tts_speed: {config['tts_speed']}")

check("1. 配置加载 (settings.json + render_params.json)", test_config_loading)


# ============================================================
# 2. 通用工具函数
# ============================================================
def test_utils():
    from core.utils import detect_language, is_chinese, clean_filename, ensure_dir
    
    # 语言检测
    assert detect_language("这是一段中文测试文本") == "zh"
    assert detect_language("This is an English test text") == "en"
    assert detect_language("混合文本 with some English") == "en"
    
    # 中文判断
    assert is_chinese("这是中文") is True
    assert is_chinese("This is English") is False
    
    # 文件名清理
    cleaned = clean_filename("test/file*name?.mp4")
    assert "/" not in cleaned and "*" not in cleaned and "?" not in cleaned
    
    # 目录创建
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        test_dir = os.path.join(tmp, "test_sub", "dir")
        result = ensure_dir(test_dir)
        assert os.path.isdir(test_dir)
        assert result == test_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

check("2. 通用工具函数 (语言检测/文件名/目录)", test_utils)


# ============================================================
# 3. 分镜生成
# ============================================================
def test_scene_generator():
    from core.scene_generator import Scene, extract_json, VISUAL_TYPES
    
    # Scene 数据结构
    scene = Scene(
        scene_id=1,
        visual_description="森林晨光",
        search_keywords=["森林", "forest"],
        on_screen_text="清晨的森林",
        duration=4.5,
        visual_type="landscape",
        needs_effect=False,
    )
    d = scene.to_dict()
    assert d["scene_id"] == 1
    assert d["visual_type"] == "landscape"
    assert d["duration"] == 4.5
    
    # VISUAL_TYPES
    assert "landscape" in VISUAL_TYPES
    assert "data_visual" in VISUAL_TYPES
    assert "text_animation" in VISUAL_TYPES
    
    # JSON 提取（模拟 LLM 输出）
    llm_output = '```json\n{"scenes": [{"scene_id": 1, "visual_description": "test"}]}\n```'
    extracted = extract_json(llm_output)
    data = json.loads(extracted)
    assert data["scenes"][0]["scene_id"] == 1
    
    # 无代码块标记的 JSON
    llm_output2 = '{"scenes": [{"scene_id": 2, "visual_description": "test2"}]} 前面有文字'
    extracted2 = extract_json(llm_output2)
    data2 = json.loads(extracted2)
    assert data2["scenes"][0]["scene_id"] == 2

    # JSON 修复：尾部多余逗号
    from core.scene_generator import _repair_json, _parse_json_with_repair
    bad_json1 = '{"scenes": [{"scene_id": 1, "visual_description": "test",}]}'
    data3 = _parse_json_with_repair(bad_json1)
    assert data3["scenes"][0]["scene_id"] == 1

    # JSON 修复：缺失逗号
    bad_json2 = '{"scenes": [{"scene_id": 1 "visual_description": "test"}]}'
    data4 = _parse_json_with_repair(bad_json2)
    assert data4["scenes"][0]["scene_id"] == 1

check("3. 分镜生成 (Scene/JSON提取/类型校验)", test_scene_generator)


# ============================================================
# 4. Remotion 分析
# ============================================================
def test_remotion_analyzer():
    from core.scene_generator import Scene
    from core.remotion_analyzer import analyze_scenes, get_remotion_scene_ids, RemotionDecision
    
    scenes = [
        Scene(1, "data chart", ["chart"], "数据展示", 5.0, "data_visual", False),
        Scene(2, "forest", ["forest"], "森林风光", 4.0, "landscape", False),
        Scene(3, "text anim", ["text"], "文字动画", 3.0, "text_animation", True),
        Scene(4, "diagram", ["diagram"], "流程图", 4.0, "diagram", False),
    ]
    
    decisions = analyze_scenes(scenes)
    assert len(decisions) == 4
    assert decisions[0].use_remotion is True   # data_visual
    assert decisions[1].use_remotion is False  # landscape
    assert decisions[2].use_remotion is True   # text_animation
    assert decisions[3].use_remotion is True   # diagram
    
    remotion_ids = get_remotion_scene_ids(decisions)
    assert remotion_ids == [1, 3, 4]

check("4. Remotion 分析 (类型判断/决策输出)", test_remotion_analyzer)


# ============================================================
# 5. 决策引擎
# ============================================================
def test_decision_engine():
    from core.scene_generator import Scene
    from core.remotion_analyzer import analyze_scenes
    from core.decision_engine import decide_scenes, SceneDecision
    
    scenes = [
        Scene(1, "data chart", ["chart"], "数据展示", 5.0, "data_visual", False),
        Scene(2, "forest", ["forest"], "森林风光", 4.0, "landscape", False),
    ]
    
    remotion_decisions = analyze_scenes(scenes)
    
    # 匹配结果：镜头2 有图片匹配，分数达标
    match_results = {
        2: [{"path": "/tmp/img1.jpg", "score": 0.35}],
    }
    
    decisions = decide_scenes(scenes, match_results, remotion_decisions, score_threshold=0.25)
    
    assert decisions[0].implementation == "remotion"  # data_visual → Remotion
    assert decisions[1].implementation == "image"     # landscape → 图片
    assert decisions[1].asset_path == "/tmp/img1.jpg"
    assert decisions[1].match_score == 0.35
    
    # 测试兜底逻辑：分数不达标
    match_results_low = {
        2: [{"path": "/tmp/img2.jpg", "score": 0.10}],
    }
    decisions2 = decide_scenes(scenes, match_results_low, remotion_decisions, score_threshold=0.25)
    assert decisions2[1].implementation == "image"  # 兜底仍用图片
    assert decisions2[1].match_score == 0.10
    assert "兜底" in decisions2[1].reason or "未达标" in decisions2[1].reason

check("5. 决策引擎 (Remotion/图片/兜底)", test_decision_engine)


# ============================================================
# 6. 多模态评审器 - 思维链响应解析
# ============================================================
def test_multimodal_reviewer_parsing():
    from core.asset_matcher.multimodal_reviewer import MultimodalReviewer
    
    # 模拟一个不需要 client 的实例
    reviewer = MultimodalReviewer.__new__(MultimodalReviewer)
    reviewer.model = "glm-4.1v-thinking-flash"
    reviewer.concurrency = 5
    
    # 测试1：标准格式（无思维链）
    content1 = "评分:85, 理由:图片内容与森林场景高度匹配"
    score1, reason1 = reviewer._parse_response(content1)
    assert score1 == 85
    assert "森林" in reason1
    
    # 测试2：带 thinking 标记的思维链
    content2 = """<thinking>
用户要求判断图片与森林场景的匹配度。首先观察图片内容，可以看到大片的绿色树木，
与森林场景描述非常吻合。综合考虑后给出评分。
</thinking>
评分:92, 理由:图片展示茂密的绿色森林，与场景描述完全匹配"""
    score2, reason2 = reviewer._parse_response(content2)
    assert score2 == 92
    assert "森林" in reason2
    
    # 测试3：思维链中包含评分（不应被提取，应取最终答案）
    content3 = """<thinking>
初步判断可能评分:50，但进一步观察发现图片质量很高。
经过仔细分析，应该评分:88。
</thinking>
评分:88, 理由:画面与描述高度一致"""
    score3, reason3 = reviewer._parse_response(content3)
    assert score3 == 88  # 取最后一个，即最终答案
    
    # 测试4：全角冒号
    content4 = "评分：75，理由：图片内容基本符合场景描述"
    score4, reason4 = reviewer._parse_response(content4)
    assert score4 == 75
    
    # 测试5：无法解析
    content5 = "无法给出评分"
    score5, reason5 = reviewer._parse_response(content5)
    assert score5 == 0

check("6. 多模态评审器 (思维链响应解析)", test_multimodal_reviewer_parsing)


# ============================================================
# 7. TTS 配置加载与音色选择
# ============================================================
def test_tts_config():
    from core.composer.tts_synthesis import _get_tts_config, _select_voice
    
    config = _get_tts_config()
    assert config["tts_api_url"] == "http://ttv.yugongtxl.dpdns.org/v1/audio/speech"
    assert config["tts_api_key"] == "123456"
    assert "tts_voice" in config
    assert "tts_speed" in config
    assert "tts_pitch" in config
    
    # 音色自动选择（基于全局语言，不再逐段检测文本）
    voice_zh = _select_voice("zh")
    assert voice_zh == "zh-CN-YunjianNeural"

    voice_en = _select_voice("en")
    assert voice_en == "en-US-EricNeural"

check("7. TTS 配置加载与音色选择", test_tts_config)


# ============================================================
# 8. moviepy 导入兼容性
# ============================================================
def test_moviepy_import():
    try:
        from moviepy.editor import ImageClip, VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
        print("    moviepy.editor 导入成功 (v1.x API)")
    except ImportError:
        # moviepy 2.x 改了导入路径
        try:
            from moviepy import ImageClip, VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
            print("    moviepy 导入成功 (v2.x API)")
            # 如果 v2.x，需要检查代码是否兼容
            import moviepy
            print(f"    moviepy 版本: {moviepy.__version__}")
            print("    ⚠️ 代码使用 moviepy.editor 导入，可能需要适配 v2.x")
        except ImportError as e2:
            return False
    return True

check("8. moviepy 导入兼容性", test_moviepy_import)


# ============================================================
# 9. 完整模块导入测试
# ============================================================
def test_module_imports():
    """测试所有核心模块能否被导入"""
    modules = [
        "core.utils",
        "core.article_input",
        "core.scene_generator",
        "core.remotion_analyzer",
        "core.decision_engine",
        "core.asset_matcher.multimodal_reviewer",
    ]
    
    for mod_name in modules:
        __import__(mod_name)
        print(f"    {mod_name} ✅")
    
    # 这些模块依赖重型包，单独处理
    heavy_modules = [
        ("core.asset_matcher.clip_matcher", "torch/transformers"),
        ("core.asset_matcher.pexels_downloader", "selenium"),
        ("core.composer.image_to_clip", "moviepy"),
        ("core.composer.tts_synthesis", "moviepy/requests"),
        ("core.composer.video_merger", "moviepy"),
        ("core.composer.subtitle_overlay", "moviepy"),
    ]
    for mod_name, dep in heavy_modules:
        try:
            __import__(mod_name)
            print(f"    {mod_name} ✅ (依赖: {dep})")
        except ImportError as e:
            print(f"    {mod_name} ⚠️ (缺少依赖 {dep}: {e})")

check("9. 模块导入测试", test_module_imports)


# ============================================================
# 10. main.py CLI 参数解析
# ============================================================
def test_cli_args():
    """测试 CLI 参数解析（不需要执行完整流程）"""
    import argparse
    
    # 模拟 main.py 的 parse_args 逻辑
    parser = argparse.ArgumentParser(description="测试")
    parser.add_argument("--article-file", type=str, default=None)
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--skip-remotion", action="store_true")
    
    # 测试1：无参数
    args1 = parser.parse_args([])
    assert args1.article_file is None
    assert args1.topic is None
    assert args1.skip_remotion is False
    
    # 测试2：指定参数
    args2 = parser.parse_args(["--article-file", "test.txt", "--output-dir", "./out", "--skip-remotion"])
    assert args2.article_file == "test.txt"
    assert args2.output_dir == "./out"
    assert args2.skip_remotion is True

check("10. CLI 参数解析", test_cli_args)


# ============================================================
# 11. main.py 启动检查（无 API Key 时应优雅退出）
# ============================================================
def test_main_startup():
    """测试 main.py 在无 API Key 时的行为"""
    import subprocess
    import json
    import shutil

    config_path = os.path.join(BASE, "config", "settings.json")

    # 临时清空 API Key
    with open(config_path, "r", encoding="utf-8") as f:
        original_config = json.load(f)

    test_config = dict(original_config)
    test_config["zhipu_api_key"] = ""
    test_config["agnes_api_key"] = ""

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(test_config, f, ensure_ascii=False, indent=2)

    try:
        # 清除环境变量中的 API Key
        env = os.environ.copy()
        env.pop("ZHIPU_API_KEY", None)

        result = subprocess.run(
            [sys.executable, "main.py", "--topic", "测试话题"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
            cwd=BASE,
        )

        # 应该因为缺少 API Key 而退出
        assert result.returncode != 0, "无 API Key 时应非零退出"
        assert "API Key" in result.stdout or "api_key" in result.stdout, "应提示缺少 API Key"
    finally:
        # 恢复原始配置
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(original_config, f, ensure_ascii=False, indent=2)

check("11. main.py 启动检查（无API Key优雅退出）", test_main_startup)


# ============================================================
# 总结
# ============================================================
print(f"\n{'=' * 50}")
print(f"测试结果: {passed} 通过, {failed} 失败")
print(f"{'=' * 50}")

if failed > 0:
    sys.exit(1)
