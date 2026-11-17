"""环节3c：多模态大模型精评（阶段二）

在 CLIP 初筛基础上，用多模态大模型对候选图片做精准评分。
CLIP 做粗筛，多模态模型做精评，兼顾效率与精度。
支持并发调用，最多同时评分 5 张图片。
"""

import base64
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List


class MultimodalReviewer:
    """使用多模态大模型对图片做内容匹配精评

    支持 GLM-4.1V-Thinking-Flash 等内置深度思考的多模态模型。
    模型会先输出思维链推理过程，再给出最终评分，解析时需从最终回答中提取。
    支持并发调用，默认 5 路并发。
    """

    def __init__(self, client, model: str = "glm-4.1v-thinking-flash", concurrency: int = 5):
        """初始化多模态评审器

        Args:
            client: 智谱AI客户端
            model: 多模态模型名称，默认使用 glm-4.1v-thinking-flash
            concurrency: 并发数，默认 5
        """
        self.client = client
        self.model = model
        self.concurrency = concurrency

    def review(self, description: str, image_paths: List[str]) -> List[dict]:
        """对候选图片做精评（并发）

        使用线程池并发调用多模态 API，默认 5 路并发。

        Args:
            description: 画面描述
            image_paths: 候选图片路径列表

        Returns:
            评分结果列表，按分数降序排列，每项:
            {"path": ..., "score": 0-100, "reason": ...}
        """
        results = []
        max_workers = min(self.concurrency, len(image_paths))

        if max_workers <= 1:
            # 只有一张图片或并发数为 1，直接串行处理
            for path in image_paths:
                score, reason = self._review_single(description, path)
                results.append({"path": path, "score": score, "reason": reason})
        else:
            # 多张图片，并发处理
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self._review_single, description, path): path
                    for path in image_paths
                }
                for future in as_completed(future_map):
                    path = future_map[future]
                    try:
                        score, reason = future.result()
                        results.append({"path": path, "score": score, "reason": reason})
                    except Exception as e:
                        print(f"    ❌ 多模态评审异常: {e}")
                        results.append({"path": path, "score": 0, "reason": str(e)})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def review_best(self, description: str, image_paths: List[str]) -> dict:
        """返回最佳精评结果

        Args:
            description: 画面描述
            image_paths: 候选图片路径

        Returns:
            最佳匹配结果或 None
        """
        results = self.review(description, image_paths)
        return results[0] if results else None

    def _review_single(self, description: str, image_path: str):
        """对单张图片评分

        Args:
            description: 画面描述
            image_path: 图片路径

        Returns:
            (score, reason) 元组
        """
        # 读取并压缩图片（避免 base64 过大导致 Prompt 超长）
        from PIL import Image
        import io
        with Image.open(image_path) as img:
            img = img.convert('RGB')
            # 限制最大边为 512px，控制 base64 大小
            w, h = img.size
            max_side = 512
            if max(w, h) > max_side:
                ratio = max_side / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            # 转为 JPEG 压缩
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=80)
            img_data = buf.getvalue()
        img_base64 = base64.b64encode(img_data).decode('utf-8')

        prompt = (
            f"请分析这张图片的内容，判断它与以下场景描述的匹配程度。\n"
            f"场景描述：{description}\n"
            f"请给出 0-100 的匹配度评分，并简要说明理由。\n"
            f"只返回格式：评分:XX, 理由:XX"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_base64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content.strip()

            # GLM-4.1V-Thinking 可能将思维链单独放在 reasoning_content 字段
            # 若单独存在，content 即为最终回答，无需额外处理
            # 若思维链内联在 content 中，由 _parse_response 负责提取
            score, reason = self._parse_response(content)
            return score, reason
        except Exception as e:
            print(f"    ❌ 多模态评审失败: {e}")
            return 0, str(e)

    def _parse_response(self, content: str):
        """解析评分响应

        GLM-4.1V-Thinking 系列模型内置深度思考，响应可能包含思维链推理过程
        （以 <thinking>...</thinking> 标记包裹，或内联在 content 中）。
        需要从最终回答部分提取评分，而非从推理过程中提取。

        Args:
            content: 模型返回的文本

        Returns:
            (score, reason) 元组
        """
        # 如果包含思维链标记，截取最后一个 </thinking> 之后的内容作为最终回答
        if '</thinking>' in content:
            last_thinking_end = content.rfind('</thinking>')
            content = content[last_thinking_end + len('</thinking>'):].strip()
        elif '<thinking>' in content:
            # 只有起始标记没有结束标记的异常情况，取标记之后的内容
            content = content[content.rfind('<thinking>') + len('<thinking>'):].strip()

        # 从最终回答中提取评分（取最后一个匹配，确保是最终答案）
        matches = re.findall(r'评分[:：]\s*(\d+)', content)
        if matches:
            score = int(matches[-1])
            # 提取理由
            reason_match = re.search(r'理由[:：]\s*(.+)', content, flags=re.DOTALL)
            if reason_match:
                reason = reason_match.group(1).strip()
            else:
                reason = content.strip()
            return score, reason

        return 0, content
