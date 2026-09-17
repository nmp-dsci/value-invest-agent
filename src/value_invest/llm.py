"""The one place a model is named, a billing path chosen, or an SDK client built.

Every model call in this project — the title classifier now, the golden-call
extractor in M2, the analyst agent and optimiser later — is a Claude Agent SDK
session billed to the owner's subscription, exactly as ConvFinQA-agent's
``evalloop/sdk.py`` and DABStep-loop's ``agent/llm.py`` do it. ``require_live``
refuses to start in a state where the bill would be a surprise, and
``subscription_env`` builds the *only* environment an SDK child ever gets.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from value_invest.config import settings

T = TypeVar("T", bound=BaseModel)

MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}


class BillingError(RuntimeError):
    """The environment would bill the wrong way, or cannot bill at all."""


class StructuredCallError(RuntimeError):
    """The SDK returned nothing that validates against the requested schema."""


def resolve_model(name: str | None) -> str:
    n = (name or settings().model).strip().lower()
    return MODELS.get(n, name or settings().model)


def require_live() -> None:
    s = settings()
    if s.demo_mode:
        raise BillingError("DEMO_MODE: this deployment never calls a model")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if s.billing == "subscription" and key:
        raise BillingError(
            "ANTHROPIC_API_KEY is set in the process environment while BILLING=subscription. "
            "Unset it: with a key present the CLI bills per token."
        )
    if s.billing == "api" and not key:
        raise BillingError("BILLING=api but ANTHROPIC_API_KEY is not set")


def subscription_env() -> dict[str, str]:
    """Environment for the SDK child, with per-token billing made impossible.

    Ported from DABStep/ConvFinQA: an ``ANTHROPIC_API_KEY`` in the child makes
    the CLI bill per token silently, and ``CLAUDE_CODE_*`` / ``CLAUDECODE`` make
    a child started from inside a Claude Code session bill against that
    session. The SDK merges this mapping over the parent's environment, so the
    keys are blanked, not merely omitted.
    """
    drop = {"ANTHROPIC_API_KEY", "CLAUDECODE"}
    env = {
        k: v for k, v in os.environ.items() if k not in drop and not k.startswith("CLAUDE_CODE_")
    }
    if settings().billing == "subscription":
        env["ANTHROPIC_API_KEY"] = ""
        env["CLAUDECODE"] = ""
    return env


def _extract_json(text: str) -> Any:
    fenced = text.split("```")
    for chunk in [text, *fenced] if len(fenced) > 1 else [text]:
        candidate = chunk.strip().removeprefix("json").strip()
        start = min(i for i in (candidate.find("{"), candidate.find("[")) if i != -1) if (
            "{" in candidate or "[" in candidate
        ) else -1
        if start == -1:
            continue
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if end <= start:
            continue
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
    raise StructuredCallError(f"no JSON in the reply: {text[:300]!r}")


async def run_structured(
    prompt: str,
    *,
    schema: type[T],
    system_prompt: str,
    model: str | None = None,
    max_turns: int = 4,
    attempts: int = 2,
    effort: str = "medium",
) -> tuple[T, dict[str, Any]]:
    """One Agent SDK session, no tools, one validated object back.

    Returns the parsed object and a usage dict (turns, tokens, cost, session id).
    Retries once on an empty/invalid reply — the observed transient failure.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    require_live()
    model_id = resolve_model(model)
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model_id,
        tools=[],
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        env=subscription_env(),
        setting_sources=[],
        effort=effort,  # type: ignore[arg-type]
    )
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        final_text = ""
        usage: dict[str, Any] = {"model": model_id}
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    if texts:
                        final_text = texts[-1]
                elif isinstance(msg, ResultMessage):
                    u = msg.usage or {}
                    usage.update(
                        turns=msg.num_turns,
                        cost_usd=msg.total_cost_usd,
                        session_id=msg.session_id,
                        input_tokens=int(u.get("input_tokens", 0))
                        + int(u.get("cache_read_input_tokens", 0))
                        + int(u.get("cache_creation_input_tokens", 0)),
                        output_tokens=int(u.get("output_tokens", 0)),
                    )
                    if msg.result and not final_text:
                        final_text = msg.result
                    if msg.is_error:
                        last = StructuredCallError(f"{msg.subtype}: {str(msg.result)[:300]}")
        try:
            data = _extract_json(final_text)
            return schema.model_validate(data), usage
        except (StructuredCallError, ValidationError) as e:
            last = e
    raise StructuredCallError(str(last))


def run_structured_sync(prompt: str, **kw: Any) -> tuple[Any, dict[str, Any]]:
    return asyncio.run(run_structured(prompt, **kw))
