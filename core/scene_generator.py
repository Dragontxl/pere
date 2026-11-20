"""环节2：LLM 分镜生成

将文章拆解为结构化的镜头列表（JSON）
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Scene:
    """镜头数据结构"""
    scene_id: int
    visual_description: str
    search_keywords: List[str]
    on_screen_text: str
    duration: float
    visual_type: str
    needs_effect: bool

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "visual_description": self.visual_description,
            "search_keywords": self.search_keywords,
            "on_screen_text": self.on_screen_text,
            "duration": self.duration,
            "visual_type": self.visual_type,
            "needs_effect": self.needs_effect,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(
            scene_id=d["scene_id"],
            visual_description=d["visual_description"],
            search_keywords=d["search_keywords"],
            on_screen_text=d["on_screen_text"],
            duration=d["duration"],
            visual_type=d["visual_type"],
            needs_effect=d["needs_effect"],
        )


# 视觉类型枚举
VISUAL_TYPES = {
    "landscape",       # 自然风光/实景
    "concept",         # 概念/抽象
    "data_visual",     # 数据可视化
    "text_animation",  # 文字动画
    "diagram",         # 流程图/结构图
    "portrait",        # 人物/肖像
    "event",           # 事件/动作场景
}

# 分镜生成 Prompt 模板
SCENE_PROMPT_TEMPLATE = """请将以下文章拆解为镜头列表，用于视频创作。

要求：
1. 每个镜头包含以下字段：
   - scene_id: 从1开始的序号
   - visual_description: 画面描述，用于后续素材匹配
   - search_keywords: 用于搜索素材的关键词列表，需包含中英文
   - on_screen_text: 该镜头的解说文本（从文章中提取）
   - duration: 预估时长（秒），不设上限，按解说文本实际长度估算，中文约3-4字/秒
   - visual_type: 镜头类型，只能从以下值选择：landscape, concept, data_visual, text_animation, diagram, portrait, event
   - needs_effect: 是否需要特效（布尔值）

2. search_keywords 需要包含中英文，方便素材搜索，提供2-4个候选词。

3. 镜头时长不设上限。根据文章总字数和语速（约3-4字/秒）估算所需镜头数量，确保生成足够多的场景完整覆盖整篇文章。

4. 只输出 JSON，不要任何解释或额外内容。

JSON 格式示例：
{{"scenes": [{{"scene_id": 1, "visual_description": "画面描述", "search_keywords": ["中文关键词", "english keyword"], "on_screen_text": "解说文本", "duration": 4.5, "visual_type": "landscape", "needs_effect": false}}]}}

文章内容：
{article}
"""


def _repair_json(json_str: str) -> str:
    """修复常见 JSON 语法错误

    处理 LLM 输出中常见的 JSON 格式问题：
    - 尾部多余逗号: {"a":1,} → {"a":1}
    - 数组尾部逗号: [1,2,] → [1,2]
    - 缺失逗号: {"a":1 "b":2} → {"a":1,"b":2}

    Args:
        json_str: 原始 JSON 字符串

    Returns:
        修复后的 JSON 字符串
    """
    import re

    # 修复尾部多余逗号: ,} → } 和 ,] → ]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    # 修复缺失逗号: 数字/布尔/null 后紧跟引号（对象内缺失逗号）
    # 匹配: "value": 1 "next" → "value": 1, "next"
    json_str = re.sub(
        r'(\d|true|false|null)\s+(")',
        r'\1,\2',
        json_str
    )

    # 修复对象间缺失逗号: } "key" → }, "key"
    json_str = re.sub(r'}\s+(")', r'},\1', json_str)

    return json_str


def extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 字符串

    处理 markdown 代码块标记，提取有效的 JSON 对象

    Args:
        text: LLM 输出的原始文本

    Returns:
        提取的 JSON 字符串
    """
    # 去除 markdown 代码块标记
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)

    # 匹配从第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text.strip()


def _parse_json_with_repair(json_str: str) -> dict:
    """解析 JSON，失败时尝试修复后重试

    Args:
        json_str: JSON 字符串

    Returns:
        解析后的字典

    Raises:
        json.JSONDecodeError: 修复后仍解析失败
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复常见语法错误
        repaired = _repair_json(json_str)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            # 修复失败，抛出原始错误
            raise


CHUNK_SCENE_PROMPT_TEMPLATE = """你是短视频分镜师。下面是一篇文章被切成的若干「解说片段」，每个片段会单独配音、单独配一个镜头。

请为每个片段设计画面，只输出 JSON，不要任何解释。

要求：
1. 严格按输入片段的数量和顺序输出，id 必须与输入编号一一对应，不要增删、合并或拆分。
2. visual_description：一句话描述画面内容（中文），用于后续图库检索匹配。
3. search_keywords：3-4 个英文检索词（必须英文，不要中文），用于 Pexels 图库搜索，尽量具体可视化。
4. visual_type：只能是 landscape / concept / data_visual / text_animation / diagram / portrait / event 之一。
   - data_visual：片段里出现具体数字、百分比、增降幅
   - diagram：片段在讲原因、机制、步骤、因果链条
   - text_animation：金句、结论、需要强调的观点
   - portrait：人物相关
   - event：新闻现场、动作场景
   - landscape / concept：实景或抽象概念
5. needs_effect：布尔值，是否需要额外特效。

输出格式：
{{"scenes": [{{"id": 1, "visual_description": "画面描述", "search_keywords": ["english", "keyword"], "visual_type": "landscape", "needs_effect": false}}]}}

