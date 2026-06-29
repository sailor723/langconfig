"""
Chat model wrapper that strips <think>...</think> and <tool_call>...</tool_call>
blocks from the model's output before it reaches the rest of the pipeline.

Why wrap the model (vs. filter at the SSE layer):
  - The think-block emission is a provider-level concern, not a transport one.
  - One wrap, no per-call filter plumbing.
  - Works for both streaming and non-streaming paths.
  - Any code path that uses the agent (CLI, eval, web) gets the fix
    automatically — no separate fix per call site.

The non-streaming path (`_generate`) strips the blocks from the final
content. The streaming path (`_astream`) feeds the filter one chunk
at a time so block splits across chunks are handled.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Iterator, List, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from think_filter import ThinkFilter


class ThinkStrippingChatModel(BaseChatModel):
    """Wraps a chat model. Strips think/tool_call XML from the content."""

    model: BaseChatModel
    think_tags: tuple = ("<think>", "</think>")
    tool_call_tags: tuple = ("<tool_call>", "</tool_call>")

    class Config:
        # Allow nested BaseChatModel field.
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return self.model._llm_type

    # Delegate bind_tools to the wrapped model — required by DeepAgent's
    # internal middleware chain which calls model.bind_tools(...) during
    # agent construction. Must return a wrapped result so that the
    # think-stripping is preserved on the bound model.
    def bind_tools(
        self,
        tools: Sequence[Union[BaseTool, type, dict]],
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> "ThinkStrippingChatModel":
        bound = self.model.bind_tools(tools, tool_choice=tool_choice, **kwargs)
        # If the result is already a ThinkStrippingChatModel, return as-is.
        if isinstance(bound, ThinkStrippingChatModel):
            return bound
        return ThinkStrippingChatModel(model=bound)

    # ----- non-streaming -----
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        result: ChatResult = self.model._generate(messages, stop=stop, **kwargs)
        flt = ThinkFilter()
        for gen_list in result.generations:
            for gen in gen_list:
                if isinstance(gen.message.content, str):
                    visible = flt.feed(gen.message.content) + flt.flush()
                    gen.message.content = visible
        return result

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = await self.model._agenerate(messages, stop=stop, **kwargs)
        flt = ThinkFilter()
        for gen_list in result.generations:
            for gen in gen_list:
                if isinstance(gen.message.content, str):
                    visible = flt.feed(gen.message.content) + flt.flush()
                    gen.message.content = visible
        return result

    # ----- streaming -----
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Iterator[AIMessageChunk]:
        flt = ThinkFilter()
        for chunk in self.model._stream(messages, stop=stop, **kwargs):
            text = chunk.content if isinstance(chunk.content, str) else ""
            visible = flt.feed(text)
            if visible or getattr(chunk, "tool_call_chunks", None):
                yield chunk.__class__(content=visible)
        tail = flt.flush()
        if tail:
            yield chunk.__class__(content=tail)

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        flt = ThinkFilter()
        async for chunk in self.model._astream(messages, stop=stop, **kwargs):
            text = chunk.content if isinstance(chunk.content, str) else ""
            visible = flt.feed(text)
            if visible or getattr(chunk, "tool_call_chunks", None):
                yield chunk.__class__(content=visible)
        tail = flt.flush()
        if tail:
            yield chunk.__class__(content=tail)
