"""One apply per staged publish, and `applied` is final.

The failure this exists for, measured on `new_coldchain_v6` (2026-11-11):

    19:07:26  commit baaa1a88 — ontology(new_coldchain_v6): publish 1794395035-a0d021
    19:07:30  status 1794395035-a0d021 = "refused", note "gates failed on re-check"
              report: 20 samples refused with "I can answer about: metrics [], classes []"

A successful install, recorded four seconds later as a refusal. A double-click ran `apply` twice: the
second call re-read a row that was still `staged`, ran the gate re-check against the staging tree the
first call was deleting (`apply` ends with `shutil.rmtree(staging)`), got an empty menu, and wrote
"refused" over "applied".

Two rules, both guarded here:

  * `apply` is serialised per staged id, so a second caller waits and then finds the row no longer
    `staged` — it is told "already applied at …" instead of racing the first one's cleanup;
  * `applied` is a terminal status: no later writer can rewrite it (`_audit_row`'s upsert carries
    `WHERE status <> 'applied'`), because history may be appended to, never rewritten.

A refusal also no longer leaves its staging tree behind: `.staging/` means "waiting for a human", so a
tree nobody may apply is only disk. Measured: nine such trees sat beside the one real pending publish.
"""
import json
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PUBLISH = REPO / "backend" / "services" / "ontology_publish.py"


# ── the rules, in the source ───────────────────────────────────────────────

def test_apply_is_serialised_per_staged_id():
    text = PUBLISH.read_text(encoding="utf-8")
    assert "def _apply_lock(" in text
    assert "with _apply_lock(staged_id):" in text, "apply went back to running unguarded"
    assert "def _apply_locked(" in text, "the locked body must be its own function"


def test_a_second_apply_is_told_what_happened():
    text = PUBLISH.read_text(encoding="utf-8")
    assert '"already_applied": True' in text
    assert "already applied" in text


def test_already_applied_is_not_reported_as_a_failure():
    """`ok` is what the route and the UI key off, so the idempotent case must carry `ok: True`.

    Measured on ebl_ops_v1 (2026-11-14): a second click on a publish that HAD installed came back
    `ok: False`, the route raised 409, and Settings painted it red as "apply failed" — the operator
    had to open the ledger to learn the install had worked. The click asked for "this publish is
    installed"; that was already true, so the answer is success with a flag, not an error.
    """
    text = PUBLISH.read_text(encoding="utf-8")
    block = text[text.index('if status == "applied":'):]
    block = block[:block.index('why = "refused at stage time')]
    assert '"ok": True' in block, "already-applied still reports ok False, so the UI paints it red"
    assert '"ok": False' not in block, "already-applied must not carry an error"
    assert '"error"' not in block, "already-applied must not carry an error string"
    assert '"message"' in block, "nothing for the UI to show as the (non-)action it took"


def test_applied_cannot_be_overwritten():
    text = PUBLISH.read_text(encoding="utf-8")
    assert "WHERE ontology_publishes.status <> 'applied'" in text, \
        "a late writer can rewrite a successful install as a failure again"


def test_a_refused_staging_does_not_leave_its_tree():
    text = PUBLISH.read_text(encoding="utf-8")
    block = text[text.index('status = "staged" if ok else "refused"'):]
    block = block[:block.index("# ────")]
    assert "shutil.rmtree(staging" in block, \
        ".staging/ must mean 'waiting for a human'; a refused tree is only disk"


# ── behaviour: two concurrent applies install once ────────────────────────

def test_a_double_click_installs_once_and_the_ledger_says_applied(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    from services import ontology_publish as pub

    ledger: dict[str, dict] = {}

    def fake_audit_row(pid, key, actor, status, note="", files=None, report=None, git_commit=None):
        row = ledger.setdefault(pid, {"id": pid, "key": key, "status": "staged", "note": "",
                                      "report": {}, "updated_at": None})
        # mirror the SQL guard: `applied` is terminal
        if row["status"] == "applied":
            return
        row.update(status=status, note=note, report=report or {}, updated_at=f"t{time.time():.0f}")

    monkeypatch.setattr(pub, "_audit_row", fake_audit_row)
    monkeypatch.setattr(pub, "_audit_list",
                        lambda pid: [dict(ledger[pid], created_at="now")] if pid in ledger else [])
    monkeypatch.setattr(pub, "_compile_report", lambda profile: {"metrics": 1, "compiled": 1,
                                                                 "refused": []})
    # `_run_gates(profile, key=…)` — the fake has to take the keyword the service actually passes,
    # otherwise this test dies inside the thread and never exercises the race at all (measured
    # 2026-11-14: the fake predated `key=` and the whole double-click test was failing on TypeError).
    monkeypatch.setattr(pub, "_run_gates", lambda profile, key=None, truth=None: {"ok": True, "fails": [],
                                                                                "not_run": [], "text": ""})
    monkeypatch.setattr(pub, "reload_workbench", lambda key: "")
    monkeypatch.setattr(pub, "_supersede_older", lambda key, keep: [])

    staged_id = "test-double-click"
    key = "probe_key"
    # ONTOLOGIES first: `_staging_dir` is derived from it, so a tree made before the patch is invisible
    # to apply() — the first version of this test failed for exactly that reason.
    monkeypatch.setattr(pub, "ONTOLOGIES", tmp_path / "profiles")
    live = pub.ONTOLOGIES / key
    live.mkdir(parents=True, exist_ok=True)
    (live / "probe_key_settings.json").write_text("{}", encoding="utf-8")
    staging = pub._staging_dir(key) / staged_id
    (staging / "ontology").mkdir(parents=True, exist_ok=True)
    (staging / "probe_key_settings.json").write_text(json.dumps({"dsn": {}, "ontology_dir": "ontology"}),
                                                    encoding="utf-8")

    ledger[staged_id] = {"id": staged_id, "key": key, "status": "staged", "note": "",
                         "report": {}, "updated_at": None}

    results: list[dict] = []

    def one():
        results.append(pub.apply(staged_id, actor="test", confirmed=True, git_commit=False))

    threads = [threading.Thread(target=one) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    installs = [r for r in results if r.get("ok") and not r.get("already_applied")]
    assert len(installs) == 1, f"expected exactly one install, got {results}"
    repeat = [r for r in results if r.get("already_applied")]
    assert len(repeat) == 1, \
        f"the second caller was not told the publish was already applied: {results}"
    # ... and told it as SUCCESS: the click got what it asked for. A 409 here reads as "apply failed"
    # on the Settings page, which is the bug this pins.
    assert repeat[0].get("ok") is True, f"already-applied came back as a failure: {repeat[0]}"
    assert "error" not in repeat[0], f"already-applied carries an error string: {repeat[0]}"
    assert ledger[staged_id]["status"] == "applied", ledger[staged_id]

    import shutil as _shutil

    _shutil.rmtree(pub._staging_dir(key), ignore_errors=True)
