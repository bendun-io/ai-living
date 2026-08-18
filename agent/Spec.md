For your use case, I would not make n8n itself the AI agent. Instead, I'd make n8n the orchestration layer and let a dedicated LLM agent handle reasoning.

The architecture that scales best is this:

                ┌─────────────────────┐
                │  n8n Workflow       │
                │ (Trigger/Event)     │
                └─────────┬───────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │ AI Agent            │
                │ (OpenAI Responses   │
                │ API or Agents SDK)  │
                └─────────┬───────────┘
                          │
          Tool Calls      │
     (n8n workflows)      │
                          ▼
         ┌──────────────────────────┐
         │ MCP Server or Tool API   │
         │ exposing n8n workflows   │
         └─────────┬────────────────┘
                   │
          executes workflows
                   │
                   ▼
          Individual n8n Workflows

After completion

AI Agent
      │
      ▼
Webhook / API
      │
      ▼
Final n8n Workflow
Why this architecture?

It cleanly separates responsibilities.

n8n
automation
integrations
scheduling
retries
authentication
long-running processes
AI agent
planning
deciding which workflow to call
multi-step reasoning
memory
tool selection

This keeps the AI focused on intelligence and n8n focused on automation.

Expose every workflow as a tool

Rather than giving the agent one "Call n8n" tool, expose every important workflow as its own skill.

Example:

create_invoice(customer, amount)

lookup_customer(email)

search_documents(query)

book_meeting(date)

send_email(to, subject, body)

create_jira_ticket(...)

generate_quote(...)

The agent then chooses them automatically.

Use MCP

The cleanest solution today is an MCP (Model Context Protocol) server.

AI Agent
      │
      ▼
MCP Server
      │
      ├── Workflow A
      ├── Workflow B
      ├── Workflow C
      └── Workflow D

Each workflow appears as a native tool.

Advantages:

automatic tool discovery
typed parameters
descriptions
authentication
reusable
easy to add workflows
Triggering

The starting workflow should simply send context to the agent.

Example payload:

{
  "conversationId": "...",
  "user": "...",
  "message": "...",
  "attachments": [],
  "metadata": {
    "tenant": "...",
    "language": "en"
  }
}

Avoid embedding business logic in this workflow.

Agent execution

The agent might reason like this:

Need customer

↓

lookup_customer()

↓

Need open invoices

↓

list_invoices()

↓

Need summary

↓

generate_summary()

↓

Need approval

↓

send_slack_message()

This is exactly what LLM agents excel at.

Returning the result

Instead of returning the final answer directly to the user, have the agent call a dedicated callback endpoint.

POST /workflow/agentFinished

{
    "conversationId":"...",
    "result":"...",
    "toolLog":[...],
    "metadata":{...}
}

That callback starts another n8n workflow responsible for:

storing logs
sending emails
Slack
Teams
CRM updates
notifications
database writes
analytics

The AI never needs to know where the result ultimately goes.

Memory

Keep memory outside n8n.

For example:

Vector DB

Redis

Postgres

OpenAI conversation state

The agent loads relevant memory before reasoning.

Logging

Keep complete traces.

n8n Trigger

↓

Agent Input

↓

Tool Calls

↓

Workflow Results

↓

Final Answer

↓

Callback Workflow

↓

Audit Log

This makes debugging much easier.

Recommended technology stack
Component	Recommendation
Workflow engine	n8n
Agent	OpenAI Responses API (or Agents SDK if you need more built-in orchestration)
Tool layer	MCP server exposing n8n workflows
Memory	PostgreSQL + pgvector or a dedicated vector database
Callback	n8n webhook
Authentication	OAuth/API keys managed by n8n
Observability	OpenTelemetry, Langfuse, or similar tracing
Overall recommendation

For a production-grade system, I would structure it as:

n8n Workflow A receives an event and gathers any required context.
It invokes an OpenAI agent.
The agent accesses n8n workflows as individual tools, ideally through an MCP server.
The agent performs as many tool calls as needed to complete the task.
When finished, the agent sends its structured result to a callback webhook.
n8n Workflow B receives the callback, handles delivery, persistence, notifications, and any downstream automation.

This design is highly modular, easy to extend by adding new workflows as tools, and keeps the AI agent focused on reasoning while n8n remains the reliable orchestration and integration platform.

Alright. For the start, please sketch the implementation of the agent with an optional connected MCP server.

