from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import (
    AuditRevertRequest,
    AuditSearchRequest,
    IdRequest,
    ItemCreateRequest,
    ItemDeleteRequest,
    ItemUpdateRequest,
    ListCreateRequest,
    ListDeleteRequest,
    ListUpdateRequest,
    SearchRequest,
    TOOL_DEFINITIONS,
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


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "utils-lists",
        "tools": [tool["name"] for tool in TOOL_DEFINITIONS],
    }


@router.get("/agent/tool-definitions")
def agent_tool_definitions() -> dict[str, Any]:
    return {"tools": TOOL_DEFINITIONS}


@router.post("/lists/get")
def lists_get(request: IdRequest) -> dict[str, Any]:
    return get_list(request.id, include_deleted=request.include_deleted)


@router.post("/lists/search")
def lists_search(request: SearchRequest) -> dict[str, Any]:
    return search_lists(
        query=request.query,
        include_deleted=request.include_deleted,
        limit=request.limit,
        offset=request.offset,
    )


@router.post("/lists/create")
def lists_create(request: ListCreateRequest) -> dict[str, Any]:
    return create_list(name=request.name, description=request.description, actor=request.actor)


@router.post("/lists/update")
def lists_update(request: ListUpdateRequest) -> dict[str, Any]:
    return update_list(list_id=request.id, name=request.name, description=request.description, actor=request.actor)


@router.post("/lists/delete")
def lists_delete(request: ListDeleteRequest) -> dict[str, Any]:
    return delete_list(list_id=request.id, actor=request.actor)


@router.post("/items/get")
def items_get(request: IdRequest) -> dict[str, Any]:
    return get_item(request.id, include_deleted=request.include_deleted)


@router.post("/items/search")
def items_search(request: SearchRequest) -> dict[str, Any]:
    return search_items(
        query=request.query,
        include_deleted=request.include_deleted,
        limit=request.limit,
        offset=request.offset,
    )


@router.post("/items/create")
def items_create(request: ItemCreateRequest) -> dict[str, Any]:
    return create_item(
        list_id=request.list_id,
        title=request.title,
        notes=request.notes,
        status=request.status,
        actor=request.actor,
    )


@router.post("/items/update")
def items_update(request: ItemUpdateRequest) -> dict[str, Any]:
    return update_item(
        item_id=request.id,
        title=request.title,
        notes=request.notes,
        status=request.status,
        actor=request.actor,
    )


@router.post("/items/delete")
def items_delete(request: ItemDeleteRequest) -> dict[str, Any]:
    return delete_item(item_id=request.id, actor=request.actor)


@router.post("/audit/get")
def audit_get(request: IdRequest) -> dict[str, Any]:
    return get_audit_entry(request.id)


@router.post("/audit/search")
def audit_search(request: AuditSearchRequest) -> dict[str, Any]:
    return search_audit(
        target_type=request.target_type,
        target_id=request.target_id,
        operation=request.operation,
        limit=request.limit,
        offset=request.offset,
    )


@router.post("/audit/revert")
def audit_revert(request: AuditRevertRequest) -> dict[str, Any]:
    return revert_audit(audit_id=request.audit_id, actor=request.actor)
