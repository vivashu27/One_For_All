---
description: Lightweight prime — load only a compact priority-ranked manifest of the knowledge graph, then recall full nodes just-in-time with kb.py as the task needs them (keeps context flat as the graph grows). Use --full for the old deep briefing.
argument-hint: "[optional target context, e.g. graphql api oauth] [--graph a,b] [--full]"
---

You are running **INDUCE-KNOWLEDGE** mode for One For All (bug-bounty knowledge memory).

Load and follow the **`knowledge-graph`** skill now, then execute its **INDUCE mode**
(section 5). This is **read-only** for node content (recall may bump a node's usage
counter — that is expected and desirable).

Target/focus context from the user (may be empty): `$ARGUMENTS`

The point of this command is to **prime, not dump**: as the graph compounds, loading
every node would eat the model's context. Instead load a cheap priority manifest now
and pull full detail on demand.

Do this:
1. Bootstrap the knowledge base (skill §1). Set `KBPY="${CLAUDE_PLUGIN_ROOT}/web/kb.py"`
   (fall back to the repo path if unset). **Choose the graph(s):** `--graph a,b` in
   `$ARGUMENTS` induces those graphs together (union); with no `--graph`, use `default`.
   Set `G` to that comma list (default `default`) and pass it through as `--graph "$G"` —
   kb.py resolves the paths and, when several graphs are loaded, labels every node
   `graph:slug`. Run `python3 "$KBPY" graphs` first if you need to see what exists.
2. **Prime (default).** Load only the compact, priority-ranked manifest — no bodies:
   ```bash
   python3 "$KBPY" --graph "$G" manifest --top 20
   ```
   If `$ARGUMENTS` has focus terms (anything other than `--full`), also run a focused
   query so the most relevant items lead:
   ```bash
   python3 "$KBPY" --graph "$G" query "<focus terms>" --top 10
   ```
   Disabled nodes (`enabled: false`) are already excluded by kb.py.
3. **Brief, don't expand.** Summarize what exists from the manifest/query output — a few
   lines grouped by category (techniques · tools · references · lessons · workflow ·
   reporting), highest priority first, each with its slug. Do **not** open node bodies yet.
4. **Establish the just-in-time habit (state this to the user and follow it):** while
   working, when you hit a concrete sub-task, recall only what's relevant —
   `python3 "$KBPY" --graph "$G" query "<sub-task terms>"` then
   `python3 "$KBPY" --graph "$G" get <slug> [<slug> ...]` to load the 1–3 nodes you need.
   `get` bumps those nodes' usage counters, which raises their future priority.
5. Confirm the graph is primed and that you will recall deeper knowledge on the fly.

**`--full` mode:** if `$ARGUMENTS` contains `--full`, skip the lightweight path and give
the classic deep briefing instead — read the actual node files for the top/relevant nodes
(still skipping `enabled: false`) and present the richer grouped briefing. Use this only
when the user explicitly wants everything loaded up front.
