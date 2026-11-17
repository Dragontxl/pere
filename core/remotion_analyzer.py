"""环节4：Remotion 适用性分析

判断哪些镜头适合用 Remotion 编码视频实现。
基于镜头的 visual_type 做规则判断。
"""

from dataclasses import dataclass
from typing import List


# Remotion 适用的视觉类型
REMOTION_TYPES = {"data_visual", "text_animation", "diagram"}


@dataclass
class RemotionDecision:
    """Remotion 分析决策"""
    scene_id: int
    use_remotion: bool
    reason: str


def analyze_scenes(scenes: List) -> List[RemotionDecision]:
    """分析每个镜头是否适合用 Remotion 编码视频

    规则：
    - data_visual / text_animation / diagram → 适合 Remotion
    - 其他类型 → 适合图片素材

    Args:
        scenes: 镜头列表（Scene 对象）

    Returns:
        Remotion 决策列表
    """
    decisions = []
    for scene in scenes:
        if scene.visual_type in REMOTION_TYPES:
            decisions.append(RemotionDecision(
                scene_id=scene.scene_id,
                use_remotion=True,
                reason=f"视觉类型 {scene.visual_type} 适合编码视频实现"
            ))
        else:
            decisions.append(RemotionDecision(
                scene_id=scene.scene_id,
                use_remotion=False,
                reason=f"视觉类型 {scene.visual_type} 适合使用图片素材"
            ))
    return decisions


def get_remotion_scene_ids(decisions: List[RemotionDecision]) -> list:
    """获取需要使用 Remotion 的镜头 ID 列表

    Args:
        decisions: Remotion 决策列表

    Returns:
        需要 Remotion 的镜头 ID 列表
    """
    return [d.scene_id for d in decisions if d.use_remotion]
