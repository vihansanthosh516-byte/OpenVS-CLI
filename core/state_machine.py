"""
State Machine Engine — enforces deterministic execution flow.

No agent can skip steps. Every transition is validated.
Recovery loops (PATCH → EXECUTE) are bounded by max_retries.
"""

from enum import Enum
from typing import Optional


class State(Enum):
    INIT = "init"
    PLAN = "plan"
    VALIDATE = "validate"
    EXECUTE = "execute"
    VERIFY = "verify"
    PATCH = "patch"
    DONE = "done"


# Legal transitions — nothing else is allowed
VALID_TRANSITIONS = {
    State.INIT:    [State.PLAN],
    State.PLAN:    [State.VALIDATE],
    State.VALIDATE: [State.EXECUTE, State.PLAN],  # re-plan if invalid
    State.EXECUTE: [State.VERIFY],
    State.VERIFY:  [State.PATCH, State.DONE],
    State.PATCH:   [State.EXECUTE],               # recovery loop
    State.DONE:    [],
}


class TransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class StateMachine:
    """Strict state machine for the orchestrator.

    Rules:
    - Only VALID_TRANSITIONS are allowed
    - PATCH→EXECUTE loops are bounded by max_retries
    - State history is recorded for debugging
    """

    def __init__(self, max_retries: int = 3):
        self.state = State.INIT
        self.max_retries = max_retries
        self.patch_count = 0
        self.history: list[dict] = []

    def transition(self, next_state: State) -> State:
        """Attempt a state transition. Raises TransitionError if illegal."""
        allowed = VALID_TRANSITIONS.get(self.state, [])

        if next_state not in allowed:
            raise TransitionError(
                f"Invalid transition {self.state.value} → {next_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        # Bound recovery loops
        if next_state == State.PATCH:
            self.patch_count += 1
            if self.patch_count > self.max_retries:
                raise TransitionError(
                    f"Max recovery retries ({self.max_retries}) exceeded. "
                    f"Task cannot be completed."
                )

        prev = self.state
        self.state = next_state
        self.history.append({
            "from": prev.value,
            "to": next_state.value,
            "patch_count": self.patch_count,
        })

        return self.state

    def can_transition(self, next_state: State) -> bool:
        """Check if a transition is legal without performing it."""
        return next_state in VALID_TRANSITIONS.get(self.state, [])

    def reset(self):
        """Reset to initial state."""
        self.state = State.INIT
        self.patch_count = 0
        self.history.clear()

    @property
    def current(self) -> State:
        return self.state

    @property
    def is_done(self) -> bool:
        return self.state == State.DONE

    @property
    def step_count(self) -> int:
        return len(self.history)