---
description: Launch the local web interface to view, edit, and share the bug-bounty knowledge graph (interactive graph, node editor, export/import). Dependency-free Python server, localhost by default.
argument-hint: "[--port 8787] [--host 0.0.0.0 to share on LAN] [--token SECRET] [--stop]"
---

You are launching the **knowledge-graph web interface** for the Bug Bounty Knowledge
Memory builder.

Arguments from the user (may be empty): `$ARGUMENTS`

Do this:

1. **Bootstrap** the knowledge base so it exists (idempotent):
   ```bash
   KB="$HOME/.claude/bug-bounty-knowledge"
   mkdir -p "$KB/nodes"
   if [ ! -f "$KB/INDEX.md" ] && [ -d "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/knowledge-seed" ]; then
     cp -r "${CLAUDE_PLUGIN_ROOT}/knowledge-seed/." "$KB/"
   fi
   ```

2. **If `$ARGUMENTS` contains `--stop`:** stop any running instance and report, then skip the rest:
   ```bash
   pkill -f 'bug_bounty_knowledge_web|web/server.py --kb' 2>/dev/null && echo "stopped" || echo "no running server found"
   ```

3. **Parse options** from `$ARGUMENTS`: `--port` (default `8787`), `--host`
   (default `127.0.0.1`), `--token` (default none). Warn the user before binding to
   anything other than `127.0.0.1`/`localhost`, and recommend pairing `--host` with a
   `--token` since the UI can read AND write the KB. Generate a random token if the
   user asks to share without supplying one.

4. **Start the server in the background** (it is a dependency-free stdlib server):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/web/server.py" --kb "$HOME/.claude/bug-bounty-knowledge" \
     --port <PORT> --host <HOST> [--token <TOKEN>]
   ```
   Run it with `run_in_background`. If the port is already in use, pick the next free
   port and tell the user.

5. **Verify** it is up and **report the URL** to the user as a clickable link, e.g.
   `http://127.0.0.1:8787/` (append `?token=<TOKEN>` when a token is set):
   ```bash
   sleep 1; curl -fsS "http://127.0.0.1:<PORT>/api/ping${TOKEN:+?token=$TOKEN}" && echo " OK"
   ```

6. Tell the user they can **view** (sidebar + interactive graph + journal), **edit**
   (open a node → Edit → Save; or New node), and **share/backup** (Export .zip/.json,
   Import, or re-run with `--host`/`--token` for live LAN sharing). To stop it later:
   `/serve-knowledge --stop`.

Keep the final message short: the URL, what they can do, and how to stop it.
