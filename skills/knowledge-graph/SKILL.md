---
name: knowledge-graph
description: Read, write, dedupe, link, and query the compounding bug-bounty knowledge graph used by the One_For_All plugin. Load this at the START of any bug bounty or security assessment work — recon, enumeration, vulnerability hunting, exploitation, chaining, or report writing — to recall relevant prior knowledge just-in-time via the priority graph (web/kb.py) before working, and to capture new techniques/lessons afterward. Also load whenever building knowledge (/build-knowledge), inducing it (/induce-knowledge), recalling it (/recall-knowledge), or any time you need to create, edit, merge, traverse, or query knowledge-graph nodes.
---

# Bug Bounty Knowledge Graph Engine

This skill is the storage and reasoning layer behind the `/build-knowledge` and
`/induce-knowledge` commands. It defines **where** knowledge lives, **how** it is
shaped, how to **compound** it without creating duplicates, and how to **query**
it as a graph.

Read this whole file before touching the knowledge base.

---

## 1. Where the knowledge lives

The live knowledge base (KB) is a single, global, per-user store — independent of
any assessment's working directory so it is shared by every chat session:

```
~/.claude/bug-bounty-knowledge/
├── INDEX.md          # the graph hub: every node, grouped by type + a link map
├── JOURNAL.md        # chronological log of each knowledge-building session
└── nodes/            # one markdown file per knowledge node: nodes/<slug>.md
```

The plugin ships starter content in `${CLAUDE_PLUGIN_ROOT}/knowledge-seed/`.

### Bootstrap (run first, every time — it is idempotent)

Resolve the KB path and seed it on first use:

```bash
KB="$HOME/.claude/bug-bounty-knowledge"
mkdir -p "$KB/nodes"
# Seed only when the live store is empty; the guard makes this safe to re-run.
if [ ! -f "$KB/INDEX.md" ] && [ -d "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/knowledge-seed" ]; then
  cp -r "${CLAUDE_PLUGIN_ROOT}/knowledge-seed/." "$KB/"
fi
echo "KB=$KB"
```

Use the **absolute** path it prints for all Read/Write/Edit calls (on this machine
that resolves to `/home/pentest/.claude/bug-bounty-knowledge`). Never write to the
plugin's `knowledge-seed/` — that is a read-only template.

The same store is also browsable/editable through the local web interface
(`/serve-knowledge` → `web/server.py`), which reads and writes these exact files — so
edits made there and by these commands stay in sync. Keep the schema below stable so
both stay interoperable.

---

## 2. Node schema

Every node is `nodes/<slug>.md`. `<slug>` is lowercase, kebab-case, and is the
node's identity — other nodes link to it by this slug. Frontmatter:

```yaml
---
id: <slug>                 # MUST equal the filename without .md
title: <Human Readable Title>
type: technique            # one of: technique | tool | reference | lesson | workflow | reporting | vuln-class
tags: [idor, api, access-control]
vuln_class: [idor]         # optional: bug classes this relates to ([] if n/a)
related: [burp-autorize, broken-access-control]   # graph edges → other slugs
confidence: medium         # seed | low | medium | high  (how battle-tested)
reinforced: 0              # times independently confirmed across assessments
uses: 0                    # times recalled during work — feeds the priority score
pin: false                 # optional: true forces this node to the top of priority
enabled: true              # false retires the node WITHOUT deleting it (see below)
created: 2026-10-11
updated: 2026-10-11
source: assessment         # seed | assessment
---
```

`uses` and `pin` are optional (default `0` / unpinned when absent) and feed the
**priority graph** — see section 8. Do not hand-edit `uses`; `kb.py` maintains it.

