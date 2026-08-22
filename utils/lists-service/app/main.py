from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from psycopg.rows import dict_row


def _build_default_db_url() -> str:
    user = os.getenv("POSTGRES_USER", "ai_living_user")
    password = os.getenv("POSTGRES_PASSWORD", "ai_living_password")
    database = os.getenv("POSTGRES_DB", "ai_living")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


DATABASE_URL = os.getenv("DATABASE_URL", _build_default_db_url())


def _public(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items()}
    return value


def _connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _init_db() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS lists (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS list_items (
                    id UUID PRIMARY KEY,
                    list_id UUID NOT NULL REFERENCES lists(id),
                    title TEXT NOT NULL,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id UUID PRIMARY KEY,
                    operation TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id UUID,
                    actor TEXT NOT NULL,
                    payload JSONB,
                    before_state JSONB,
                    after_state JSONB,
                    revert_of_audit_id UUID,
                    reverted_by_audit_id UUID,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lists_name ON lists (LOWER(name));
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_items_title ON list_items (LOWER(title));
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_items_list_id ON list_items (list_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log (target_type, target_id);
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_revert_once
                ON audit_log (revert_of_audit_id)
                WHERE revert_of_audit_id IS NOT NULL;
                """
            )


def _fetch_list(conn: psycopg.Connection, list_id: uuid.UUID, include_deleted: bool = False) -> dict[str, Any] | None:
    query = "SELECT * FROM lists WHERE id = %s"
    params: list[Any] = [list_id]
    if not include_deleted:
        query += " AND is_deleted = FALSE"
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def _fetch_item(conn: psycopg.Connection, item_id: uuid.UUID, include_deleted: bool = False) -> dict[str, Any] | None:
    query = "SELECT * FROM list_items WHERE id = %s"
    params: list[Any] = [item_id]
    if not include_deleted:
        query += " AND is_deleted = FALSE"
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def _write_audit(
    conn: psycopg.Connection,
    operation: str,
    target_type: str,
    target_id: uuid.UUID | str | None,
    actor: str,
    payload: dict[str, Any] | None,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    revert_of_audit_id: uuid.UUID | str | None = None,
) -> str:
    audit_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (
                id,
                operation,
                target_type,
                target_id,
                actor,
                payload,
                before_state,
                after_state,
                revert_of_audit_id
            ) VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s
            )
            """,
            [
                audit_id,
                operation,
                target_type,
                target_id,
                actor,
                json.dumps(_public(payload)) if payload is not None else None,
                json.dumps(_public(before_state)) if before_state is not None else None,
                json.dumps(_public(after_state)) if after_state is not None else None,
                revert_of_audit_id,
            ],
        )
    return audit_id


class IdRequest(BaseModel):
    id: uuid.UUID
    include_deleted: bool = False


class SearchRequest(BaseModel):
    query: str | None = None
    include_deleted: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ListCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    actor: str = "agent"


class ListUpdateRequest(BaseModel):
    id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    actor: str = "agent"


class ListDeleteRequest(BaseModel):
    id: uuid.UUID
    actor: str = "agent"


class ItemCreateRequest(BaseModel):
    list_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None
    status: str = "open"
    actor: str = "agent"


class ItemUpdateRequest(BaseModel):
    id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    status: str | None = None
    actor: str = "agent"


class ItemDeleteRequest(BaseModel):
    id: uuid.UUID
    actor: str = "agent"


class AuditSearchRequest(BaseModel):
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    operation: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AuditRevertRequest(BaseModel):
    audit_id: uuid.UUID
    actor: str = "agent"


TOOL_DEFINITIONS = [
    {
        "name": "lists_get",
        "description": "Get one list by id.",
        "endpoint": "/lists/get",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "List UUID."},
                "include_deleted": {"type": "boolean", "default": False},
            },
            "required": ["id"],
        },
    },
    {
        "name": "lists_search",
        "description": "Search lists by optional text query with pagination.",
        "endpoint": "/lists/search",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include_deleted": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "lists_create",
        "description": "Create a list with name and optional description.",
        "endpoint": "/lists/create",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "lists_update",
        "description": "Update list name and or description.",
        "endpoint": "/lists/update",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "lists_delete",
        "description": "Soft-delete a list.",
        "endpoint": "/lists/delete",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "items_get",
        "description": "Get one list item by id.",
        "endpoint": "/items/get",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "include_deleted": {"type": "boolean", "default": False},
            },
            "required": ["id"],
        },
    },
    {
        "name": "items_search",
        "description": "Search list items by text with pagination.",
        "endpoint": "/items/search",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include_deleted": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "items_create",
        "description": "Create a list item inside a list.",
        "endpoint": "/items/create",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string"},
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "status": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["list_id", "title"],
        },
    },
    {
        "name": "items_update",
        "description": "Update list item fields.",
        "endpoint": "/items/update",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "status": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "items_delete",
        "description": "Soft-delete a list item.",
        "endpoint": "/items/delete",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "audit_get",
        "description": "Get one audit entry by id.",
        "endpoint": "/audit/get",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}
            },
            "required": ["id"],
        },
    },
    {
        "name": "audit_search",
        "description": "Search audit entries with filters.",
        "endpoint": "/audit/search",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string"},
                "target_id": {"type": "string"},
                "operation": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "audit_revert",
        "description": "Revert one mutation using its audit id.",
        "endpoint": "/audit/revert",
        "method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["audit_id"],
        },
    },
]

