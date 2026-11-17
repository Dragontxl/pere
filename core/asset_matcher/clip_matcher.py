"""环节3b：CLIP 图片内容匹配

使用 CLIP 模型将图片和文本描述编码为向量，
计算余弦相似度，选出匹配度最高的图片。
"""

import os
import torch
from PIL import Image


class CLIPMatcher:
    """使用 CLIP 模型进行图片与文本的相似度匹配"""

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32", device: str = None):
        """初始化 CLIP 匹配器

        Args:
            model_name: CLIP 模型名称
            device: 计算设备（'cuda' 或 'cpu'），默认自动检测
        """
        # 国内网络默认使用 HuggingFace 镜像，避免 SSL 证书验证失败
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        from transformers import CLIPModel, CLIPProcessor

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = CLIPModel.from_pretrained(model_name).to(self.device)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model.eval()

        print(f"  ✅ CLIP 模型已加载: {model_name} (device: {self.device})")

    def _extract_features(self, outputs) -> torch.Tensor:
        """从模型输出中提取特征张量

        transformers 4.x: get_text_features() 直接返回张量
        transformers 5.x: 返回 BaseModelOutputWithPooling 对象，
                          特征在 pooler_output 属性中

        Args:
            outputs: 模型输出

        Returns:
            特征张量
        """
        if torch.is_tensor(outputs):
            return outputs
        # transformers 5.x 返回对象，尝试提取特征张量
        if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
            return outputs.pooler_output
        if hasattr(outputs, 'last_hidden_state') and outputs.last_hidden_state is not None:
            return outputs.last_hidden_state
        if isinstance(outputs, (list, tuple)) and len(outputs) > 0:
            return outputs[0]
        raise ValueError(f"无法从模型输出中提取特征张量: {type(outputs)}")

    def encode_text(self, text: str) -> torch.Tensor:
        """将文本编码为归一化向量

        Args:
            text: 文本描述

        Returns:
            归一化的文本向量
        """
        inputs = self.processor(
            text=text, return_tensors="pt", truncation=True, max_length=77
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
        embedding = self._extract_features(outputs)
        return embedding / embedding.norm(dim=-1, keepdim=True)

    def encode_images(self, image_paths: list) -> tuple:
        """将多张图片编码为归一化向量

        单张图片加载失败时自动跳过，不影响整体编码。

        Args:
            image_paths: 图片路径列表

        Returns:
            (归一化的图片向量, 成功加载的图片路径列表)
            所有图片失败时返回 (空张量, 空列表)
        """
        images = []
        valid_paths = []
        for path in image_paths:
            try:
                img = Image.open(path).convert('RGB')
                images.append(img)
                valid_paths.append(path)
            except Exception as e:
                print(f"    ⚠️ CLIP 图片加载失败，跳过: {path} ({e})")

        if not images:
            # 所有图片都失败，返回空张量
            return torch.zeros(0, 512), []

        inputs = self.processor(images=images, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
        embedding = self._extract_features(outputs)
        return embedding / embedding.norm(dim=-1, keepdim=True), valid_paths

    def match(self, description: str, image_paths: list) -> list:
        """计算图片与描述的相似度

        Args:
            description: 画面描述文本
            image_paths: 候选图片路径列表

        Returns:
            排序后的匹配结果，每项: {"path": ..., "score": ...}
            按相似度降序排列
        """
        if not image_paths:
            return []

        text_embedding = self.encode_text(description)

        try:
            image_embeddings, valid_paths = self.encode_images(image_paths)
        except MemoryError:
            print(f"    ⚠️ CLIP 编码内存不足，跳过相似度匹配，使用原始顺序")
            return [{"path": path, "score": 0.0} for path in image_paths]

        # 所有图片加载失败，返回原始顺序
        if image_embeddings.shape[0] == 0:
            return [{"path": path, "score": 0.0} for path in image_paths]

        # 计算余弦相似度
        similarities = (image_embeddings @ text_embedding.T).squeeze(-1).cpu().numpy()

        results = [
            {"path": path, "score": float(score)}
            for path, score in zip(valid_paths, similarities)
        ]

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def match_best(self, description: str, image_paths: list) -> dict:
        """返回最佳匹配结果

        Args:
            description: 画面描述
            image_paths: 候选图片路径

        Returns:
            {"path": ..., "score": ...} 或 None（无候选时）
        """
        results = self.match(description, image_paths)
        return results[0] if results else None
