"""
Catalog Writer — Persists all extracted data into a SQLite database
following the schema defined in REQ-4.1.

Design ref: §3.7 Catalog Writer (SQLite)
"""

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("fde-onboarding.catalog_writer")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repos (
    repo_url TEXT PRIMARY KEY,
    clone_date TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    scan_duration_ms INTEGER,
    total_files INTEGER,
    total_modules INTEGER,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    magika_type TEXT NOT NULL,
    language TEXT,
    size_bytes INTEGER,
    is_generated BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS modules (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL,
    file_count INTEGER,
    line_count INTEGER
);

CREATE TABLE IF NOT EXISTS dependencies (
    source_module TEXT NOT NULL,
    target_module TEXT NOT NULL,
    dependency_type TEXT NOT NULL,
    PRIMARY KEY (source_module, target_module, dependency_type)
);

CREATE TABLE IF NOT EXISTS conventions (
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    config_path TEXT,
    PRIMARY KEY (category, name)
);

CREATE TABLE IF NOT EXISTS pipeline_chain (
    step_order INTEGER PRIMARY KEY,
    module_name TEXT NOT NULL,
    produces TEXT,
    consumes TEXT
);

CREATE TABLE IF NOT EXISTS module_boundaries (
    edge_id TEXT PRIMARY KEY,
    producer TEXT NOT NULL,
    consumer TEXT NOT NULL,
    transform_description TEXT
);

CREATE TABLE IF NOT EXISTS tech_stack (
    tag TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    confidence REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS level_patterns (
    pattern TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    description TEXT
);
"""


@dataclass
class CatalogWriteResult:
    """Result of writing the catalog."""

    catalog_path: str
    tables_written: int
    rows_inserted: int
    duration_ms: int


def write_catalog(
    catalog_path: str,
    repo_url: str,
    commit_sha: str,
    scan_duration_ms: int,
    files: list,
    modules: list,
    edges: list,
    conventions: list,
    pipeline_chain: list,
    module_boundaries: list,
    tech_stack: list,
    level_patterns: list,
    error_count: int = 0,
) -> CatalogWriteResult:
    """
    Write all extracted data to the SQLite catalog.

    Returns:
        CatalogWriteResult with metadata.
    """
    start = time.time()
    rows_inserted = 0

    os.makedirs(os.path.dirname(catalog_path) if os.path.dirname(catalog_path) else ".", exist_ok=True)

    conn = sqlite3.connect(catalog_path)
    try:
        conn.executescript(SCHEMA_SQL)
        _clear_tables(conn)

        # Write repos metadata
        conn.execute(
            "INSERT OR REPLACE INTO repos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                repo_url,
                datetime.now(timezone.utc).isoformat(),
                commit_sha,
                scan_duration_ms,
                len(files),
                len(modules),
                error_count,
            ),
        )
        rows_inserted += 1

        # Write files
        for f in files:
            conn.execute(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)",
                (_attr(f, "path"), _attr(f, "magika_type"), _attr(f, "language"),
                 _attr(f, "size_bytes"), _attr(f, "is_generated")),
            )
            rows_inserted += 1

        # Write modules
        for m in modules:
            conn.execute(
                "INSERT OR REPLACE INTO modules VALUES (?, ?, ?, ?, ?)",
                (_attr(m, "name"), _attr(m, "path"), _attr(m, "type"),
                 len(_attr(m, "functions", [])) + len(_attr(m, "classes", [])), 0),
            )
            rows_inserted += 1

        # Write dependencies
        for edge in edges:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO dependencies VALUES (?, ?, ?)",
                    (_attr(edge, "source_module"), _attr(edge, "target_module"),
                     _attr(edge, "dependency_type")),
                )
                rows_inserted += 1
            except sqlite3.IntegrityError:
                pass

        # Write conventions
        for conv in conventions:
            conn.execute(
                "INSERT OR REPLACE INTO conventions VALUES (?, ?, ?, ?)",
                (_attr(conv, "category"), _attr(conv, "name"),
                 _attr(conv, "version"), _attr(conv, "config_path")),
            )
            rows_inserted += 1

        # Write pipeline chain
        for step in pipeline_chain:
            conn.execute(
                "INSERT OR REPLACE INTO pipeline_chain VALUES (?, ?, ?, ?)",
                (_attr(step, "step_order"), _attr(step, "module_name"),
                 _attr(step, "produces"), _attr(step, "consumes")),
            )
            rows_inserted += 1

        # Write module boundaries
        for boundary in module_boundaries:
            conn.execute(
                "INSERT OR REPLACE INTO module_boundaries VALUES (?, ?, ?, ?)",
                (_attr(boundary, "edge_id"), _attr(boundary, "producer"),
                 _attr(boundary, "consumer"), _attr(boundary, "transform_description")),
            )
            rows_inserted += 1

        # Write tech stack
        for tag in tech_stack:
            conn.execute(
                "INSERT OR REPLACE INTO tech_stack VALUES (?, ?, ?)",
                (_attr(tag, "tag"), _attr(tag, "category"), _attr(tag, "confidence", 1.0)),
            )
            rows_inserted += 1

        # Write level patterns
        for pat in level_patterns:
            conn.execute(
                "INSERT OR REPLACE INTO level_patterns VALUES (?, ?, ?)",
                (_attr(pat, "pattern"), _attr(pat, "level"), _attr(pat, "description")),
            )
            rows_inserted += 1

        conn.commit()
    finally:
        conn.close()

    duration_ms = int((time.time() - start) * 1000)

    logger.info("Catalog written: %s (%d rows, %dms)", catalog_path, rows_inserted, duration_ms)

    return CatalogWriteResult(
        catalog_path=catalog_path,
        tables_written=9,
        rows_inserted=rows_inserted,
        duration_ms=duration_ms,
    )


def _clear_tables(conn: sqlite3.Connection) -> None:
    """Clear all data tables for a fresh write."""
    tables = [
        "files", "modules", "dependencies", "conventions",
        "pipeline_chain", "module_boundaries", "tech_stack", "level_patterns",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")


def _attr(obj, name: str, default=None):
    """Get attribute from object or dict."""
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


# --- Catalog Query Interface (§5.2) ---


def get_tech_stack(catalog_path: str) -> list[str]:
    """REQ-6.1: Returns tech_stack tags for data contract population."""
    conn = sqlite3.connect(catalog_path)
    try:
        return [row[0] for row in conn.execute("SELECT tag FROM tech_stack")]
    finally:
        conn.close()


def get_suggested_level(catalog_path: str, task_labels: list[str], task_description: str) -> str:
    """REQ-6.2: Returns suggested engineering level based on pattern matching."""
    conn = sqlite3.connect(catalog_path)
    try:
        patterns = conn.execute("SELECT pattern, level FROM level_patterns").fetchall()
        for pattern, level in patterns:
            if pattern.lower() in task_description.lower() or pattern in task_labels:
                return level
        return "L3"
    finally:
        conn.close()


def get_module_context(catalog_path: str, file_path: str) -> dict:
    """REQ-6.1: Returns module context for constraint extractor."""
    conn = sqlite3.connect(catalog_path)
    try:
        module = conn.execute(
            "SELECT name, type, file_count FROM modules WHERE path LIKE ?",
            (f"%{file_path}%",),
        ).fetchone()
        deps = conn.execute(
            "SELECT target_module, dependency_type FROM dependencies WHERE source_module = ?",
            (module[0],) if module else ("",),
        ).fetchall()
        return {"module": module, "dependencies": deps}
    finally:
        conn.close()
