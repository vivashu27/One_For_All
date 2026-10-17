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
import sys
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
KB_DIR = ""
NODES_DIR = ""
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TOKEN = ""


def today():
    return datetime.date.today().isoformat()


# --------------------------------------------------------------------------- #
# Frontmatter (minimal YAML subset: scalars, ints, bools, inline [lists])     #
# --------------------------------------------------------------------------- #
def parse_value(val):
    val = val.strip()
    if val == "":
        return ""
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.match(r"^-?\d+$", val):
        return int(val)
    return val.strip("\"'")


def parse_frontmatter(text):
    """Return (meta_dict, body_str)."""
    meta = {}
    body = text
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


# --------------------------------------------------------------------------- #
# KB access                                                                   #
# --------------------------------------------------------------------------- #
def node_path(slug):
    if not SLUG_RE.match(slug or ""):
        raise ValueError("invalid slug")
    p = os.path.join(NODES_DIR, slug + ".md")
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(NODES_DIR):
        raise ValueError("path escape")
    return p


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def write_text(path, text):
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def list_nodes():
    out = []
    if not os.path.isdir(NODES_DIR):
        return out
    for name in sorted(os.listdir(NODES_DIR)):
        if not name.endswith(".md"):
            continue
        slug = name[:-3]
        raw = read_text(os.path.join(NODES_DIR, name))
        if raw is None:
            continue
        meta, body = parse_frontmatter(raw)
        out.append({"slug": slug, "meta": meta, "body": body, "raw": raw,
                    "summary": extract_summary(body)})
    return out


def build_graph():
    nodes = list_nodes()
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


def update_frontmatter(raw, updates):
    """Set/insert frontmatter keys losslessly. `updates`: {key: serialized_str}."""
    m = re.match(r"^(---\s*\n)(.*?\n)(---\s*\n?)(.*)$", raw, re.S)
    if not m:
        return raw  # no frontmatter block; leave untouched
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


def regenerate_index():
    """Rewrite INDEX.md from the current nodes, matching the skill's format."""
    graph = build_graph()
    nodes = graph["nodes"]
    by_type = {t: [] for t in TYPE_ORDER}
    for n in nodes:
        by_type.setdefault(n["type"], []).append(n)
    lines = ["# Bug Bounty Knowledge Graph — Index", ""]
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
    write_text(os.path.join(KB_DIR, "INDEX.md"), "\n".join(lines))


def export_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ("INDEX.md", "JOURNAL.md"):
            txt = read_text(os.path.join(KB_DIR, fname))
            if txt is not None:
                zf.writestr(f"bug-bounty-knowledge/{fname}", txt)
        for n in list_nodes():
            zf.writestr(f"bug-bounty-knowledge/nodes/{n['slug']}.md", n["raw"])
    return buf.getvalue()


def export_json():
    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "index": read_text(os.path.join(KB_DIR, "INDEX.md")) or "",
        "journal": read_text(os.path.join(KB_DIR, "JOURNAL.md")) or "",
        "nodes": [{"slug": n["slug"], "raw": n["raw"]} for n in list_nodes()],
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

    def _body_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
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
            if path == "/api/ping":
                return self._json({"ok": True, "kb": KB_DIR})
            if path == "/api/graph":
                return self._json(build_graph())
            if path == "/api/journal":
                return self._json({"text": read_text(os.path.join(KB_DIR, "JOURNAL.md")) or ""})
            if path == "/api/index":
                return self._json({"text": read_text(os.path.join(KB_DIR, "INDEX.md")) or ""})
            if path == "/api/export":
                fmt = query.get("format", ["zip"])[0]
                if fmt == "json":
                    data = json.dumps(export_json(), indent=2).encode("utf-8")
                    return self._bytes(data, "application/json", filename=f"bug-bounty-knowledge-{today()}.json")
                return self._bytes(export_zip(), "application/zip", filename=f"bug-bounty-knowledge-{today()}.zip")
            m = re.match(r"^/api/node/([^/]+)$", path)
            if m:
                try:
                    p = node_path(m.group(1))
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
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        if path == "/api/node":
            d = self._body_json()
            slug = (d.get("slug") or "").strip().lower()
            if not SLUG_RE.match(slug):
                return self._json({"error": "slug must be lowercase kebab-case [a-z0-9-]"}, 400)
            try:
                p = node_path(slug)
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
            regenerate_index()
            return self._json({"ok": True, "slug": slug})
        m = re.match(r"^/api/node/([^/]+)/enabled$", path)
        if m:
            try:
                p = node_path(m.group(1))
            except ValueError:
                return self._json({"error": "invalid slug"}, 400)
            raw = read_text(p)
            if raw is None:
                return self._json({"error": "not found"}, 404)
            enabled = bool(self._body_json().get("enabled", True))
            raw = update_frontmatter(raw, {"enabled": "true" if enabled else "false",
                                           "updated": today()})
            write_text(p, raw)
            regenerate_index()
            return self._json({"ok": True, "slug": m.group(1), "enabled": enabled})
        if path == "/api/reindex":
            regenerate_index()
            return self._json({"ok": True})
        if path == "/api/import":
            d = self._body_json()
            nodes = d.get("nodes", [])
            written, skipped = [], []
            for item in nodes:
                slug = (item.get("slug") or "").strip().lower()
                raw = item.get("raw", "")
                if not SLUG_RE.match(slug) or not raw.strip().startswith("---"):
                    skipped.append(slug or "(blank)")
                    continue
                try:
                    write_text(node_path(slug), raw)
                    written.append(slug)
                except ValueError:
                    skipped.append(slug)
            regenerate_index()
            return self._json({"ok": True, "written": written, "skipped": skipped})
        return self._json({"error": "unknown endpoint"}, 404)

    def do_PUT(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        m = re.match(r"^/api/node/([^/]+)$", path)
        if not m:
            return self._json({"error": "unknown endpoint"}, 404)
        slug = m.group(1)
        try:
            p = node_path(slug)
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
        regenerate_index()
        return self._json({"ok": True, "slug": slug})

    def do_DELETE(self):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        if not self._token_ok(query):
            return self._json({"error": "unauthorized"}, 401)
        m = re.match(r"^/api/node/([^/]+)$", path)
        if not m:
            return self._json({"error": "unknown endpoint"}, 404)
        try:
            p = node_path(m.group(1))
        except ValueError:
            return self._json({"error": "invalid slug"}, 400)
        if not os.path.exists(p):
            return self._json({"error": "not found"}, 404)
        os.remove(p)
        regenerate_index()
        return self._json({"ok": True})


def main():
    global KB_DIR, NODES_DIR, TOKEN
    ap = argparse.ArgumentParser(description="Bug Bounty Knowledge web interface")
    ap.add_argument("--kb", default=os.path.expanduser("~/.claude/bug-bounty-knowledge"),
                    help="knowledge base directory")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default localhost)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--token", default="", help="require this token on API requests (recommended with --host)")
    args = ap.parse_args()

    KB_DIR = os.path.abspath(os.path.expanduser(args.kb))
    NODES_DIR = os.path.join(KB_DIR, "nodes")
    TOKEN = args.token
    os.makedirs(NODES_DIR, exist_ok=True)

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
