"""Regression tests for the skill tools' list coercion.

The bug these guard: ``create_skill`` and ``update_skill`` declare
``tags: list[str]`` / ``triggers: list[str]``, but Python does not enforce
annotations at runtime and the caller is an LLM. A model that passes
``'["greeting", "weather"]'`` (JSON text) or ``"greeting, weather"`` (comma
separated) put a *string* into the JSON columns, and then:

* ``GET /api/skills/{id}`` returned **500** — ``SkillResponse.tags`` must be a
  list, and the input was a string;
* ``GET /api/skills`` looked fine, because it tolerates per-row validation
  failures and substitutes a placeholder.

That asymmetry is what makes it worth a test: the damage is invisible in the
list view and fatal in the detail view.

The coercion is a pure function, so these tests need no database.
"""

import json

import pytest

from tools.native_impl import _coerce_str_list


# ── the shapes an LLM actually sends ────────────────────────────────────────

def test_real_list_passes_through():
    assert _coerce_str_list(["greeting", "weather"]) == ["greeting", "weather"]


def test_json_text_becomes_a_list():
    """The exact shape that produced the 500."""
    assert _coerce_str_list('["greeting", "weather", "courtesy"]') == [
        "greeting",
        "weather",
        "courtesy",
    ]


def test_comma_separated_becomes_a_list():
    assert _coerce_str_list("greeting, weather , conversation") == [
        "greeting",
        "weather",
        "conversation",
    ]


def test_json_array_of_non_strings_is_stringified():
    assert _coerce_str_list("[1, 2]") == ["1", "2"]


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),          # "not provided" must stay distinguishable from "[]"
        ([], []),
        ("", []),
        ("   ", []),
        ((), []),
    ],
)
def test_empty_shapes(value, expected):
    assert _coerce_str_list(value) == expected


def test_scalar_is_wrapped():
    assert _coerce_str_list(42) == ["42"]
    assert _coerce_str_list("solo") == ["solo"]


def test_json_object_falls_back_to_text():
    """A dict is not a tag list; keep it visible rather than silently dropping it."""
    assert _coerce_str_list('{"a": 1}') == ['{"a": 1}']


def test_blank_items_are_dropped_and_whitespace_trimmed():
    assert _coerce_str_list([" greeting ", "", "  ", "weather"]) == ["greeting", "weather"]
    assert _coerce_str_list("a, ,b") == ["a", "b"]


def test_result_is_json_serialisable_as_an_array():
    """The stored value must be a JSON *array* — that is what the API validates."""
    import json as _json

    encoded = _json.dumps(_coerce_str_list('["a", "b"]'))
    assert _json.loads(encoded) == ["a", "b"]
    assert encoded.startswith("[")
