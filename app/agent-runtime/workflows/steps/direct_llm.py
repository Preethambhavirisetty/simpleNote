"""Answer straight from the model, with no retrieval and no tools."""

from __future__ import annotations

from integrations.llm import llm_call_general
from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from integrations import observability as obs
from utils import load_prompt
from workflows.steps.base import StepContext, failed


MAX_TOKENS = 800
TEMPERATURE = 0.3
MAX_HISTORY = 8


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    prompt = load_prompt("direct_llm")
    messages = [{"role": "system", "content": prompt["system"]}]
    messages += [
        {"role": message.role, "content": message.content}
        for message in state.context.history[-MAX_HISTORY:]
    ]
    messages.append({"role": "user", "content": state.question})

    with obs.timed("direct_llm", "llm answer") as timer:
        answer = llm_call_general(
            messages, max_tokens=MAX_TOKENS, temperature=TEMPERATURE
        ).strip()
        timer.track(answer_chars=len(answer), history_turns=len(state.context.history))
    if not answer:
        return failed(step, "the model returned an empty answer")

    state.answer = answer
    return StepRun(step=step.step, output=answer)
