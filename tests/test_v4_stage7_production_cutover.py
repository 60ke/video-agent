from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4.production import PRODUCTION_DAG_DEPENDENCIES
from video_agent.v4.production import NODE_ORDER, V4ProductionOrchestrator


def test_production_dag_node_set_matches_frozen_contract() -> None:
    assert set(NODE_ORDER) == set(PRODUCTION_DAG_DEPENDENCIES)
    assert NODE_ORDER.index("anchor") < NODE_ORDER.index("motion_audio")
    assert NODE_ORDER.index("bgm") < NODE_ORDER.index("compile")
    assert NODE_ORDER.index("cover") < NODE_ORDER.index("delivery_qa")


def test_production_module_does_not_import_v3_orchestrator() -> None:
    source = Path(V4ProductionOrchestrator.__module__.replace(".", "/") + ".py")
    # Resolve via package file
    import video_agent.v4.production as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    assert "video_agent.orchestrator" not in text
    assert "LegacyOrchestrator" not in text
    assert "_prepend_one_frame" not in text


def test_public_generate_command_uses_v4_production() -> None:
    import video_agent.cli as cli

    text = Path(cli.__file__).read_text(encoding="utf-8")
    # The generate entry must call V4ProductionOrchestrator and must not call V3 Orchestrator.run
    assert "V4ProductionOrchestrator" in text
    assert "Orchestrator(context).run()" not in text


def test_remotion_root_has_no_vertical_demo() -> None:
    root = Path(__file__).resolve().parents[1] / "remotion" / "src" / "Root.tsx"
    text = root.read_text(encoding="utf-8")
    assert "VerticalDemo" not in text
    assert "V4Timeline" in text
