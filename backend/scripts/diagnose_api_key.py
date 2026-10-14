"""Why does a saved API key read as "not configured" in an agent?

    cd <tree>/backend
    .venv/bin/python scripts/diagnose_api_key.py [key_name]     # default tavily_api_key

A key can be present in the database and still be unusable, and this script exists
because the obvious check can't tell the difference. ``SELECT
document->'api_keys'->>'tavily_api_key'`` returns whatever is *stored* — normally
a Fernet token starting with ``gAAAA`` — so it reports "key present" while the
application is unable to read it:

* ``store.get_document`` decrypts secret-role fields, and ``decrypt`` RAISES when a
  Fernet-shaped value cannot be decrypted with the current key ("the encryption key
  has changed since this value was stored, or the value is corrupt");
* ``config._db_api_key_only`` wraps that call in ``try/except Exception: return
  None``, so the failure is swallowed and surfaces to the user as
  "Tavily API key not configured" — a missing-key message for a wrong-key problem.

Read-only: it decrypts and reports, and writes nothing.
"""
import os
import sys

sys.path.insert(0, os.getcwd())  # run from <tree>/backend, as a file or via stdin

from sqlalchemy import text  # noqa: E402

from db.database import SessionLocal, engine  # noqa: E402

KEY = (sys.argv[1] if len(sys.argv) > 1 else "tavily_api_key").strip()

print(f"  key                 : {KEY}")

# ── 1. Which seed is the encryption using? ──────────────────────────────────
try:
    from services.encryption import ENCRYPTION_KEY_ENV, _resolve_key_str
    source = _resolve_key_str()
    from config import settings as app_settings
    from_settings = bool(getattr(app_settings, "api_key_encryption_key", None))
    print(f"  API_KEY_ENCRYPTION_KEY in .env/settings : {from_settings}")
    print(f"  {ENCRYPTION_KEY_ENV} in the process env     : {bool(os.getenv(ENCRYPTION_KEY_ENV))}")
    if source == "langconfig-dev-insecure-key-change-me":
        print("  -> using the DEV FALLBACK key (no key configured anywhere)")
    else:
        print(f"  -> using a configured key ({len(source)} chars)")
except Exception as exc:  # noqa: BLE001
    print(f"  ! could not resolve the encryption key: {exc}")

# ── 2. What is stored, raw? ─────────────────────────────────────────────────
with engine.connect() as conn:
    raw = conn.execute(
        text("SELECT document->'api_keys'->>:k FROM settings_documents WHERE ns = 'models'"),
        {"k": KEY},
    ).scalar()
    ns_row = conn.execute(
        text("SELECT count(*) FROM settings_documents WHERE ns = 'models'")
    ).scalar()

print(f"  models settings document exists         : {bool(ns_row)}")
print(f"  stored value present                    : {bool(raw)}")
print(f"  stored value is an encrypted token      : {bool(raw and raw.startswith('gAAAA'))}")

# ── 3. Can the application actually read it? ────────────────────────────────
db = SessionLocal()
decrypted = None
read_error = None
try:
    from core.settings import get_document
    doc = get_document(db, "models")
    decrypted = (doc.get("api_keys") or {}).get(KEY)
except Exception as exc:  # noqa: BLE001 — the message IS the finding
    read_error = f"{type(exc).__name__}: {exc}"
finally:
    db.close()

print(f"  readable through the app path           : {bool(decrypted)}")
if read_error:
    print(f"    error: {read_error[:160]}")

# ── 4. Isolate a decryption failure ─────────────────────────────────────────
if raw and raw.startswith("gAAAA") and not decrypted:
    try:
        from services.encryption import encryption_service
        encryption_service.decrypt(raw)
        print("  direct decrypt                          : ok (so the app path failed elsewhere)")
    except Exception as exc:  # noqa: BLE001
        print(f"  direct decrypt                          : FAILED — {type(exc).__name__}: {str(exc)[:120]}")

# ── verdict ─────────────────────────────────────────────────────────────────
print()
if decrypted:
    print("  The key is stored AND decryptable, so the tool should find it. If an agent")
    print("  still reports it missing, the tool is running somewhere that cannot reach")
    print("  this database — compare against the tool row's own code path.")
elif raw and not decrypted:
    print("  The value is stored but cannot be decrypted: it was written with a DIFFERENT")
    print("  API_KEY_ENCRYPTION_KEY than the one in use now, so every stored provider key")
    print("  is equally unreadable. Re-enter the keys in Settings, or restore the original")
    print("  key. Rotating this value orphans everything encrypted with the old one.")
elif not raw:
    print("  Nothing is stored under this name. Check Settings, and check the field name:")
    print("  a provider whose api_key_field differs writes under that name instead.")