app = FastAPI(title="utils-lists", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    _init_db()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "utils-lists",
        "tools": [tool["name"] for tool in TOOL_DEFINITIONS],
    }


@app.get("/agent/tool-definitions")
def agent_tool_definitions() -> dict[str, Any]:
    return {"tools": TOOL_DEFINITIONS}


@app.post("/lists/get")
def lists_get(request: IdRequest) -> dict[str, Any]:
    with _connect() as conn:
        list_row = _fetch_list(conn, request.id, include_deleted=request.include_deleted)
        if not list_row:
            raise HTTPException(status_code=404, detail="List not found")
        return {"list": _public(list_row)}


@app.post("/lists/search")
def lists_search(request: SearchRequest) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if not request.include_deleted:
        where.append("is_deleted = FALSE")
    if request.query:
        where.append("(name ILIKE %s OR COALESCE(description, '') ILIKE %s)")
        token = f"%{request.query}%"
        params.extend([token, token])

    params.extend([request.limit, request.offset])
    query = f"""
        SELECT *
        FROM lists
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return {"lists": _public(rows), "count": len(rows)}


@app.post("/lists/create")
def lists_create(request: ListCreateRequest) -> dict[str, Any]:
    list_id = uuid.uuid4()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lists (id, name, description)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                [list_id, request.name, request.description],
            )
            created = cur.fetchone()
        audit_id = _write_audit(
            conn=conn,
            operation="lists.create",
            target_type="list",
            target_id=list_id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=None,
            after_state=created,
        )
        return {"list": _public(created), "audit_id": audit_id}


@app.post("/lists/update")
def lists_update(request: ListUpdateRequest) -> dict[str, Any]:
    with _connect() as conn:
        current = _fetch_list(conn, request.id, include_deleted=True)
        if not current:
            raise HTTPException(status_code=404, detail="List not found")

        new_name = request.name if request.name is not None else current["name"]
        new_description = request.description if request.description is not None else current["description"]

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE lists
                SET name = %s,
                    description = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                [new_name, new_description, request.id],
            )
            updated = cur.fetchone()

        audit_id = _write_audit(
            conn=conn,
            operation="lists.update",
            target_type="list",
            target_id=request.id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=current,
            after_state=updated,
        )
        return {"list": _public(updated), "audit_id": audit_id}


@app.post("/lists/delete")
def lists_delete(request: ListDeleteRequest) -> dict[str, Any]:
    with _connect() as conn:
        current = _fetch_list(conn, request.id, include_deleted=True)
        if not current:
            raise HTTPException(status_code=404, detail="List not found")
        if current["is_deleted"]:
            raise HTTPException(status_code=409, detail="List already deleted")

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE lists
                SET is_deleted = TRUE,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                [request.id],
            )
            updated = cur.fetchone()

        audit_id = _write_audit(
            conn=conn,
            operation="lists.delete",
            target_type="list",
            target_id=request.id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=current,
            after_state=updated,
        )
        return {"list": _public(updated), "audit_id": audit_id}


@app.post("/items/get")
def items_get(request: IdRequest) -> dict[str, Any]:
    with _connect() as conn:
        row = _fetch_item(conn, request.id, include_deleted=request.include_deleted)
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"item": _public(row)}


@app.post("/items/search")
def items_search(request: SearchRequest) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if not request.include_deleted:
        where.append("is_deleted = FALSE")
    if request.query:
        where.append("(title ILIKE %s OR COALESCE(notes, '') ILIKE %s OR status ILIKE %s)")
        token = f"%{request.query}%"
        params.extend([token, token, token])

    params.extend([request.limit, request.offset])
    query = f"""
        SELECT *
        FROM list_items
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return {"items": _public(rows), "count": len(rows)}


