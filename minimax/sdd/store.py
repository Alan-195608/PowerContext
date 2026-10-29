"""Real embedded seekdb store. All returned source text comes from SQL rows."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import pylibseekdb
import pymysql

from .common import audit, digest


@contextmanager
def database(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    instance = pylibseekdb.open(str(directory / "seekdb"))
    connection = None
    try:
        options = dict(instance.connection_options())
        options.update(database="test", autocommit=False, charset="utf8mb4")
        connection = pymysql.connect(**options)
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            cursor.execute("""CREATE TABLE IF NOT EXISTS sdd_documents (
                path VARCHAR(512) PRIMARY KEY,
                kind VARCHAR(16) NOT NULL,
                sha256 VARCHAR(64) NOT NULL,
                content LONGTEXT NOT NULL
            )""")
        connection.commit()
        audit(directory, "seekdb.open", version=version)
        yield connection
    finally:
        if connection is not None:
            connection.close()
        instance.close()


def ingest(directory, project):
    project = Path(project).resolve()
    records = []
    for path in sorted(project.rglob("*")):
        if (
            path.is_symlink()
            or not path.is_file()
            or any(part.startswith(".") for part in path.relative_to(project).parts)
        ):
            continue
        relative = path.relative_to(project).as_posix()
        if path.suffix not in {".md", ".py"} or "__pycache__" in path.parts:
            continue
        content = path.read_text()
        kind = (
            "spec"
            if path.suffix == ".md"
            else "test"
            if "tests" in path.relative_to(project).parts
            else "code"
        )
        records.append((relative, kind, digest(content), content))
    if not records:
        raise ValueError("No project documents found")
    # One transaction replaces this project's snapshot, including deletions.
    with database(directory) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM sdd_documents")
            cursor.executemany(
                "INSERT INTO sdd_documents(path,kind,sha256,content) VALUES (%s,%s,%s,%s)",
                records,
            )
        connection.commit()
    audit(
        directory,
        "seekdb.ingest",
        documents=[{"path": r[0], "sha256": r[2]} for r in records],
    )
    return {"count": len(records), "sources": [r[0] for r in records]}


def retrieve(directory, query, limit_per_kind=4):
    terms = list(dict.fromkeys(re.findall(r"[\w-]+", query.casefold())))[:16]
    if not terms:
        raise ValueError("A nonempty query is required")
    # INSTR treats wildcard and quote characters literally; values are always bound.
    predicates = " OR ".join(
        "INSTR(LOWER(CONCAT(path,' ',content)),%s)>0" for _ in terms
    )
    sql = f"SELECT path,kind,sha256,content FROM sdd_documents WHERE kind=%s AND ({predicates}) ORDER BY path LIMIT %s"
    results = []
    with database(directory) as connection:
        with connection.cursor() as cursor:
            for kind in ("spec", "code", "test"):
                params = [kind, *terms, limit_per_kind]
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                audit(
                    directory,
                    "seekdb.query",
                    sql=sql,
                    parameters=params,
                    returned=[row[0] for row in rows],
                )
                results.extend(
                    {
                        "path": r[0],
                        "kind": r[1],
                        "sha256": r[2],
                        "content": r[3],
                        "lines": [1, len(r[3].splitlines())],
                    }
                    for r in rows
                )
    return results