I'd design the agent so that MCP is just one possible tool provider. The agent itself shouldn't care whether a tool comes from an MCP server, a local function, or a direct API. That makes it much easier to evolve the system.

High-level architecture
                        n8n Trigger Workflow
                                │
                                ▼
                     POST /agent/run
                                │
                                ▼
                 ┌─────────────────────────┐
                 │      Agent Service      │
                 ├─────────────────────────┤
                 │                         │
                 │ Session Manager         │
                 │ Memory                 │
                 │ Prompt Builder         │
                 │ LLM Client             │
                 │ Tool Executor          │
                 │ Callback Client        │
                 └──────────┬──────────────┘
                            │
             ┌──────────────┼───────────────┐
             │              │               │
             ▼              ▼               ▼
      Local Tools      MCP Adapter      REST Adapter
             │              │               │
             ▼              ▼               ▼
      Local code      MCP Server(s)     External APIs
                            │
                            ▼
                     n8n Workflows

When finished

Agent
    │
    ▼
POST /workflow/agentFinished
    │
    ▼
n8n Callback Workflow
Suggested project structure
agent/

    app.py

    config.py

    models.py

    routes/
        run.py

    agent/
        agent.py
        planner.py
        executor.py
        prompts.py

    llm/
        openai_client.py

    tools/
        registry.py
        executor.py

        adapters/
            local.py
            mcp.py
            rest.py

    memory/
        memory.py

    callbacks/
        callback.py

    logging/
        trace.py

The key idea is that the LLM only ever interacts with a single ToolRegistry.

Agent lifecycle
Receive Request

↓

Load Memory

↓

Build Prompt

↓

Ask LLM

↓

Needs Tool?

YES
    ↓
Execute Tool
    ↓
Continue Conversation

NO
    ↓
Return Final Response

↓

Send Callback

↓

Done
Core interfaces
Agent
class Agent:

    async def run(self, request):
        ...

Nothing else should call the LLM directly.

Tool

Every tool implements the same interface.

class Tool:

    name: str

    description: str

    input_schema: dict

    async def execute(self, arguments):
        ...

The LLM never knows where the tool comes from.

Tool Registry
registry.register(LocalTool())

registry.register(MCPTool())

registry.register(RestTool())

Later:

registry.tools()

returns

[
    create_invoice,
    search_customer,
    send_mail,
    jira_create,
    ...
]
MCP Adapter

The MCP adapter is responsible for:

Connect

↓

Discover Tools

↓

Convert MCP Tool

↓

Register Tool

↓

Forward Calls

The agent never speaks MCP directly.

Instead:

LLM

↓

Tool Registry

↓

MCP Adapter

↓

MCP Server

This abstraction means you can remove MCP later without changing the agent.

Execution loop
while True

    ask LLM

    if response == final

        break

    execute tool

    append result

Exactly like the OpenAI Responses API is designed to work.

Callback interface

The callback should also be abstracted.

class Callback:

    async def send(result):
        ...

Current implementation

POST

/workflow/agentFinished

Future implementations

Kafka
RabbitMQ
EventBridge
Azure Service Bus

without changing the agent.

Configuration
llm:
  provider: openai

mcp:
  enabled: true
  servers:
    - http://localhost:9000

callback:
  url: https://n8n.example.com/webhook/finished

memory:
  provider: postgres

logging:
  level: info

If mcp.enabled = false, the registry simply skips the MCP adapter.

Tool discovery

On startup:

Agent starts

↓

Load Local Tools

↓

Connect MCP

↓

Read available tools

↓

Register tools

↓

Ready

This avoids discovering tools on every request.

Request flow
n8n
 │
 │ POST
 ▼
Agent

Load Context

↓

Load Memory

↓

Build Prompt

↓

LLM

↓

Tool?

↓

Execute

↓

LLM

↓

Tool?

↓

Execute

↓

LLM

↓

Final Answer

↓

Callback

↓

n8n
Why this design?

This architecture keeps the core agent intentionally small and stable. It depends only on a few abstractions—LLMClient, ToolRegistry, Memory, and Callback. Everything else (MCP integration, REST-based tools, local tools, different callback mechanisms, or even a different LLM provider) becomes a plug-in behind those interfaces.

As your system grows, you can add new tool sources or replace existing ones without modifying the agent's reasoning loop, which is exactly the kind of separation of concerns that leads to maintainable AI agent systems.