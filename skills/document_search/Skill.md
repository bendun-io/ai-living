# document_search

## When to use this skill
Use this skill when the user is asking for information that should be found in project documents, README files, architecture notes, or internal written guidance.

## What it does
This skill searches the available documentation library for closely matching terms and returns the most relevant passages or references. It is intended to support grounded answers that are backed by the project’s written records rather than assumptions.

## Process
1. Find the likely document or note that matches the user’s request.
2. Search for the key terms or concept names from the question.
3. Extract the most relevant passages.
4. Summarize the answer in plain language.
5. If the result is ambiguous, call out the uncertainty and suggest the next best source.

## Guardrails
- Prefer evidence from existing project docs over memory.
- If there are no direct matches, say so clearly.
- Do not invent missing facts.

## Example
If the user asks, "Where do we configure the agent port?", this skill should look for README or config docs that mention the relevant setting before answering.
