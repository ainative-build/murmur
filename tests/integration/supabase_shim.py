"""psycopg-backed shim for the Supabase client surface used in `db.py`.

`db.py` calls `supabase.create_client(...)` and uses a fluent chain like
`client.table("messages").upsert(row, on_conflict=..., ignore_duplicates=True).execute()`.
This module installs a replacement that translates each supported operation
to raw SQL against the local test Postgres.

Phase 1 status: skeleton + minimal upsert/select/delete/update/in_/gt/order/limit/single/text_search.
Phase 2+: extend coverage as tests need it. Unsupported ops raise NotImplementedError
so missing surface area is loud, not silent.

Tests that don't touch `db` (e.g. the `/health` smoke test) do not trigger
this shim — the autouse fixture that installs it lives in conftest and the
smoke test bypasses it via `request.applymarker("no_db_shim")` if needed.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import patch

import psycopg
from psycopg import sql


def _serialise_value(v: Any) -> Any:
    """Convert psycopg-native types to JSON-friendly forms supabase-py would return."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _serialise_row(row: dict) -> dict:
    return {k: _serialise_value(v) for k, v in row.items()}


@dataclass
class _APIResponse:
    """Mimics `supabase.PostgrestResponse` — code reads `.data` and sometimes `.count`."""

    data: Optional[list] = None
    count: Optional[int] = None


