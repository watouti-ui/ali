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
  `canonical_id`. Identity is company + normalised title + normalised
  location, deliberately *not* including the source's requisition ID:
  Indeed's `jobKey` and LinkedIn's posting ID are different namespaces for
  the same opening, so including either guaranteed cross-source duplicates
  could never collapse (one Google TPM role surfaced twice before this was
  fixed). Location normalisation folds `"Dublin, Ireland"`,
  `"Dublin, County Dublin, Ireland"` and `"DUBLIN 2, Ireland"` together.
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

## Scoring (spec §4)

`scoring/` implements the four-stage model. The split between code and
reasoning is deliberate:

- **Deterministic, in `scoring/schema.py`** — the weighted overall score,
  tier assignment, and the surfacing rule (both qualification match and
  overall must clear 70, and any hard blocker suppresses regardless of
  score). Keeping these in code means they are consistent across runs,
  visible in a diff, and recalibrated by editing config rather than
  re-prompting.
- **Reasoning, done by the Claude session** — Stage 2 qualification match
  and Stage 3 recruiter interest, with reasons, concerns and the evidence
  cited for each. No weighted keyword count judges a JD against the
  evidence bank honestly.

`scoring/hard_filters.py` draws a second boundary, between what code can
*decide* and what it can only *notice*. Blockers (a graduate title, a job
outside IE/UK work rights) suppress. Flags do not: Ali holds no PMP and
was never awarded a bachelor's degree, so a JD mentioning either matters —
but "PMP preferred" and "PMP required" are one word apart, and degree
lines are often boilerplate an employer waives for 15 years of evidence.
Code raises the flag; the reasoning pass decides with the JD in front of
it. A false blocker is an opportunity Ali never sees and never knows he
didn't see, so the module is biased hard against suppressing.

`config/candidate_profile.yaml` holds the profile every score is computed
against — seniority band, markets and work rights, real credential
constraints, and per-role-family evidence leads *and negative signals*
(bank §8.2). The negative signals matter as much as the positive ones:
they are where a role with a perfectly matching title should still score
low. Bump `profile_version` on any scoring-relevant change; scores carry
the version that produced them, and `pending` re-queues anything scored
under an older one.

### Running a scoring pass

```bash
python3 -m career_agent.scoring.cli pending --limit 20 > batch.json
# the Claude session scores each job against the evidence bank -> scored.json
python3 -m career_agent.scoring.cli record scored.json
python3 -m career_agent.scoring.cli shortlist
```

Emit and record are separate files on disk so a bad batch can be diffed,
re-run or discarded without touching job state. `record` recomputes
blockers and flags from the job record rather than trusting the batch to
echo them back — a surfacing decision should never depend on whether a
hand-written batch remembered to copy a blocker across.

## Not yet wired up

- **More Apify searches** — only Dublin is covered so far (25 results per
  platform). Add London and other role-family searches by copying an
  existing `source: apify` board entry.
- **Calibration against Ali's own judgement** (spec §5) — the scores are a
  first pass and have not been checked against roles Ali rates himself.
  That benchmark is what decides whether the weights and thresholds are
  right; until it exists, treat the ranking as a starting point.
- **Daily schedule** — no Routine created yet; pending sign-off on a run
  time/timezone.
- **Digest, Gmail tracking, Drive filing** — later phases per the skill.

## Run it

```bash
python3 -m career_agent.scout.pipeline
```

Reads `config/target_roles.yaml`, writes `state/jobs.json`, prints a run
summary (boards checked, raw jobs found, suppressed, unique after dedup).
