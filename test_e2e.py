"""微型端到端测试：验证视频合成管道在 moviepy 2.x 下能实际运行

测试范围：
1. 图片 → Ken Burns 视频片段（image_to_clip）
2. 视频片段拼接（merge_clips）
3. 字幕叠加（add_subtitles）

不依赖：API Key、torch、opencv、网络、Pexels
仅依赖：moviepy（已装）、PIL（已装）、ffmpeg（moviepy 自带）
"""

import os
import sys
import time
import traceback
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE = r'F:\Programs\pexel-remotion'
sys.path.insert(0, BASE)
os.chdir(BASE)

# 输出目录
OUTPUT_DIR = Path(BASE) / 'test_e2e_output'
OUTPUT_DIR.mkdir(exist_ok=True)

passed = 0
failed = 0

def check(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f'✅ {name}')
    except Exception as e:
        failed += 1
        print(f'❌ {name}: {e}')
        traceback.print_exc()


# ============================================================
# 准备测试素材
# ============================================================
def setup_test_images():
    """创建两张测试图片"""
    from PIL import Image
    img1 = Image.new('RGB', (1920, 1080), (34, 139, 34))  # 森林绿
    img1.save(str(OUTPUT_DIR / 'test_img1.png'))

    img2 = Image.new('RGB', (1920, 1080), (70, 130, 180))  # 海洋蓝
    img2.save(str(OUTPUT_DIR / 'test_img2.png'))

    print(f"  ✅ 测试图片已创建: test_img1.png, test_img2.png")

check("准备测试素材", setup_test_images)


# ============================================================
# 测试1：图片 → Ken Burns 视频片段
# ============================================================
def test_image_to_clip():
    from core.composer.image_to_clip import image_to_clip
    from core.scene_generator import Scene

    clip1_path = str(OUTPUT_DIR / 'clip_1.mp4')
    clip2_path = str(OUTPUT_DIR / 'clip_2.mp4')

    # 镜头1：zoom_in（scene_id=0）
    image_to_clip(
        image_path=str(OUTPUT_DIR / 'test_img1.png'),
        duration=2.0,
        output_path=clip1_path,
        scene_id=0,
        visual_type='landscape',
        resolution=(640, 360),  # 小分辨率加速测试
        fps=12,
        codec='libx264',
        audio_codec='aac',
        preset='ultrafast',
        threads=2
    )
    assert os.path.exists(clip1_path), "片段1未生成"
    assert os.path.getsize(clip1_path) > 0, "片段1文件为空"
    print(f"  ✅ 片段1: {os.path.getsize(clip1_path) / 1024:.1f} KB")

    # 镜头2：pan_right（scene_id=3 → pan_right）
    image_to_clip(
        image_path=str(OUTPUT_DIR / 'test_img2.png'),
        duration=2.0,
        output_path=clip2_path,
        scene_id=3,
        visual_type='landscape',
        resolution=(640, 360),
        fps=12,
        codec='libx264',
        audio_codec='aac',
        preset='ultrafast',
        threads=2
    )
    assert os.path.exists(clip2_path), "片段2未生成"
    assert os.path.getsize(clip2_path) > 0, "片段2文件为空"
    print(f"  ✅ 片段2: {os.path.getsize(clip2_path) / 1024:.1f} KB")

check("1. 图片 → Ken Burns 视频片段", test_image_to_clip)


# ============================================================
# 测试2：视频片段拼接
# ============================================================
def test_merge_clips():
    from core.composer.video_merger import merge_clips

    merged_path = str(OUTPUT_DIR / 'merged.mp4')
    clip_paths = [
        str(OUTPUT_DIR / 'clip_1.mp4'),
        str(OUTPUT_DIR / 'clip_2.mp4'),
    ]

    merge_clips(clip_paths, merged_path)
    assert os.path.exists(merged_path), "合并视频未生成"
    assert os.path.getsize(merged_path) > 0, "合并视频文件为空"
    print(f"  ✅ 合并视频: {os.path.getsize(merged_path) / 1024:.1f} KB")

check("2. 视频片段拼接", test_merge_clips)


# ============================================================
# 测试3：字幕叠加
# ============================================================
def test_add_subtitles():
    from core.composer.subtitle_overlay import add_subtitles
    from core.scene_generator import Scene

    final_path = str(OUTPUT_DIR / 'final_with_subs.mp4')

    # 创建模拟场景
    scenes = [
        Scene(
            scene_id=1,
            visual_description="森林场景",
            search_keywords=["forest"],
            on_screen_text="这是第一段解说文字",
            duration=2.0,
            visual_type='landscape',
            needs_effect=False,
        ),
        Scene(
            scene_id=2,
            visual_description="海洋场景",
            search_keywords=["ocean"],
            on_screen_text="这是第二段解说文字",
            duration=2.0,
            visual_type='landscape',
            needs_effect=False,
        ),
    ]

    add_subtitles(
        video_path=str(OUTPUT_DIR / 'merged.mp4'),
        scenes=scenes,
        output_path=final_path,
        resolution=(640, 360),
        fps=12,
        codec='libx264',
        audio_codec='aac',
        crf=23
    )
    assert os.path.exists(final_path), "字幕视频未生成"
    assert os.path.getsize(final_path) > 0, "字幕视频文件为空"
    print(f"  ✅ 字幕视频: {os.path.getsize(final_path) / 1024:.1f} KB")

check("3. 字幕叠加", test_add_subtitles)


# ============================================================
# 测试4：TTS 时长获取（不实际调用 API，测试配置和函数结构）
# ============================================================
def test_tts_structure():
    from core.composer.tts_synthesis import _get_tts_config, _select_voice, synthesize_speech

    config = _get_tts_config()
    assert config["tts_api_url"] == "http://ttv.yugongtxl.dpdns.org/v1/audio/speech"
    assert config["tts_api_key"] == "123456"

    voice_zh = _select_voice("zh")
    assert voice_zh == "zh-CN-YunjianNeural"

    voice_en = _select_voice("en")
    assert voice_en == "en-US-EricNeural"

    print(f"  ✅ TTS 配置和音色选择正确")
    print(f"  ✅ synthesize_speech 函数签名: {synthesize_speech.__doc__[:50]}...")

check("4. TTS 结构验证", test_tts_structure)


# ============================================================
# 总结
# ============================================================
print(f"\n{'=' * 50}")
print(f"端到端测试结果: {passed} 通过, {failed} 失败")
print(f"{'=' * 50}")

if failed > 0:
    print(f"\n❌ 有 {failed} 项测试失败")
    sys.exit(1)
else:
    print(f"\n✅ 全部端到端测试通过！视频合成管道在 moviepy 2.x 下正常工作。")
    print(f"📁 测试输出目录: {OUTPUT_DIR}")
    sys.exit(0)
