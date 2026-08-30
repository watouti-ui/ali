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
- `scout/sources/apify.py` — runs a configured Apify actor synchronously
  and normalizes its dataset items into `JobRecord`. Actor output isn't
  one fixed shape (unlike the ATS adapters): it handles both flat fields
  (`companyName`, `descriptionText`) and nested ones (`employer.name`,
  `location: {city, country, ...}`, `description: {html, text}`), the
  shapes actually returned by the two actors below — verified via
  `fetch-actor-details`, not assumed. Reads `APIFY_API_TOKEN`/
  `APIFY_TOKEN` from the environment at run time — never hardcode a token
  in this repo. Actor IDs use Apify's Store format (`owner/actor-name`);
  the adapter converts to the `owner~actor-name` REST API expects.

### Apify actors in use

Chosen by comparing usage, rating (weighted by rating *count*, not just
average — a 5.0★ actor with 2 ratings is a weaker signal than a 4.6★ actor
with 140), and price per result across everything matching "LinkedIn jobs"
/ "Indeed jobs" in the Apify Store, then verifying each candidate's actual
output schema and running a small live test (~25 results each, well under
$0.10 total) before wiring it into config:

| Platform | Actor | Users | Rating | Price/result |
|---|---|---|---|---|
| LinkedIn | `curious_coder/linkedin-jobs-scraper` | 142k+ (14.5k monthly) | 4.59★ (140 ratings) | $0.002 |
| Indeed | `valig/indeed-jobs-scraper` | 26k+ (3.6k monthly) | 5.0★ (17 ratings) | $0.0001 |

Cheaper LinkedIn/Indeed actors exist, but had thin rating samples (a
handful of reviews) or, in one case (a different Indeed actor considered),
would have needed extra normalization work for no real benefit once the
schema was checked. `valig/indeed-jobs-scraper` and `borderline/indeed-scraper`
(the other well-proven Indeed option) both nest `location`; the normalizer
handles that generically rather than picking an actor to dodge it.
- `scout/dedup.py` — merges freshly fetched jobs into existing state by
  `canonical_id`.
- `scout/filters.py` — Stage 1 hard filters (spec §4): word-boundary
  keyword matching on title/location, configurable, conservative by design.
- `scout/pipeline.py` — orchestrates fetch → filter → dedup → persist,
  isolating per-board failures so one bad token doesn't kill a run.
- `config/target_roles.yaml` — target role taxonomy, markets, and boards
  to poll (Trainline on Ashby, plus a LinkedIn and an Indeed search via
  Apify, both scoped to Dublin for now), and hard-filter keywords. **Edit
  this** — add more target companies/searches (e.g. London) as you
  confirm them; copy an existing `source: apify` entry and change
  keywords/location.
- `state/jobs.json` — persisted job records (git-versioned for an audit
  trail). Currently 80 real jobs from a live run across all three sources.
- `tests/` — unit tests for dedup determinism and filter correctness
  (`python3 -m unittest discover -s career_agent/tests`).

## Not yet wired up

- **More Apify searches** — only Dublin is covered so far (25 results per
  platform). Add London and other role-family searches by copying an
  existing `source: apify` board entry.
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
