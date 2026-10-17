#!/usr/bin/env python3
"""
SessionStart hook for One_For_All (bug-bounty knowledge memory).

Injects a tiny pointer so a fresh session KNOWS the compounding knowledge graph
exists and recalls from it on the fly during security work — without the user
having to run a command. It does NOT load node bodies (that stays just-in-time).

Fail-safe by design: any problem → print nothing and exit 0, so it can never
disrupt the start of a session. Emits nothing when there is no knowledge yet.
"""
import json
import os
import sys


def main():
    try:
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        kb = os.environ.get("BBK_KB") or os.path.expanduser("~/.claude/bug-bounty-knowledge")
        nodes_dir = os.path.join(kb, "nodes")
        kbpy = os.path.join(plugin_root, "web", "kb.py")
        if not os.path.isdir(nodes_dir) or not os.path.isfile(kbpy):
            return 0

        # Prefer an accurate enabled-node count via kb.py; fall back to a file count.
        try:
            sys.path.insert(0, os.path.join(plugin_root, "web"))
            import kb as kbmod
            nodes = kbmod.load_nodes(kb)
            enabled = sum(1 for n in nodes if n["enabled"])
        except Exception:
            enabled = len([f for f in os.listdir(nodes_dir) if f.endswith(".md")])
        if enabled <= 0:
            return 0

        ctx = (
            f"[One For All — bug-bounty knowledge memory active] A compounding knowledge graph of prior "
            f"assessments is available ({enabled} nodes) but is NOT auto-loaded into context. "
            f"When this session involves a security assessment, bug bounty, recon, enumeration, "
            f"vulnerability hunting, exploitation, or report writing, recall only the knowledge relevant "
            f"to the current task instead of re-deriving it — and prefer this over loading the whole graph:\n"
            f"  survey : python3 {kbpy} manifest --top 20\n"
            f"  find   : python3 {kbpy} query \"<task terms>\"\n"
            f"  load   : python3 {kbpy} get <slug> [<slug> ...]   (loads the full node; raises its priority)\n"
            f"For a fuller prime run /induce-knowledge; capture new techniques/lessons afterward with "
            f"/build-knowledge. If this session is not security-related, ignore this note."
        )
        print(json.dumps({
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}
        }))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
