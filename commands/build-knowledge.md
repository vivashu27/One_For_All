---
description: Harvest durable, reusable knowledge from this assessment and compound it into the global bug-bounty knowledge graph (dedupes, reinforces, and links).
argument-hint: "[optional focus, e.g. idor,graphql] [--graph <name> to target a specific knowledge graph]"
---

You are running **BUILD-KNOWLEDGE** mode for One For All (bug-bounty knowledge memory).

Load and follow the **`knowledge-graph`** skill now, then execute its **BUILD mode**
(section 4) end to end.

Focus hint from the user (may be empty): `$ARGUMENTS`

Do this:
1. **Pick the target graph.** `--graph <name>` in `$ARGUMENTS` selects which knowledge
   graph to compound into; otherwise use `default`. Resolve the directory: `default` →
   `$HOME/.claude/bug-bounty-knowledge`, any other name →
   `$HOME/.claude/knowledge-graphs/<name>`. Verify it exists
   (`python3 "$KBPY" graphs`); if the named graph does not exist, stop and tell the user
   to create it with `python3 "$KBPY" new <name>` rather than inventing it. Then
   bootstrap (skill §1) and confirm the absolute path. **Write only into that graph.**
2. Review this session / assessment and extract durable, **reusable** knowledge:
   techniques & tricks that worked, tools that helped (and how), references/links
   worth keeping, lessons learned, workflow improvements, and reporting insights.
   If `$ARGUMENTS` is set, prioritize that focus.
3. Apply the safety rules (skill §3): sanitize out all client/target-specific data,
   credentials, hostnames, and secrets — store only generalizable knowledge.
4. For each candidate: **search the graph first**, then either create a new node or
   **reinforce/merge/supersede** the existing one. Never duplicate.
5. Link new/updated nodes (`related:` + `[[wikilinks]]`, reciprocal), update
   `INDEX.md`, and append a dated entry to `JOURNAL.md`.
6. Report back a compact summary: nodes **created**, **reinforced**, **superseded**
   (with slugs). If nothing durable came up, say so instead of padding the graph.
