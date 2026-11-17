"""测试 AgnesClient 适配器接口兼容性

验证 AgnesClient 的 chat.completions.create() 接口
与现有代码的调用方式完全兼容。
"""

import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(r'F:\Programs\pexel-remotion')

from core.agnes_client import AgnesClient
from core.utils import load_config

config = load_config("settings.json")
api_key = config["agnes_api_key"]
base_url = config["agnes_api_base_url"]
model = config["model_name"]

print(f"模型: {model}")
print(f"Base URL: {base_url}")

# 创建客户端
client = AgnesClient(base_url=base_url, api_key=api_key)

# 测试1：模拟文章生成调用（article_input.py 的模式）
print("\n[1] 测试文章生成调用...")
response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "请用一句话介绍人工智能。"}],
)
content = response.choices[0].message.content
print(f"✅ 返回: {content}")
assert content, "返回内容不应为空"

# 测试2：模拟分镜生成调用（scene_generator.py 的模式）
print("\n[2] 测试分镜生成调用...")
scene_prompt = '请将以下文章拆解为分镜，返回JSON格式：\n{"scenes": [{"scene_id": 1, "visual_description": "测试场景"}]}\n文章：人工智能正在改变世界。'
response2 = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": scene_prompt}],
)
content2 = response2.choices[0].message.content
print(f"✅ 返回前80字: {content2[:80]}...")
assert content2, "返回内容不应为空"

# 测试3：带额外参数
print("\n[3] 测试带 max_tokens 参数...")
response3 = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "1+1=?"}],
    max_tokens=50,
)
content3 = response3.choices[0].message.content
print(f"✅ 返回: {content3}")

print("\n✅ AgnesClient 适配器接口兼容性测试通过！")
