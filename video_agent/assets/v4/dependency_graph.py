from __future__ import annotations

from collections import defaultdict, deque

from video_agent.contracts.v4 import SceneSemanticPlan, SemanticScene

from .stage4_errors import Stage4Error


def topo_sort_scenes(plan: SceneSemanticPlan) -> list[SemanticScene]:
    by_id = {scene.scene_id: scene for scene in plan.scenes}
    if len(by_id) != len(plan.scenes):
        raise Stage4Error("invalid_scene_dependency", "duplicate scene_id in SceneSemanticPlan")

    edges: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {scene_id: 0 for scene_id in by_id}

    for scene in plan.scenes:
        for inp in scene.inputs:
            if inp.from_scene not in by_id:
                raise Stage4Error(
                    "invalid_scene_dependency",
                    f"input {inp.input_name} references missing scene {inp.from_scene}",
                    scene_id=scene.scene_id,
                )
            upstream = by_id[inp.from_scene]
            if upstream.order >= scene.order:
                raise Stage4Error(
                    "invalid_scene_dependency",
                    f"dependency {inp.from_scene} must have smaller order than {scene.scene_id}",
                    scene_id=scene.scene_id,
                )
            if scene.scene_id not in edges[inp.from_scene]:
                edges[inp.from_scene].add(scene.scene_id)
                indegree[scene.scene_id] += 1
            output_names = {item.output_name for item in upstream.outputs}
            if inp.from_output not in output_names:
                raise Stage4Error(
                    "missing_scene_output",
                    f"upstream scene {inp.from_scene} has no output {inp.from_output}",
                    scene_id=scene.scene_id,
                )

    ready = sorted(
        [scene_id for scene_id, degree in indegree.items() if degree == 0],
        key=lambda scene_id: (by_id[scene_id].order, scene_id),
    )
    queue = deque(ready)
    ordered: list[SemanticScene] = []
    while queue:
        scene_id = queue.popleft()
        ordered.append(by_id[scene_id])
        for nxt in sorted(edges[scene_id], key=lambda item: (by_id[item].order, item)):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(by_id):
        raise Stage4Error("invalid_scene_dependency", "scene dependency graph contains a cycle")
    return ordered
