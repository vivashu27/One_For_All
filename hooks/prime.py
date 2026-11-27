#!/usr/bin/env python3
"""
Hooks for One_For_All (bug-bounty knowledge memory). One script, dispatched on the
hook event in the stdin JSON:

  SessionStart      pointer note (always); in opted-in projects also the standing rules
                    for phase all+scope and the pipeline spine. Fires again after compact.
  SubagentStart     opted-in: rules + pointers for the agent's phase (hooks/agent-phases.json).
  UserPromptSubmit  opted-in: up to 3 strongly matching node summaries not shown yet.
  PostToolUse       opted-in, main session: one delegation nudge after 8 inline tool calls.

Opt-in = a `.claude/one-for-all.json` in the project (or a parent dir), or
`~/.claude/one-for-all.json` with "rules": "global". Keys: graphs, pin, disable.

Fail-safe by design: any problem → print nothing and exit 0, so it can never
disrupt a session.
"""
import json
import os
import re
import sys
import tempfile

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or \
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KBPY = os.path.join(PLUGIN_ROOT, "web", "kb.py")
kbmod = None   # web/kb.py, imported inside main()'s try so a broken install stays silent

FANOUT = "coordinator-subagent-fanout"
NUDGE_AFTER = 8          # node allows ~5 inline calls; 8 leaves slack before nudging
RECALL_MIN = 8           # relevance score a prompt must reach to inject a node
RECALL_TOP = 3
CFG_NAME = "one-for-all.json"
# prompts are prose, not search terms: filler words would match nearly every node body
STOP = set("the and for with this that now then from into are was you can all any not but how why what "
           "when where which who use using test testing check let lets please again also just more some "
           "flow next try make get run".split())


def emit(event, ctx):
    if ctx:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}}))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return None


def project_cfg(cwd):
    """Nearest project config walking up from cwd (stopping at $HOME), else the
    user-level one only if it opts in globally. None = not opted in."""
    home = os.path.realpath(os.path.expanduser("~"))
    d = os.path.realpath(cwd or os.getcwd())
    while d != home:
        p = os.path.join(d, ".claude", CFG_NAME)
        if os.path.isfile(p):
            return read_json(p) or {}     # present but unreadable still opts in
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    g = read_json(os.path.join(home, ".claude", CFG_NAME))
    return g if g and g.get("rules") == "global" else None


def load_nodes(cfg):
    out = []
    for name in cfg.get("graphs") or ["default"]:
        try:
            out += kbmod.load_nodes(kbmod.resolve_graph(name), name)
        except ValueError:
            continue
    return out


def fanout_enabled(cfg):
    """Read only the delegation node, not the whole graph: this runs on every tool call."""
    for name in cfg.get("graphs") or ["default"]:
        try:
            raw = kbmod.read_text(kbmod.node_path(kbmod.resolve_graph(name), FANOUT))
        except ValueError:
            continue
        if raw is not None:
            return kbmod.enabled(kbmod.parse_frontmatter(raw)[0])
    return False


def agent_map():
    return read_json(os.path.join(PLUGIN_ROOT, "hooks", "agent-phases.json")) or {}


# ---- per-session state (shown slugs, inline-call counter) ----
def state_path(sid):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(sid or ""))[:100]
    if not sid:
        return None
    d = os.path.join(tempfile.gettempdir(), "one-for-all")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, sid + ".json")


def load_state(p):
    return (read_json(p) if p else None) or {"shown": [], "inline": 0, "nudged": False}


def save_state(p, st):
    if p:
        kbmod.write_text(p, json.dumps(st))


def shown_slugs(block):
    return re.findall(r"^- \(?([a-z0-9][a-z0-9-]*)", block, re.M)


def pointer_note():
    nd = kbmod.nodes_dir(kbmod.DEFAULT_KB)
    if not os.path.isdir(nd):
        return ""
    # count files only: parsing every node on every session start is wasted work
    count = len([f for f in os.listdir(nd) if f.endswith(".md")])
    if count <= 0:
        return ""
    others = ""
    try:   # the "other graphs" hint is optional; never lose the main pointer over it
        extra = [n for n, _ in kbmod.all_graphs() if n != "default"]
        if extra:
            others = (" Other graphs available: " + ", ".join(extra)
                      + " — add `--graph <name>` (or `--graph a,b`) to target them.")
    except Exception:
        pass
    return (
        f"[One For All — bug-bounty knowledge memory active] A compounding knowledge graph of prior "
        f"assessments is available ({count} nodes) but is NOT auto-loaded into context. "
        f"When this session involves a security assessment, bug bounty, recon, enumeration, "
        f"vulnerability hunting, exploitation, or report writing, recall only the knowledge relevant "
        f"to the current task instead of re-deriving it — and prefer this over loading the whole graph:\n"
        f"  survey : python3 {KBPY} manifest --top 20   (add --phase <p> to narrow)\n"
        f"  find   : python3 {KBPY} query \"<task terms>\"\n"
        f"  load   : python3 {KBPY} get <slug> [<slug> ...]   (loads the full node; raises its priority)\n"
        f"For a fuller prime run /induce-knowledge; capture new techniques/lessons afterward with "
        f"/build-knowledge." + others
        + " If this session is not security-related, ignore this note."
    )


