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


def node_path(kb, slug):
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid slug: {slug}")
    nd = nodes_dir(kb)
    p = os.path.join(nd, slug + ".md")
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(nd):
        raise ValueError("path escape")
    return p


def load_nodes(kb):
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
        })
    return out


def compact_line(n):
    m = n["meta"]
    pin = " ★" if _truthy(m.get("pin")) else ""
    dis = " (disabled)" if not n["enabled"] else ""
    return (f"{n['priority']:6.2f}  {n['slug']}  [{m.get('type', '?')}]{pin}  "
            f"({m.get('confidence', '?')}·r{_int(m.get('reinforced', 0))}·u{_int(m.get('uses', 0))}) "
            f"— {n['summary']}{dis}")


def compact_obj(n, extra=None):
    m = n["meta"]
    o = {
        "slug": n["slug"], "title": m.get("title", n["slug"]), "type": m.get("type"),
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
    nodes = load_nodes(a.kb)
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
          + (f" (type={a.type})" if a.type else "") + "  [priority  slug  [type]  (conf·reinf·uses) — summary]")
    for n in top:
        print(compact_line(n))
    print("\nLoad full detail for the few you need:  python3 kb.py get <slug> [<slug> ...]")


def cmd_query(a):
    terms = tokenize(a.terms)
    nodes = [n for n in load_nodes(a.kb) if n["enabled"]]
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
    print(f"# Query: {a.terms!r} — {len(top)} hit(s)  [rank(match)  slug  [type]  (conf·reinf·uses) — summary]")
    for final, rel, n in top:
        print(f"{final:6.2f}(m{rel})  {compact_line(n)}")
    slugs = " ".join(n["slug"] for _, _, n in top[:3])
    print(f"\nLoad the top ones:  python3 kb.py get {slugs}")


def _bump_uses(kb, slug, n=1):
    p = node_path(kb, slug)
    with open(p, "r", encoding="utf-8") as fh:
        raw = fh.read()
    meta, _ = parse_frontmatter(raw)
    new = _int(meta.get("uses", 0)) + n
    raw = update_frontmatter(raw, {"uses": str(new)})
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(raw if raw.endswith("\n") else raw + "\n")
    return new


def cmd_get(a):
    missing = []
    for slug in a.slugs:
        try:
            p = node_path(a.kb, slug)
        except ValueError as e:
            missing.append(f"{slug} ({e})")
            continue
        if not os.path.exists(p):
            missing.append(slug)
            continue
        with open(p, "r", encoding="utf-8") as fh:
            raw = fh.read()
        meta, _ = parse_frontmatter(raw)
        used = ""
        if not a.peek:
            try:
                used = f"  (uses→{_bump_uses(a.kb, slug)})"
            except Exception:
                used = ""
        flag = "" if enabled(meta) else "  [DISABLED — normally skipped on induce]"
        print(f"\n===== {slug}{flag}{used} =====")
        print(raw.rstrip())
    if missing:
        print(f"\n# not found: {', '.join(missing)}", file=sys.stderr)


def cmd_use(a):
    try:
        new = _bump_uses(a.kb, a.slug, a.n)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{a.slug}: uses → {new}")


def cmd_pin(a):
    try:
        p = node_path(a.kb, a.slug)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not os.path.exists(p):
        print(f"error: not found: {a.slug}", file=sys.stderr)
        return 1
    with open(p, "r", encoding="utf-8") as fh:
        raw = fh.read()
    raw = update_frontmatter(raw, {"pin": "false" if a.off else "true"})
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(raw if raw.endswith("\n") else raw + "\n")
    print(f"{a.slug}: {'unpinned' if a.off else 'pinned ★'}")


def cmd_stats(a):
    nodes = load_nodes(a.kb)
    en = [n for n in nodes if n["enabled"]]
    by_type = {}
    for n in en:
        by_type[n["meta"].get("type", "?")] = by_type.get(n["meta"].get("type", "?"), 0) + 1
    print(f"nodes: {len(nodes)} total · {len(en)} enabled · {len(nodes) - len(en)} disabled")
    print("by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    en.sort(key=lambda n: (-n["priority"], n["slug"]))
    print("top of the priority graph:")
    for n in en[:5]:
        print("  " + compact_line(n))


def main():
    ap = argparse.ArgumentParser(description="Priority-ranked retrieval over the bug-bounty knowledge graph")
    ap.add_argument("--kb", default=os.path.expanduser("~/.claude/bug-bounty-knowledge"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest"); m.add_argument("--top", type=int, default=0); m.add_argument("--type"); m.add_argument("--json", action="store_true"); m.add_argument("--all", action="store_true"); m.set_defaults(fn=cmd_manifest)
    q = sub.add_parser("query"); q.add_argument("terms"); q.add_argument("--top", type=int, default=8); q.add_argument("--type"); q.add_argument("--json", action="store_true"); q.add_argument("--all", action="store_true"); q.set_defaults(fn=cmd_query)
    g = sub.add_parser("get"); g.add_argument("slugs", nargs="+"); g.add_argument("--peek", action="store_true"); g.set_defaults(fn=cmd_get)
    u = sub.add_parser("use"); u.add_argument("slug"); u.add_argument("--n", type=int, default=1); u.set_defaults(fn=cmd_use)
    p = sub.add_parser("pin"); p.add_argument("slug"); p.add_argument("--off", action="store_true"); p.set_defaults(fn=cmd_pin)
    s = sub.add_parser("stats"); s.set_defaults(fn=cmd_stats)

    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
