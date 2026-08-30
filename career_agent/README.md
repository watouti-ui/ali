# career_agent

An autonomous Career Orchestrator with a deterministic Scout underneath it.

**Start with `AGENT.md`** — it is the orchestrator's operating policy and
owns what the agent decides. `OPERATIONS.md` documents how individual
operations are invoked; it is a reference, not a plan.
`docs/ADR-001-orchestrator-control-layer.md` records why the control
layer is shaped this way and what the earlier pipeline design got wrong.

## Control layer

- `agent/memory.py` — persistent strategy memory: what each source has
  actually been worth, when each company was last checked, which
  investigations are open, and a revision log so every strategy change is
  traceable and reversible.
- `agent/tools.py` — the granular tool surface the agent acts through:
  run one board, triage specific jobs, read one description, list
  borderline roles worth investigating, find coverage gaps. Wraps the
  Scout; does not reimplement it.
- `agent/decisions.py` — the decision log (what was decided, why, on what
  evidence, with what confidence) and the feedback store (what Ali did,
  and what the market did back).
- `calibration/` — the benchmark that gates Phase 1 at 90% recall of
  strong opportunities Ali identifies himself. Separates discovery
  failures from ranking failures, because they need different fixes.

## Scout (unchanged, and deliberately so)

- `scout/schema.py` — canonical `JobRecord` and dedup key (`canonical_id`),
  stable across sources so the same real-world job collapses to one record.
- `scout/sources/{greenhouse,lever,ashby,workday,smartrecruiters}.py` —
  adapters for each ATS's public, unauthenticated JSON job-board API.
  Every one was verified against a real live board before being shipped
  (GitLab and Airbnb on Greenhouse, Trainline on Ashby, Mastercard on
  Workday, SmartRecruiters' own board). See **ATS coverage** below for
  what each covers and what was deliberately left out.
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

### ATS coverage

The aggregator searches (LinkedIn, Indeed via Apify) do broad discovery.
ATS adapters do the opposite job: complete, authoritative coverage of a
named employer's board, with no ranking algorithm in between. Both matter
— Mastercard's London Cardholder Services role showed up on LinkedIn
*and* on their Workday board, but only Workday can guarantee nothing at
that employer was missed.

**Shipped, each verified against a live board:**

| Platform | Endpoint style | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | Descriptions inline |
| Lever | `api.lever.co/v0/postings/{token}` | Descriptions inline |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}` | Descriptions inline |
| Workday | `POST /wday/cxs/{tenant}/{site}/jobs` | Data centre in hostname; descriptions need a second request |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{co}/postings` | Case-sensitive token; descriptions need a second request |

Two traps worth knowing, both of which fail *silently*:

- **A wrong SmartRecruiters token returns HTTP 200 with an empty list**,
  which is indistinguishable from an employer with no vacancies. Confirm
  a new token gives a non-zero `totalFound` before trusting it.
- **A wrong Workday site path returns HTTP 422**, and the data centre
  (`wd1`/`wd3`/`wd5`/`wd12`) differs per employer, so it is configured
  rather than derived. Of fourteen plausible tenants probed, six worked;
  the rest had a different site path, not a missing board.

**Checked and deliberately not shipped:**

- **Workable** — the public endpoints (`/api/v1/widget/accounts/{t}` and
  `POST /api/v3/accounts/{t}/jobs`) respond, but every tenant tried
  returned zero jobs, so the result shape could not be verified against
  real data. Shipping an adapter written against a guessed shape is how
  you get a source that silently returns nothing. Build it when a target
  employer actually using it is identified.
- **Recruitee, Personio** — Personio publishes XML rather than JSON, and
  no Recruitee tenant tried resolved. Both are viable later; neither is
  common among Ali's target employers.
- **Teamtailor, iCIMS, Jobvite** — no public unauthenticated job API.
  These need either an employer-issued API key or scraping, and scraping
  a login-gated board is out of scope; an Apify actor is the right route
  if one of them ever matters.

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
- `config/target_roles.yaml` — the boards to poll and the hard-filter
  keywords. The search matrix is three role families (technical
  programme, product operations, delivery management) across four
  locations, on both LinkedIn and Indeed, plus Trainline's Ashby board.
  Locations are the co-primary markets at their widest usable form:
  *Greater Dublin Area* and *Greater London* supersede the bare city
  searches — Greater London genuinely reaches Reading and Bracknell — and
  each market gets a remote sweep, since bank Part 7 gives full IE/UK/EU
  work rights with no sponsorship needed. On LinkedIn remote is expressed
  in the keywords rather than a filter, because the actor's input has no
  workplace field: LinkedIn removed it when it moved to AI search.
  **Edit this** to add target companies or searches; every entry is one
  actor run and spends credits, which `limitPerSource`/`limit` cap.
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
constraints, and per-role-family evidence leads *and negative signals*.
The negative signals matter as much as the positive ones: they are where
a role with a perfectly matching title should still score low. Bump
`profile_version` on any scoring-relevant change; scores carry the
version that produced them, and `pending` re-queues anything scored under
an older one.

Five families are scored. Four come from bank §8.2 (technical programme,
product operations, transformation, AI adoption); **delivery management
is derived** from Part 5's end-to-end release lifecycle and Part 4.2's
operating model, and is labelled as derived in the config so its
provenance stays honest. Delivery Manager spans a very wide band, so its
negative signals pull down the single-team, scrum-master, agile-coaching
and client-account variants rather than filtering them at search time,
where a title alone cannot tell them apart.

`evidence_guardrails` in the same file carries constraints that travel
with specific evidence. The product operating model (Part 4.2) was
approved for rollout in April 2026, so its measures are *targets, never
achieved outcomes*; its go-to-market claim has an approved wording with
no sprint or week count; and the Utilities release recovery must stay
separate from it. A high score licenses building an application, so
anything the scoring pass cites has to survive the interview it leads to.

`scoring/batch.py` holds the scaffolding each round repeats — carrying
forward scores a profile change doesn't affect, disposing in bulk of the
engineering and clinical posts broad keyword searches always sweep in,
and asserting every pending job got scored before recording. A job that
drops out silently never reaches the shortlist, which is indistinguishable
from the Scout never having found it. Only the judgement is written fresh
each round.

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
