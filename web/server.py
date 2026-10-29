#!/usr/bin/env python3
"""
Local web interface for the Bug Bounty Knowledge graph.

Serves a self-contained (offline, no external deps) UI to view, edit, and share
the knowledge base stored as markdown files under a KB directory
(default: ~/.claude/bug-bounty-knowledge/).

Usage:
    python3 server.py [--kb DIR] [--port 8787] [--host 127.0.0.1] [--token TOKEN]

Safety:
    * Binds to 127.0.0.1 (localhost only) by default.
    * --host 0.0.0.0 exposes the UI on your LAN for sharing — a warning is printed,
      and you should pair it with --token so only people with the link can read/write.
    * Node slugs are strictly validated; all file access is confined to KB/nodes.
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# type -> (INDEX heading, order). Mirrors the knowledge-graph skill schema.
TYPE_ORDER = ["technique", "tool", "reference", "lesson", "workflow", "reporting", "vuln-class"]
TYPE_HEADING = {
    "technique": "Techniques",
    "tool": "Tools",
    "reference": "References",
    "lesson": "Lessons",
    "workflow": "Workflows",
    "reporting": "Reporting",
    "vuln-class": "Vuln Classes (hubs)",
}

# Set by main()
KB_DIR = ""        # graph selected at launch; the UI can switch per request
WRITE_LOCK = threading.RLock()   # serialises read-modify-write so edits cannot be lost
# shortcut: this lock is per-process only, so a kb.py run firing at the same instant as a
# web edit can still last-writer-win on one counter; upgrade to an on-disk lock file if the
# CLI and the web UI end up being used together routinely.
import kb as kblib   # always beside this file; also the single source of the parser
from kb import parse_frontmatter, extract_summary, update_frontmatter
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TOKEN = ""


def today():
    return datetime.date.today().isoformat()


# --------------------------------------------------------------------------- #
# Frontmatter (minimal YAML subset: scalars, ints, bools, inline [lists])     #
# --------------------------------------------------------------------------- #
def nodes_dir(kb):
    return os.path.join(kb, "nodes")


def graph_map():
    """name -> directory for every graph this server may address."""
    m = dict(kblib.all_graphs())
    if KB_DIR and os.path.isdir(KB_DIR) and os.path.abspath(KB_DIR) not in [os.path.abspath(d) for d in m.values()]:
        m[os.path.basename(KB_DIR.rstrip("/")) or "kb"] = KB_DIR
    return m


def current_graph():
    for n, d in graph_map().items():
        if os.path.abspath(d) == os.path.abspath(KB_DIR):
            return n
    return "default"


def node_path(kb, slug):
    if not SLUG_RE.match(slug or ""):
        raise ValueError("invalid slug")
    nd = nodes_dir(kb)
    p = os.path.join(nd, slug + ".md")
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(nd):
        raise ValueError("path escape")
    return p


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def write_text(path, text):
    """Atomic: write a temp file in the same dir, then replace. No truncated files."""
    if not text.endswith("\n"):
        text += "\n"
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def count_nodes(kb):
    """Just how many nodes, without parsing any of them."""
    nd = nodes_dir(kb)
    if not os.path.isdir(nd):
        return 0
    return sum(1 for f in os.listdir(nd) if f.endswith(".md"))


def list_nodes(kb):
    out = []
    nd = nodes_dir(kb)
    if not os.path.isdir(nd):
        return out
    for name in sorted(os.listdir(nd)):
        if not name.endswith(".md"):
            continue
        slug = name[:-3]
        raw = read_text(os.path.join(nd, name))
        if raw is None:
            continue
        meta, body = parse_frontmatter(raw)
        out.append({"slug": slug, "meta": meta, "body": body, "raw": raw,
                    "summary": extract_summary(body)})
    return out


def build_graph(kb):
    nodes = list_nodes(kb)
    ids = {n["slug"] for n in nodes}
    out_nodes = []
    for n in nodes:
        m = n["meta"]
        try:
            reinforced = int(m.get("reinforced", 0) or 0)
        except (ValueError, TypeError):
            reinforced = 0
        en = m.get("enabled", True)  # only an explicit false disables; missing = enabled
        enabled = not (en is False or (isinstance(en, str) and en.strip().lower() == "false"))
        out_nodes.append({
            "id": n["slug"],
            "title": m.get("title", n["slug"]),
            "type": m.get("type", "technique"),
            "tags": m.get("tags", []) or [],
            "vuln_class": m.get("vuln_class", []) or [],
            "confidence": m.get("confidence", "low"),
            "reinforced": reinforced,
            "related": [r for r in (m.get("related", []) or []) if r],
            "summary": n["summary"],
            "enabled": enabled,
            "created": str(m.get("created", "")),
            "updated": str(m.get("updated", "")),
        })
    seen = set()
    edges = []
    for node in out_nodes:
        for tgt in node["related"]:
            if tgt in ids and tgt != node["id"]:
                key = tuple(sorted((node["id"], tgt)))
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": node["id"], "target": tgt})
    return {"nodes": out_nodes, "edges": edges, "count": len(out_nodes)}


def scaffold(slug, title, ntype, tags, summary):
    tags = tags or []
    taglist = "[" + ", ".join(tags) + "]"
    t = today()
    return (
        "---\n"
        f"id: {slug}\n"
        f"title: {title}\n"
        f"type: {ntype}\n"
        f"tags: {taglist}\n"
        "vuln_class: []\n"
        "related: []\n"
        "confidence: low\n"
        "reinforced: 0\n"
        "uses: 0\n"
        "enabled: true\n"
        f"created: {t}\n"
        f"updated: {t}\n"
        "source: assessment\n"
        "---\n\n"
        f"# {title}\n\n"
        f"**Summary:** {summary or 'TODO — one or two sentences.'}\n\n"
        "## Notes\n\n"
        "## Related\n"
    )


def graph_name_for(kb):
    for n, d in graph_map().items():
        if os.path.abspath(d) == os.path.abspath(kb):
            return n
    return os.path.basename(kb.rstrip("/")) or "default"


def regenerate_index(kb):
    """Rewrite INDEX.md from the current nodes, matching the skill's format."""
    graph = build_graph(kb)
    nodes = graph["nodes"]
    by_type = {t: [] for t in TYPE_ORDER}
    for n in nodes:
        by_type.setdefault(n["type"], []).append(n)
    lines = [f"# Knowledge Graph: {graph_name_for(kb)} — Index", ""]
    lines.append(f"_Last updated: {today()} · {len(nodes)} nodes_")
    lines.append("")
    lines.append("This is the hub of the compounding knowledge graph. Each entry links to a node in")
    lines.append("`nodes/`. Grow it with `/build-knowledge`; load it with `/induce-knowledge`.")
    lines.append("")
    # Standard types first, then any non-standard type so no node is ever dropped.
    extra_types = sorted(k for k in by_type if k not in TYPE_ORDER)
    for t in TYPE_ORDER + extra_types:
        group = sorted(by_type.get(t, []), key=lambda x: x["title"].lower())
        if not group:
            continue
        lines.append(f"## {TYPE_HEADING.get(t, t.replace('-', ' ').title())}")
        for n in group:
            summ = n["summary"] or n["title"]
            tail = "" if n.get("enabled", True) else " _(disabled)_"
            lines.append(f"- [[{n['id']}]] — {summ} ({n['confidence']} · {n['reinforced']}){tail}")
        lines.append("")
    # Link map
    lines.append("## Link map")
    ids = {x["id"] for x in nodes}
    for n in sorted(nodes, key=lambda x: x["id"]):
        rels = [r for r in n["related"] if r in ids]
        if rels:
            lines.append(f"- {n['id']} → {', '.join(rels)}")
    lines.append("")
    lines.append("_Format per entry: `[[slug]] — summary (confidence · reinforced-count)`._")
    write_text(os.path.join(kb, "INDEX.md"), "\n".join(lines))


