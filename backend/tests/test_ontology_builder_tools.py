"""A builder agent without its tool rows can do a whole ladder step and be unable to land it.

Measured on talent_v1 (2026-11-14): the agent row listed `ontology_open / ontology_inspect /
ontology_publish`, `custom_tools` held none of the three, and the agent finished S1′-S3 and then reported
"ontology_publish 不在我的工具集里". The four ontology tools are seeded by their OWN scripts rather than by
`SEEDABLE_TOOL_META`, so creating a builder never created them — a sixth artefact that has to agree.

This is a source-level guard (the seeding itself needs a database): the registration script must have a
step for the tool rows, and it must run BEFORE the profile directory check, where a reader looks for the
artefacts a builder needs.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILDER = REPO / "backend" / "scripts" / "seeds" / "in" / "add_ontology_builder.py"
SEEDS = REPO / "backend" / "scripts" / "seeds" / "in"


def test_the_registration_seeds_the_ontology_tools():
    text = BUILDER.read_text(encoding="utf-8")
    assert "def step_tools(" in text, "no tool-seeding step: a new builder cannot publish"
    for name in ("seed_ontology_open_tool", "seed_ontology_inspect_tool",
                 "seed_ontology_publish_tool", "seed_ontology_ask_tool"):
        assert name in text, f"{name} is not seeded by the registration"
        assert (SEEDS / f"{name}.py").is_file(), f"{name}.py is missing"


def test_the_tool_step_runs_as_part_of_the_registration():
    text = BUILDER.read_text(encoding="utf-8")
    assert "step_tools(apply=args.apply)" in text, "step_tools exists but is never called"


def test_every_ontology_tool_seed_exposes_a_main():
    """The step imports each seed module and calls `main()`; a module without one silently seeds nothing."""
    for name in ("seed_ontology_open_tool", "seed_ontology_inspect_tool",
                 "seed_ontology_publish_tool", "seed_ontology_ask_tool"):
        body = (SEEDS / f"{name}.py").read_text(encoding="utf-8")
        assert "def main(" in body, f"{name} has no main()"
