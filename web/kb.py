#!/usr/bin/env python3
"""
kb.py — priority-ranked, just-in-time retrieval over the bug-bounty knowledge graph.

Standalone (stdlib only; no server required). Lets an agent load ONLY the knowledge
relevant to the current task instead of inducing the whole graph — so context cost
stays flat as the graph compounds.

Priority score (higher = load sooner) is computed per node from:
  confidence (seed<low<medium<high) + reinforced count + recency(updated)
  + a usage counter that bumps every time the node is recalled + an optional manual pin.

Usage:
  python3 kb.py manifest [--top N] [--type T] [--json] [--all]
      Compact, priority-ranked index (no bodies). The cheap "what do I know" layer.
  python3 kb.py query "<terms>" [--top N] [--type T] [--json]
      Rank nodes by relevance to <terms> blended with priority. Returns compact hits.
  python3 kb.py get <slug> [<slug> ...] [--peek]
      Print the FULL node(s) for just those slugs (the just-in-time load). Bumps each
      node's usage counter unless --peek.
  python3 kb.py use <slug> [--n K]      Manually bump a node's usage counter.
  python3 kb.py pin <slug> [--off]      Pin (or unpin) a node to force it to the top.
  python3 kb.py stats                   Totals + the current top of the priority graph.

--kb defaults to ~/.claude/bug-bounty-knowledge.
"""
import argparse
import datetime
import json
import math
import os
import re
import sys

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Graph names are directory names, so underscores are fine too (node slugs stay kebab-case).
GRAPH_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CONF = {"seed": 0, "low": 1, "medium": 2, "high": 3}


# ---- frontmatter (minimal YAML subset: scalars, ints, bools, inline [lists]) ----
def parse_value(val):
    val = val.strip()
    if val == "":
        return ""
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        return [x.strip().strip("\"'") for x in inner.split(",") if x.strip()] if inner else []
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.match(r"^-?\d+$", val):
        return int(val)
    return val.strip("\"'")


def parse_frontmatter(text):
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.split("\n"):
            raw = line.rstrip()
            if not raw or raw.lstrip().startswith("#") or ":" not in raw:
                continue
            key, _, val = raw.partition(":")
            meta[key.strip()] = parse_value(val)
    return meta, body


def extract_summary(body):
    m = re.search(r"\*\*Summary:\*\*\s*(.+)", body)
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())
    for line in body.split("\n"):
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return re.sub(r"\s+", " ", s)
    return ""


def update_frontmatter(raw, updates):
    m = re.match(r"^(---\s*\n)(.*?\n)(---\s*\n?)(.*)$", raw, re.S)
    if not m:
        return raw
    head, fm, close, body = m.group(1), m.group(2), m.group(3), m.group(4)
    lines = fm.rstrip("\n").split("\n")
    for key, val in updates.items():
        pat = re.compile(rf"^{re.escape(key)}\s*:")
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = f"{key}: {val}"
                break
        else:
            lines.append(f"{key}: {val}")
    return head + "\n".join(lines) + "\n" + close + body


# ---- scoring ----
def _int(x):
    try:
        return int(x)
    except (ValueError, TypeError):
        return 0


def _truthy(x):
    return str(x).strip().lower() == "true"


def enabled(meta):
    en = meta.get("enabled", True)
    return not (en is False or (isinstance(en, str) and en.strip().lower() == "false"))


def recency_factor(updated, today):
    try:
        d = datetime.date.fromisoformat(str(updated)[:10])
    except Exception:
        return 0.3  # unknown date → neutral
    days = max(0, (today - d).days)
    return math.exp(-days / 180.0)  # ~6-month half-life-ish decay, 0..1


def priority_score(meta, today):
    conf = CONF.get(str(meta.get("confidence", "low")).strip().lower(), 1)
    reinforced = _int(meta.get("reinforced", 0))
    uses = _int(meta.get("uses", 0))
    rec = recency_factor(meta.get("updated", ""), today)
    pin = _truthy(meta.get("pin"))
    return round(3 * conf + 2.0 * math.log2(1 + reinforced) + 1.5 * math.log2(1 + uses)
                 + 1.0 * rec + (100 if pin else 0), 3)


def tokenize(q):
    return [t for t in re.split(r"[^a-z0-9]+", (q or "").lower()) if len(t) >= 2]


