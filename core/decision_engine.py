"""环节5：综合决策引擎

综合素材匹配结果和 Remotion 分析，
决定每个镜头的最终实现方式。
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SceneDecision:
    """镜头决策结果"""
    scene_id: int
    implementation: str       # "image" 或 "remotion"
    asset_path: Optional[str] = None
    match_score: float = 0.0
    reason: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SceneDecision":
        return cls(
            scene_id=d["scene_id"],
            implementation=d["implementation"],
            asset_path=d.get("asset_path"),
            match_score=d.get("match_score", 0.0),
            reason=d.get("reason", ""),
        )


def decide_scenes(
    scenes: List,
    match_results: dict,
    remotion_decisions: List,
    score_threshold: float = 0.25
) -> List[SceneDecision]:
    """为每个镜头做最终决策

    决策逻辑：
    1. Remotion 适用类型 → 使用 Remotion 编码视频
    2. 图片匹配分数 >= 阈值 → 使用图片 + Ken Burns 动效
    3. 图片不达标 → 使用最佳候选（兜底，后续可接入文生图补位）

    Args:
        scenes: 镜头列表（Scene 对象）
        match_results: {scene_id: [{"path":..., "score":...}, ...]}
        remotion_decisions: Remotion 分析结果
        score_threshold: 图片匹配分数阈值

    Returns:
        决策列表，与 scenes 一一对应
    """
    remotion_map = {d.scene_id: d for d in remotion_decisions}

    decisions = []
    for scene in scenes:
        remotion_dec = remotion_map.get(scene.scene_id)

        # 1. Remotion 适用类型 → 使用 Remotion，同时设置兜底图片路径
        # 即使 Remotion 渲染失败，兜底代码也能用 asset_path 直接生成图片片段
        if remotion_dec and remotion_dec.use_remotion:
            fallback_matches = match_results.get(scene.scene_id, [])
            fallback_path = fallback_matches[0]["path"] if fallback_matches else None
            fallback_score = fallback_matches[0].get("score", 0.0) if fallback_matches else 0.0
            decisions.append(SceneDecision(
                scene_id=scene.scene_id,
                implementation="remotion",
                asset_path=fallback_path,
                match_score=fallback_score,
                reason=remotion_dec.reason
            ))
            continue

        # 2-3. 图片匹配
        matches = match_results.get(scene.scene_id, [])
        best_match = matches[0] if matches else None

        if best_match and best_match["score"] >= score_threshold:
            decisions.append(SceneDecision(
                scene_id=scene.scene_id,
                implementation="image",
                asset_path=best_match["path"],
                match_score=best_match["score"],
                reason=f"图片匹配分数 {best_match['score']:.3f} 达标"
            ))
        else:
            # 不达标，使用最佳候选作为兜底
            fallback_path = best_match["path"] if best_match else None
            score = best_match["score"] if best_match else 0.0
            decisions.append(SceneDecision(
                scene_id=scene.scene_id,
                implementation="image",
                asset_path=fallback_path,
                match_score=score,
                reason=f"图片匹配未达标（{score:.3f}），使用最佳候选"
            ))

    return decisions
