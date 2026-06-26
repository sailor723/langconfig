"""
create langchain and deep agent respectively, and you can see different results. for deep agent, there is plan to do then call tool.
"""

from langchain.agents import create_agent
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

SYSTEM_PROMPT = """You are a literary data assistant.

## Capabilities

- `fetch_text_from_url`: loads document text from a URL into the conversation.
Do not guess line counts or positions—ground them in tool results from the saved file."""


FAKE_GATSBY = """The Great Gatsby

By F. Scott Fitzgerald

*** START OF THE PROJECT GUTENBERG EBOOK 64317 ***

Chapter 1

In my younger and more vulnerable years my father gave me some advice that I've
been turning over in my mind ever since.

Then I went to Daisy and Gatsby and had dinner. Gatsby was nowhere to be seen.
I was surprised and disappointed. But then I saw Gatsby walking toward us through
the garden. Gatsby believed in the green light, the orgastic future.

I didn't know Gatsby and I didn't know Daisy. But I knew Gatsby.

Chapter 2

Gatsby looked at Daisy and said nothing. Daisy cried. Gatsby smiled.

Gatsby is the best man I know. Gatsby will always be there for Daisy.

Chapter 3

Gatsby gave a party every Saturday night. Gatsby's parties were legendary.

Daisy was at Gatsby's party. Gatsby saw Daisy across the room.

Chapter 4

Gatsby told me about Daisy. Gatsby said Daisy was the love of his life.

Gatsby wanted Daisy to know everything. Gatsby said he was rich.

Chapter 5

Gatsby met Daisy at Nick's cottage. Daisy was overwhelmed by Gatsby.

Gatsby kissed Daisy. Daisy kissed Gatsby back.

Chapter 6

Gatsby's father came to the funeral. Gatsby was dead.

Gatsby died because of Daisy. Gatsby will never see Daisy again.

*** END OF THE PROJECT GUTENBERG EBOOK 64317 ***"""


@tool
def fetch_text_from_url(url: str) -> str:
    """Fetch the document from a URL.
    """
    return FAKE_GATSBY


model = init_chat_model(
    "deepseek-chat",
    # model_provider="google-genai",
    temperature=0.5,
    timeout=600,
    max_tokens=25000,
    streaming=True,
)

checkpointer = InMemorySaver()

agent = create_agent(
    model=model,
    tools=[fetch_text_from_url],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

deep_agent = create_deep_agent(
    model=model,
    tools=[fetch_text_from_url],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

content = f"""Project Gutenberg hosts a full plain-text copy of F. Scott Fitzgerald's The Great Gatsby.
URL: https://www.gutenberg.org/files/64317/64317-0.txt

Answer as much as you can:

1) How many lines in the complete Gutenberg file contain the substring `Gatsby` (count lines, not occurrences within a line, each line ends with a line break).
2) The 1-based line number of the first line in the file that contains `Daisy`.
3) A two-sentence neutral synopsis.

Do your best on (1) and (2). If at any point you realize you cannot **verify** an exact answer with
your available tools and reasoning, do not fabricate numbers: use `null` for that field and spell out
the limitation in `how_you_computed_counts`. If you encounter any errors please report what the error was and what the error message was."""

def stream_agent(name: str, ag, config: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}\n", flush=True)

    print("[DEBUG] Calling stream()...", flush=True)
    import time
    t0 = time.time()
    last_ai_content = ""
    for i, event in enumerate(ag.stream(
        {"messages": [{"role": "user", "content": content}]},
        config=config,
        stream_mode="values",
    )):
        elapsed = time.time() - t0
        msgs = event.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        if not hasattr(last, "type"):
            continue
        if last.type == "tool":
            tc_name = getattr(last, "name", "?")
            content_preview = (getattr(last, "content", "") or "")[:80]
            print(f"[{elapsed:.0f}s] TOOL  {tc_name}: {content_preview}", flush=True)
        elif last.type == "ai":
            has_tc = bool(getattr(last, "tool_calls", None))
            cont = getattr(last, "content", "") or ""
            if has_tc:
                tc = last.tool_calls[0]
                print(f"[{elapsed:.0f}s] AI     tool_call: {tc.get('name','?')}", flush=True)
            elif cont:
                delta = cont[len(last_ai_content):]
                last_ai_content = cont
                print(delta, end="", flush=True)
    print(f"\n[DEBUG] Stream ended after {time.time()-t0:.1f}s\n", flush=True)


stream_agent("create_agent (langchain.agents)", agent, {"configurable": {"thread_id": "great-gatsby-lc"}})
stream_agent("create_deep_agent (deepagents)", deep_agent, {"configurable": {"thread_id": "great-gatsby-da"}})
print("Done.")