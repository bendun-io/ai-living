from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core import (
    create_item,
    create_list,
    delete_item,
    delete_list,
    get_audit_entry,
    get_item,
    get_list,
    revert_audit,
    search_audit,
    search_items,
    search_lists,
    update_item,
    update_list,
)

router = APIRouter()


class ListPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    actor: str = "rest"


class ListCreateRestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    actor: str = "rest"


class ItemCreateForListRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None
    status: str = "open"
    actor: str = "rest"


class ItemPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    status: str | None = None
    actor: str = "rest"


class AuditRevertBody(BaseModel):
    actor: str = "rest"


@router.get("/lists")
def rest_lists_search(
    query: str | None = None,
    include_deleted: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return search_lists(query=query, include_deleted=include_deleted, limit=limit, offset=offset)


@router.post("/lists")
def rest_lists_create(request: ListCreateRestRequest) -> dict[str, Any]:
    return create_list(
        name=request.name,
        description=request.description,
        actor=request.actor,
    )


@router.get("/lists/{list_id}")
def rest_lists_get(list_id: uuid.UUID, include_deleted: bool = False) -> dict[str, Any]:
    return get_list(list_id, include_deleted=include_deleted)


@router.patch("/lists/{list_id}")
def rest_lists_update(list_id: uuid.UUID, request: ListPatchRequest) -> dict[str, Any]:
    return update_list(list_id=list_id, name=request.name, description=request.description, actor=request.actor)


@router.delete("/lists/{list_id}")
def rest_lists_delete(list_id: uuid.UUID, actor: str = "rest") -> dict[str, Any]:
    return delete_list(list_id=list_id, actor=actor)


@router.get("/lists/{list_id}/items")
def rest_list_items_search(
    list_id: uuid.UUID,
    query: str | None = None,
    include_deleted: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return search_items(
        query=query,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        list_id=list_id,
    )


@router.post("/lists/{list_id}/items")
def rest_items_create(list_id: uuid.UUID, request: ItemCreateForListRequest) -> dict[str, Any]:
    return create_item(
        list_id=list_id,
        title=request.title,
        notes=request.notes,
        status=request.status,
        actor=request.actor,
    )


@router.get("/items/{item_id}")
def rest_items_get(item_id: uuid.UUID, include_deleted: bool = False) -> dict[str, Any]:
    return get_item(item_id=item_id, include_deleted=include_deleted)


@router.patch("/items/{item_id}")
def rest_items_update(item_id: uuid.UUID, request: ItemPatchRequest) -> dict[str, Any]:
    return update_item(item_id=item_id, title=request.title, notes=request.notes, status=request.status, actor=request.actor)


@router.delete("/items/{item_id}")
def rest_items_delete(item_id: uuid.UUID, actor: str = "rest") -> dict[str, Any]:
    return delete_item(item_id=item_id, actor=actor)


@router.get("/audit")
def rest_audit_search(
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    operation: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return search_audit(target_type=target_type, target_id=target_id, operation=operation, limit=limit, offset=offset)


@router.get("/audit/{audit_id}")
def rest_audit_get(audit_id: uuid.UUID) -> dict[str, Any]:
    return get_audit_entry(audit_id)


@router.post("/audit/{audit_id}/revert")
def rest_audit_revert(audit_id: uuid.UUID, request: AuditRevertBody) -> dict[str, Any]:
    return revert_audit(audit_id=audit_id, actor=request.actor)
