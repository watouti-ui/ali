# ADR-001 — The orchestrator owns the goal, not the schedule

**Status:** accepted, 30 August 2026
**Supersedes:** the `DAILY_RUN.md`-as-decision-engine design

## Context

Phase 1 produced a Scout that works: six source adapters, cross-source
deduplication that survived three rounds of real bugs, hard filters
biased against false suppression, a scoring model splitting deterministic
arithmetic from reasoning, and 746 tracked roles with 80 above threshold.

That part is sound and is retained unchanged.

The control layer above it is not. What was built is a **cron-triggered
pipeline with a reasoning step in the middle**, which is a different
thing from the autonomous agent the skill specifies. The drift is
structural, not cosmetic:

- `pipeline.py` iterates a fixed list of 62 boards. Nothing decides which
  sources deserve attention today, so a source that has returned nothing
  relevant for a month is polled with the same priority as one that
  produced the top of the shortlist.
- Scoring runs uniformly over everything pending. Nothing decides to
  investigate one role harder than another, so a role that would repay
  reading the company's engineering blog gets the same treatment as a
  clearly irrelevant one.
- Borderline roles are dropped by a numeric threshold and never revisited.
  The skill asks for the opposite: investigate a promising job more
  deeply before discarding it.
- There is no memory beyond scores. No source yield history, no query
  family performance, no feedback events. Every learning signal the skill
  lists — apply/skip, recruiter response, interview, rejection, LinkedIn
  Top Applicant — is unimplemented, so the system cannot improve.
- `DAILY_RUN.md` is a procedure and the Routine executes it top to bottom.
  The procedure is the decision engine.

The consequence is that adding features would have compounded the wrong
shape. The previous Career OS did not fail for lack of features; it failed
on discovery and ranking quality. This architecture would have failed the
same way, more elaborately.

## Decision

**The Career Orchestrator owns the goal and decides the actions.** The
deterministic Python components become tools it invokes selectively.

Three things change and one thing does not.

### 1. Control inverts

Before: the schedule runs a pipeline; the model scores what the pipeline
produced.

After: the schedule *wakes an agent*. The agent reads its state and
memory, forms a plan for the day from what it knows, calls tools to
execute that plan, and records why. Two wakes on different days should
produce different action sequences, because the state differs.

`pipeline.run()` is retained as a batch convenience for a full sweep, but
it is no longer how a day's work is decided.

### 2. Memory becomes first-class

The agent needs to know what it has already learned:

- which sources and query families actually yield surfaced roles, and at
  what cost;
- when each company was last checked, so coverage can be spread rather
  than repeated;
- which opportunities are open investigations rather than closed
  decisions;
- what Ali did with what it surfaced, and what happened downstream.

This lives in `career_agent/agent/memory.py` and is versioned. Strategy
changes by writing memory and configuration — **never by the production
agent modifying its own source code**.

### 3. Decisions and feedback are recorded

Every consequential action gets a machine-readable record: what was
decided, why, what evidence supported it, which tools ran, confidence,
and the outcome once known. Without this the learning behaviour cannot be
debugged, and an agent whose learning cannot be debugged should not be
trusted to learn.

### 4. What does not change

The Scout, the ATS and aggregator adapters, `canonical_job_id` and the
deduplication rules, the hard-filter blocker/flag split, the scoring
schema and thresholds, and the persistence layer. These are working,
tested, and expensive to re-derive. They are wrapped, not rewritten.

## Calibration gates everything downstream

Phase 1 is **not** complete when the agent runs autonomously. It is
complete when discovery is demonstrably good:

> **≥ 90% recall** of the strong opportunities Ali identifies manually,
> including roles LinkedIn marks as Top Applicant, while keeping obvious
> false positives low.

Benchmark cases come from Ali and are stored as a fixture. Until that
gate passes, no work proceeds on the Application Agent, inbox tracking,
Drive filing, or interview intelligence. Building those on weak discovery
would repeat the previous system's failure with more surface area.

## Consequences

**Accepted costs.** An agent that decides is less predictable than a
pipeline that executes; two runs on the same data may do different things.
That is the point, but it means the decision log stops being documentation
and becomes the primary debugging surface. Runs also become more variable
in cost, since the agent may choose to research deeply on one day and
sweep broadly on another.

**Retained guarantees.** Determinism stays where it belongs. Identity,
deduplication, thresholds, tier bands and the surfacing rule remain
arithmetic in code — reviewable in a diff and identical run to run. The
agent decides *what to look at* and *how hard to look*; it does not get to
quietly redefine what counts as a match.

**Approval boundaries are unchanged.** The agent may search, research,
score, investigate, draft and organise autonomously. Submitting an
application, contacting a recruiter, or making any external commitment
still requires explicit approval.
