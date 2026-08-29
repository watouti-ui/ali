# career_agent

Phase 1 (Scout) scaffold for the autonomous career agent defined in
`.claude/skills/career-agent-builder/SKILL.md`. Deterministic pieces only —
fetching, deduplication, hard filtering, and persistence. Scoring
(qualification match, recruiter interest) and enrichment need reasoning
against the evidence bank and are done by the Claude session that runs this
pipeline, not by this code.

## What's here

- `scout/schema.py` — canonical `JobRecord` and dedup key (`canonical_id`),
  stable across sources so the same real-world job collapses to one record.
- `scout/sources/{greenhouse,lever,ashby}.py` — adapters for each ATS's
  public, unauthenticated JSON job-board API. Verified live against real
  boards (GitLab/Airbnb on Greenhouse, Trainline on Ashby).
- `scout/dedup.py` — merges freshly fetched jobs into existing state by
  `canonical_id`.
- `scout/filters.py` — Stage 1 hard filters (spec §4): word-boundary
  keyword matching on title/location, configurable, conservative by design.
- `scout/pipeline.py` — orchestrates fetch → filter → dedup → persist,
  isolating per-board failures so one bad token doesn't kill a run.
- `config/target_roles.yaml` — target role taxonomy, markets, boards to
  poll, and hard-filter keywords. **Edit this** — `boards` currently has
  only Trainline; add real target companies as you confirm them.
- `state/jobs.json` — persisted job records (git-versioned for an audit
  trail), created on first run.
- `tests/` — unit tests for dedup determinism and filter correctness
  (`python3 -m unittest discover -s career_agent/tests`).

## Not yet wired up

- **Apify** — MCP server is installed and connected (`claude mcp list`
  shows `apify: https://mcp.apify.com (HTTP) - Connected`), but no adapter
  uses it yet. Add once the Apify tools are available in a running session
  and you've decided which actors to use (LinkedIn/Indeed need it; ATS
  boards don't).
- **Scoring** (spec §4 stages 2–4) — not implemented as code. The plan is
  for the daily-run Claude session to read `state/jobs.json`, score each
  job against the evidence bank, and write the scores back.
- **Daily schedule** — no Routine created yet; pending your sign-off on a
  run time/timezone.
- **Digest, Gmail tracking, Drive filing** — later phases per the skill.

## Run it

```bash
python3 -m career_agent.scout.pipeline
```

Reads `config/target_roles.yaml`, writes `state/jobs.json`, prints a run
summary (boards checked, raw jobs found, suppressed, unique after dedup).
