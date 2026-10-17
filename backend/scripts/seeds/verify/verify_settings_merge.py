"""Prove the team-settings merge never overwrites a teammate's own value.

Three keys, three outcomes, in one run:

  A. a key they never touched  -> adopts the team value
  B. a key they changed        -> keeps THEIRS
  C. a key the team added      -> arrives

Run against a scratch database (POSTGRES_DB=langconfig_seedtest), so the live one
is untouched.
"""
import json
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, SETTINGS_SEED  # noqa: E402


from sqlalchemy import text                      # noqa: E402
from db.database import engine, SessionLocal, init_db  # noqa: E402
from core.settings import store                  # noqa: E402
from core.settings.defaults import get_defaults  # noqa: E402
from core.settings.team_seed import apply_team_seed  # noqa: E402

URL = engine.url.render_as_string(hide_password=False)
assert "langconfig_seedtest" in URL, f"refusing to run outside the scratch DB: {URL}"

defaults = get_defaults()
base_models = defaults["models"]

print("1. schema + a teammate's settings (code defaults, with ONE value changed)")
init_db()
db = SessionLocal()
try:
    teammate = json.loads(json.dumps(base_models))
    # B: they deliberately picked their own default model
    teammate["default_model"] = "THEIR-OWN-MODEL"
    store.put_document(db, "models", teammate)
    db.commit()
    print(f"   their default_model = {teammate['default_model']}")
    print(f"   their fallback_models (untouched) = {teammate.get('fallback_models')}  "
          f"(code default: {base_models.get('fallback_models')})")
finally:
    db.close()

print("\n2. applying the team seed")
result = apply_team_seed()
print(f"   written={result['written']} applied={len(result['applied'])} kept={len(result['kept'])}")
print(f"   kept keys: {result['kept']}")

print("\n3. reading back")
db = SessionLocal()
try:
    now = store.get_document(db, "models")
finally:
    db.close()

seed = json.loads(SETTINGS_SEED.read_text())
team_models = seed["models"]

print(f"   default_model : {now['default_model']!r}")
print(f"   fallback_models: {now.get('fallback_models')}")

checks = [
    ("A. untouched key adopted the team value",
     now.get("fallback_models") == team_models.get("fallback_models")),
    ("B. their changed default_model survived",
     now["default_model"] == "THEIR-OWN-MODEL"),
    ("C. the team's other keys landed",
     all(now.get(k) == v for k, v in team_models.items() if k != "default_model")),
    ("no secret was reintroduced", "api_keys" not in now),
]
print("\n=== verdict ===")
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
print("\n" + ("ALL CHECKS PASSED" if all(o for _, o in checks) else "SOME CHECKS FAILED"))
