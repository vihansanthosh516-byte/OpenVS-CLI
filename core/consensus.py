"""
Consensus Engine — resolve disagreements between agents.

Strategies:
  - Majority voting: 3/5 agents approve → accepted
  - Weighted authority: critic weight 3, tester weight 2, coder weight 1
  - Debate mode: proposal → counterproposal → rebuttal → judge
  - Critic authority: critic has final say (v11 rule, still default)
"""

import time
from enum import Enum
from typing import Optional
from core.event_bus import bus


class ConsensusStrategy(Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    DEBATE = "debate"
    CRITIC_AUTHORITY = "critic_authority"


# Default weights for weighted voting
ROLE_WEIGHTS = {
    "planner": 1,
    "coder": 1,
    "critic": 3,  # critic has highest authority
    "tester": 2,
    "security_auditor": 2,
}


class Vote:
    """A single agent's vote on a proposal."""

    def __init__(self, agent_role: str, decision: str, reasoning: str = "", weight: int = 1):
        self.agent_role = agent_role
        self.decision = decision  # "approve", "reject", "abstain"
        self.reasoning = reasoning
        self.weight = weight
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "agent_role": self.agent_role,
            "decision": self.decision,
            "reasoning": self.reasoning[:200],
            "weight": self.weight,
        }


class ConsensusResult:
    """The outcome of a consensus round."""

    def __init__(self, proposal: str, strategy: ConsensusStrategy, votes: list[Vote]):
        self.proposal = proposal
        self.strategy = strategy
        self.votes = votes
        self.decision: Optional[str] = None  # "approved" or "rejected"
        self.reasoning = ""
        self.timestamp = time.time()

    def resolve(self) -> str:
        """Compute the final decision based on strategy and votes."""
        if self.strategy == ConsensusStrategy.MAJORITY:
            self.decision = self._majority_vote()
        elif self.strategy == ConsensusStrategy.WEIGHTED:
            self.decision = self._weighted_vote()
        elif self.strategy == ConsensusStrategy.CRITIC_AUTHORITY:
            self.decision = self._critic_authority()
        elif self.strategy == ConsensusStrategy.DEBATE:
            self.decision = self._debate_resolution()
        else:
            self.decision = self._majority_vote()  # fallback

        bus.emit("consensus.resolved", {
            "proposal": self.proposal[:100],
            "strategy": self.strategy.value,
            "decision": self.decision,
            "votes": len(self.votes),
        })

        return self.decision

    def _majority_vote(self) -> str:
        """Simple majority: >50% approve wins."""
        approves = sum(1 for v in self.votes if v.decision == "approve")
        rejects = sum(1 for v in self.votes if v.decision == "reject")
        total = len(self.votes)

        if total == 0:
            self.reasoning = "No votes cast"
            return "rejected"

        if approves > total / 2:
            self.reasoning = f"Majority approves ({approves}/{total})"
            return "approved"
        self.reasoning = f"Majority rejects ({rejects}/{total})"
        return "rejected"

    def _weighted_vote(self) -> str:
        """Weighted voting: sum of weights determines outcome."""
        approve_weight = sum(v.weight for v in self.votes if v.decision == "approve")
        reject_weight = sum(v.weight for v in self.votes if v.decision == "reject")

        if approve_weight > reject_weight:
            self.reasoning = f"Weighted approves ({approve_weight} vs {reject_weight})"
            return "approved"
        self.reasoning = f"Weighted rejects ({reject_weight} vs {approve_weight})"
        return "rejected"

    def _critic_authority(self) -> str:
        """Critic has final say regardless of other votes."""
        critic_votes = [v for v in self.votes if v.agent_role == "critic"]
        if critic_votes:
            critic_decision = critic_votes[0].decision
            self.reasoning = f"Critic authority: {critic_decision}"
            return "approved" if critic_decision == "approve" else "rejected"

        # No critic vote — fall back to weighted
        self.reasoning = "No critic vote, falling back to weighted"
        return self._weighted_vote()

    def _debate_resolution(self) -> str:
        """Debate: if any agent rejects, require majority of remaining to override."""
        rejectors = [v for v in self.votes if v.decision == "reject"]
        if not rejectors:
            self.reasoning = "No objections in debate"
            return "approved"

        # Check if approvers outweigh rejectors (weighted)
        approve_weight = sum(v.weight for v in self.votes if v.decision == "approve")
        reject_weight = sum(v.weight for v in self.votes if v.decision == "reject")

        if approve_weight > reject_weight * 2:  # need 2x weight to override objection
            self.reasoning = f"Debate: objections overridden ({approve_weight} vs {reject_weight})"
            return "approved"
        self.reasoning = f"Debate: objections sustained ({reject_weight} vs {approve_weight})"
        return "rejected"

    def to_dict(self) -> dict:
        return {
            "proposal": self.proposal[:200],
            "strategy": self.strategy.value,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "votes": [v.to_dict() for v in self.votes],
        }


class ConsensusEngine:
    """Manages consensus rounds across agents.

    Usage:
        engine = ConsensusEngine()
        result = engine.vote(
            proposal="Apply patch to auth.py",
            strategy=ConsensusStrategy.WEIGHTED,
            votes=[
                Vote("coder", "approve", "patch looks correct", weight=1),
                Vote("critic", "reject", "missing error handling", weight=3),
                Vote("tester", "approve", "tests pass", weight=2),
            ]
        )
        # result.decision == "rejected" (critic weight wins)
    """

    def __init__(self, default_strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED):
        self.default_strategy = default_strategy
        self._history: list[ConsensusResult] = []

    def vote(
        self,
        proposal: str,
        votes: list[Vote],
        strategy: ConsensusStrategy = None,
    ) -> ConsensusResult:
        """Run a consensus round and return the result."""
        strategy = strategy or self.default_strategy

        result = ConsensusResult(proposal, strategy, votes)
        result.resolve()
        self._history.append(result)

        return result

    def quick_vote(
        self,
        proposal: str,
        agent_votes: dict[str, str],
        strategy: ConsensusStrategy = None,
    ) -> ConsensusResult:
        """Convenience: vote with a simple {role: decision} dict.

        Args:
            agent_votes: {"coder": "approve", "critic": "reject", ...}
        """
        votes = []
        for role, decision in agent_votes.items():
            weight = ROLE_WEIGHTS.get(role, 1)
            votes.append(Vote(role, decision, weight=weight))

        return self.vote(proposal, votes, strategy)

    def history(self, limit: int = 20) -> list[dict]:
        """Return recent consensus results."""
        return [r.to_dict() for r in self._history[-limit:]]

    def stats(self) -> dict:
        """Consensus statistics."""
        total = len(self._history)
        approved = sum(1 for r in self._history if r.decision == "approved")
        return {
            "total_rounds": total,
            "approved": approved,
            "rejected": total - approved,
            "default_strategy": self.default_strategy.value,
        }


# Global singleton
consensus = ConsensusEngine()