@app.post("/items/create")
def items_create(request: ItemCreateRequest) -> dict[str, Any]:
    item_id = uuid.uuid4()
    with _connect() as conn:
        parent = _fetch_list(conn, request.list_id, include_deleted=False)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent list not found")

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO list_items (id, list_id, title, notes, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                [item_id, request.list_id, request.title, request.notes, request.status],
            )
            created = cur.fetchone()

        audit_id = _write_audit(
            conn=conn,
            operation="items.create",
            target_type="item",
            target_id=item_id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=None,
            after_state=created,
        )
        return {"item": _public(created), "audit_id": audit_id}


@app.post("/items/update")
def items_update(request: ItemUpdateRequest) -> dict[str, Any]:
    with _connect() as conn:
        current = _fetch_item(conn, request.id, include_deleted=True)
        if not current:
            raise HTTPException(status_code=404, detail="Item not found")

        new_title = request.title if request.title is not None else current["title"]
        new_notes = request.notes if request.notes is not None else current["notes"]
        new_status = request.status if request.status is not None else current["status"]

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE list_items
                SET title = %s,
                    notes = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                [new_title, new_notes, new_status, request.id],
            )
            updated = cur.fetchone()

        audit_id = _write_audit(
            conn=conn,
            operation="items.update",
            target_type="item",
            target_id=request.id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=current,
            after_state=updated,
        )
        return {"item": _public(updated), "audit_id": audit_id}


@app.post("/items/delete")
def items_delete(request: ItemDeleteRequest) -> dict[str, Any]:
    with _connect() as conn:
        current = _fetch_item(conn, request.id, include_deleted=True)
        if not current:
            raise HTTPException(status_code=404, detail="Item not found")
        if current["is_deleted"]:
            raise HTTPException(status_code=409, detail="Item already deleted")

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE list_items
                SET is_deleted = TRUE,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                [request.id],
            )
            updated = cur.fetchone()

        audit_id = _write_audit(
            conn=conn,
            operation="items.delete",
            target_type="item",
            target_id=request.id,
            actor=request.actor,
            payload=request.model_dump(),
            before_state=current,
            after_state=updated,
        )
        return {"item": _public(updated), "audit_id": audit_id}


@app.post("/audit/get")
def audit_get(request: IdRequest) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM audit_log WHERE id = %s", [request.id])
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Audit entry not found")
            return {"audit": _public(row)}


