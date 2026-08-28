"""Built-in role profiles (spec section 9) and the demo project seed.

The profiles encode the one rule the whole system exists for: shared facts,
unshared thinking. Each profile differs in three ways — what it can see,
what it is measured on, and what it is forbidden from doing.
"""

from __future__ import annotations

from typing import Any

from .store import Store

ROLE_PROFILES: list[dict[str, Any]] = [
    {
        "id": "progress",
        "name": "Progress AI",
        "goal": "企画全体を前進させる",
        "priority": "最短で安全に工程を進める",
        "visible_context": [
            "project", "current_phase", "status", "owner", "implementation_state",
            "dependencies", "deliverables", "locked_decisions", "handoff",
            "agents", "recent_changes",
        ],
        "hidden_context": ["world", "assets", "api", "facts"],
        "evaluation_axes": ["依存関係", "停滞", "完了条件", "次工程"],
        "prohibitions": ["不要なデザイン変更", "仕様の再議論"],
    },
    {
        "id": "design",
        "name": "Design AI",
        "goal": "視覚・体験設計",
        "priority": "世界観の一貫性を保ったまま現フェーズを完成させる",
        "visible_context": [
            "project", "current_phase", "status", "world", "assets", "constraints",
            "locked_decisions", "dependencies", "deliverables", "handoff",
        ],
        "hidden_context": ["api", "implementation_state", "files", "recent_changes"],
        "evaluation_axes": ["一貫性", "可読性", "独自性", "体験"],
        "prohibitions": ["実装都合だけでデザインを決める"],
    },
    {
        "id": "builder",
        "name": "Builder / Codex",
        "goal": "実装",
        "priority": "確定仕様どおりに、壊さず作る",
        "visible_context": [
            "project", "current_phase", "status", "implementation_state", "api",
            "locked_decisions", "constraints", "files", "dependencies",
            "deliverables", "handoff",
        ],
        "hidden_context": ["world", "open_decisions", "failures"],
        "evaluation_axes": ["正確性", "安定性", "保守性", "再現性"],
        "prohibitions": ["勝手な仕様変更"],
    },
    {
        "id": "critic",
        "name": "Critic AI",
        "goal": "企画の弱点を発見する",
        "priority": "破綻を早期に見つける",
        "visible_context": [
            "project", "current_phase", "status", "locked_decisions",
            "open_decisions", "constraints", "dependencies", "failures",
            "implementation_state",
        ],
        "hidden_context": ["assets", "handoff", "recent_changes"],
        "evaluation_axes": ["破綻点", "依存リスク", "矛盾", "見落とし"],
        "prohibitions": ["無条件な賛成"],
    },
    {
        "id": "explorer",
        "name": "Explorer AI",
        "goal": "現在案と異なる可能性を探す",
        "priority": "既存案の外側を出す",
        "visible_context": ["project", "summary", "constraints", "locked_decisions"],
        "hidden_context": [
            "assets", "world", "files", "handoff", "implementation_state",
            "open_decisions", "recent_changes", "relations", "agents",
        ],
        "evaluation_axes": ["新規性", "差別化", "可能性"],
        "prohibitions": ["現行案の言い換え"],
    },
]

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {"id": "progress", "name": "Progress AI", "role": "工程管理",
     "context_profile": "progress"},
    {"id": "design", "name": "Design AI", "role": "デザイン",
     "context_profile": "design"},
    {"id": "codex", "name": "Codex", "role": "実装", "context_profile": "builder"},
    {"id": "critic", "name": "Critic AI", "role": "批評", "context_profile": "critic"},
    {"id": "explorer", "name": "Explorer AI", "role": "探索",
     "context_profile": "explorer"},
]


def install_defaults(store: Store) -> None:
    """Idempotently install the five role profiles and their agents."""
    for profile in ROLE_PROFILES:
        store.upsert_role_profile(actor="system", **profile)
    for agent in DEFAULT_AGENTS:
        store.upsert_agent(actor="system", **agent)


def seed_demo(store: Store) -> str:
    """Load the SYNAPTIC GROVE example from the spec. Returns the project id."""
    pid = "synaptic_grove"
    store.upsert_project(pid, "SYNAPTIC GROVE", "ACTIVE",
                         "生体組織的な世界観のアセット企画", actor="system")
    facts = [
        ("GR-01 MEMBRANE COMPLETE", ["phase", "milestone"]),
        ("asset budget 7/21", ["constraint", "budget"]),
        ("7 assets adopted", ["asset", "adopted"]),
        ("MEMBRANEと同一組織に見える描画を維持する", ["world", "design"]),
        ("manifest: D:\\projects\\synaptic_grove\\manifest.json", ["file"]),
    ]
    existing = {f["body"] for f in store.list_facts(pid)}
    for body, tags in facts:
        if body not in existing:
            store.add_fact(pid, body, tags=tags, actor="system")
    if not store.list_decisions(pid):
        store.add_decision(
            pid, "CHANNELはパイプや配線に見せない",
            "MEMBRANEと同じ身体組織内の流路として表現する。均一な管状表現は禁止。",
            status="LOCKED", phase="GR-02", tags=["design"], actor="system")
        store.add_decision(pid, "アセット総数は21で固定", "採用済み7。残り14。",
                           status="LOCKED", phase="GR-01", tags=["constraint"],
                           actor="system")
    if not store.state_history(pid):
        store.set_state(pid, "GR-01 MEMBRANE", "COMPLETE", owner="Design AI",
                        actor="system")
        store.set_state(pid, "GR-02 CHANNEL", "IN_PROGRESS", owner="Design AI",
                        deliverables=["CHANNEL assets", "branch rules",
                                      "continuous placement QA", "manifest update",
                                      "GR-02 REPORT"], actor="system")
    store.upsert_handoff("GR-02", pid,
                         "D:\\projects\\synaptic_grove\\handoff\\GR-02.md",
                         title="GR-02 CHANNEL", phase="GR-02", owner="Design AI",
                         status="ACTIVE", actor="system")
    for src, rel, dst in [("GR-02", "depends_on", "GR-01"),
                          ("GR-02", "implemented_by", "codex"),
                          ("GR-02", "designed_by", "design")]:
        store.add_relation(pid, src, rel, dst, actor="system")
    return pid