class _Query:
    """Builder for a single chained query against one table.

    Captures clauses (filters, ordering, limit) until `.execute()` translates
    them into SQL. Each operation returns `self` so chaining works.
    """

    def __init__(self, table: str, dsn: str):
        self._table = table
        self._dsn = dsn
        self._op: Optional[str] = None  # "select" | "upsert" | "update" | "delete" | "fts"
        self._select_cols: str = "*"
        self._want_count: bool = False
        self._upsert_row: Optional[dict] = None
        self._upsert_on_conflict: Optional[str] = None
        self._upsert_ignore_duplicates: bool = False
        self._update_data: Optional[dict] = None
        self._eq_filters: list[tuple[str, Any]] = []
        self._in_filters: list[tuple[str, list]] = []
        self._gt_filters: list[tuple[str, Any]] = []
        self._lt_filters: list[tuple[str, Any]] = []
        self._order_by: Optional[tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._single: bool = False
        self._fts: Optional[tuple[str, str]] = None  # (col, query)

    # -------- top-level ops --------

    def select(self, cols: str = "*", **kwargs):
        self._op = "select"
        self._select_cols = cols
        # supabase-py: select(cols, count="exact") returns total row count alongside data
        self._want_count = kwargs.get("count") is not None
        return self

    def upsert(self, row, *, on_conflict: Optional[str] = None, ignore_duplicates: bool = False, **kw):
        self._op = "upsert"
        self._upsert_row = row
        self._upsert_on_conflict = on_conflict
        self._upsert_ignore_duplicates = ignore_duplicates
        return self

    def insert(self, row, **kw):
        """Plain INSERT (no conflict handling). Returns inserted row."""
        self._op = "upsert"
        self._upsert_row = row
        self._upsert_on_conflict = None
        self._upsert_ignore_duplicates = False
        return self

    def update(self, data, **kw):
        self._op = "update"
        self._update_data = data
        return self

    def delete(self, **kw):
        self._op = "delete"
        return self

    def text_search(self, col: str, query: str, **kw):
        self._op = "fts"
        self._fts = (col, query)
        self._select_cols = "*"
        return self

    # -------- filters / modifiers --------

    def eq(self, col: str, val: Any):
        self._eq_filters.append((col, val))
        return self

    def in_(self, col: str, vals: list):
        self._in_filters.append((col, vals))
        return self

    def gt(self, col: str, val: Any):
        self._gt_filters.append((col, val))
        return self

    def lt(self, col: str, val: Any):
        self._lt_filters.append((col, val))
        return self

    def order(self, col: str, desc: bool = False):
        self._order_by = (col, desc)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def single(self):
        self._single = True
        self._limit = 1
        return self

    # -------- execute --------

    def execute(self) -> _APIResponse:
        with psycopg.connect(self._dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as conn:
            with conn.cursor() as cur:
                if self._op == "select" or self._op == "fts":
                    return self._exec_select(cur)
                if self._op == "upsert":
                    return self._exec_upsert(cur)
                if self._op == "update":
                    return self._exec_update(cur)
                if self._op == "delete":
                    return self._exec_delete(cur)
                raise NotImplementedError(f"Unhandled op {self._op!r} on {self._table}")

    # -------- SQL builders --------

    def _where_clause(self) -> tuple[sql.Composable, list]:
        clauses: list[sql.Composable] = []
        params: list[Any] = []
        for col, val in self._eq_filters:
            clauses.append(sql.SQL("{} = %s").format(sql.Identifier(col)))
            params.append(val)
        for col, val in self._gt_filters:
            clauses.append(sql.SQL("{} > %s").format(sql.Identifier(col)))
            params.append(val)
        for col, val in self._lt_filters:
            clauses.append(sql.SQL("{} < %s").format(sql.Identifier(col)))
            params.append(val)
        for col, vals in self._in_filters:
            placeholders = sql.SQL(",").join([sql.Placeholder()] * len(vals))
            clauses.append(sql.SQL("{} IN ({})").format(sql.Identifier(col), placeholders))
            params.extend(vals)
        if self._fts:
            col, query = self._fts
            clauses.append(sql.SQL("{} @@ to_tsquery('simple', %s)").format(sql.Identifier(col)))
            params.append(query)
        if not clauses:
            return sql.SQL(""), params
        return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses), params

    def _exec_select(self, cur) -> _APIResponse:
        cols = sql.SQL("*") if self._select_cols == "*" else sql.SQL(self._select_cols)
        where, params = self._where_clause()
        order = sql.SQL("")
        if self._order_by:
            col, desc = self._order_by
            order = sql.SQL(" ORDER BY {} {}").format(sql.Identifier(col), sql.SQL("DESC" if desc else "ASC"))
        limit = sql.SQL(" LIMIT {}").format(sql.Literal(self._limit)) if self._limit else sql.SQL("")
        query = sql.SQL("SELECT {} FROM {}{}{}{}").format(
            cols, sql.Identifier(self._table), where, order, limit
        )
        cur.execute(query, params)
        rows = [_serialise_row(r) for r in cur.fetchall()]
        count = len(rows) if self._want_count else None
        if self._single:
            return _APIResponse(data=rows[0] if rows else None, count=count)
        return _APIResponse(data=rows, count=count)

    def _exec_upsert(self, cur) -> _APIResponse:
        row = self._upsert_row
        cols_list = list(row.keys())
        cols = sql.SQL(",").join(sql.Identifier(c) for c in cols_list)
        placeholders = sql.SQL(",").join([sql.Placeholder()] * len(cols_list))
        params = [row[c] for c in cols_list]

        conflict_clause = sql.SQL("")
        if self._upsert_on_conflict:
            conflict_cols = [c.strip() for c in self._upsert_on_conflict.split(",")]
            conflict_target = sql.SQL("({})").format(
                sql.SQL(",").join(sql.Identifier(c) for c in conflict_cols)
            )
            if self._upsert_ignore_duplicates:
                conflict_clause = sql.SQL(" ON CONFLICT {} DO NOTHING").format(conflict_target)
            else:
                # MERGE — update all non-conflict columns
                update_cols = [c for c in cols_list if c not in conflict_cols]
                if update_cols:
                    set_clause = sql.SQL(",").join(
                        sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                        for c in update_cols
                    )
                    conflict_clause = sql.SQL(" ON CONFLICT {} DO UPDATE SET {}").format(
                        conflict_target, set_clause
                    )
                else:
                    conflict_clause = sql.SQL(" ON CONFLICT {} DO NOTHING").format(conflict_target)

        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}){} RETURNING *").format(
            sql.Identifier(self._table), cols, placeholders, conflict_clause
        )
        cur.execute(query, params)
        rows = [_serialise_row(r) for r in cur.fetchall()]
        return _APIResponse(data=rows)

    def _exec_update(self, cur) -> _APIResponse:
        data = self._update_data
        set_pairs = sql.SQL(",").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in data.keys()
        )
        where, where_params = self._where_clause()
        params = list(data.values()) + where_params
        query = sql.SQL("UPDATE {} SET {}{} RETURNING *").format(
            sql.Identifier(self._table), set_pairs, where
        )
        cur.execute(query, params)
        return _APIResponse(data=cur.fetchall())

    def _exec_delete(self, cur) -> _APIResponse:
        where, params = self._where_clause()
        query = sql.SQL("DELETE FROM {}{} RETURNING *").format(
            sql.Identifier(self._table), where
        )
        cur.execute(query, params)
        return _APIResponse(data=cur.fetchall())


class _PsycopgSupabaseClient:
    """Drop-in replacement for `supabase.Client` for the operations we use."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def table(self, name: str) -> _Query:
        return _Query(name, self._dsn)


_active_patches: list = []


def install_psycopg_shim(dsn: str) -> None:
    """Install the shim. Idempotent — calling twice replaces the active one."""
    uninstall_psycopg_shim()

    client = _PsycopgSupabaseClient(dsn)
    p1 = patch("db._client", client)
    p1.start()
    _active_patches.append(p1)

    # Some db.py paths call get_client() directly — make it return our shim.
    p2 = patch("db.get_client", return_value=client)
    p2.start()
    _active_patches.append(p2)


def uninstall_psycopg_shim() -> None:
    while _active_patches:
        p = _active_patches.pop()
        try:
            p.stop()
        except RuntimeError:
            pass
