"""A scripted model so the agent mesh can be tested without a real LLM. Each agent gets its own
script: a list of (tool_name, args) calls issued one per model turn, then a final text answer."""
from typing import AsyncGenerator

from google.adk.models import BaseLlm, LlmResponse
from google.genai import types


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    calls: list = []
    final: str = "done"
    seen_instructions: list = []

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        si = getattr(llm_request.config, "system_instruction", None)
        self.seen_instructions.append(si if isinstance(si, str) else str(si))
        step = sum(1 for c in llm_request.contents or [] for p in c.parts or []
                   if getattr(p, "function_response", None))
        if step < len(self.calls):
            name, args = self.calls[step]
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            part = types.Part(text=self.final)
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def factory(scripts: dict):
    """build(llm=factory(scripts)): agents without a script just answer 'done'."""
    made = {}

    def make(name):
        made[name] = ScriptedLlm(calls=list(scripts.get(name, [])), final=f"{name} done", seen_instructions=[])
        return made[name]
    make.made = made
    return make


def scripted_mesh():
    """The `llm` for a separately started LDU process in tests (CPA_LLM_FACTORY=fakes:scripted_mesh())."""
    from test_mesh import SCRIPTS
    return factory(SCRIPTS)
