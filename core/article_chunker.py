"""文章切块

把文章按句子切成适合单个镜头的解说片段。

设计动机：
- 每个片段会单独配音、单独渲染成一个 clip，时长 = 实测语音时长（不设上限）
- 中文 TTS 语速约 5 字/秒，50 字左右 ≈ 10 秒，用于控制镜头节奏；
  这只是切块粒度，不再是硬性时长上限
- 片段数量由文章长度决定，不再依赖 LLM 自由发挥（LLM 曾把 6210 字的文章
  只切成 8 个镜头，导致 94% 的解说被丢弃）
"""

import re

# 单个片段的字数参考值：52 字 ≈ 10 秒（5.2 字/秒），用于控制镜头节奏与素材数量。
# 镜头时长不设上限：配音超过 10 秒时不会再拆成子镜头。
MAX_CHARS = 52
# 单个片段的字数下限：太短的片段（如「这就是答案。」）不利于画面表达
MIN_CHARS = 22


def clean_article(text: str) -> str:
    """清理文章中的 Markdown / HTML 残留

    Args:
        text: 原始文章

    Returns:
        纯文本
    """
    if not text:
        return ""

    # HTML 实体（如 &#x20; 表示空格）
    text = re.sub(r"&#x?[0-9a-fA-F]+;", " ", text)

    # Markdown 图片 / 链接：[文字](url) → 文字
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)

    # 行首标记：# 标题、> 引用、- 列表、* 列表、1. 有序列表
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s{0,3}>\s*", "", text)
    text = re.sub(r"(?m)^\s{0,3}[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s{0,3}\d+[.、)]\s+", "", text)

    # 行内强调标记
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
    text = text.replace("`", "")

    # 分隔线
    text = re.sub(r"(?m)^\s*[-=*_]{3,}\s*$", "", text)

    # 压缩空白
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)

    return text.strip()


def _split_sentences(text: str) -> list:
    """按句末标点切句，保留标点

    Args:
        text: 纯文本

    Returns:
        句子列表
    """
    # 段落换行也视为句子边界
    parts = re.split(r"(?<=[。！？!?；;…])|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _split_long(sentence: str, max_chars: int) -> list:
    """把超长句子按逗号等次级标点切开

    Args:
        sentence: 超过 max_chars 的句子
        max_chars: 单个片段最大字数

    Returns:
        片段列表（可能仍有超出 max_chars 的硬切结果）
    """
    pieces = re.split(r"(?<=[，,、：:—])", sentence)
    result = []
    buf = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > max_chars:
            # 连逗号都没有的超长句：硬切
            if buf:
                result.append(buf)
                buf = ""
            for i in range(0, len(piece), max_chars):
                chunk = piece[i:i + max_chars].strip()
                if chunk:
                    result.append(chunk)
            continue
        if len(buf) + len(piece) <= max_chars:
            buf += piece
        else:
            if buf:
                result.append(buf)
            buf = piece
    if buf:
        result.append(buf)
    return result


def split_into_chunks(text: str, max_chars: int = MAX_CHARS,
                      min_chars: int = MIN_CHARS) -> list:
    """把文章切成适合单个镜头的解说片段

    规则：
    1. 优先在句号/问号/感叹号/分号/换行处断开
    2. 相邻短句合并到接近 max_chars，但不超限
    3. 超长句在逗号处二次切分，仍超长则硬切
    4. 末尾过短的片段并回上一块（合并后不超限时）

    Args:
        text: 文章全文
        max_chars: 单个片段最大字数（默认 52，约 10 秒；仅控制切块粒度，不是时长上限）
        min_chars: 单个片段最小字数（默认 22）

    Returns:
        片段文本列表
    """
    cleaned = clean_article(text)
    if not cleaned:
        return []

    sentences = _split_sentences(cleaned)

    # 先按句合并
    chunks = []
    buf = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_long(sentence, max_chars))
            continue
        if len(buf) + len(sentence) <= max_chars:
            buf += sentence
        else:
            if buf:
                chunks.append(buf)
            buf = sentence
    if buf:
        chunks.append(buf)

    # 合并过短的片段（尽量不留 1-2 个字的碎片）
    merged = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if merged and len(chunk) < min_chars and len(merged[-1]) + len(chunk) <= max_chars:
            merged[-1] += chunk
        else:
            merged.append(chunk)

    # 首块过短时并到后一块
    if len(merged) >= 2 and len(merged[0]) < min_chars and len(merged[0]) + len(merged[1]) <= max_chars:
        merged = [merged[0] + merged[1]] + merged[2:]

    return merged
