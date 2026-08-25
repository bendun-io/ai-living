# Human-in-the-loop

How to add a confirmation/review step before the agent's actions actually execute.

## Where it belongs

n8n owns orchestration, triggers, and delivery in this stack; the [agent](../../../agent) is
deliberately a stateless reasoning layer with no long-running waits (see
[agent/docs/architecture.md](../../../agent/docs/architecture.md)). That makes n8n, not the agent,
the right place to pause a flow and wait on a person — it already sits between the agent and the
mutating workflows (e.g. [`calendar_update.yaml`](../../mcp-server/workflows/calendar_update.yaml),
[`calendar_create.yaml`](../../mcp-server/workflows/calendar_create.yaml)).

## Recommended approach: n8n's native Form Trigger + Wait-for-form

Use n8n's built-in **Form Trigger** / **Wait for form submission** node instead of building a
separate webservice:

- The agent proposes an action but stops short of calling the mutating webhook.
- An n8n workflow pauses on a Wait node, generates a hosted form URL pre-filled with the proposed
  fields (e.g. event start/end time, summary, attendees).
- The link is sent to the user over the existing delivery channel (Telegram, per
  [`workflows/Telegram Ingres.json`](../../workflows/Telegram%20Ingres.json)).
- The user reviews/edits the fields and submits; the workflow resumes and calls the real
  create/update webhook with the (possibly edited) data.

This fits the existing pattern with no new service to run or maintain: the calendar workflows
already live behind n8n webhooks, so a "confirm" workflow sits alongside them.

**Trade-offs:** n8n forms give less UI control/branding and are limited to n8n's field types
(multi-step and conditional fields are supported, but nothing custom-coded). Fine for internal
approval UX; not for anything that needs to be embedded in the
[desktop app](../../../desktop-app-electron) or heavily styled.

## When to build a dedicated webservice instead

Only if the form/approval UX needs to outgrow n8n's native form node — e.g. custom UI, richer
validation, or surfacing the confirmation inside the desktop app rather than via a link. Until
then, a bespoke service is unnecessary extra infrastructure.

## Simple yes/no confirmations

Skip forms entirely for a binary approval (no fields to edit) — just have n8n ask in the existing
Telegram thread and branch on the reply. A form is overkill when there's nothing to review but a
yes/no.
