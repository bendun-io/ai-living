# calendar_lookup

## When to use this skill
Use this skill when the user asks about meeting times, calendar availability, upcoming events, or scheduling follow-up work.

## What it does
This skill looks through the known calendar context to identify nearby meetings, open time blocks, or appointment windows. It helps answer scheduling questions and narrow down the most suitable time to meet.

## Process
1. Parse the user’s time-related requirement.
2. Check the relevant calendar entries and availability windows.
3. Compare available slots against constraints such as preferred date, duration, and urgency.
4. Recommend the best candidate slot with a short explanation.
5. If no slot fits perfectly, surface the closest match and a short reason.

## Guardrails
- Do not assume availability without checking calendar data.
- Prefer precise times and durations when available.
- If a meeting request is unclear, ask a clarifying question before selecting a slot.

## Example
If the user asks, "When is the next free slot for a 30-minute call this week?", this skill should identify the earliest suitable time and explain the reasoning.