def relevance(node, terms):
    m = node["meta"]
    title = str(m.get("title", node["slug"])).lower()
    tags = " ".join((m.get("tags") or []) + (m.get("vuln_class") or [])).lower()
    summ = node["summary"].lower()
    body = node["body"].lower()
    score = 0
    for t in terms:
        if t in title:
            score += 5
        if t in tags:
            score += 4
        if t in summ:
            score += 2
        elif t in body:
            score += 1
    return score


# ---- KB access ----
def nodes_dir(kb):
    return os.path.join(os.path.abspath(os.path.expanduser(kb)), "nodes")


GRAPHS_ROOT = os.path.expanduser("~/.claude/knowledge-graphs")
DEFAULT_KB = os.path.expanduser("~/.claude/bug-bounty-knowledge")


def resolve_graph(name):
    """Graph name -> directory. 'default' keeps the original KB path (no migration)."""
    name = (name or "default").strip()
    if name == "default":
        return DEFAULT_KB
    if not GRAPH_RE.match(name):
        sug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
        raise ValueError(f"invalid graph name '{name}' (lowercase letters, digits, - and _ only)"
                         + (f" — did you mean '{sug}'?" if sug and GRAPH_RE.match(sug) else ""))
    return os.path.join(GRAPHS_ROOT, name)


def roots(a):
    """[(graph_name, dir)] this invocation addresses. --kb wins; --graph takes a list."""
    if getattr(a, "kb", None):
        p = os.path.abspath(os.path.expanduser(a.kb))
        return [(os.path.basename(p) or "kb", p)]
    names = [x.strip() for x in (getattr(a, "graph", None) or "default").split(",") if x.strip()]
    return [(n, resolve_graph(n)) for n in (names or ["default"])]


def all_graphs():
    """Every known graph: 'default' plus each directory under GRAPHS_ROOT."""
    out = [("default", DEFAULT_KB)]
    if os.path.isdir(GRAPHS_ROOT):
        for n in sorted(os.listdir(GRAPHS_ROOT)):
            if os.path.isdir(os.path.join(GRAPHS_ROOT, n)):
                out.append((n, os.path.join(GRAPHS_ROOT, n)))
    return out


def node_path(kb, slug):
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid slug: {slug}")
    nd = nodes_dir(kb)
    p = os.path.join(nd, slug + ".md")
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(nd):
        raise ValueError("path escape")
    return p


def find_node(rs, token):
    """'slug' or 'graph:slug' -> (graph, dir, slug, filepath), or None."""
    if ":" in token:
        g, slug = token.split(":", 1)
        cands = [(n, p) for (n, p) in rs if n == g]
        if not cands:
            try:
                cands = [(g, resolve_graph(g))]
            except ValueError:
                return None
    else:
        slug, cands = token, rs
    for name, p in cands:
        try:
            fp = node_path(p, slug)
        except ValueError:
            return None
        if os.path.exists(fp):
            return name, p, slug, fp
    return None


def load_nodes(kb, graph="default"):
    nd = nodes_dir(kb)
    out = []
    if not os.path.isdir(nd):
        return out
    today = datetime.date.today()
    for name in sorted(os.listdir(nd)):
        if not name.endswith(".md"):
            continue
        slug = name[:-3]
        with open(os.path.join(nd, name), "r", encoding="utf-8") as fh:
            raw = fh.read()
        meta, body = parse_frontmatter(raw)
        out.append({
            "slug": slug, "meta": meta, "body": body, "raw": raw,
            "summary": extract_summary(body),
            "priority": priority_score(meta, today),
            "enabled": enabled(meta),
            "graph": graph, "path": os.path.join(nd, name),
        })
    return out


def load_many(rs):
    out = []
    for name, p in rs:
        out += load_nodes(p, name)
    return out


def ref(n, multi):
    return f"{n['graph']}:{n['slug']}" if multi else n["slug"]


def compact_line(n, multi=False):
    m = n["meta"]
    pin = " ★" if _truthy(m.get("pin")) else ""
    dis = " (disabled)" if not n["enabled"] else ""
    return (f"{n['priority']:6.2f}  {ref(n, multi)}  [{m.get('type', '?')}]{pin}  "
            f"({m.get('confidence', '?')}·r{_int(m.get('reinforced', 0))}·u{_int(m.get('uses', 0))}) "
            f"— {n['summary']}{dis}")