片段列表：
{chunks}
"""

# 每批送给 LLM 的片段数量（过多会导致输出被截断）
CHUNK_BATCH_SIZE = 15


def _fallback_visual_type(text: str) -> str:
    """LLM 失败时的兜底视觉类型判断

    Args:
        text: 片段文本

    Returns:
        视觉类型
    """
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|％|万亿|亿|万|家|人|元|倍)", text):
        return "data_visual"
    if re.search(r"(因为|所以|步骤|第一|第二|首先|其次|意味着|导致)", text):
        return "diagram"
    return "landscape"


def _parse_chunk_batch(content: str, batch: list) -> dict:
    """解析一批片段的分镜结果

    Args:
        content: LLM 原始输出
        batch: 本批片段文本列表

    Returns:
        {片段序号(1-based): 分镜元数据字典}
    """
    json_str = extract_json(content)
    data = _parse_json_with_repair(json_str)
    items = data.get("scenes", data if isinstance(data, list) else [])
    if not isinstance(items, list):
        raise ValueError("分镜结果不是列表")

    result = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("id", i + 1))
        except (TypeError, ValueError):
            idx = i + 1
        result[idx] = item
    return result


def generate_scenes_from_chunks(chunks: List[str], client,
                                model: str = "agnes-3.0-flash") -> List[Scene]:
    """按「文章片段」生成分镜

    每个片段就是一个镜头：on_screen_text 严格使用片段原文，
    保证配音文本与字幕完全一致；LLM 只负责画面描述、检索词和镜头类型。

    Args:
        chunks: 文章片段列表（来自 core.article_chunker）
        client: Agnes 客户端
        model: 模型名称

    Returns:
        镜头列表（数量与 chunks 相同，顺序一致）
    """
    import time

    metas = {}  # 全局片段序号(0-based) → 元数据

    total_batches = (len(chunks) + CHUNK_BATCH_SIZE - 1) // CHUNK_BATCH_SIZE
    for b in range(total_batches):
        start = b * CHUNK_BATCH_SIZE
        batch = chunks[start:start + CHUNK_BATCH_SIZE]
        listing = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
        prompt = CHUNK_SCENE_PROMPT_TEMPLATE.format(chunks=listing)

        parsed = {}
        for attempt in range(2):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content.strip()
                parsed = _parse_chunk_batch(content, batch)
                if parsed:
                    break
            except Exception as e:
                print(f"  ⚠️ 第 {b + 1}/{total_batches} 批分镜失败"
                      f"（第 {attempt + 1} 次）: {e}")
                time.sleep(2)

        for i, text in enumerate(batch):
            meta = parsed.get(i + 1, {})
            metas[start + i] = meta
        print(f"  ✅ 分镜批次 {b + 1}/{total_batches} 完成"
              f"（{len(parsed)}/{len(batch)} 有效）")

    scenes = []
    for idx, text in enumerate(chunks):
        meta = metas.get(idx, {})
        vtype = meta.get("visual_type", "")
        if vtype not in VISUAL_TYPES:
            vtype = _fallback_visual_type(text)

        keywords = meta.get("search_keywords") or []
        if not isinstance(keywords, list):
            keywords = [str(keywords)]
        # LLM 有时把短语写成连字符形式（stock-market），
        # 图库检索用空格分隔的短语效果更好
        cleaned_kws = []
        for k in keywords:
            k = str(k).strip()
            if not k:
                continue
            if "-" in k and k.isascii():
                k = k.replace("-", " ")
            k = re.sub(r"\s+", " ", k).strip()
            if k and k not in cleaned_kws:
                cleaned_kws.append(k)
        keywords = cleaned_kws

        scenes.append(Scene(
            scene_id=idx + 1,
            visual_description=meta.get("visual_description", "") or text,
            search_keywords=keywords,
            on_screen_text=text,
            duration=0.0,  # 由实际配音时长决定
            visual_type=vtype,
            needs_effect=bool(meta.get("needs_effect", False)),
        ))

    return scenes


def generate_scenes(article: str, client, model: str = "agnes-3.0-flash") -> List[Scene]:
    """调用 LLM 将文章拆解为分镜

    Args:
        article: 文章全文
        client: Agnes 客户端
        model: 使用的模型名称

    Returns:
        镜头列表

    Raises:
        ValueError: JSON 解析失败
    """
    prompt = SCENE_PROMPT_TEMPLATE.format(article=article)

    # 重试机制：JSON 解析失败时重新请求
    max_retries = 2
    last_error = None

    for attempt in range(max_retries + 1):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content.strip()

        # 保存原始输出（便于调试）
        raw_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "temp", "scene_raw_response.txt")
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        try:
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

        # 提取并解析 JSON
        json_str = extract_json(content)
        try:
            data = _parse_json_with_repair(json_str)
            break
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < max_retries:
                print(f"  ⚠️ 分镜 JSON 解析失败（第 {attempt+1} 次），重新生成...")
                continue
            raise ValueError(f"分镜 JSON 解析失败: {e}")

    scenes = []
    scene_items = data.get("scenes", [])
    if not scene_items:
        raise ValueError("分镜生成结果为空，未找到 scenes 字段或列表为空")

    for i, item in enumerate(scene_items):
        # 校验并补齐字段，防止 LLM 返回异常数据导致 KeyError
        vtype = item.get("visual_type", "landscape")
        if vtype not in VISUAL_TYPES:
            vtype = "landscape"

        # scene_id 缺失时按序号补齐
        sid = item.get("scene_id", i + 1)
        try:
            sid = int(sid)
        except (ValueError, TypeError):
            sid = i + 1

        scenes.append(Scene(
            scene_id=sid,
            visual_description=item.get("visual_description", ""),
            search_keywords=item.get("search_keywords", []),
            on_screen_text=item.get("on_screen_text", ""),
            duration=float(item.get("duration", 5.0)),
            visual_type=vtype,
            needs_effect=item.get("needs_effect", False),
        ))

    return scenes
