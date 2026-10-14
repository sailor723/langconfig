"""Find settings documents holding secrets that the current key cannot decrypt.

    cd <tree>/backend
    .venv/bin/python scripts/audit_settings_secrets.py            # report
    .venv/bin/python scripts/audit_settings_secrets.py --clear    # blank those fields

A stored secret is a Fernet token encrypted with whatever `API_KEY_ENCRYPTION_KEY` was in force
when it was written. Change that key — or write rows on a machine that had one and read them on a
machine that does not — and the token is permanently unreadable. The application then fails in
two different styles, which is why this script exists:

* readers that guard the call (`config._db_api_key_only`) swallow the error and behave as if no key
  were configured — the tool says "no API key", the Settings panel shows empty;
* readers that do not guard (`store.get_document`, used by the Settings UI and by `seed_all.py`
  step 4b) raise `ValueError: Stored secret cannot be decrypted with the current
  API_KEY_ENCRYPTION_KEY`, which aborts a whole seed run over one unusable field.

Neither is the field's fault, and neither is fixable by re-running anything: the ciphertext is
gone unless the original key is restored. What can be done is to name the affected fields and, on
request, blank them so encrypting fresh values becomes possible again.

    --clear blanks only the undecryptable secret fields. Nothing else in the document is touched,
    and every field it changes is listed first.

Recovery recipe for a machine whose seed run aborted at step 4b:

    cd <tree>/backend
    .venv/bin/python scripts/audit_settings_secrets.py            # names the fields
    .venv/bin/python scripts/audit_settings_secrets.py --clear    # blanks them
    .venv/bin/python scripts/seeds/seed_all.py                    # step 4b now completes

Then re-enter the API keys in Settings → API Keys. Blanking is not a repair — the old value is
unrecoverable — it unblocks the rows that were holding the whole namespace hostage. The only real
repair is restoring the `API_KEY_ENCRYPTION_KEY` that wrote those rows, if it is still known.

Read-only unless --clear is given.
"""
import argparse
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Run from anywhere: take backend/ from this file's own location and work from there. The
# app resolves settings paths against the process CWD ("./data/documents"), so the CWD must be
# backend/ no matter where the script was invoked from.
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402


def fernet_fields(document, prefix=""):
    """Every (dotted path, value) in a settings document that looks like a Fernet token.

    Deliberately schema-independent: the question is whether a stored ciphertext can be read
    with the key in force *now*, so anything that is ciphertext must be tried. Walking the
    schemas instead would miss a secret whose namespace forgot its ``role='secret'`` marker,
    and would see nothing at all in a namespace with no registered schema.
    """
    for key, value in (document or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from fernet_fields(value, f"{path}.")
        elif isinstance(value, str) and value.startswith("gAAAA"):
            yield path, value


def get_at(document, dotted):
    node = document
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def scan() -> tuple[list, int]:
    """``([(namespace, field, reason)], tokens_checked)`` for every unreadable secret."""
    from services.encryption import encryption_service

    found = []
    checked = 0
    with engine.connect() as conn:
        rows = list(conn.execute(text("SELECT ns, document FROM settings_documents")))
    for ns, document in rows:
        if not isinstance(document, dict):
            continue
        for dotted, value in fernet_fields(document):
            checked += 1
            try:
                encryption_service.decrypt(value)
            except Exception as exc:  # noqa: BLE001 — the exception IS the finding
                found.append((ns, dotted, type(exc).__name__))
    return found, checked


def blank(namespace: str, dotted: str) -> bool:
    """Set one field to null, reporting whether the row actually changed.

    ``jsonb_set`` is a silent no-op when an intermediate key is missing, so the update is read
    back and compared rather than assumed.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE settings_documents
            SET document = jsonb_set(document::jsonb, CAST(:path AS text[]), 'null'::jsonb)::json
            WHERE ns = :ns
        """), {"path": "{" + ",".join(dotted.split(".")) + "}", "ns": namespace})
        after = conn.execute(
            text("SELECT document FROM settings_documents WHERE ns = :ns"), {"ns": namespace}
        ).scalar()
    return get_at(after, dotted) in (None, "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clear", action="store_true", help="blank the undecryptable fields")
    args = ap.parse_args()

    from services.encryption import _resolve_key_str
    source = _resolve_key_str()
    dev_fallback = source == "langconfig-dev-insecure-key-change-me"
    print(f"  encryption key : {'DEV FALLBACK (no key configured anywhere)' if dev_fallback else f'configured ({len(source)} chars)'}")

    with engine.connect() as conn:
        namespaces = [r[0] for r in conn.execute(text("SELECT ns FROM settings_documents ORDER BY ns"))]
    print(f"  settings rows  : {', '.join(namespaces) or 'none'}")

    broken, checked = scan()
    print(f"  secrets checked: {checked} encrypted value(s) across those rows")
    if checked == 0:
        print("\n  no encrypted secrets are stored in this database — nothing to verify")
        return 0
    if not broken:
        print(f"\n  every stored secret is readable with the current key ({checked} checked)")
        return 0

    print(f"\n  {len(broken)} unreadable secret field(s):")
    for ns, dotted, reason in broken:
        print(f"    {ns}.{dotted}  ({reason})")

    print("\n  These were encrypted with a different API_KEY_ENCRYPTION_KEY. The value cannot be")
    print("  recovered without that key; what is left is to blank the field and store a new one.")
    print("  While unreadable, seed_all.py step 4b aborts and the Settings UI fails to load these")
    print("  namespaces at all.")

    if not args.clear:
        print("\n  report only. Re-run with --clear to blank exactly these fields.")
        return 0

    blanked = 0
    for ns, dotted, _ in broken:
        if blank(ns, dotted):
            blanked += 1
        else:
            print(f"    ! could not blank {ns}.{dotted} — the field is unchanged")
    print(f"\n  blanked {blanked}/{len(broken)} field(s) — re-enter the values in Settings → API Keys")
    remaining, _ = scan()
    print(f"  remaining unreadable: {len(remaining)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
