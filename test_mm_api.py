"""测试多模态评审器实际 API 调用

使用真实 API Key 调用 GLM-4.1V-Thinking-Flash，
验证并发评分功能正常工作。
"""

import sys
import os
import time
import traceback

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(r'F:\Programs\pexel-remotion')

from PIL import Image

# 创建测试图片
os.makedirs('test_mm_output', exist_ok=True)

# 不同内容的测试图片（用文字+颜色模拟不同场景）
img_specs = [
    ("forest.png", (34, 139, 34), "🌲🌲🌲 森林 🌲🌲🌲"),     # 绿色 - 森林
    ("ocean.png", (70, 130, 180), "🌊🌊🌊 海洋 🌊🌊🌊"),     # 蓝色 - 海洋
    ("sunset.png", (255, 140, 0), "🌅🌅🌅 夕阳 🌅🌅🌅"),      # 橙色 - 夕阳
    ("city.png", (128, 128, 128), "🏙️🏙️🏙️ 城市 🏙️🏙️🏙️"),   # 灰色 - 城市
]

for name, color, text in img_specs:
    img = Image.new('RGB', (512, 512), color)
    # 用 PIL 画文字
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", 48)
    except:
        font = ImageFont.load_default()
    draw.text((100, 240), text, fill=(255, 255, 255), font=font)
    img.save(f'test_mm_output/{name}')
    print(f"  ✅ {name} 已创建")

image_paths = [f'test_mm_output/{name}' for name, _, _ in img_specs]

# 加载配置和 API Key
from core.utils import load_config
config = load_config("settings.json")
api_key = config["zhipu_api_key"]
assert api_key, "API Key 未配置"

# 初始化智谱AI客户端
from zhipuai import ZhipuAI
client = ZhipuAI(api_key=api_key)

# 初始化多模态评审器（5并发）
from core.asset_matcher.multimodal_reviewer import MultimodalReviewer
reviewer = MultimodalReviewer(
    client,
    model=config["multimodal_model_name"],
    concurrency=config.get("multimodal_concurrency", 5)
)

print(f"\n✅ 多模态评审器已初始化")
print(f"   模型: {reviewer.model}")
print(f"   并发: {reviewer.concurrency}")
print(f"   API Key: {api_key[:12]}...")

# 测试1：并发评审 4 张图片
print(f"\n⏳ 开始并发评审 4 张图片...")
start = time.time()
results = reviewer.review("一个茂密的绿色森林，有大量树木和自然光线", image_paths)
elapsed = time.time() - start

print(f"\n评审结果（耗时 {elapsed:.1f} 秒）:")
for i, r in enumerate(results, 1):
    name = os.path.basename(r["path"])
    print(f"  {i}. {name}: 评分 {r['score']}, 理由: {r['reason'][:60]}")

# 验证最佳匹配
best = results[0]
best_name = os.path.basename(best["path"])
print(f"\n最佳匹配: {best_name} (评分 {best['score']})")
assert "forest" in best_name, f"森林场景应匹配 forest.png，实际: {best_name}"

# 测试2：评审单张图片
print(f"\n⏳ 单张图片评审...")
start2 = time.time()
single = reviewer.review_best("一个广阔的蓝色海洋，波涛起伏", [image_paths[1]])
elapsed2 = time.time() - start2
print(f"海洋场景最佳匹配: {os.path.basename(single['path'])} (评分 {single['score']}, 耗时 {elapsed2:.1f}s)")
assert single["score"] > 0, "评分应大于0"

# 清理
import shutil
shutil.rmtree('test_mm_output', ignore_errors=True)

print("\n✅ 多模态评审器 API 调用测试全部通过！")
print(f"   4张图片并发评审耗时: {elapsed:.1f}s")
print(f"   单张评审耗时: {elapsed2:.1f}s")