def compact_obj(n, extra=None):
    m = n["meta"]
    o = {
        "slug": n["slug"], "graph": n.get("graph", "default"),
        "title": m.get("title", n["slug"]), "type": m.get("type"),
        "tags": m.get("tags", []), "vuln_class": m.get("vuln_class", []),
        "confidence": m.get("confidence"), "reinforced": _int(m.get("reinforced", 0)),
        "uses": _int(m.get("uses", 0)), "pin": _truthy(m.get("pin")),
        "priority": n["priority"], "summary": n["summary"], "enabled": n["enabled"],
    }
    if extra:
        o.update(extra)
    return o


# ---- commands ----
def cmd_manifest(a):
    rs = roots(a); multi = len(rs) > 1
    nodes = load_many(rs)
    if not a.all:
        nodes = [n for n in nodes if n["enabled"]]
    if a.type:
        nodes = [n for n in nodes if n["meta"].get("type") == a.type]
    nodes.sort(key=lambda n: (-n["priority"], n["slug"]))
    top = nodes[: a.top] if a.top else nodes
    if a.json:
        print(json.dumps([compact_obj(n) for n in top], indent=2))
        return
    print(f"# Priority manifest — {len(top)} of {len(nodes)} node(s)"
          + f"  [graphs: {', '.join(n for n, _ in rs)}]"
          + (f" (type={a.type})" if a.type else "") + "  [priority  slug  [type]  (conf·reinf·uses) — summary]")
    for n in top:
        print(compact_line(n, multi))
    print(f"\nLoad full detail for the few you need:  python3 kb.py get "
          f"{'<graph>:<slug>' if multi else '<slug>'} [...]")


def cmd_query(a):
    terms = tokenize(a.terms)
    rs = roots(a); multi = len(rs) > 1
    nodes = [n for n in load_many(rs) if n["enabled"]]
    if a.type:
        nodes = [n for n in nodes if n["meta"].get("type") == a.type]
    if not terms:
        return cmd_manifest(a)
    scored = []
    for n in nodes:
        rel = relevance(n, terms)
        if rel > 0:
            final = round(rel + 0.3 * n["priority"], 3)
            scored.append((final, rel, n))
    scored.sort(key=lambda x: (-x[0], x[2]["slug"]))
    top = scored[: a.top] if a.top else scored
    if a.json:
        print(json.dumps([compact_obj(n, {"match": rel, "rank": final}) for final, rel, n in top], indent=2))
        return
    if not top:
        print(f"# No matches for: {a.terms}\nTry broader terms, or: python3 kb.py manifest")
        return
    print(f"# Query: {a.terms!r} — {len(top)} hit(s)  [graphs: {', '.join(n for n, _ in rs)}]"
          "  [rank(match)  slug  [type]  (conf·reinf·uses) — summary]")
    for final, rel, n in top:
        print(f"{final:6.2f}(m{rel})  {compact_line(n, multi)}")
    slugs = " ".join(ref(n, multi) for _, _, n in top[:3])
    print(f"\nLoad the top ones:  python3 kb.py get {slugs}")


def _bump_uses(p, n=1):
    with open(p, "r", encoding="utf-8") as fh:
        raw = fh.read()
    meta, _ = parse_frontmatter(raw)
    new = _int(meta.get("uses", 0)) + n
    raw = update_frontmatter(raw, {"uses": str(new)})
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(raw if raw.endswith("\n") else raw + "\n")
    return new


def cmd_get(a):
    rs = roots(a); multi = len(rs) > 1
    missing = []
    for token in a.slugs:
        hit = find_node(rs, token)
        if not hit:
            missing.append(token)
            continue
        graph, _d, slug, fp = hit
        with open(fp, "r", encoding="utf-8") as fh:
            raw = fh.read()
        meta, _ = parse_frontmatter(raw)
        used = ""
        if not a.peek:
            try:
                used = f"  (uses→{_bump_uses(fp)})"
            except Exception:
                used = ""
        flag = "" if enabled(meta) else "  [DISABLED — normally skipped on induce]"
        label = f"{graph}:{slug}" if multi else slug
        print(f"\n===== {label}{flag}{used} =====")
        print(raw.rstrip())
    if missing:
        print(f"\n# not found: {', '.join(missing)}", file=sys.stderr)


