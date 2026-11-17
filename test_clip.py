"""测试 CLIP 匹配器实际功能

加载 CLIP 模型，创建测试图片，验证文本-图像匹配的正确性。
"""

import sys
import os
import shutil

sys.stdout.reconfigure(encoding='utf-8')

os.chdir(r'F:\Programs\pexel-remotion')

# 创建测试图片
os.makedirs('test_clip_output', exist_ok=True)
from PIL import Image

img1 = Image.new('RGB', (224, 224), (34, 139, 34))   # 绿色（模拟森林）
img1.save('test_clip_output/green.png')
img2 = Image.new('RGB', (224, 224), (70, 130, 180))   # 蓝色（模拟海洋）
img2.save('test_clip_output/blue.png')
img3 = Image.new('RGB', (224, 224), (255, 215, 0))     # 金色（模拟阳光）
img3.save('test_clip_output/gold.png')

print('✅ 测试图片已创建')

# 加载 CLIP 模型
print('⏳ 加载 CLIP 模型（首次需下载，约 350MB）...')
from core.asset_matcher.clip_matcher import CLIPMatcher
matcher = CLIPMatcher(model_name='openai/clip-vit-base-patch32')

# 测试图片路径
image_paths = [
    'test_clip_output/green.png',
    'test_clip_output/blue.png',
    'test_clip_output/gold.png',
]

# 匹配"森林"
results = matcher.match('a lush green forest', image_paths)
print(f'\n匹配 "a lush green forest":')
for r in results:
    name = os.path.basename(r['path'])
    print(f'  {name}: 分数 {r["score"]:.4f}')

# 匹配"海洋"
results2 = matcher.match('a vast ocean sea', image_paths)
print(f'\n匹配 "a vast ocean sea":')
for r in results2:
    name = os.path.basename(r['path'])
    print(f'  {name}: 分数 {r["score"]:.4f}')

# 验证最佳匹配
best_forest = matcher.match_best('a lush green forest', image_paths)
best_ocean = matcher.match_best('a vast ocean sea', image_paths)

forest_best = os.path.basename(best_forest['path'])
ocean_best = os.path.basename(best_ocean['path'])

print(f'\n森林最佳匹配: {forest_best} ({best_forest["score"]:.4f})')
print(f'海洋最佳匹配: {ocean_best} ({best_ocean["score"]:.4f})')

# 验证结果合理性
assert 'green' in forest_best, f'森林应匹配绿色图片，实际: {forest_best}'
assert 'blue' in ocean_best, f'海洋应匹配蓝色图片，实际: {ocean_best}'

# 清理
shutil.rmtree('test_clip_output', ignore_errors=True)

print('\n✅ CLIP 匹配器功能测试通过！')
print(f'   模型: openai/clip-vit-base-patch32')
print(f'   设备: {matcher.device}')
