"""Drive a run through the nodes until it finishes or pauses.

This is a deliberate hand-rolled loop rather than a graph library. The shape of
a run is a routing decision followed by a fixed, declarative list of steps -
there is no dynamic topology to express, and the one hard requirement, pausing
for approval and resuming later, is served by returning the state and taking it
back. Nodes are plain `(state, context) -> state` functions, so moving to
LangGraph later is a change of driver, not of nodes.
"""

from __future__ import annotations

import logging

from graph import edges, nodes
from graph.context import RunContext
from state.state import Message, RunState, RuntimeContext

log = logging.getLogger(__name__)

# A run visits at most one node per plan step, plus routing and answering.
# The cap is a backstop against a node that never changes the phase.
MAX_TRANSITIONS = 64

NODES = {
    "route": nodes.route,
    "execute": nodes.execute,
    "answer": nodes.answer,
    "fail": nodes.fail,
}


def start(
    question: str,
    user_id: str,
    context: RunContext,
    history: list[Message] | None = None,
    role: str = "user",
) -> RunState:
    state = RunState(
        question=question,
        context=RuntimeContext(user_id=user_id, role=role, history=history or []),
    )
    return drive(state, context)


def resume(state: RunState, context: RunContext, *, choice: str | None = None) -> RunState:
    """Continue a paused run once the user has confirmed or chosen."""
    if not edges.is_paused(state):
        return state
    nodes.approve(state, context, choice=choice)
    return drive(state, context)


def drive(state: RunState, context: RunContext) -> RunState:
    for _ in range(MAX_TRANSITIONS):
        if edges.is_paused(state):
            return state

        name = edges.next_node(state)
        if name is None:
            return state

        state = NODES[name](state, context)

        if name in edges.TERMINAL_AFTER:
            return state

    state.errors.append("run exceeded the transition limit")
    state.phase = "failed"
    return nodes.fail(state, context)
