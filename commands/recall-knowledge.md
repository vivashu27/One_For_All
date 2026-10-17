---
description: Just-in-time recall — query the knowledge graph for what's relevant to the current task and load only the top few full nodes (not the whole graph). Priority-ranked; bumps usage so useful knowledge rises over time.
argument-hint: "<what you need, e.g. graphql idor auth bypass> [--top N] [--peek]"
---

You are running **RECALL** for One For All (bug-bounty knowledge memory) — pull in only
the prior knowledge relevant to what you're doing right now, instead of inducing the
whole graph.

Query from the user: `$ARGUMENTS`

Do this:
1. Set `KB="$HOME/.claude/bug-bounty-knowledge"` and
   `KBPY="${CLAUDE_PLUGIN_ROOT}/web/kb.py"` (fall back to the repo copy of `web/kb.py`
   if `CLAUDE_PLUGIN_ROOT` is unset). Ensure `$KB/nodes` exists.
2. **Rank** candidates by relevance × priority (disabled nodes are excluded):
   ```bash
   python3 "$KBPY" --kb "$KB" query "$ARGUMENTS"
   ```
   If `$ARGUMENTS` is empty, run `manifest --top 20` instead to show the priority graph.
3. **Load only what's needed.** Pick the 1–3 best hits and load their full bodies:
   ```bash
   python3 "$KBPY" --kb "$KB" get <slug> [<slug> ...]
   ```
   (`get` bumps each node's usage counter, raising its future priority. Add `--peek` if
   the user said not to count this as a use.)
4. Apply that knowledge to the current task and briefly tell the user which node(s) you
   pulled (by slug) and the key takeaway — don't paste whole bodies back unless asked.

Keep it lean: a couple of targeted nodes beats dumping the graph.
