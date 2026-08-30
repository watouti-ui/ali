# Operations reference

**This is not the plan.** The Career Orchestrator decides what a day is
for; see `AGENT.md`, which owns that. This file documents *how* an
operation is invoked once the agent has decided to invoke it — the
commands, their arguments, and the traps each one carries.

Reading this top to bottom and executing it is the failure mode the
control-layer redesign exists to correct (see
`docs/ADR-001-orchestrator-control-layer.md`). A full sweep of every
board is a legitimate choice; it is just not the only one, and it is not
the default.

The granular alternative to most of what follows is
`career_agent/agent/tools.py`, which lets the agent run one source, read
one description, or triage one job rather than processing everything.

## 1. Get the current state

```bash
cd /home/user/ali
git fetch origin claude/career-agent-builder-skill-scxy4y
git checkout claude/career-agent-builder-skill-scxy4y
git pull --ff-only origin claude/career-agent-builder-skill-scxy4y
pip install -r requirements.txt -q
```

## 2. Scout

```bash
python3 -m career_agent.scout.pipeline
```

`APIFY_API_TOKEN` must be set in the environment for the LinkedIn and
Indeed boards. If it is missing, those boards fail individually and are
reported in the run summary — the ATS boards (Workday, SmartRecruiters,
Ashby) need no credentials and still run. **A run with every Apify board
failing is a degraded run, not a healthy one: say so in the report rather
than presenting the ATS-only results as the full picture.**

## 3. Score what is new

```bash
python3 -m career_agent.scoring.cli pending > /tmp/batch.json
```

This is the reasoning step and the only part that is not mechanical.
For each pending job, score `qualification_match` and `recruiter_interest`
against `config/candidate_profile.yaml`, which distils the evidence bank.

Rules that matter more than throughput:

- **Read the job description before scoring anything plausible.** Titles
  lie in both directions. BNY's "Director, Platforms Operating Model"
  reads like a perfect match and is a Product Owner role for ETF fund
  accounting; MongoDB's Staff TPM has an ideal title and asks for a
  ten-year software development background Ali does not have.
- **Respect `evidence_guardrails` in the profile.** A high score licenses
  building an application, so anything cited has to survive the interview
  it leads to. The product operating model's measures are targets, not
  achieved outcomes.
- **Negative signals matter as much as positive ones** — they are where a
  perfectly matching title should still score low.
- Use `career_agent/scoring/batch.py` for the scaffolding: `bulk_dispose`
  for the engineering, clinical and retail posts broad searches sweep in,
  `carry_forward` when a profile change does not affect a prior score,
  and `assert_complete` before recording. Only the judgement is written
  fresh.
- Where the posting genuinely does not establish level or scope, say so
  in the concern and set `confidence` to `low`. Do not invent nuance to
  make a card look considered.

Then:

```bash
python3 -m career_agent.scoring.cli record /tmp/scored.json
python3 -m career_agent.scoring.cli pending   # must report 0
```

## 4. Refresh the review page — best effort

```bash
python3 -m career_agent.review.render
```

This regenerates `scout_calibration.html` from the current scores, and
committing it in step 6 is what actually preserves it. Republishing is a
bonus on top, not the deliverable.

If the Artifact tool is available, publish it with the existing URL so it
updates in place rather than creating a second page:

    url: https://claude.ai/code/artifact/a389a850-4d8f-49a1-a43d-0b2bfc0db290

Read the artifact first (`action: "read"` with that url) — a publish to
an artifact the session has not read is refused.

**Scheduled runs fire with a restricted tool set that may not include the
Artifact tool.** If it is unavailable, do not treat that as a failed run
and do not work around it by publishing to a new URL — that would
fragment the page across a different link every morning. Render and
commit the file, note in the report that the hosted page was not
refreshed this run, and carry on. The digest text is the deliverable.

## 5. Digest

```bash
python3 -m career_agent.digest
```

Prints what changed since the last run and updates the snapshot. This is
the body of the report: lead with what is newly above threshold, not with
the standing top five.

## 6. Persist

```bash
git add -A career_agent
git commit -m "Daily scout run: <n> new, <m> surfaced"
git push origin claude/career-agent-builder-skill-scxy4y
```

State is committed so the job history and every score are an auditable
record rather than living only in a container that gets reclaimed.

## 7. Report

Lead with the delta and keep it to a screen. Include the review page
link. If nothing crossed the threshold, say that plainly — a quiet day
is a real result and padding it wastes the one thing a daily message has,
which is Ali's trust that it only speaks when there is something to say.

Flag rather than bury: boards that failed, anything that looks like a
scoring or dedup bug, and any run where the Apify boards did not execute.
