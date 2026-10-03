# little-tutor Automation Guardrails

Updated: 2026-10-01

This file defines what an automated project session may and may not do.
The current sprint scope in `D:\python\learn\面试准备\08-双线执行总表.md`
is the source of truth for task order and user review gates.

## Current Sprint Scope

Only these two outcomes are in scope:

1. Close the current reliability gaps around LLM timeout, retry, fallback,
   and auditable teacher-review evidence.
2. Produce a qualitative LLM attribution case study from real errors.

Direct-square-root and factoring expansion, broader knowledge graphs, RAG,
multi-Agent teaching, OCR, and subject expansion are outside this sprint.

## Allowed Work Per Run

- Advance at most one predefined work bundle from the sprint backlog.
- If a work bundle is unfinished, continue on later runs only after the
  tracker is updated with current results and blockers.
- Combine implementation, its focused tests, and task-specific documentation
  into the same run when they are part of one deliverable.
- Preserve existing uncommitted work and never revert user changes.
- Prefer the smallest change that can satisfy the task contract.
- Run focused tests for the changed behavior.
- Run the full suite when shared contracts, graph routing, persistence,
  or cross-module behavior changes.
- Update the execution tracker with what changed, what was verified,
  what remains, and any blocker.

## Forbidden Work

- Do not invent a new sprint goal or start the next work bundle before the
  current one is completed or explicitly paused.
- Do not add adjacent features just because they are convenient.
- Do not create filler changes when no valid work bundle is ready.
- Do not claim that a capability is "verified" only because code was written.
- Do not fabricate student errors, teacher feedback, or evaluation results.
- Do not commit, push, or rewrite history unless the user explicitly asks.
- Do not remove or weaken tests to make a change pass.
- Do not label a change as "LLM value verified" without real teacher-reviewed
  cases and human judgment.
- Do not report decision delay as teacher review duration. Existing data does
  not measure when human review started.

## Stop Conditions

Stop and report, without forcing progress, when:

- the next task is not explicitly defined in the sprint tracker;
- a user decision is required;
- the work would leave the current sprint scope;
- a test or contract exposes a design conflict;
- the working tree contains overlapping user changes that cannot be integrated
  safely.

After a major stage is completed, wait for human review before moving to the
next major stage.

## Evidence Rules

- Program grading remains the source of truth for correctness.
- LLM attribution remains advisory and must not decide correctness.
- Automated work must distinguish:
  - implemented;
  - covered by tests;
  - manually observed;
  - not yet validated.
- Teacher usability is only recorded from real interaction. If there was no
  interaction, record "no evidence this period"; do not infer it.

## Interview Trigger

When an interview invitation arrives:

1. Pause project development.
2. Focus practice on Q1-Q12.
3. Keep applying to jobs.
4. Resume the same sprint after the interview; do not switch direction.
