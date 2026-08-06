"""SQLite setup + test for the LangGraph SQL agent.

Downloads the Chinook sample database (digital media store) if missing and
runs a quick sanity check against it. Also exposes the SQL tools shared by
sql_agent.py and sql_agent_hitl.py.

Mimics https://docs.langchain.com/oss/python/langgraph/sql-agent sections 2-3.
"""
import pathlib
import sqlite3

import requests
from langchain.tools import tool

# Chinook.db lives at the repo root so every script finds it regardless of CWD.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "Chinook.db"
CHINOOK_URL = "https://storage.googleapis.com/benchmarks-artifacts/chinook/Chinook.db"


def ensure_chinook_db() -> pathlib.Path:
    """Download Chinook.db once; skip when it already exists."""
    if DB_PATH.exists():
        print(f"{DB_PATH} already exists, skipping download.")
    else:
        response = requests.get(CHINOOK_URL, timeout=60)
        if response.status_code == 200:
            DB_PATH.write_bytes(response.content)
            print(f"File downloaded and saved as {DB_PATH}")
        else:
            raise RuntimeError(
                f"Failed to download the file. Status code: {response.status_code}"
            )
    return DB_PATH


def _connect() -> sqlite3.Connection:
    """Open a read-only connection so model-generated SQL can never mutate the DB."""
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


@tool
def sql_db_list_tables() -> str:
    """Input is an empty string, output is a comma-separated list of tables in the database."""
    con = _connect()
    try:
        cursor = con.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [
            row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")
        ]
        return ", ".join(tables)
    finally:
        con.close()


@tool
def sql_db_schema(table_names: str) -> str:
    """Input to this tool is a comma-separated list of tables, output is the schema and sample rows for those tables.
    Be sure that the tables actually exist by calling sql_db_list_tables first!
    Example Input: table1, table2, table3"""
    con = _connect()
    try:
        cursor = con.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        valid_tables = {
            row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")
        }
        results = []
        for table in table_names.split(","):
            table = table.strip()
            if table not in valid_tables:
                results.append(
                    f"Error: table_names {{{table!r}}} not found in database"
                )
                continue
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;",
                (table,),
            )
            schema_row = cursor.fetchone()
            if schema_row:
                results.append(schema_row[0])
                try:
                    quoted_table = '"' + table.replace('"', '""') + '"'
                    cursor.execute(f"SELECT * FROM {quoted_table} LIMIT 3;")
                    rows = cursor.fetchall()
                    if rows:
                        col_names = [description[0] for description in cursor.description]
                        results.append(
                            f"/*\n3 rows from {table} table:\n"
                            + "\t".join(col_names)
                            + "\n"
                            + "\n".join(
                                "\t".join(str(x) for x in row) for row in rows
                            )
                            + "\n*/"
                        )
                except Exception as e:
                    results.append(f"Error fetching sample rows: {e}")
        return "\n\n".join(results)
    finally:
        con.close()


@tool
def sql_db_query(query: str) -> str:
    """Input to this tool is a detailed and correct SQL query, output is a result from the database.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    If you encounter an issue with Unknown column 'xxxx' in 'field list', use sql_db_schema to query the correct table fields."""
    con = _connect()
    try:
        cursor = con.cursor()
        cursor.execute(query)
        res = cursor.fetchall()
        return str(res)
    except Exception as e:
        return f"Error: {e}"
    finally:
        con.close()


def main() -> None:
    """Download + inspect Chinook, then run a few sanity queries."""
    ensure_chinook_db()

    con = sqlite3.connect(DB_PATH)
    try:
        cursor = con.cursor()

        # 1. List available tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [
            row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")
        ]
        print("Dialect: sqlite")
        print(f"Available tables: {tables}")

        # 2. Sample output
        cursor.execute("SELECT * FROM Artist LIMIT 5;")
        print(f"Sample output: {cursor.fetchall()}")

        # 3. Sanity queries exercised by the agent later
        test_queries = [
            "SELECT COUNT(*) FROM Track;",
            "SELECT g.Name, ROUND(AVG(t.Milliseconds)) AS avg_ms "
            "FROM Track t JOIN Genre g ON t.GenreId = g.GenreId "
            "GROUP BY g.Name ORDER BY avg_ms DESC LIMIT 3;",
        ]
        for query in test_queries:
            cursor.execute(query)
            print(f"\nQuery: {query}\nResult: {cursor.fetchall()}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
