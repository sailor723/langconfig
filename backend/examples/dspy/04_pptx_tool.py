"""
DSPy Deep Agent tool demo: write a PowerPoint (.pptx) deck.

1. DSPy turns a topic + audience into a structured deck outline (JSON).
2. python-pptx renders that outline into a real .pptx file.
3. The renderer is exposed as a LangChain tool so a Deep Agent can call it.
"""
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("../.env")

import dspy
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

dspy.configure(lm=dspy.LM(
    model=f"openai/{os.getenv('MINIMAX_MODEL', 'minimax-M3')}",
    api_base=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    api_key=os.getenv("MINIMAX_API_KEY"),
))


class DeckOutline(dspy.Signature):
    """Create a professional presentation outline as JSON."""
    topic: str = dspy.InputField()
    audience: str = dspy.InputField()
    slide_count: int = dspy.InputField()
    outline: str = dspy.OutputField(
        desc='JSON like {"title": str, "slides": [{"type": "title|section|content", '
             '"title": str, "subtitle": str, "bullets": [str], "notes": str}]}'
    )


class DeckOutliner(dspy.Module):
    def __init__(self):
        super().__init__()
        self.plan = dspy.Predict(DeckOutline)

    def forward(self, topic, audience, slide_count):
        return self.plan(
            topic=topic, audience=audience, slide_count=slide_count
        ).outline


outliner = DeckOutliner()


def _parse_outline(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model did not return a JSON outline: {raw[:200]}")
    data = json.loads(text[start:end + 1])
    if "title" not in data or not isinstance(data.get("slides"), list):
        raise ValueError(f"Outline missing title/slides: {data}")
    return data


def _render_pptx(outline: dict, output_dir: Path) -> Path:
    """Render a deck outline dict into a 16:9 .pptx file and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    accent = RGBColor(0x4F, 0x46, 0xE5)
    dark = RGBColor(0x1A, 0x1A, 0x1A)
    blank = prs.slide_layouts[6]

    def add_text(slide, left, top, width, height, text, size, bold=False, align=PP_ALIGN.LEFT, color=dark):
        box = slide.shapes.add_textbox(
            Inches(left), Inches(top), Inches(width), Inches(height)
        )
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = color
        p.alignment = align
        return box

    def add_bullets(slide, bullets, top=1.7):
        box = slide.shapes.add_textbox(
            Inches(0.75), Inches(top), Inches(11.8), Inches(5.2)
        )
        tf = box.text_frame
        tf.word_wrap = True
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"• {b}"
            p.font.size = Pt(18)
            p.space_before = Pt(10)
            p.font.color.rgb = dark

    def add_accent_bar(slide):
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.12), Inches(7.5)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()

    for slide_data in outline["slides"]:
        stype = slide_data.get("type", "content")
        title = slide_data.get("title", "")
        subtitle = slide_data.get("subtitle", "")
        bullets = slide_data.get("bullets") or []
        notes = slide_data.get("notes") or ""

        slide = prs.slides.add_slide(blank)
        add_accent_bar(slide)

        if stype == "title":
            add_text(slide, 0.8, 2.3, 11.7, 1.4, title, 42, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                add_text(slide, 0.8, 3.9, 11.7, 0.8, subtitle, 22, align=PP_ALIGN.CENTER)
        elif stype == "section":
            add_text(slide, 0.8, 2.8, 11.7, 1.2, title, 36, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                add_text(slide, 0.8, 4.2, 11.7, 0.8, subtitle, 18, align=PP_ALIGN.CENTER)
        else:
            add_text(slide, 0.5, 0.45, 12.3, 1.0, title, 30, bold=True)
            add_bullets(slide, bullets)

        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_deck.pptx"
    path = output_dir / filename
    prs.save(str(path))
    return path


@tool
def write_pptx(topic: str, audience: str = "General audience", slide_count: int = 4) -> str:
    """Create a PowerPoint (.pptx) deck about a topic. Returns the absolute file path."""
    raw = outliner(topic=topic, audience=audience, slide_count=slide_count)
    outline = _parse_outline(raw)
    path = _render_pptx(outline, Path("/tmp/dspy-pptx-demo"))
    return f"Created {path} with {len(outline['slides'])} slides"


async def main():
    # 1) Call the tool directly (no agent yet).
    direct = write_pptx.invoke({
        "topic": "DSPy and Deep Agents",
        "audience": "AI engineers",
        "slide_count": 4,
    })
    print("TOOL RESULT:", direct)

    # 2) Let a Deep Agent discover and call the same tool.
    llm = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-M3"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        api_key=os.getenv("MINIMAX_API_KEY"),
        streaming=True,
    )
    agent = create_deep_agent(
        model=llm,
        tools=[write_pptx],
        backend=FilesystemBackend(root_dir="/tmp/dspy-deepagent-demo"),
        checkpointer=MemorySaver(),
    )
    result = await agent.ainvoke(
        {"messages": [("human", "Create a 4-slide PowerPoint about LangChain Deep Agents for engineers.")]},
        config={"configurable": {"thread_id": "dspy-pptx-demo-1"}, "recursion_limit": 30},
    )
    print("AGENT RESULT:", result["messages"][-1].content)


asyncio.run(main())