def cmd_use(a):
    hit = find_node(roots(a), a.slug)
    if not hit:
        print(f"error: not found: {a.slug}", file=sys.stderr)
        return 1
    print(f"{hit[0]}:{hit[2]}: uses → {_bump_uses(hit[3], a.n)}")


def cmd_pin(a):
    hit = find_node(roots(a), a.slug)
    if not hit:
        print(f"error: not found: {a.slug}", file=sys.stderr)
        return 1
    fp = hit[3]
    with open(fp, "r", encoding="utf-8") as fh:
        raw = fh.read()
    raw = update_frontmatter(raw, {"pin": "false" if a.off else "true"})
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write(raw if raw.endswith("\n") else raw + "\n")
    print(f"{hit[0]}:{hit[2]}: {'unpinned' if a.off else 'pinned ★'}")


def cmd_stats(a):
    rs = roots(a); multi = len(rs) > 1
    nodes = load_many(rs)
    en = [n for n in nodes if n["enabled"]]
    by_type = {}
    for n in en:
        by_type[n["meta"].get("type", "?")] = by_type.get(n["meta"].get("type", "?"), 0) + 1
    print(f"graphs: {', '.join(n for n, _ in rs)}")
    print(f"nodes: {len(nodes)} total · {len(en)} enabled · {len(nodes) - len(en)} disabled")
    print("by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    en.sort(key=lambda n: (-n["priority"], n["slug"]))
    print("top of the priority graph:")
    for n in en[:5]:
        print("  " + compact_line(n, multi))


def cmd_graphs(a):
    rows = all_graphs()
    print(f"# {len(rows)} knowledge graph(s)   [name  nodes(enabled/total)  path]")
    for name, p in rows:
        ns = load_nodes(p, name)
        en = sum(1 for n in ns if n["enabled"])
        mark = " (missing)" if not os.path.isdir(p) else ""
        print(f"  {name:<16} {en}/{len(ns):<6} {p}{mark}")
    print("\nUse one:  --graph <name>      Several:  --graph a,b      New:  kb.py new <name>")


def rename_graph(old, new):
    """Rename a graph directory. Returns (ok, message). Safe because nothing inside a
    graph, and no other graph, refers to it by name (links are intra-graph slugs)."""
    if old == "default" or new == "default":
        return False, "the 'default' graph cannot be renamed (its path is fixed and commands pass it as --kb)"
    try:
        src, dst = resolve_graph(old), resolve_graph(new)
    except ValueError as e:
        return False, str(e)
    if not os.path.isdir(src):
        return False, f"no such graph: {old}"
    if os.path.exists(dst):
        return False, f"graph '{new}' already exists"
    if os.path.dirname(os.path.realpath(src)) != os.path.realpath(GRAPHS_ROOT):
        return False, "refusing to rename a directory outside the graphs root"
    os.rename(src, dst)
    # INDEX.md is rewritten (with the graph name) on the next reindex; JOURNAL.md is not.
    p = os.path.join(dst, "JOURNAL.md")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            t = fh.read()
        t2 = t.replace(f"Knowledge Graph: {old}", f"Knowledge Graph: {new}") \
              .replace(f"--graph {old}", f"--graph {new}")
        if t2 != t:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(t2)
    return True, f"renamed graph '{old}' -> '{new}'"


def cmd_rename(a):
    ok, msg = rename_graph(a.old, a.new)
    if not ok:
        print(f"error: {msg}", file=sys.stderr)
        return 1
    print(msg)
    print(f"use it:  --graph {a.new}"
          "\nnote: restart any running web server that was launched against the old name")


def cmd_delete(a):
    """Delete a whole graph. 'default' is protected; confirmation is always required."""
    try:
        p = resolve_graph(a.name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if a.name == "default":
        print("error: the 'default' graph is protected and cannot be deleted", file=sys.stderr)
        return 1
    if not os.path.isdir(p):
        print(f"error: no such graph: {a.name}", file=sys.stderr)
        return 1
    # never remove anything that is not a direct child of the graphs root
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(GRAPHS_ROOT):
        print("error: refusing to delete a directory outside the graphs root", file=sys.stderr)
        return 1
    n = len(load_nodes(p, a.name))
    if a.yes:
        pass                                  # explicit non-interactive confirmation
    elif sys.stdin.isatty():
        print(f"About to permanently delete graph '{a.name}' ({n} node(s)) at {p}")
        if input(f"Type the graph name to confirm: ").strip() != a.name:
            print("aborted (name did not match)", file=sys.stderr)
            return 1
    else:
        print(f"error: refusing to delete '{a.name}' ({n} node(s)) without confirmation — "
              f"re-run with --yes, or run it interactively", file=sys.stderr)
        return 1
    import shutil
    shutil.rmtree(os.path.realpath(p))
    print(f"deleted graph '{a.name}' ({n} node(s) removed) from {p}")


def create_graph(name, seed=False):
    """Create a new, separate graph. Returns (ok, message, path)."""
    if name == "default":
        return False, "'default' is the existing graph", None
    try:
        p = resolve_graph(name)
    except ValueError as e:
        return False, str(e), None
    if os.path.isdir(p):
        return False, f"graph '{name}' already exists at {p}", None
    os.makedirs(os.path.join(p, "nodes"), exist_ok=True)
    seeddir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge-seed")
    if seed and os.path.isdir(seeddir):
        import shutil
        shutil.copytree(seeddir, p, dirs_exist_ok=True)
    else:
        d = datetime.date.today().isoformat()
        with open(os.path.join(p, "INDEX.md"), "w", encoding="utf-8") as fh:
            fh.write(f"# Knowledge Graph: {name} — Index\n\n_Last updated: {d} · 0 nodes_\n\n"
                     "Grow it with `/build-knowledge --graph " + name + "`.\n")
        with open(os.path.join(p, "JOURNAL.md"), "w", encoding="utf-8") as fh:
            fh.write(f"# Knowledge Graph: {name} — Journal\n\nNewest entries on top.\n\n---\n\n"
                     f"## {d} — Created\n- Empty graph created.\n")
    return True, f"created graph '{name}' at {p}" + (" (seeded from knowledge-seed)" if seed else " (empty)"), p


def cmd_new(a):
    ok, msg, _ = create_graph(a.name, a.seed)
    if not ok:
        print(f"error: {msg}", file=sys.stderr)
        return 1
    print(msg)
    print(f"use it:  --graph {a.name}")


def main():
    ap = argparse.ArgumentParser(description="Priority-ranked retrieval over the bug-bounty knowledge graph")
    ap.add_argument("--graph", default=None,
                    help="graph name, or a comma list to read several at once (default: 'default')")
    ap.add_argument("--kb", default=None, help="explicit KB directory; overrides --graph")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest"); m.add_argument("--top", type=int, default=0); m.add_argument("--type"); m.add_argument("--json", action="store_true"); m.add_argument("--all", action="store_true"); m.set_defaults(fn=cmd_manifest)
    q = sub.add_parser("query"); q.add_argument("terms"); q.add_argument("--top", type=int, default=8); q.add_argument("--type"); q.add_argument("--json", action="store_true"); q.add_argument("--all", action="store_true"); q.set_defaults(fn=cmd_query)
    g = sub.add_parser("get"); g.add_argument("slugs", nargs="+"); g.add_argument("--peek", action="store_true"); g.set_defaults(fn=cmd_get)
    u = sub.add_parser("use"); u.add_argument("slug"); u.add_argument("--n", type=int, default=1); u.set_defaults(fn=cmd_use)
    p = sub.add_parser("pin"); p.add_argument("slug"); p.add_argument("--off", action="store_true"); p.set_defaults(fn=cmd_pin)
    s = sub.add_parser("stats"); s.set_defaults(fn=cmd_stats)
    gl = sub.add_parser("graphs"); gl.set_defaults(fn=cmd_graphs)
    dl = sub.add_parser("delete"); dl.add_argument("name"); dl.add_argument("--yes", action="store_true",
        help="confirm non-interactively (required when stdin is not a TTY)"); dl.set_defaults(fn=cmd_delete)
    rn = sub.add_parser("rename"); rn.add_argument("old"); rn.add_argument("new"); rn.set_defaults(fn=cmd_rename)
    nw = sub.add_parser("new"); nw.add_argument("name"); nw.add_argument("--seed", action="store_true",
        help="copy the shipped bug-bounty seed nodes into the new graph (default: empty)"); nw.set_defaults(fn=cmd_new)

    a = ap.parse_args()
    try:
        sys.exit(a.fn(a) or 0)
    except ValueError as e:   # bad --graph name etc: clean message, not a traceback
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