def spine():
    by_phase = {}
    for agent, ph in agent_map().items():
        by_phase.setdefault(ph, []).append(agent)
    route = "; ".join(f"{p} → {', '.join(by_phase[p])}" for p in kbmod.PHASES if p in by_phase)
    return (f"Pipeline: {' → '.join(kbmod.PHASES)}. You are the coordinator and own "
            f"scope; dispatch each later phase to its agent ({route}). Each agent receives its phase's "
            "rules automatically when it starts.")


def on_session_start(inp, cfg, st):
    parts = []
    if cfg is not None:
        block = kbmod.inject_block(load_nodes(cfg), ["scope"], cfg, KBPY)
        parts += [b for b in (block, spine()) if b]
        st["shown"] = shown_slugs(block)   # context was (re)built: earlier recalls are gone
        st["inline"], st["nudged"] = 0, False
    note = pointer_note()
    if note:
        parts.append(note)
    return "\n\n".join(parts)


def on_subagent_start(inp, cfg, st):
    if cfg is None:
        return ""
    ph = agent_map().get(str(inp.get("agent_type") or ""))
    return kbmod.inject_block(load_nodes(cfg), [ph] if ph else ["all"], cfg, KBPY)


def on_prompt(inp, cfg, st):
    if cfg is None:
        return ""
    terms = [t for t in kbmod.tokenize(inp.get("prompt")) if len(t) >= 3 and t not in STOP]
    off, seen = set(cfg.get("disable") or []), set(st["shown"])
    hits = []
    for n in load_nodes(cfg):
        if n["enabled"] and n["slug"] not in off and n["slug"] not in seen:
            rel = kbmod.relevance(n, terms)
            if rel >= RECALL_MIN:
                hits.append((rel, n["priority"], n))   # relevance first: a pin's +100 must not outrank a match
    hits.sort(key=lambda x: (-x[0], -x[1], x[2]["slug"]))
    top = [n for _, _, n in hits[:RECALL_TOP]]
    if not top:
        return ""
    st["shown"] += [n["slug"] for n in top]
    return ("[One For All] Knowledge likely relevant to this prompt — load with "
            f"`python3 {KBPY} get <slug>` before acting:\n"
            + "\n".join(f"- {n['slug']} — {n['summary'][:200]}" for n in top))


def on_tool(inp, cfg, st):
    if cfg is None or inp.get("agent_id") or FANOUT in (cfg.get("disable") or []):
        return ""
    if not fanout_enabled(cfg):
        return ""
    if inp.get("tool_name") in ("Agent", "Task"):
        st["inline"], st["nudged"] = 0, False
        return ""
    st["inline"] = int(st.get("inline", 0)) + 1
    if st["inline"] < NUDGE_AFTER or st.get("nudged"):
        return ""
    st["nudged"] = True
    return (f"[One For All] You have made {st['inline']} tool calls inline without delegating. Per the "
            "user's standing delegation rule (coordinator-subagent-fanout), spawn the matching phase agent "
            "for this work now, or record in the hunt journal why inline is justified.")


HANDLERS = {"SessionStart": on_session_start, "SubagentStart": on_subagent_start,
            "UserPromptSubmit": on_prompt, "PostToolUse": on_tool}


def main():
    global kbmod
    try:
        sys.path.insert(0, os.path.join(PLUGIN_ROOT, "web"))
        import kb as kbmod   # owns graph paths (incl. BBK_KB), so hook and CLI agree
        raw = "" if sys.stdin.isatty() else sys.stdin.read()
        try:
            inp = json.loads(raw) if raw.strip() else {}
        except ValueError:
            inp = {}
        event = inp.get("hook_event_name") or "SessionStart"
        fn = HANDLERS.get(event)
        if not fn:
            return 0
        cfg = project_cfg(inp.get("cwd"))
        sp = state_path(inp.get("session_id"))
        st = load_state(sp)
        ctx = fn(inp, cfg, st)
        if cfg is not None:
            save_state(sp, st)
        emit(event, ctx)
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
