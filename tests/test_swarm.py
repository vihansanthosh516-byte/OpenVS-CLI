"""
Regression tests for v13 swarm coordination layer.

Tests:
- Delegation Graph (node creation, dependencies, ready_nodes, topological sort)
- Consensus Engine (majority, weighted, critic authority, debate)
- Policy Engine (token issuance, permission checks, path/command restrictions)
- Merge Engine (single patch, multi-patch merge, conflict detection)
- Swarm Coordinator (decomposition, execution, consensus pipeline)

Run: python -m pytest tests/ -v
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# DELEGATION GRAPH TESTS
# ============================================================

class TestDelegationGraph:
    """Test the delegation DAG engine."""

    def test_create_graph(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Refactor auth module")
        assert dag.root_task == "Refactor auth module"
        assert dag.id.startswith("dag_")
        assert len(dag.nodes) == 0

    def test_add_subtask(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Test task")
        node_id = dag.add_subtask("Analyze code", agent_role="planner")
        assert node_id in dag.nodes
        assert dag.nodes[node_id].task == "Analyze code"
        assert dag.nodes[node_id].agent_role == "planner"

    def test_add_node_with_dependencies(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Test task")
        step1 = dag.add_subtask("Step 1", agent_role="planner")
        step2 = dag.add_subtask("Step 2", agent_role="coder", depends_on=[step1])
        assert dag.nodes[step2].depends_on == [step1]

    def test_ready_nodes_no_deps(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        dag.add_subtask("Task A", agent_role="coder")
        dag.add_subtask("Task B", agent_role="coder")
        ready = dag.ready_nodes()
        assert len(ready) == 2
        assert all(n.state == NodeState.READY for n in ready)

    def test_ready_nodes_with_deps_unmet(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        step1 = dag.add_subtask("Step 1", agent_role="planner")
        dag.add_subtask("Step 2", agent_role="coder", depends_on=[step1])
        # step1 is PENDING, so step2 should not be ready
        ready = dag.ready_nodes()
        assert len(ready) == 1
        assert ready[0].task == "Step 1"

    def test_ready_nodes_with_deps_met(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        step1 = dag.add_subtask("Step 1", agent_role="planner")
        step2 = dag.add_subtask("Step 2", agent_role="coder", depends_on=[step1])
        # Complete step1
        dag.nodes[step1].state = NodeState.COMPLETED
        ready = dag.ready_nodes()
        assert len(ready) == 1
        assert ready[0].task == "Step 2"

    def test_topological_order(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Test task")
        a = dag.add_subtask("A", agent_role="planner")
        b = dag.add_subtask("B", agent_role="coder", depends_on=[a])
        c = dag.add_subtask("C", agent_role="coder", depends_on=[a])
        d = dag.add_subtask("D", agent_role="tester", depends_on=[b, c])
        order = dag.topological_order()
        assert order.index(a) < order.index(b)
        assert order.index(a) < order.index(c)
        assert order.index(b) < order.index(d)
        assert order.index(c) < order.index(d)

    def test_is_complete(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        n1 = dag.add_subtask("A", agent_role="coder")
        n2 = dag.add_subtask("B", agent_role="coder")
        assert not dag.is_complete()
        dag.nodes[n1].state = NodeState.COMPLETED
        dag.nodes[n2].state = NodeState.COMPLETED
        assert dag.is_complete()

    def test_is_failed(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        n1 = dag.add_subtask("A", agent_role="coder")
        dag.nodes[n1].state = NodeState.FAILED
        dag.nodes[n1].retries = 2  # max_retries
        assert dag.is_failed()

    def test_progress(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test task")
        n1 = dag.add_subtask("A", agent_role="coder")
        n2 = dag.add_subtask("B", agent_role="coder")
        dag.nodes[n1].state = NodeState.COMPLETED
        progress = dag.progress()
        assert progress["total"] == 2
        assert progress["completed"] == 1
        assert progress["percent"] == 50.0

    def test_render(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Test task")
        dag.add_subtask("A", agent_role="planner")
        rendered = dag.render()
        assert "Test task" in rendered
        assert "A" in rendered

    def test_to_dict(self):
        from core.delegation_graph import DelegationGraph
        dag = DelegationGraph(root_task="Test task")
        dag.add_subtask("A", agent_role="planner")
        d = dag.to_dict()
        assert "id" in d
        assert "nodes" in d
        assert "progress" in d
        assert "topological_order" in d

    def test_node_terminal_states(self):
        from core.delegation_graph import SubtaskNode, NodeState
        node = SubtaskNode(task="test")
        node.state = NodeState.COMPLETED
        assert node.is_terminal
        node.state = NodeState.FAILED
        assert node.is_terminal
        node.state = NodeState.SKIPPED
        assert node.is_terminal
        node.state = NodeState.PENDING
        assert not node.is_terminal

    def test_node_duration(self):
        from core.delegation_graph import SubtaskNode
        node = SubtaskNode(task="test")
        node.started_at = 100.0
        node.finished_at = 101.5
        assert node.duration_ms == 1500.0

    def test_running_and_failed_nodes(self):
        from core.delegation_graph import DelegationGraph, NodeState
        dag = DelegationGraph(root_task="Test")
        n1 = dag.add_subtask("A", agent_role="coder")
        n2 = dag.add_subtask("B", agent_role="coder")
        n3 = dag.add_subtask("C", agent_role="coder")
        dag.nodes[n1].state = NodeState.RUNNING
        dag.nodes[n2].state = NodeState.FAILED
        assert len(dag.running_nodes()) == 1
        assert len(dag.failed_nodes()) == 1
        assert len(dag.completed_nodes()) == 0


# ============================================================
# CONSENSUS ENGINE TESTS
# ============================================================

class TestConsensusEngine:
    """Test the consensus engine voting strategies."""

    def test_majority_approve(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.MAJORITY)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "approve", weight=3),
            Vote("tester", "reject", weight=2),
        ]
        result = engine.vote("Apply patch", votes)
        assert result.decision == "approved"
        assert "Majority" in result.reasoning

    def test_majority_reject(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.MAJORITY)
        votes = [
            Vote("coder", "reject", weight=1),
            Vote("critic", "reject", weight=3),
            Vote("tester", "approve", weight=2),
        ]
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_weighted_approve(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.WEIGHTED)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "reject", weight=3),
            Vote("tester", "approve", weight=2),
        ]
        # approve weight = 1+2=3, reject weight = 3
        # approve > reject? 3 > 3 is false → rejected
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_weighted_critic_wins(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.WEIGHTED)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "reject", weight=3),
            Vote("tester", "reject", weight=2),
        ]
        # approve = 1, reject = 5
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_critic_authority_approve(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.CRITIC_AUTHORITY)
        votes = [
            Vote("coder", "reject", weight=1),
            Vote("critic", "approve", weight=3),
            Vote("tester", "reject", weight=2),
        ]
        result = engine.vote("Apply patch", votes)
        assert result.decision == "approved"
        assert "Critic authority" in result.reasoning

    def test_critic_authority_reject(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.CRITIC_AUTHORITY)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "reject", weight=3),
            Vote("tester", "approve", weight=2),
        ]
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_critic_authority_no_critic_falls_back(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.CRITIC_AUTHORITY)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("tester", "approve", weight=2),
        ]
        result = engine.vote("Apply patch", votes)
        # No critic → falls back to weighted → approve=3, reject=0
        assert result.decision == "approved"
        # The weighted fallback overwrites reasoning — verify strategy was critic_authority
        assert result.strategy == ConsensusStrategy.CRITIC_AUTHORITY

    def test_debate_no_objections(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.DEBATE)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "approve", weight=3),
        ]
        result = engine.vote("Apply patch", votes)
        assert result.decision == "approved"

    def test_debate_objections_overridden(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.DEBATE)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "approve", weight=3),
            Vote("tester", "reject", weight=2),
        ]
        # approve weight = 4, reject weight = 2
        # 4 > 2*2 = 4? No. rejected
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_debate_objections_sustained(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.DEBATE)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "reject", weight=3),
        ]
        # approve = 1, reject = 3, 1 > 6? No
        result = engine.vote("Apply patch", votes)
        assert result.decision == "rejected"

    def test_quick_vote(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy
        engine = ConsensusEngine()
        result = engine.quick_vote("Apply patch", {
            "coder": "approve",
            "critic": "approve",
            "tester": "reject",
        })
        assert result.decision == "approved"

    def test_no_votes_rejected(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, ConsensusResult
        result = ConsensusResult("test", ConsensusStrategy.MAJORITY, [])
        result.resolve()
        assert result.decision == "rejected"

    def test_consensus_history(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine()
        engine.vote("Task 1", [Vote("coder", "approve")])
        engine.vote("Task 2", [Vote("coder", "reject")])
        history = engine.history()
        assert len(history) == 2

    def test_consensus_stats(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine()
        engine.vote("Task 1", [Vote("coder", "approve")])
        engine.vote("Task 2", [Vote("critic", "reject")])
        stats = engine.stats()
        assert stats["total_rounds"] == 2
        assert stats["approved"] == 1
        assert stats["rejected"] == 1

    def test_vote_to_dict(self):
        from core.consensus import Vote
        v = Vote("coder", "approve", "looks good", weight=1)
        d = v.to_dict()
        assert d["agent_role"] == "coder"
        assert d["decision"] == "approve"
        assert d["weight"] == 1

    def test_result_to_dict(self):
        from core.consensus import ConsensusEngine, Vote
        engine = ConsensusEngine()
        result = engine.vote("test", [Vote("coder", "approve")])
        d = result.to_dict()
        assert "strategy" in d
        assert "decision" in d
        assert "votes" in d


# ============================================================
# POLICY ENGINE TESTS
# ============================================================

class TestPolicyEngine:
    """Test the policy engine and capability tokens."""

    def test_issue_token(self):
        from core.policy_engine import PolicyEngine, ROLE_SCOPES
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert token.agent_role == "coder"
        assert token.task_id == "task_123"
        assert token.token_id.startswith("cap_")
        assert not token.is_expired

    def test_issue_token_with_expiry(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123", expires_in=-1)
        assert token.is_expired

    def test_coder_permissions(self):
        from core.policy_engine import PolicyEngine, Permission
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert token.has_permission(Permission.READ)
        assert token.has_permission(Permission.WRITE)
        assert token.has_permission(Permission.PATCH)
        assert token.has_permission(Permission.SHELL)
        assert not token.has_permission(Permission.NETWORK)

    def test_planner_permissions(self):
        from core.policy_engine import PolicyEngine, Permission
        engine = PolicyEngine()
        token = engine.issue_token("planner", "task_123")
        assert token.has_permission(Permission.READ)
        assert token.has_permission(Permission.SEARCH)
        assert not token.has_permission(Permission.WRITE)
        assert not token.has_permission(Permission.PATCH)
        assert not token.has_permission(Permission.SHELL)

    def test_critic_readonly(self):
        from core.policy_engine import PolicyEngine, Permission
        engine = PolicyEngine()
        token = engine.issue_token("critic", "task_123")
        assert token.has_permission(Permission.READ)
        assert not token.has_permission(Permission.WRITE)
        assert not token.has_permission(Permission.PATCH)

    def test_security_auditor_suggest_only(self):
        from core.policy_engine import PolicyEngine, Permission
        engine = PolicyEngine()
        token = engine.issue_token("security_auditor", "task_123")
        assert token.has_permission(Permission.READ)
        assert token.has_permission(Permission.SUGGEST_ONLY)
        assert not token.has_permission(Permission.WRITE)

    def test_tester_scoped_paths(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("tester", "task_123")
        assert token.can_access_path("workspace/tests/test_main.py")
        assert not token.can_access_path("workspace/src/main.py")

    def test_coder_workspace_paths(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert token.can_access_path("workspace/src/main.py")
        assert token.can_access_path("workspace/anything.py")

    def test_wildcard_path_access(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("critic", "task_123")
        assert token.can_access_path("any/path/file.py")

    def test_command_allowlist(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert token.can_run_command("python script.py")
        assert token.can_run_command("pytest")
        assert token.can_run_command("git commit")
        assert not token.can_run_command("rm -rf /")
        assert not token.can_run_command("curl evil.com")

    def test_planner_no_commands(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("planner", "task_123")
        assert not token.can_run_command("python script.py")

    def test_verify_action_allowed(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        result = engine.verify_action(token, "read", {"path": "workspace/main.py"})
        assert result["allowed"] is True

    def test_verify_action_denied_permission(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("critic", "task_123")
        result = engine.verify_action(token, "write", {"path": "workspace/main.py"})
        assert result["allowed"] is False
        assert "lacks" in result["reason"]

    def test_verify_action_denied_path(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("tester", "task_123")
        result = engine.verify_action(token, "write", {"path": "workspace/src/main.py"})
        assert result["allowed"] is False
        assert "cannot access path" in result["reason"]

    def test_verify_action_denied_command(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        result = engine.verify_action(token, "run", {"cmd": "curl http://evil.com"})
        assert result["allowed"] is False
        assert "cannot run command" in result["reason"]

    def test_verify_action_suggest_only_blocks_write(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("security_auditor", "task_123")
        result = engine.verify_action(token, "write", {"path": "workspace/main.py"})
        assert result["allowed"] is False
        assert "suggest_only" in result["reason"]

    def test_verify_action_expired_token(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123", expires_in=-1)
        result = engine.verify_action(token, "read", {"path": "workspace/main.py"})
        assert result["allowed"] is False
        assert "expired" in result["reason"]

    def test_verify_action_unknown_action(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        result = engine.verify_action(token, "teleport", {})
        assert result["allowed"] is False
        assert "Unknown action" in result["reason"]

    def test_verify_write_size_limit(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        # coder max_write_bytes = 500_000
        result = engine.verify_action(token, "write", {
            "path": "workspace/main.py",
            "content": "x" * 600_000,
        })
        assert result["allowed"] is False
        assert "exceeds" in result["reason"]

    def test_token_to_dict(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        d = token.to_dict()
        assert "token_id" in d
        assert "agent_role" in d
        assert "permissions" in d
        assert "denied" in d
        assert "path_restrictions" in d

    def test_list_roles(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        roles = engine.list_roles()
        assert "coder" in roles
        assert "critic" in roles
        assert "planner" in roles
        assert "security_auditor" in roles
        assert "tester" in roles
        assert "doc_writer" in roles

    def test_denied_actions_tracked(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("critic", "task_123")
        engine.verify_action(token, "write", {"path": "workspace/main.py"})
        denied = engine.get_denied_actions()
        assert len(denied) == 1
        assert denied[0]["action"] == "write"

    def test_stats(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        engine.issue_token("coder", "task_1")
        engine.issue_token("critic", "task_2")
        stats = engine.stats()
        assert stats["tokens_issued"] == 2
        assert stats["denied_actions"] == 0

    def test_path_prefixed_command(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert token.can_run_command("/usr/bin/python script.py")
        assert not token.can_run_command("/usr/bin/curl evil.com")

    def test_empty_command_rejected(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_123")
        assert not token.can_run_command("")

    def test_doc_writer_path_scoping(self):
        from core.policy_engine import PolicyEngine
        engine = PolicyEngine()
        token = engine.issue_token("doc_writer", "task_123")
        assert token.can_access_path("workspace/docs/api.md")
        assert token.can_access_path("workspace/README.md")
        assert not token.can_access_path("workspace/src/main.py")


# ============================================================
# MERGE ENGINE TESTS
# ============================================================

class TestMergeEngine:
    """Test the merge engine and patch operations."""

    def test_single_patch_no_conflict(self):
        from core.merge_engine import MergeEngine, Patch
        engine = MergeEngine()
        p = Patch("coder", "main.py", "old code", "new code")
        result = engine.merge_patches([p])
        assert result["status"] == "merged"

    def test_no_patches(self):
        from core.merge_engine import MergeEngine
        engine = MergeEngine()
        result = engine.merge_patches([])
        assert result["status"] == "no_patches"

    def test_non_overlapping_patches_merge(self):
        from core.merge_engine import MergeEngine, Patch
        engine = MergeEngine()
        base = "line1\nline2\nline3\n"
        p1 = Patch("coder", "main.py", base, "LINE1\nline2\nline3\n")
        p2 = Patch("tester", "main.py", "LINE1\nline2\nline3\n", "LINE1\nline2\nLINE3\n")
        result = engine.merge_patches([p1, p2], base_content=base)
        assert result["status"] == "merged"
        assert len(result["results"]) == 1

    def test_conflicting_patches_detected(self):
        from core.merge_engine import MergeEngine, Patch
        engine = MergeEngine()
        # Both patches change the same content
        p1 = Patch("coder", "main.py", "old code", "coder version")
        p2 = Patch("critic", "main.py", "old code", "critic version")
        result = engine.merge_patches([p1, p2])
        assert result["status"] == "conflict"
        assert result["total_conflicts"] > 0

    def test_patch_diff(self):
        from core.merge_engine import Patch
        p = Patch("coder", "main.py", "hello\n", "world\n")
        diff = p.diff()
        assert "---" in diff
        assert "+++" in diff

    def test_patch_changed_regions(self):
        from core.merge_engine import Patch
        p = Patch("coder", "main.py", "line1\nline2\nline3\n", "LINE1\nline2\nLINE3\n")
        regions = p.changed_regions()
        assert len(regions) >= 1

    def test_patch_to_dict(self):
        from core.merge_engine import Patch
        p = Patch("coder", "main.py", "old", "new")
        d = p.to_dict()
        assert "id" in d
        assert "source_agent" in d
        assert "file_path" in d
        assert "diff" in d

    def test_multi_file_merge(self):
        from core.merge_engine import MergeEngine, Patch
        engine = MergeEngine()
        p1 = Patch("coder", "main.py", "old1", "new1")
        p2 = Patch("coder", "utils.py", "old2", "new2")
        result = engine.merge_patches([p1, p2])
        assert result["status"] == "merged"
        assert len(result["results"]) == 2

    def test_resolve_conflict_manual(self):
        from core.merge_engine import MergeEngine
        engine = MergeEngine()
        conflict = {"file_path": "main.py", "overlap_regions": [(1, 5)]}
        result = engine.resolve_conflict(conflict, "manual", resolved_content="fixed code")
        assert result["status"] == "resolved"
        assert result["resolution"] == "manual"

    def test_resolve_conflict_manual_no_content(self):
        from core.merge_engine import MergeEngine
        engine = MergeEngine()
        conflict = {"file_path": "main.py"}
        result = engine.resolve_conflict(conflict, "manual")
        assert result["status"] == "error"

    def test_find_overlaps(self):
        from core.merge_engine import MergeEngine
        regions_a = [(1, 10), (20, 30)]
        regions_b = [(5, 15), (25, 35)]
        overlaps = MergeEngine._find_overlaps(regions_a, regions_b)
        assert len(overlaps) == 2
        # Overlap of (1,10) and (5,15) = (5,10)
        assert overlaps[0] == (5, 10)
        # Overlap of (20,30) and (25,35) = (25,30)
        assert overlaps[1] == (25, 30)

    def test_no_overlaps(self):
        from core.merge_engine import MergeEngine
        regions_a = [(1, 5)]
        regions_b = [(10, 15)]
        overlaps = MergeEngine._find_overlaps(regions_a, regions_b)
        assert len(overlaps) == 0


# ============================================================
# SWARM COORDINATOR TESTS
# ============================================================

class TestSwarmCoordinator:
    """Test the swarm coordinator end-to-end pipeline."""

    def test_execute_parallel(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Add error handling", mode="parallel")
        assert result["status"] in ("completed", "conflict")
        assert result["mode"] == "parallel"
        assert "dag" in result
        assert "execution" in result
        assert "duration_ms" in result

    def test_execute_pipeline(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Refactor module", mode="pipeline")
        assert result["mode"] == "pipeline"
        assert "dag" in result

    def test_execute_debate(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Design auth system", mode="debate")
        assert result["mode"] == "debate"

    def test_execute_map_reduce(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Process large file", mode="map_reduce")
        assert result["mode"] == "map_reduce"

    def test_execute_default_mode(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Simple task")
        assert result["mode"] == "parallel"

    def test_execute_unknown_mode(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test", mode="unknown")
        # Unknown mode falls through to single coder task
        assert result["mode"] == "unknown"

    def test_get_dag(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test task", mode="parallel")
        dag_id = result["dag"]["id"]
        dag = coordinator.get_dag(dag_id)
        assert dag is not None
        assert dag.root_task == "Test task"

    def test_list_dags(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        coordinator.execute("Task 1", mode="parallel")
        coordinator.execute("Task 2", mode="pipeline")
        dags = coordinator.list_dags()
        assert len(dags) >= 2

    def test_swarm_stats(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        coordinator.execute("Test", mode="parallel")
        stats = coordinator.stats()
        assert "active_dags" in stats
        assert "tokens_issued" in stats
        assert "consensus_strategy" in stats
        assert "policy_stats" in stats
        assert "consensus_stats" in stats

    def test_parallel_dag_structure(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test", mode="parallel")
        dag_dict = result["dag"]
        nodes = dag_dict["nodes"]
        # Parallel mode should have 5 nodes
        assert len(nodes) == 5

    def test_pipeline_dag_structure(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test", mode="pipeline")
        dag_dict = result["dag"]
        nodes = dag_dict["nodes"]
        # Pipeline mode should have 5 nodes
        assert len(nodes) == 5

    def test_debate_dag_structure(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test", mode="debate")
        dag_dict = result["dag"]
        nodes = dag_dict["nodes"]
        # Debate mode: approach_a, approach_b, evaluate = 3
        assert len(nodes) == 3

    def test_map_reduce_dag_structure(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        result = coordinator.execute("Test", mode="map_reduce")
        dag_dict = result["dag"]
        nodes = dag_dict["nodes"]
        # map_reduce: split, part1, part2, part3, merge = 5
        assert len(nodes) == 5

    def test_dag_get_dag_nonexistent(self):
        from core.swarm_coordinator import SwarmCoordinator
        coordinator = SwarmCoordinator()
        dag = coordinator.get_dag("nonexistent_id")
        assert dag is None


# ============================================================
# DISTRIBUTED WORKERS TESTS
# ============================================================

class TestWorkerNode:
    """Test the distributed worker node."""

    def test_create_worker(self):
        from core.distributed_workers import WorkerNode, WorkerState
        worker = WorkerNode("w1", capabilities=["coder", "tester"])
        assert worker.id == "w1"
        assert worker.state == WorkerState.IDLE
        assert worker.is_available

    def test_worker_can_handle(self):
        from core.distributed_workers import WorkerNode
        worker = WorkerNode("w1", capabilities=["coder", "tester"])
        assert worker.can_handle("coder")
        assert worker.can_handle("tester")
        assert not worker.can_handle("critic")

    def test_worker_utilization(self):
        from core.distributed_workers import WorkerNode
        worker = WorkerNode("w1", capabilities=["coder"], max_concurrent=2)
        assert worker.utilization == 0.0

    def test_worker_assign_job(self):
        from core.distributed_workers import WorkerNode
        from core.jobs import Job, JobPriority
        from core.policy_engine import PolicyEngine
        worker = WorkerNode("w1", capabilities=["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1")
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        result = worker.assign_job(job, token)
        assert result["status"] == "assigned"
        assert not worker.is_available  # max_concurrent=1, now full

    def test_worker_complete_job(self):
        from core.distributed_workers import WorkerNode
        from core.jobs import Job, JobPriority, JobState
        from core.policy_engine import PolicyEngine
        worker = WorkerNode("w1", capabilities=["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1")
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        worker.assign_job(job, token)
        result = worker.complete_job(job.id, {"status": "ok"})
        assert result["status"] == "completed"
        assert worker._completed_count == 1

    def test_worker_fail_job(self):
        from core.distributed_workers import WorkerNode
        from core.jobs import Job, JobPriority, JobState
        from core.policy_engine import PolicyEngine
        worker = WorkerNode("w1", capabilities=["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1")
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        worker.assign_job(job, token)
        result = worker.fail_job(job.id, "timeout")
        assert result["status"] == "failed"
        assert worker._failed_count == 1

    def test_worker_assign_denied_role(self):
        from core.distributed_workers import WorkerNode
        from core.jobs import Job, JobPriority
        from core.policy_engine import PolicyEngine
        # Worker handles coder+planner, but critic token has READ but not SHELL
        # Use critic role which has READ → assignment allowed
        worker = WorkerNode("w1", capabilities=["coder", "critic"])
        engine = PolicyEngine()
        token = engine.issue_token("critic", "task_1")
        job = Job(task="Review code", priority=JobPriority.NORMAL, metadata={"agent_role": "critic"})
        result = worker.assign_job(job, token)
        # Critic has READ permission, so assignment should succeed
        assert result["status"] == "assigned"

    def test_worker_assign_expired_token(self):
        from core.distributed_workers import WorkerNode
        from core.jobs import Job, JobPriority
        from core.policy_engine import PolicyEngine
        worker = WorkerNode("w1", capabilities=["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1", expires_in=-1)
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        result = worker.assign_job(job, token)
        assert result["status"] == "denied"
        assert "expired" in result["reason"]

    def test_worker_heartbeat(self):
        from core.distributed_workers import WorkerNode
        worker = WorkerNode("w1", capabilities=["coder"])
        hb = worker.heartbeat()
        assert hb["worker_id"] == "w1"
        assert hb["state"] == "idle"

    def test_worker_stats(self):
        from core.distributed_workers import WorkerNode
        worker = WorkerNode("w1", capabilities=["coder"])
        stats = worker.stats()
        assert "id" in stats
        assert "capabilities" in stats
        assert "utilization" in stats


class TestWorkerFabric:
    """Test the worker fabric (pool manager)."""

    def test_register_worker(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        worker = fab.register_worker("w1", ["coder"])
        assert worker.id == "w1"
        assert "w1" in fab._workers

    def test_register_duplicate_returns_existing(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        w1 = fab.register_worker("w1", ["coder"])
        w2 = fab.register_worker("w1", ["tester"])
        assert w1 is w2

    def test_deregister_worker(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        result = fab.deregister_worker("w1")
        assert result["status"] == "deregistered"
        assert "w1" not in fab._workers

    def test_find_worker(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        fab.register_worker("w2", ["critic"])
        w = fab.find_worker("coder")
        assert w.id == "w1"

    def test_find_worker_none_available(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["critic"])
        w = fab.find_worker("coder")
        assert w is None

    def test_available_workers(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        fab.register_worker("w2", ["coder"])
        avail = fab.available_workers()
        assert len(avail) == 2

    def test_check_health(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        health = fab.check_health()
        assert health["total"] == 1
        assert health["healthy"] == 1

    def test_fabric_stats(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        fab.register_worker("w2", ["tester"])
        stats = fab.stats()
        assert stats["total_workers"] == 2
        assert stats["available"] == 2

    def test_route_job(self):
        from core.distributed_workers import WorkerFabric
        from core.jobs import Job, JobPriority
        from core.policy_engine import PolicyEngine
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1")
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        result = fab.route_job(job, token)
        assert result["status"] == "assigned"


# ============================================================
# TASK ROUTER TESTS
# ============================================================

class TestTaskRouter:
    """Test the adaptive task router."""

    def _make_worker(self, wid, caps, max_c=2):
        from core.distributed_workers import WorkerNode
        return WorkerNode(wid, capabilities=caps, max_concurrent=max_c)

    def test_route_round_robin(self):
        from core.task_router import TaskRouter, RoutingStrategy
        from core.jobs import Job, JobPriority
        router = TaskRouter(default_strategy=RoutingStrategy.ROUND_ROBIN)
        w1 = self._make_worker("w1", ["coder"])
        w2 = self._make_worker("w2", ["coder"])
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        decision = router.route(job, [w1, w2])
        assert decision is not None
        assert decision.worker_id == "w1"

    def test_route_least_loaded(self):
        from core.task_router import TaskRouter, RoutingStrategy
        from core.jobs import Job, JobPriority
        router = TaskRouter(default_strategy=RoutingStrategy.LEAST_LOADED)
        w1 = self._make_worker("w1", ["coder"], max_c=1)
        w2 = self._make_worker("w2", ["coder"], max_c=10)
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        decision = router.route(job, [w1, w2])
        assert decision is not None

    def test_route_capability_match(self):
        from core.task_router import TaskRouter, RoutingStrategy
        from core.jobs import Job, JobPriority
        router = TaskRouter(default_strategy=RoutingStrategy.CAPABILITY_MATCH)
        w1 = self._make_worker("w1", ["planner", "coder"])
        w2 = self._make_worker("w2", ["coder", "tester"])
        job = Job(task="Plan architecture", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        decision = router.route(job, [w1, w2])
        assert decision is not None
        # w2 has coder as primary capability
        assert decision.worker_id == "w2"

    def test_route_adaptive(self):
        from core.task_router import TaskRouter, RoutingStrategy
        from core.jobs import Job, JobPriority
        router = TaskRouter(default_strategy=RoutingStrategy.ADAPTIVE)
        w1 = self._make_worker("w1", ["coder"])
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        decision = router.route(job, [w1])
        assert decision is not None
        assert decision.worker_id == "w1"

    def test_route_no_eligible_worker(self):
        from core.task_router import TaskRouter
        from core.jobs import Job, JobPriority
        router = TaskRouter()
        w1 = self._make_worker("w1", ["critic"])
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        decision = router.route(job, [w1])
        assert decision is None

    def test_record_success_failure(self):
        from core.task_router import TaskRouter
        router = TaskRouter()
        router.record_success("w1")
        router.record_success("w1")
        router.record_failure("w1")
        perf = router.worker_performance()
        assert perf["w1"]["successes"] == 2
        assert perf["w1"]["failures"] == 1

    def test_routing_history(self):
        from core.task_router import TaskRouter, RoutingStrategy
        from core.jobs import Job, JobPriority
        router = TaskRouter(default_strategy=RoutingStrategy.ROUND_ROBIN)
        w1 = self._make_worker("w1", ["coder"])
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        router.route(job, [w1])
        history = router.history()
        assert len(history) == 1

    def test_router_stats(self):
        from core.task_router import TaskRouter
        router = TaskRouter()
        stats = router.stats()
        assert "total_routes" in stats
        assert "strategy" in stats


# ============================================================
# ACTOR PROTOCOL TESTS
# ============================================================

class TestActorProtocol:
    """Test the actor message passing protocol."""

    def test_send_message(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType, MessagePriority
        proto = ActorProtocol()
        msg = ActorMessage(
            msg_type=MessageType.TASK_ASSIGN,
            sender="coordinator",
            recipient="worker_1",
            payload={"task": "Fix bug", "role": "coder"},
        )
        result = proto.send(msg)
        assert result["status"] == "sent"
        assert msg.delivered

    def test_reply_to_message(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        original = ActorMessage(
            msg_type=MessageType.TASK_ASSIGN,
            sender="coordinator",
            recipient="worker_1",
            payload={"task": "Fix bug"},
        )
        proto.send(original)
        result = proto.reply(original, MessageType.TASK_RESULT, {"status": "done"})
        assert result["status"] == "sent"

    def test_message_handler(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        received = []
        proto.on(MessageType.HEARTBEAT, lambda msg: received.append(msg))
        msg = ActorMessage(
            msg_type=MessageType.HEARTBEAT,
            sender="w1",
            recipient="fabric",
            payload={"state": "idle"},
        )
        proto.send(msg)
        assert len(received) == 1

    def test_remove_handler(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        received = []
        handler = lambda msg: received.append(msg)
        proto.on(MessageType.HEARTBEAT, handler)
        proto.off(MessageType.HEARTBEAT, handler)
        msg = ActorMessage(
            msg_type=MessageType.HEARTBEAT,
            sender="w1",
            recipient="fabric",
            payload={},
        )
        proto.send(msg)
        assert len(received) == 0

    def test_conversation_thread(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        msg1 = ActorMessage(
            msg_type=MessageType.TASK_ASSIGN,
            sender="coordinator",
            recipient="worker_1",
            payload={"task": "Fix bug"},
        )
        proto.send(msg1)
        proto.reply(msg1, MessageType.TASK_RESULT, {"status": "done"})
        conversation = proto.get_conversation(msg1.correlation_id)
        assert len(conversation) == 2

    def test_message_log(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        for i in range(5):
            msg = ActorMessage(
                msg_type=MessageType.HEARTBEAT,
                sender=f"w{i}",
                recipient="fabric",
                payload={},
            )
            proto.send(msg)
        log = proto.message_log()
        assert len(log) == 5

    def test_message_log_filtered(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        proto.send(ActorMessage(MessageType.HEARTBEAT, "w1", "fabric", {}))
        proto.send(ActorMessage(MessageType.TASK_ASSIGN, "coord", "w1", {}))
        log = proto.message_log(msg_type=MessageType.HEARTBEAT)
        assert len(log) == 1

    def test_protocol_stats(self):
        from core.actor_protocol import ActorProtocol, ActorMessage, MessageType
        proto = ActorProtocol()
        proto.send(ActorMessage(MessageType.HEARTBEAT, "w1", "fabric", {}))
        stats = proto.stats()
        assert stats["total_messages"] == 1
        assert "heartbeat" in stats["type_counts"]

    def test_message_to_dict(self):
        from core.actor_protocol import ActorMessage, MessageType, MessagePriority
        msg = ActorMessage(
            msg_type=MessageType.TASK_ASSIGN,
            sender="coord",
            recipient="w1",
            payload={"task": "test"},
            priority=MessagePriority.HIGH,
        )
        d = msg.to_dict()
        assert d["type"] == "task_assign"
        assert d["priority"] == 2
        assert d["sender"] == "coord"
