"""
Unit tests for ThinkFilter — the stateful streaming filter that strips
`<think>...</think>` and `<tool_call>...</tool_call>` XML from a token stream.

Run with: python test_think_filter.py
Or:        python -m unittest test_think_filter
"""
import sys
import unittest
from pathlib import Path

# Allow running this file directly (`python test_think_filter.py`).
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from think_filter import ThinkFilter


def feed_all(f: ThinkFilter, *chunks: str) -> str:
    """Feed a sequence of chunks to a filter and return the joined output."""
    return "".join(f.feed(c) for c in chunks) + f.flush()


class TestThinkFilterBasics(unittest.TestCase):
    """Sanity: clean text passes through, no tags means no work to do."""

    def test_passthrough(self):
        self.assertEqual(feed_all(ThinkFilter(), "Hello, world!"), "Hello, world!")

    def test_empty(self):
        self.assertEqual(feed_all(ThinkFilter(), ""), "")
        self.assertEqual(feed_all(ThinkFilter()), "")

    def test_unknown_tag_passes_through(self):
        # Tags we don't recognise are not treated as block delimiters.
        self.assertEqual(feed_all(ThinkFilter(), "<b>bold</b>"), "<b>bold</b>")


class TestThinkBlocks(unittest.TestCase):
    """`<think>...</think>` is stripped together with its body."""

    def test_simple_think(self):
        out = feed_all(ThinkFilter(), "<think>reasoning</think>Hello!")
        self.assertEqual(out, "Hello!")

    def test_think_in_middle(self):
        out = feed_all(ThinkFilter(), "A<think>x</think>B")
        self.assertEqual(out, "AB")

    def test_think_with_newlines(self):
        out = feed_all(ThinkFilter(), "<think>line1\nline2\nline3</think>answer")
        self.assertEqual(out, "answer")

    def test_unclosed_think_is_dropped(self):
        # No closing tag → entire (visible-so-far + hidden) content is dropped
        # at flush. Visible text before <think> is still emitted.
        out = feed_all(ThinkFilter(), "Hello <think>unterminated reasoning")
        self.assertEqual(out, "Hello ")


class TestToolCallBlocks(unittest.TestCase):
    """`<tool_call>...</tool_call>` is stripped together with its body."""

    def test_simple_tool_call(self):
        out = feed_all(
            ThinkFilter(),
            '<tool_call><invoke name="x">1</invoke></tool_call>Result',
        )
        self.assertEqual(out, "Result")

    def test_tool_call_then_visible(self):
        out = feed_all(
            ThinkFilter(),
            '<tool_call><invoke name="a">x</invoke></tool_call>answer',
        )
        self.assertEqual(out, "answer")

    def test_unclosed_tool_call_is_dropped(self):
        out = feed_all(
            ThinkFilter(),
            'Vis <tool_call><invoke name="a">x</invoke>',
        )
        self.assertEqual(out, "Vis ")


class TestMultipleBlocks(unittest.TestCase):
    """Multiple think + tool_call blocks in one stream."""

    def test_two_think_blocks(self):
        out = feed_all(
            ThinkFilter(),
            "<think>a</think>foo<think>b</think>bar",
        )
        self.assertEqual(out, "foobar")

    def test_think_then_tool_call(self):
        out = feed_all(
            ThinkFilter(),
            '<think>plan</think><tool_call><invoke name="x"/></tool_call>answer',
        )
        self.assertEqual(out, "answer")

    def test_interleaved(self):
        out = feed_all(
            ThinkFilter(),
            "hi<think>a</think>you<tool_call>b</tool_call>there",
        )
        self.assertEqual(out, "hiyouthere")


class TestNestedTags(unittest.TestCase):
    """A <tool_call> inside <think> is treated as hidden content (dropped)."""

    def test_tool_call_inside_think(self):
        out = feed_all(
            ThinkFilter(),
            '<think>plan<tool_call><invoke name="x"/></tool_call>rest</think>visible',
        )
        # The outer think wins — the inner tool_call is part of the
        # think body and is hidden. "visible" comes after </think>.
        self.assertEqual(out, "visible")

    def test_think_inside_tool_call(self):
        out = feed_all(
            ThinkFilter(),
            '<tool_call><invoke name="x"><think>side</think></invoke></tool_call>result',
        )
        self.assertEqual(out, "result")


class TestCrossChunkSplit(unittest.TestCase):
    """Blocks split across chunk boundaries are still detected."""

    def test_open_tag_split(self):
        # The <think> tag is split across two chunks.
        # Correct split: "<thi" | "nk>reasoning...</think>Hello"
        f = ThinkFilter()
        out1 = f.feed("<thi")
        out2 = f.feed("nk>reasoning</think>Hello")
        out3 = f.flush()
        self.assertEqual(out1 + out2 + out3, "Hello")

    def test_close_tag_split(self):
        # </think> is split across two chunks.
        f = ThinkFilter()
        out1 = f.feed("<think>reasoning</")
        out2 = f.feed("think>Hello")
        out3 = f.flush()
        self.assertEqual(out1 + out2 + out3, "Hello")

    def test_full_block_split_mid_body(self):
        # <think>, body, and </think> all in separate chunks.
        f = ThinkFilter()
        out1 = f.feed("<")
        out2 = f.feed("think>rea")
        out3 = f.feed("soning</thi")
        out4 = f.feed("nk>OK")
        out5 = f.flush()
        self.assertEqual(out1 + out2 + out3 + out4 + out5, "OK")

    def test_one_char_per_chunk(self):
        # Worst case: one character at a time.
        text = "<think>hidden</think>hello world"
        f = ThinkFilter()
        out = "".join(f.feed(c) for c in text) + f.flush()
        self.assertEqual(out, "hello world")


class TestToolCallNestedInVisible(unittest.TestCase):
    """Visible text may contain angle brackets that look tag-ish but are not."""

    def test_angle_bracket_in_text(self):
        # 1 < 2 is visible text, not a tag.
        out = feed_all(ThinkFilter(), "1 < 2 is true")
        self.assertEqual(out, "1 < 2 is true")

    def test_partial_think_in_text(self):
        # A single '<' in plain text is held back as a safety prefix,
        # but then emitted once we know it isn't a tag opener.
        f = ThinkFilter()
        out = "".join(f.feed(c) for c in "a<b") + f.flush()
        self.assertEqual(out, "a<b")


class TestStateCleanliness(unittest.TestCase):
    """Filters are reusable after a clean run."""

    def test_reuse_after_clean_stream(self):
        f = ThinkFilter()
        feed_all(f, "<think>x</think>hello")
        # After flush, state should be clean.
        self.assertEqual(feed_all(f, "world"), "world")


if __name__ == "__main__":
    unittest.main(verbosity=2)