`enabled` is optional and defaults to **true** when absent. Setting it to `false`
(e.g. via the web UI's Disable toggle) keeps the node on disk but marks it retired:
**INDUCE mode must skip `enabled: false` nodes**, and the web UI greys them out. Use
it to park knowledge that is stale, noisy, or not relevant right now without losing it.

Body, below the frontmatter — keep sections lean, use `[[slug]]` wikilinks inline
to show relationships, and vary the middle by type:

```markdown
# <Title>

**Summary:** one or two sentences — what this is and why it matters.

## <type-specific sections>
- technique  → ## When to use / ## Steps / ## Gotchas / ## Seen working
- tool       → ## What it does / ## Best for / ## Key commands or config / ## Pairs with
- reference  → ## URL / ## Why it's worth it / ## Jump to for
- lesson     → ## What happened / ## Takeaway / ## Apply next time
- workflow   → ## Goal / ## Steps / ## Tools used / ## Output
- reporting  → ## Principle / ## Template or phrasing / ## Avoid
- vuln-class → ## What it is / ## Where it hides / ## Techniques (links) / ## Impact

## Related
[[slug-a]] — why related · [[slug-b]] — why related
```

### Confidence ladder
- `seed` — shipped starter knowledge, not yet confirmed by this user's work.
- `low` — observed/claimed once, unverified or situational.
- `medium` — confirmed in at least one real assessment.
- `high` — confirmed across two or more independent assessments (`reinforced >= 2`).

---

## 3. Safety & quality rules (critical — this is security data)

Never let client or target data leak into a shared, compounding store:
- **Never store** live credentials, tokens, cookies, API keys, PII, or secrets.
- **Never store** a specific client's in-scope hostnames, internal IPs, endpoints,
  or any data that identifies a program/engagement. Generalize it instead
  ("a GraphQL endpoint that…", not `api.acme-client.com/graphql`).
- Store **generalizable, reusable** knowledge only — a technique, a pattern, a
  tool tip, a lesson. If it only matters to one target, it does not belong here.
- Prefer verifiable facts. Do not invent reference URLs; only record links you are
  confident are real. Mark anything uncertain `confidence: low`.
- Keep legality/scope front of mind — this KB serves authorized testing only.

---

## 4. BUILD mode — compounding knowledge (/build-knowledge)

Goal: harvest durable lessons from the current session and **merge** them into the
graph so knowledge compounds instead of duplicating.

1. **Bootstrap** the KB (section 1).
2. **Gather candidates.** Review the current session/assessment (and any focus hint
   in the command arguments). Extract reusable items across the categories:
   techniques/tricks, tools that helped, references/links, lessons learned,
   workflow improvements, reporting insights. Sanitize per section 3.
3. **For each candidate, search before writing.** Grep/glob the KB for existing
   nodes covering the same idea (match on tags, title keywords, vuln_class):
   ```bash
   grep -rliE "<keyword1>|<keyword2>" "$KB/nodes/"
   ```
   - **No match → create** `nodes/<new-slug>.md` with full frontmatter,
     `source: assessment`, `reinforced: 0`, `confidence: low|medium`.
   - **Match found → reinforce/merge** the existing node (do NOT create a dup):
     - Edit the body to fold in the new nuance (append to the right section, or add
       a short `## Refinements` note dated today).
     - `reinforced` += 1 when this assessment independently confirms it; bump
       `confidence` up the ladder when `reinforced` crosses the threshold.
     - Set `updated:` to today.
   - **Proposing a better procedure?** Keep the node, rewrite the `## Steps` to the
     improved version, and add a one-line `> Superseded prior approach (reason)` note
     so the evolution is visible. This is encouraged — agents may propose better
     knowledge, not only append.
4. **Link the graph.** For every created/updated node, add relevant slugs to
   `related:` and `[[wikilinks]]` in prose. Add the reciprocal link on the other
   node too. Attach new techniques to their `vuln-class` hub node.
5. **Update `INDEX.md`** — add new nodes under their type heading and refresh the
   link map (section 6).
6. **Append to `JOURNAL.md`** a dated entry: what was added, what was reinforced,
   what was superseded (one or two lines each). This is the audit trail of how the
   graph grew.
7. **Report back** to the user: a compact list of nodes created / reinforced /
   superseded, with slugs.

If there is genuinely nothing durable to capture, say so rather than inventing
low-value nodes — graph quality beats graph size.

---

## 5. INDUCE mode — using prior knowledge (/induce-knowledge)

Goal: **prime, don't dump.** Give the session a cheap sense of what exists and what
matters most, then recall full nodes just-in-time (section 8). Loading every body up
front does not scale as the graph compounds — it burns context on knowledge the current
task doesn't need.

1. **Bootstrap** the KB (section 1).
2. **Load the priority manifest only — no bodies.** Run `kb.py manifest --top 20`
   (section 8). It is already priority-ranked and already excludes `enabled: false`
   nodes. If focus terms were given, also run `kb.py query "<focus terms>" --top 10`.
3. **Brief from the manifest.** Present a tight, priority-ordered summary grouped by
   category (techniques · tools · references · lessons · workflow · reporting), each
   line carrying its slug. Do **not** open node bodies here.
4. **Set the just-in-time habit.** Tell the user — and then do this throughout the
   session — that you will recall deeper knowledge only when a concrete sub-task needs
   it, via `kb.py query` → `kb.py get <slug>` (section 8). That keeps context flat.
5. **`--full` fallback only on request.** If the user explicitly asks for the old deep
   briefing (`--full`), read the actual files for the top/relevant nodes (still skipping
   `enabled: false`), traverse 1-hop `related:` neighbors so chains surface, and present
   the richer grouped briefing. Default induce never does this.

---

## 6. INDEX.md format

`INDEX.md` is the graph hub. Keep it regenerated/maintained so it always reflects
`nodes/`:

```markdown
# Bug Bounty Knowledge Graph — Index

_Last updated: <date> · <N> nodes_

## Techniques
- [[slug]] — one-line summary (confidence · reinforced)
...
## Tools
...
## References
...
## Lessons
...
## Workflows
...
## Reporting
...
## Vuln Classes (hubs)
...

## Link map
- broken-access-control → idor-id-enumeration, oauth-account-takeover
- idor-id-enumeration → burp-autorize, broken-access-control
...
```

---

## 7. Conventions
- Slugs: lowercase kebab-case, stable, never rename without updating every `related:`
  and `[[link]]` that points to it.
- Dates: ISO `YYYY-MM-DD`. Convert relative dates ("today", "last week") to absolute.
- One fact/idea per node — if a node grows two distinct ideas, split it and link them.
- Dedup aggressively; a smaller, denser, well-linked graph is more useful than a
  sprawling one.

---

## 8. Priority graph & just-in-time recall (`kb.py`)

As the graph grows, inducing everything is wasteful. `${CLAUDE_PLUGIN_ROOT}/web/kb.py`
(stdlib-only, no server needed) ranks knowledge by a **priority score** and loads only
what a task needs. Set `KB="$HOME/.claude/bug-bounty-knowledge"` and
`KBPY="${CLAUDE_PLUGIN_ROOT}/web/kb.py"` (fall back to the repo's `web/kb.py`).

**Priority score** (higher = surface first), computed per node, not stored:
`3·confidence(seed0→high3) + 2·log2(1+reinforced) + 1.5·log2(1+uses) + recency(updated)
+ 100 if pinned`. So battle-tested, frequently-recalled, recently-touched, and pinned
knowledge rises automatically.

**Commands:**
- `python3 "$KBPY" --kb "$KB" manifest [--top N] [--type T] [--json]` — compact
  priority-ranked index (ids + summaries, no bodies). The cheap "what do I know" layer;
  this is what INDUCE loads.
- `python3 "$KBPY" --kb "$KB" query "<terms>" [--top N]` — rank by relevance×priority;
  returns compact hits + the `get` line to load them.
- `python3 "$KBPY" --kb "$KB" get <slug> [<slug> ...]` — print the FULL node(s) for just
  those slugs (the just-in-time load). **Bumps each node's `uses`**, raising its future
  priority (`--peek` to read without counting). This is the "compounding relevance" loop.
- `python3 "$KBPY" --kb "$KB" pin <slug> [--off]` — pin/unpin a node to force it top.
- `python3 "$KBPY" --kb "$KB" stats` — totals + current top of the priority graph.

`kb.py` excludes `enabled: false` nodes from `manifest`/`query` (they stay retired).
Prefer recall (`query` → `get`) over re-reading the whole graph whenever you need prior
knowledge mid-task — that is the whole point of the priority graph.
