"""/api/layout: per-graph saved node positions (layout.json) for the web UI."""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kblayout-")
env = dict(os.environ, HOME=HOME)
env.pop("BBK_KB", None)
DEF = os.path.join(HOME, ".claude/bug-bounty-knowledge")
shutil.copytree(os.path.join(ROOT, "knowledge-seed"), DEF)
subprocess.run([sys.executable, os.path.join(ROOT, "web/kb.py"), "new", "web3"], env=env, capture_output=True)
PORT = 8794
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web/server.py"), "--kb", DEF, "--port", str(PORT)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def req(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


ok = []
ck = lambda n, c: ok.append((n, bool(c)))
try:
    for _ in range(50):
        try:
            req("GET", "/api/ping"); break
        except Exception:
            time.sleep(0.1)

    s, d = req("GET", "/api/layout")
    ck("no layout yet → empty positions", s == 200 and d == {"positions": {}})

    s, d = req("PUT", "/api/layout", {"positions": {"burp-autorize": [120.5, 40], "__hub__tool": [10, 20.26]}})
    ck("save accepted", s == 200 and d.get("ok") is True)
    pos = {"burp-autorize": [120.5, 40], "__hub__tool": [10, 20.3]}
    s, d = req("GET", "/api/layout")
    ck("saved positions read back (rounded to 0.1)", s == 200 and d["positions"] == pos)
    ck("stored as layout.json beside nodes/", os.path.isfile(os.path.join(DEF, "layout.json")))

    s, d = req("GET", "/api/layout?graph=web3")
    ck("layouts are per graph", s == 200 and d == {"positions": {}})

    for name, bad in [("non-object positions", {"positions": [1, 2]}),
                      ("bad key", {"positions": {"../evil": [1, 2]}}),
                      ("non-numeric coords", {"positions": {"a": ["x", 2]}}),
                      ("wrong arity", {"positions": {"a": [1]}}),
                      ("non-finite coords", {"positions": {"a": [1e400, 2]}})]:
        s, _ = req("PUT", "/api/layout", bad)
        ck(f"rejects {name}", s == 400)
    ck("rejected writes leave the saved layout", req("GET", "/api/layout")[1]["positions"] == pos)

    s, _ = req("PUT", "/api/layout", {"positions": {}}, {"Origin": "https://evil.example"})
    ck("cross-site save blocked", s == 403)

    # saves merge: a second tab that moves one node doesn't wipe what the first tab placed
    req("PUT", "/api/layout", {"positions": {"payloadsallthethings": [7, 8]}})
    got = req("GET", "/api/layout")[1]["positions"]
    ck("save merges into the stored layout", got == {**pos, "payloadsallthethings": [7, 8]})
    req("PUT", "/api/layout", {"positions": {"no-such-node": [1, 1]}})
    ck("positions for nodes that no longer exist are dropped",
       "no-such-node" not in req("GET", "/api/layout")[1]["positions"])
    with open(os.path.join(DEF, "layout.json"), "w") as fh:   # hand-edited file with a bad key
        json.dump({"positions": {"../x": [1, 1], "burp-autorize": [120.5, 40]}}, fh)
    s, _ = req("PUT", "/api/layout", {"positions": {"payloadsallthethings": [7, 8]}})
    ck("a bad key already on disk doesn't block saves (and is dropped)",
       s == 200 and "../x" not in req("GET", "/api/layout")[1]["positions"])

    # node types are free-form frontmatter, so hub keys must accept any type name
    s, _ = req("PUT", "/api/layout", {"positions": {"__hub__XSS class": [3, 4]}})
    ck("hub key for a free-form type is accepted", s == 200 and
       req("GET", "/api/layout")[1]["positions"].get("__hub__XSS class") == [3, 4])

    # JSON export carries the layout, and import restores it into another graph
    s, exp = req("GET", "/api/export?format=json")
    ck("JSON export includes the layout", s == 200 and exp.get("layout", {}).get("burp-autorize") == [120.5, 40])
    s, d = req("POST", "/api/import?graph=web3", exp)
    ck("import accepted", s == 200 and "burp-autorize" in d.get("written", []))
    ck("import restores the layout", req("GET", "/api/layout?graph=web3")[1]["positions"].get("burp-autorize") == [120.5, 40])
    s, _ = req("POST", "/api/import?graph=web3", {"nodes": [], "layout": {"../evil": [1, 2]}})
    ck("import rejects a bad layout", s == 400)

    with open(os.path.join(DEF, "layout.json"), "w") as fh:
        fh.write("{not json")
    s, d = req("GET", "/api/layout")
    ck("corrupt layout.json → empty positions, not a crash", s == 200 and d == {"positions": {}})
finally:
    srv.terminate()
    shutil.rmtree(HOME, ignore_errors=True)

for n, c in ok:
    print(("  [PASS] " if c else "  [FAIL] ") + n)
print("ALLPASS" if all(c for _, c in ok) else "SOME-FAILED")
