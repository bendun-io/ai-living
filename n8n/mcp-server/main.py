import inspect
import os
from typing import Annotated, Any, Optional

import httpx
import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import Field

MCP_SERVER_HOST = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
MCP_SERVER_PORT = int(os.environ.get("MCP_SERVER_PORT", "8000"))

mcp = FastMCP("n8n-workflows", host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)

JSON_SCHEMA_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def load_workflows():
    workflows = {}

    for filename in os.listdir("workflows"):
        if not filename.endswith(".yaml"):
            continue

        with open(f"workflows/{filename}") as f:
            workflow = yaml.safe_load(f)

        workflows[workflow["name"]] = workflow

    return workflows


WORKFLOWS = load_workflows()


async def execute_n8n(workflow, arguments):
    config = workflow["n8n"]

    auth = config.get("auth", {})

    headers = {
        "Content-Type": "application/json",
    }

    if auth.get("type") == "header":
        env_name = auth["env"]
        token = os.environ[env_name]

        headers[auth["key"]] = token

    async with httpx.AsyncClient(
        timeout=workflow["execution"].get("timeout_seconds", 30)
    ) as client:

        response = await client.post(
            config["url"],
            json=arguments,
            headers=headers,
        )

        response.raise_for_status()

        return response.json()


def build_signature(input_schema: dict) -> inspect.Signature:
    """Turn a workflow's JSON-schema `input` block into a real Python
    signature, so FastMCP derives its tool schema from the workflow
    definition instead of from a generic **kwargs function."""

    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    parameters = []

    for prop_name, prop_schema in properties.items():
        py_type = JSON_SCHEMA_TYPES.get(prop_schema.get("type"), Any)
        description = prop_schema.get("description", "")

        if prop_name in required:
            annotation = Annotated[py_type, Field(description=description)]
            default = inspect.Parameter.empty
        else:
            annotation = Annotated[Optional[py_type], Field(description=description)]
            default = None

        parameters.append(
            inspect.Parameter(
                prop_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )

    return inspect.Signature(parameters)


def register_workflow(workflow):
    name = workflow["name"]
    description = workflow["description"]

    async def tool(**arguments):
        return await execute_n8n(workflow, arguments)

    tool.__name__ = name
    tool.__doc__ = description
    tool.__signature__ = build_signature(workflow.get("input", {}))

    mcp.tool()(tool)


for workflow in WORKFLOWS.values():
    register_workflow(workflow)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
