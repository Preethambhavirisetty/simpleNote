"""Which node runs next, decided only from the phase.

The whole routing table is here so the shape of a run can be read in one
place. Nodes set the phase; nothing else decides where control goes.
"""

from __future__ import annotations

from state.state import RunState


# phase -> node name. "awaiting_approval" is terminal for one invocation: the
# run returns to the caller and only continues when it resumes with a decision.
TRANSITIONS = {
    "routing": "route",
    "executing": "execute",
    "answering": "answer",
    "awaiting_approval": None,
    "failed": "fail",
    "done": None,
}

# Nodes that end the run when they finish.
TERMINAL_AFTER = {"answer", "fail"}


def next_node(state: RunState) -> str | None:
    return TRANSITIONS.get(state.phase)


def is_paused(state: RunState) -> bool:
    return state.phase == "awaiting_approval"


def is_finished(state: RunState) -> bool:
    return state.phase in {"done", "failed"} and state.answer is not None
