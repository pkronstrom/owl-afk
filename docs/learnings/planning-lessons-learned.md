# Lessons Learned

Analysis of historical planning documents from the owl project, distilled into actionable takeaways.

**Source:** Archived plan docs from `docs/plans/` (2025-01 to 2026-01)

## What Worked Well

- **Phased, task-based plans** with clear file targets and test hooks made large efforts tractable (chain engine, architecture refactor, menu redesign)
- **Explicit UI flows and message mockups** reduced ambiguity for Telegram + CLI interactions and sped implementation alignment
- **Strong emphasis on modularization** (handlers, notifier abstraction, storage helpers) enabled incremental refactors without halting feature work
- **Pattern-generation approach** (specific -> general) and chain parsing logic produced predictable rule behavior and clean UX for auto-approval
- **Test-first guidance** (unit + integration) plus edge-case lists helped capture critical behaviors like chain truncation and idempotent callbacks

## What Could Have Been Done Better

- Some plans were **overly verbose** and duplicated detail across design + implementation docs; a shared template with single source of truth would reduce drift
- **Acceptance criteria and "done" definitions** were inconsistently explicit; some plans ended with known test failures or TODOs without follow-up checklist
- **Cross-plan dependencies** (UI redesign <-> wizard <-> rules UI) weren't always surfaced, risking sequencing issues
- **Risk and rollback strategies** were rarely called out, especially for refactors touching polling/approval flow
- **Performance and operational constraints** (message limits, polling intervals) were described but not consistently tied to concrete monitoring/metrics

## Recurring Themes / Architectural Decisions

- SQLite + WAL and single-leader polling via lock file were central reliability choices
- Approval flow consistently modeled as: parse -> pattern generate -> rule check -> auto-decision or Telegram UI
- Idempotent callback handling and request deduplication show up as core safety invariants
- CLI/interactive UI treated as first-class product surface, with emphasis on wizards, live panels, lazy loading
- Type safety and error handling (mypy, custom exceptions, narrower excepts) recur as long-term maintainability goals

## Key Technical Insights to Preserve

- **Recursive command parsing + wrapper awareness** enables granular approval control without losing context
- **Multi-level rule patterns** (exact -> wildcard -> unwrapped) strike practical balance between precision and usability
- **Chain approval state belongs in storage** (not memory) to survive poller restarts and support leader election
- **Safe defaults via user-editable file** are low-friction adoption lever and should stay data-driven
- **Optimistic locking for chain state** prevents race conditions when multiple pollers interact

## Anti-Patterns to Avoid

- Swallowed exceptions and broad `except Exception` blocks without logging or typed handling
- Duplicate formatting/message construction logic across handlers and notifiers
- Hardcoded constants scattered across modules (timeouts, retries, DB names)
- Large "do-everything" functions (poller handlers, manager orchestration) without extraction points
- Tight coupling to concrete implementations (direct handler instantiation, Telegram-specific logic inside core flow)

---

*Generated: 2026-01-11*
