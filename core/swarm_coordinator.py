"""
Swarm Coordinator — decomposes tasks into DAGs, dispatches to workers,
collects results, runs consensus, and merges outputs.

This is the master of masters. It sits above the orchestrator
and coordinates multiple agents working on subtasks in parallel.
"""

import time
from typing import Optional

from core.delegation_graph import DelegationGraph, SubtaskNode, NodeState
from core.consensus import consensus, ConsensusStrategy, Vote
from core.policy_engine import policy, CapabilityToken
from core.merge_engine import merge_engine, Patch
from core.event_bus import bus
from core.jobs import Job, JobPriority
from core.queue_manager import queue


class SwarmCoordinator:
    """Coordinates multi-agent task decomposition and execution.

    Pipeline:
      1. Decompose task into subtask DAG
      2. Assign subtasks to workers with capability tokens
      3. Execute subtasks (parallel where possible)
      4. Run consensus on conflicting results
      5. Merge approved patches
      6. Commit final result
    """

    def __init__(self, default_strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED):
        self.consensus_strategy = default_strategy
        self._active_dags: dict[str, DelegationGraph] = {}
        self._tokens: dict[str, CapabilityToken] = {}

    def execute(self, task: str, mode: str = "parallel") -> dict:
        """Execute a task using swarm coordination.

        Args:
            task: The task description
            mode: "parallel", "pipeline", "debate", "map_reduce"

        Returns:
            Final merged result dict
        """
        bus.emit("swarm.start", {"task": task[:100], "mode": mode})

        start_time = time.time()

        # 1. Decompose into DAG
        dag = self._decompose(task, mode)

        # 2. Execute the DAG
        execution_result = self._execute_dag(dag)

        # 3. Collect patches
        patches = execution_result.get("patches", [])

        # 4. Run consensus if there are conflicts
        consensus_result = None
        if len(patches) > 1:
            consensus_result = self._run_consensus(task, patches)

        # 5. Merge patches
        merge_result = merge_engine.merge_patches(patches)

        # 6. Final result
        duration = round((time.time() - start_time) * 1000, 1)

        result = {
            "status": "completed" if not merge_result.get("conflicts") else "conflict",
            "task": task,
            "dag": dag.to_dict(),
            "execution": execution_result,
            "consensus": consensus_result.to_dict() if consensus_result else None,
            "merge": merge_result,
            "duration_ms": duration,
            "mode": mode,
        }

        bus.emit("swarm.complete", {
            "task": task[:100],
            "status": result["status"],
            "duration_ms": duration,
        })

        return result

    def _decompose(self, task: str, mode: str) -> DelegationGraph:
        """Decompose a task into a delegation DAG.

        In production, this would call the planner model.
        Here we create a structured decomposition based on mode.
        """
        dag = DelegationGraph(root_task=task)

        if mode == "parallel":
            # Independent subtasks that can run simultaneously
            analyze_id = dag.add_subtask("Analyze project structure", agent_role="planner")
            code_id = dag.add_subtask("Implement changes", agent_role="coder")
            test_id = dag.add_subtask("Write/update tests", agent_role="tester",
                                       depends_on=[code_id])
            review_id = dag.add_subtask("Review changes", agent_role="critic",
                                         depends_on=[code_id, test_id])
            sec_id = dag.add_subtask("Security review", agent_role="security_auditor",
                                      depends_on=[code_id])

        elif mode == "pipeline":
            # Sequential chain
            step1 = dag.add_subtask("Analyze and plan", agent_role="planner")
            step2 = dag.add_subtask("Implement step 1", agent_role="coder", depends_on=[step1])
            step3 = dag.add_subtask("Implement step 2", agent_role="coder", depends_on=[step2])
            step4 = dag.add_subtask("Test and validate", agent_role="tester", depends_on=[step3])
            dag.add_subtask("Final review", agent_role="critic", depends_on=[step4])

        elif mode == "debate":
            # Two approaches, then consensus
            approach_a = dag.add_subtask("Implement approach A", agent_role="coder")
            approach_b = dag.add_subtask("Implement approach B", agent_role="coder")
            dag.add_subtask("Evaluate approaches", agent_role="critic",
                            depends_on=[approach_a, approach_b])

        elif mode == "map_reduce":
            # Split, process, merge
            split_id = dag.add_subtask("Analyze and split scope", agent_role="planner")
            part1 = dag.add_subtask("Process part 1", agent_role="coder", depends_on=[split_id])
            part2 = dag.add_subtask("Process part 2", agent_role="coder", depends_on=[split_id])
            part3 = dag.add_subtask("Process part 3", agent_role="coder", depends_on=[split_id])
            dag.add_subtask("Merge and validate", agent_role="critic",
                            depends_on=[part1, part2, part3])
        else:
            # Default: single coder task
            dag.add_subtask(task, agent_role="coder")

        self._active_dags[dag.id] = dag
        bus.emit("swarm.decomposed", {"dag_id": dag.id, "nodes": len(dag.nodes)})

        return dag

    def _execute_dag(self, dag: DelegationGraph) -> dict:
        """Execute a delegation DAG by dispatching ready nodes.

        Issues capability tokens for each agent and runs subtasks
        through the worker pool.
        """
        results = []
        patches = []
        max_iterations = 50

        for _ in range(max_iterations):
            if dag.is_complete():
                break

            # Get ready nodes
            ready = dag.ready_nodes()
            if not ready and not dag.running_nodes():
                # No progress possible — mark remaining as failed
                for node in dag.nodes.values():
                    if not node.is_terminal:
                        node.state = NodeState.FAILED
                break

            # Dispatch ready nodes
            for node in ready:
                token = policy.issue_token(node.agent_role, dag.id)
                self._tokens[node.id] = token

                # Submit as job to the queue
                job = Job(
                    task=node.task,
                    priority=JobPriority.from_string(node.priority),
                    metadata={
                        "dag_id": dag.id,
                        "node_id": node.id,
                        "agent_role": node.agent_role,
                        "token_id": token.token_id,
                    },
                )
                queue.submit(job)

                node.state = NodeState.RUNNING
                node.started_at = time.time()

                bus.emit("swarm.node_dispatched", {
                    "dag_id": dag.id,
                    "node_id": node.id,
                    "agent_role": node.agent_role,
                })

            # In a real system, we'd wait for workers to complete.
            # For the MVP, we simulate completion:
            for node in list(dag.nodes.values()):
                if node.state == NodeState.RUNNING:
                    # Simulate completion
                    node.state = NodeState.COMPLETED
                    node.finished_at = time.time()
                    node.result = {"status": "completed", "task": node.task}
                    results.append({
                        "node_id": node.id,
                        "agent_role": node.agent_role,
                        "status": "completed",
                    })

                    bus.emit("swarm.node_completed", {
                        "dag_id": dag.id,
                        "node_id": node.id,
                        "duration_ms": node.duration_ms,
                    })

        return {
            "results": results,
            "patches": patches,
            "progress": dag.progress(),
        }

    def _run_consensus(self, task: str, patches: list[Patch]) -> Optional[object]:
        """Run consensus if there are potentially conflicting patches."""
        # For now, use quick_vote with default agent opinions
        agent_votes = {
            "coder": "approve",
            "critic": "approve",
            "tester": "approve",
        }
        return consensus.quick_vote(task, agent_votes, self.consensus_strategy)

    def get_dag(self, dag_id: str) -> Optional[DelegationGraph]:
        """Retrieve a DAG by ID."""
        return self._active_dags.get(dag_id)

    def list_dags(self) -> list[dict]:
        """List all active DAGs."""
        return [
            {"id": dag.id, "root_task": dag.root_task, "progress": dag.progress()}
            for dag in self._active_dags.values()
        ]

    def stats(self) -> dict:
        """Swarm coordinator statistics."""
        return {
            "active_dags": len(self._active_dags),
            "tokens_issued": len(self._tokens),
            "consensus_strategy": self.consensus_strategy.value,
            "policy_stats": policy.stats(),
            "consensus_stats": consensus.stats(),
        }


# Global singleton
swarm = SwarmCoordinator()