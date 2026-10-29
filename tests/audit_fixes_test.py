"""Covers the fixes for the audit findings: CSRF origin check, import hardening,
per-graph export naming, INDEX heading, body-size cap, graph listing, JSON export shape."""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbh-")
env = dict(os.environ, HOME=HOME)
DEF = os.path.join(HOME, ".claude/bug-bounty-knowledge")
os.makedirs(DEF, exist_ok=True)
shutil.copytree(os.path.join(ROOT, "knowledge-seed"), DEF, dirs_exist_ok=True)
GR = os.path.join(HOME, ".claude/knowledge-graphs")
subprocess.run([sys.executable, os.path.join(ROOT, "web/kb.py"), "new", "web3"], env=env, capture_output=True)

PORT = 8831
BASE = f"http://127.0.0.1:{PORT}"
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web/server.py"), "--kb", DEF,
                        "--port", str(PORT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, env=env)
ok = []
ck = lambda n, c: ok.append((n, bool(c)))


def req(method, path, body=None, headers=None, ctype="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=5) as resp:
        raw = resp.read()
        ct = resp.headers.get("content-type", "")
        return resp.status, (json.loads(raw) if "json" in ct else raw), resp.headers


def node_raw(graph, slug):
    d = DEF if graph == "default" else os.path.join(GR, graph)
    return open(os.path.join(d, "nodes", slug + ".md")).read()


try:
    for _ in range(40):
        try:
            urllib.request.urlopen(BASE + "/api/ping", timeout=1); break
        except Exception:
            time.sleep(0.15)

    # ---- 1: CSRF. A cross-site write must be refused; same-origin and no-origin must pass.
    before = node_raw("default", "idor-id-enumeration")
    evil = {"nodes": [{"slug": "idor-id-enumeration", "raw": "---\nid: idor-id-enumeration\n---\n\nPWNED\n"}]}
    try:
        req("POST", "/api/import", evil, {"Origin": "https://evil.example"}, ctype="text/plain")
        ck("cross-site POST blocked", False)
    except urllib.error.HTTPError as e:
        ck("cross-site POST blocked (403)", e.code == 403)
    ck("node untouched by cross-site attempt", node_raw("default", "idor-id-enumeration") == before)
    for ep, body in [("/api/node", {"slug": "x-csrf", "title": "x", "type": "tool"}),
                     ("/api/reindex", {}), ("/api/graph/new?to=csrfgraph", {}),
                     ("/api/node/idor-id-enumeration/enabled", {"enabled": False})]:
        try:
            req("POST", ep, body, {"Origin": "http://attacker.test"})
            ck(f"cross-site {ep} blocked", False)
        except urllib.error.HTTPError as e:
            ck(f"cross-site {ep} blocked", e.code == 403)
    ck("attacker's graph not created", not os.path.isdir(os.path.join(GR, "csrfgraph")))
    s, d, _ = req("POST", "/api/reindex", {}, {"Origin": f"http://127.0.0.1:{PORT}"})
    ck("same-origin POST allowed", s == 200)
    s, d, _ = req("POST", "/api/reindex", {})          # no Origin: CLI / agent
    ck("no-Origin POST allowed (CLI/agents)", s == 200)
    try:
        req("DELETE", "/api/graph?graph=web3&confirm=web3", None, {"Origin": "http://evil.test"})
        ck("cross-site DELETE blocked", False)
    except urllib.error.HTTPError as e:
        ck("cross-site DELETE blocked", e.code == 403)
    ck("web3 survived cross-site delete", os.path.isdir(os.path.join(GR, "web3")))

    # ---- 2: malformed import must answer, not crash
    s, d, _ = req("POST", "/api/import", {"nodes": ["oops", 42, None]})
    ck("bad import entries skipped, not crashed", s == 200 and d["written"] == [] and len(d["skipped"]) == 3)
    try:
        req("POST", "/api/import", {"nodes": "notalist"}); ck("non-list nodes rejected", False)
    except urllib.error.HTTPError as e:
        ck("non-list nodes rejected (400)", e.code == 400)

    # ---- 3 + 11: exports are named per graph; JSON holds only what import restores
    s, raw, h = req("GET", "/api/export?format=zip&graph=web3")
    ck("zip filename carries graph name", "web3-" in h.get("Content-Disposition", ""))
    import io, zipfile
    ck("zip folder carries graph name", all(n.startswith("web3/") for n in zipfile.ZipFile(io.BytesIO(raw)).namelist()))
    s, j, h = req("GET", "/api/export?format=json&graph=default")
    ck("json filename carries graph name", "default-" in h.get("Content-Disposition", ""))
    ck("json export records its graph", j.get("graph") == "default")
    ck("json export drops unrestorable fields", "index" not in j and "journal" not in j)

    # ---- 4: the INDEX heading names its graph
    req("POST", "/api/reindex?graph=web3")
    ck("web3 INDEX names web3", "# Knowledge Graph: web3 — Index" in open(os.path.join(GR, "web3/INDEX.md")).read())
    req("POST", "/api/reindex?graph=default")
    ck("default INDEX names default", "# Knowledge Graph: default — Index" in open(os.path.join(DEF, "INDEX.md")).read())

    # ---- 7: an oversized body is refused without being read
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    sock.sendall(b"POST /api/import HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                 b"Content-Type: application/json\r\nContent-Length: 99999999\r\n\r\n{}")
    resp = sock.recv(64).decode(errors="replace"); sock.close()
    ck("oversized body refused (413)", "413" in resp)

    # ---- 9: listing graphs still reports correct counts (now without parsing)
    s, d, _ = req("GET", "/api/graphs")
    counts = {g["name"]: g["nodes"] for g in d["graphs"]}
    ck("graph counts correct", counts.get("default") == 11 and counts.get("web3") == 0)

    # ---- 10: the dead endpoint is gone
    try:
        req("GET", "/api/index"); ck("/api/index removed", False)
    except urllib.error.HTTPError as e:
        ck("/api/index removed (404)", e.code == 404)

    allp = True
    for n, c in ok:
        print(f"  [{'PASS' if c else 'FAIL'}] {n}"); allp = allp and c
    print("ALLPASS" if allp else "SOME-FAILED")
    sys.exit(0 if allp else 1)
finally:
    srv.terminate()
    try:
        out = srv.communicate(timeout=3)[0]
    except Exception:
        srv.kill(); out = ""
    if "Traceback" in (out or ""):
        print("SERVER TRACEBACK:\n", out[:1500])
    shutil.rmtree(HOME, ignore_errors=True)
