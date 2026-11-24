"""Remote agent steps for the case-orchestrator (design D2, D4).

`Dispatcher.node(agent)` is a workflow function node with the agent's name. Placed in the ADK
Workflow where the agent was, it enqueues a step job on the agent's LDU, waits for it, applies the
returned state delta to the case session, and outputs the agent's text, so the next node gets
exactly the input it got before. Order, joins, routes and merges stay in the Workflow, and the
orchestrator's Runner stays the only writer to the case session."""
import contextvars

from google.adk.agents import Context
from google.adk.utils.content_utils import to_user_content
from google.adk.workflow._function_node import FunctionNode

from ..tools._common import plain
from .manifest import Manifest, get_manifest
from .queue import FAILED, StepQueue
from .worker import jsonable

current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_run", default=None)


class StepFailed(RuntimeError):
    def __init__(self, agent: str, error: str):
        super().__init__(f"step {agent} failed: {error}")
        self.agent, self.error = agent, error


def input_text(ctx: Context, node_input) -> str:
    """What an agent node would have received as its user message (ADK's LlmAgent wrapper):
    the previous node's output, or the run's user content when there is none."""
    content = to_user_content(node_input) if node_input is not None else getattr(ctx, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(p, "text", "") or "" for p in parts)


class Observer:
    """Hooks for run tracking (current step, waiting-on-LDU). Default: no-op."""

    async def dispatched(self, run_id: str, case_id: str, ldu: str, agent: str): ...
    async def finished(self, run_id: str, case_id: str, ldu: str, agent: str, ok: bool): ...


class Dispatcher:
    def __init__(self, queue: StepQueue, manifest: Manifest | None = None, observer: Observer | None = None,
                 timeout: float | None = None):
        self.queue = queue
        self.manifest = manifest or get_manifest()
        self.observer = observer or Observer()
        self.timeout = timeout

    def node(self, agent: str) -> FunctionNode:
        ldu = self.manifest.ldu_of(agent).name

        async def step(ctx: Context, node_input=None):
            run_id = current_run.get() or ctx.invocation_id
            case_id = ctx.session.id
            payload = {"state": jsonable(plain(ctx.state)), "input": input_text(ctx, node_input)}
            jid = await self.queue.enqueue(run_id, case_id, ldu, agent, payload)
            await self.observer.dispatched(run_id, case_id, ldu, agent)
            job = await self.queue.wait(jid, self.timeout)
            await self.observer.finished(run_id, case_id, ldu, agent, job.state != FAILED)
            if job.state == FAILED:
                raise StepFailed(agent, job.error or "unknown error")
            for k, v in (job.result.get("delta") or {}).items():
                ctx.state[k] = v
            return job.result.get("output")

        step.__name__ = agent
        return FunctionNode(func=step, name=agent)