@app.post("/audit/search")
def audit_search(request: AuditSearchRequest) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if request.target_type:
        where.append("target_type = %s")
        params.append(request.target_type)
    if request.target_id:
        where.append("target_id = %s")
        params.append(request.target_id)
    if request.operation:
        where.append("operation = %s")
        params.append(request.operation)

    params.extend([request.limit, request.offset])
    query = f"""
        SELECT *
        FROM audit_log
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return {"entries": _public(rows), "count": len(rows)}


def _restore_list(conn: psycopg.Connection, state: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE lists
            SET name = %s,
                description = %s,
                is_deleted = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            [state.get("name"), state.get("description"), state.get("is_deleted", False), state.get("id")],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="List to restore not found")
        return row


def _restore_item(conn: psycopg.Connection, state: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE list_items
            SET list_id = %s,
                title = %s,
                notes = %s,
                status = %s,
                is_deleted = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            [
                state.get("list_id"),
                state.get("title"),
                state.get("notes"),
                state.get("status"),
                state.get("is_deleted", False),
                state.get("id"),
            ],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item to restore not found")
        return row


@app.post("/audit/revert")
def audit_revert(request: AuditRevertRequest) -> dict[str, Any]:
    allowed = {
        "lists.create",
        "lists.update",
        "lists.delete",
        "items.create",
        "items.update",
        "items.delete",
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM audit_log WHERE id = %s", [request.audit_id])
            source = cur.fetchone()

        if not source:
            raise HTTPException(status_code=404, detail="Audit entry not found")
        if source["operation"] not in allowed:
            raise HTTPException(status_code=409, detail="Operation is not revertable")
        if source.get("reverted_by_audit_id") is not None:
            raise HTTPException(status_code=409, detail="Operation was already reverted")

        target_type = source["target_type"]
        operation = source["operation"]
        target_id = source["target_id"]
        if target_id is None:
            raise HTTPException(status_code=409, detail="Audit entry has no target_id")

        before_state = source.get("before_state")
        after_state = source.get("after_state")

        reverted_entity: dict[str, Any] | None = None

        if operation.endswith(".create"):
            if target_type == "list":
                current = _fetch_list(conn, target_id, include_deleted=True)
                if not current:
                    raise HTTPException(status_code=404, detail="List not found for revert")
                if current["is_deleted"]:
                    raise HTTPException(status_code=409, detail="List already deleted")
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE lists
                        SET is_deleted = TRUE,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        [target_id],
                    )
                    reverted_entity = cur.fetchone()
            else:
                current = _fetch_item(conn, target_id, include_deleted=True)
                if not current:
                    raise HTTPException(status_code=404, detail="Item not found for revert")
                if current["is_deleted"]:
                    raise HTTPException(status_code=409, detail="Item already deleted")
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE list_items
                        SET is_deleted = TRUE,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        [target_id],
                    )
                    reverted_entity = cur.fetchone()

        elif operation.endswith(".delete") or operation.endswith(".update"):
            if not before_state:
                raise HTTPException(status_code=409, detail="Missing before_state in audit entry")
            if target_type == "list":
                reverted_entity = _restore_list(conn, before_state)
            else:
                parent_list_id = before_state.get("list_id")
                if not parent_list_id:
                    raise HTTPException(status_code=409, detail="Cannot restore item because before_state has no list_id")
                parent = _fetch_list(conn, uuid.UUID(str(parent_list_id)), include_deleted=False)
                if not parent:
                    raise HTTPException(status_code=409, detail="Cannot restore item because parent list is missing or deleted")
                reverted_entity = _restore_item(conn, before_state)

        revert_audit_id = _write_audit(
            conn=conn,
            operation="audit.revert",
            target_type=target_type,
            target_id=target_id,
            actor=request.actor,
            payload={"audit_id": request.audit_id, "original_operation": operation},
            before_state=after_state,
            after_state=reverted_entity,
            revert_of_audit_id=request.audit_id,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_log
                SET reverted_by_audit_id = %s
                WHERE id = %s
                """,
                [revert_audit_id, request.audit_id],
            )

        return {
            "reverted": True,
            "reverted_audit_id": revert_audit_id,
            "original_audit_id": request.audit_id,
            "entity": _public(reverted_entity),
        }