def export_zip(kb, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ("INDEX.md", "JOURNAL.md"):
            txt = read_text(os.path.join(kb, fname))
            if txt is not None:
                zf.writestr(f"{name}/{fname}", txt)
        for n in list_nodes(kb):
            zf.writestr(f"{name}/nodes/{n['slug']}.md", n["raw"])
    return buf.getvalue()


def export_json(kb, name):
    # only fields that import can restore; use the .zip for a full backup (INDEX + JOURNAL)
    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "graph": name,
        "nodes": [{"slug": n["slug"], "raw": n["raw"]} for n in list_nodes(kb)],
    }


# --------------------------------------------------------------------------- #
# HTTP handler                                                                #
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "BBKnowledgeWeb/1.0"

    def log_message(self, fmt, *args):  # quieter logs; never log the access token
        msg = re.sub(r"(?i)(token=)[^&\s]+", r"\1REDACTED", fmt % args)
        sys.stderr.write("%s - %s\n" % (self.address_string(), msg))

    # -- helpers --
    def _kb(self, query):
        """Graph dir for this request. Raises KeyError on an unknown graph name."""
        name = (query.get("graph", [""])[0] or "").strip()
        if not name:
            return KB_DIR
        gm = graph_map()
        if name not in gm:
            raise KeyError(name)
        return gm[name]

    def _origin_ok(self):
        """Block cross-site writes (CSRF). Browsers always send Origin on a POST; CLI
        tools and agents send none, so they are unaffected."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == (self.headers.get("Host") or "")

    def _token_ok(self, query):
        if not TOKEN:
            return True
        supplied = self.headers.get("X-KB-Token") or (query.get("token", [""])[0])
        return supplied == TOKEN

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data, ctype, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    MAX_BODY = 8 * 1024 * 1024

    def _body_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > self.MAX_BODY:
            raise ValueError("request body too large")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _static(self, rel):
        rel = rel.lstrip("/")
        if rel in ("", "index.html"):
            rel = "index.html"
        elif rel.startswith("static/"):
            rel = rel[len("static/"):]
        safe = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if os.path.commonpath([safe, STATIC_DIR]) != STATIC_DIR or not os.path.isfile(safe):
            self._json({"error": "not found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(os.path.splitext(safe)[1], "application/octet-stream")
        with open(safe, "rb") as fh:
            self._bytes(fh.read(), ctype)

    # -- verbs --
    def do_GET(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if path.startswith("/api/"):
            if not self._token_ok(query):
                return self._json({"error": "unauthorized"}, 401)
            try:
                kb = self._kb(query)
            except KeyError as e:
                return self._json({"error": f"unknown graph: {e.args[0]}"}, 400)
            if path == "/api/ping":
                return self._json({"ok": True, "kb": kb, "graph": current_graph()})
            if path == "/api/graphs":
                gm, cur = graph_map(), current_graph()
                rows = [{"name": n, "dir": d, "nodes": count_nodes(d),
                         "current": n == cur, "deletable": n != "default"}
                        for n, d in sorted(gm.items())]
                return self._json({"graphs": rows, "current": cur})
            if path == "/api/graph":
                return self._json(build_graph(kb))
            if path == "/api/journal":
                return self._json({"text": read_text(os.path.join(kb, "JOURNAL.md")) or ""})
            if path == "/api/export":
                fmt = query.get("format", ["zip"])[0]
                gname = graph_name_for(kb)
                if fmt == "json":
                    data = json.dumps(export_json(kb, gname), indent=2).encode("utf-8")
                    return self._bytes(data, "application/json", filename=f"{gname}-{today()}.json")
                return self._bytes(export_zip(kb, gname), "application/zip", filename=f"{gname}-{today()}.zip")
            m = re.match(r"^/api/node/([^/]+)$", path)
            if m:
                try:
                    p = node_path(kb, m.group(1))
                except ValueError:
                    return self._json({"error": "invalid slug"}, 400)
                raw = read_text(p)
                if raw is None:
                    return self._json({"error": "not found"}, 404)
                meta, body = parse_frontmatter(raw)
                return self._json({"slug": m.group(1), "meta": meta, "body": body, "raw": raw})
            return self._json({"error": "unknown endpoint"}, 404)
        # static
        return self._static(path)

    def do_POST(self):
        if not self._origin_ok():
            return self._json({"error": "cross-site request blocked"}, 403)
        try:
            with WRITE_LOCK:
                return self._post_locked()
        except ValueError as e:
            return self._json({"error": str(e)}, 413 if "too large" in str(e) else 400)

    def _post_locked(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        try:
            kb = self._kb(query)
        except KeyError as e:
            return self._json({"error": f"unknown graph: {e.args[0]}"}, 400)
        if path == "/api/node":
            d = self._body_json()
            slug = (d.get("slug") or "").strip().lower()
            if not SLUG_RE.match(slug):
                return self._json({"error": "slug must be lowercase kebab-case [a-z0-9-]"}, 400)
            try:
                p = node_path(kb, slug)
            except ValueError:
                return self._json({"error": "invalid slug"}, 400)
            if os.path.exists(p):
                return self._json({"error": "node already exists"}, 409)
            ntype = d.get("type", "technique")
            if ntype not in TYPE_ORDER:
                return self._json({"error": f"type must be one of {TYPE_ORDER}"}, 400)
            tags = d.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            write_text(p, scaffold(slug, d.get("title") or slug, ntype, tags, d.get("summary", "")))
            regenerate_index(kb)
            return self._json({"ok": True, "slug": slug})
        m = re.match(r"^/api/node/([^/]+)/enabled$", path)
        if m:
            try:
                p = node_path(kb, m.group(1))
            except ValueError:
                return self._json({"error": "invalid slug"}, 400)
            raw = read_text(p)
            if raw is None:
                return self._json({"error": "not found"}, 404)
            enabled = bool(self._body_json().get("enabled", True))
            raw = update_frontmatter(raw, {"enabled": "true" if enabled else "false",
                                           "updated": today()})
            write_text(p, raw)
            regenerate_index(kb)
            return self._json({"ok": True, "slug": m.group(1), "enabled": enabled})
        if path == "/api/graph/new":
            name = (query.get("to", [""])[0] or "").strip()
            seed = (query.get("seed", [""])[0] or "").strip() in ("1", "true", "yes")
            if not name:
                return self._json({"error": "need ?to=<name>"}, 400)
            ok, msg, _p = kblib.create_graph(name, seed)
            if not ok:
                return self._json({"error": msg}, 400)
            return self._json({"ok": True, "created": name, "message": msg})
        if path == "/api/graph/rename":
            old = (query.get("graph", [""])[0] or "").strip()
            new = (query.get("to", [""])[0] or "").strip()
            if not old or not new:
                return self._json({"error": "need ?graph=<old>&to=<new>"}, 400)
            ok, msg = kblib.rename_graph(old, new)
            if not ok:
                return self._json({"error": msg}, 400)
            return self._json({"ok": True, "renamed": old, "to": new, "message": msg})
        if path == "/api/reindex":
            regenerate_index(kb)
            return self._json({"ok": True})
        if path == "/api/import":
            d = self._body_json()
            nodes = d.get("nodes", [])
            if not isinstance(nodes, list):
                return self._json({"error": "'nodes' must be a list"}, 400)
            written, skipped = [], []
            for item in nodes:
                if not isinstance(item, dict):
                    skipped.append("(not an object)")
                    continue
                slug = (item.get("slug") or "").strip().lower()
                raw = item.get("raw", "")
                if not SLUG_RE.match(slug) or not raw.strip().startswith("---"):
                    skipped.append(slug or "(blank)")
                    continue
                try:
                    write_text(node_path(kb, slug), raw)
                    written.append(slug)
                except ValueError:
                    skipped.append(slug)
            regenerate_index(kb)
            return self._json({"ok": True, "written": written, "skipped": skipped})
        return self._json({"error": "unknown endpoint"}, 404)

    def do_PUT(self):
        if not self._origin_ok():
            return self._json({"error": "cross-site request blocked"}, 403)
        try:
            with WRITE_LOCK:
                return self._put_locked()
        except ValueError as e:
            return self._json({"error": str(e)}, 413 if "too large" in str(e) else 400)

    def _put_locked(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        try:
            kb = self._kb(query)
        except KeyError as e:
            return self._json({"error": f"unknown graph: {e.args[0]}"}, 400)
        m = re.match(r"^/api/node/([^/]+)$", path)
        if not m:
            return self._json({"error": "unknown endpoint"}, 404)
        slug = m.group(1)
        try:
            p = node_path(kb, slug)
        except ValueError:
            return self._json({"error": "invalid slug"}, 400)
        d = self._body_json()
        raw = d.get("raw", "")
        if not raw.strip().startswith("---"):
            return self._json({"error": "content must start with a --- frontmatter block"}, 400)
        meta, _ = parse_frontmatter(raw)
        if meta.get("id") and meta.get("id") != slug:
            return self._json({"error": f"frontmatter id '{meta.get('id')}' must equal slug '{slug}'"}, 400)
        # bump updated: to today — frontmatter-scoped, inserts the key if missing
        raw = update_frontmatter(raw, {"updated": today()})
        write_text(p, raw)
        regenerate_index(kb)
        return self._json({"ok": True, "slug": slug})

    def do_DELETE(self):
        if not self._origin_ok():
            return self._json({"error": "cross-site request blocked"}, 403)
        try:
            with WRITE_LOCK:
                return self._delete_locked()
        except ValueError as e:
            return self._json({"error": str(e)}, 413 if "too large" in str(e) else 400)

    def _delete_locked(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        try:
            kb = self._kb(query)
        except KeyError as e:
            return self._json({"error": f"unknown graph: {e.args[0]}"}, 400)
        if path == "/api/graph":
            name = (query.get("graph", [""])[0] or "").strip()
            confirm = (query.get("confirm", [""])[0] or "").strip()
            gm = graph_map()
            if not name or name not in gm:
                return self._json({"error": "unknown graph"}, 400)
            if name == "default":
                return self._json({"error": "the 'default' graph is protected and cannot be deleted"}, 403)
            if confirm != name:
                return self._json({"error": "confirmation required: echo the graph name in ?confirm="}, 400)
            d = gm[name]
            # only ever remove a directory that really sits under the graphs root
            root = os.path.realpath(kblib.GRAPHS_ROOT)
            rp = os.path.realpath(d)
            if os.path.dirname(rp) != root:
                return self._json({"error": "refusing to delete a graph outside the graphs root"}, 403)
            n_nodes = len(list_nodes(d))
            shutil.rmtree(rp)
            return self._json({"ok": True, "deleted": name, "nodes_removed": n_nodes})
        m = re.match(r"^/api/node/([^/]+)$", path)
        if not m:
            return self._json({"error": "unknown endpoint"}, 404)
        try:
            p = node_path(kb, m.group(1))
        except ValueError:
            return self._json({"error": "invalid slug"}, 400)
        if not os.path.exists(p):
            return self._json({"error": "not found"}, 404)
        os.remove(p)
        regenerate_index(kb)
        return self._json({"ok": True})


def main():
    global KB_DIR, TOKEN
    ap = argparse.ArgumentParser(description="Bug Bounty Knowledge web interface")
    ap.add_argument("--kb", default=os.path.expanduser("~/.claude/bug-bounty-knowledge"),
                    help="knowledge base directory")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default localhost)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--token", default="", help="require this token on API requests (recommended with --host)")
    args = ap.parse_args()

    KB_DIR = os.path.abspath(os.path.expanduser(args.kb))

    TOKEN = args.token
    os.makedirs(nodes_dir(KB_DIR), exist_ok=True)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    if TOKEN:
        url += f"?token={TOKEN}"
    print(f"Bug Bounty Knowledge web UI")
    print(f"  KB:   {KB_DIR}")
    print(f"  URL:  {url}")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"  WARNING: bound to {args.host} — reachable from your network. "
              f"{'Token auth is ON.' if TOKEN else 'No token set — anyone on the network can read/write. Use --token.'}")
    print("  Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
