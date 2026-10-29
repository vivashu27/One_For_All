import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbhome-")
env = dict(os.environ, HOME=HOME)
DEF = os.path.join(HOME, ".claude/bug-bounty-knowledge")
os.makedirs(DEF, exist_ok=True)
shutil.copytree(os.path.join(ROOT, "knowledge-seed"), DEF, dirs_exist_ok=True)
KBPY = os.path.join(ROOT, "web/kb.py")
GR = os.path.join(HOME, ".claude/knowledge-graphs")

def kb(*a):
    r = subprocess.run([sys.executable, KBPY, *a], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr

kb("new", "web3"); kb("new", "scratch")
open(os.path.join(GR, "web3/nodes/reentrancy.md"), "w").write(
    "---\nid: reentrancy\ntitle: Reentrancy\ntype: technique\ntags: []\nvuln_class: []\nrelated: []\n"
    "confidence: high\nreinforced: 1\nuses: 0\nenabled: true\ncreated: 2026-10-29\nupdated: 2026-10-29\n"
    "source: assessment\n---\n\n# Reentrancy\n\n**Summary:** cei ordering.\n")

P = 8812; BASE = f"http://127.0.0.1:{P}"
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web/server.py"), "--kb", DEF, "--port", str(P)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
def req(method, path):
    r = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return resp.status, json.loads(resp.read())

ok = []
ck = lambda n, c: ok.append((n, bool(c)))
try:
    for _ in range(40):
        try: urllib.request.urlopen(BASE + "/api/ping", timeout=1); break
        except Exception: time.sleep(0.15)

    # the UI can now SEE every graph
    s, d = req("GET", "/api/graphs")
    names = [g["name"] for g in d["graphs"]]
    ck("UI lists all graphs", s == 200 and set(names) == {"default", "web3", "scratch"})
    ck("current graph = launch graph", d["current"] == "default")
    ck("default marked not deletable", not [g for g in d["graphs"] if g["name"] == "default"][0]["deletable"])
    ck("web3 marked deletable", [g for g in d["graphs"] if g["name"] == "web3"][0]["deletable"])
    ck("node counts per graph", [g for g in d["graphs"] if g["name"] == "web3"][0]["nodes"] == 1)

    # per-request graph switching (the actual bug the user hit)
    ck("graph=default serves 11 seeds", req("GET", "/api/graph?graph=default")[1]["count"] == 11)
    ck("graph=web3 serves its 1 node", req("GET", "/api/graph?graph=web3")[1]["count"] == 1)
    ck("web3 node readable via ?graph", req("GET", "/api/node/reentrancy?graph=web3")[1]["meta"]["id"] == "reentrancy")
    try:
        req("GET", "/api/node/reentrancy"); ck("default does not leak web3 node", False)
    except urllib.error.HTTPError as e: ck("default does not leak web3 node", e.code == 404)
    try:
        req("GET", "/api/graph?graph=nope"); ck("unknown graph -> 400", False)
    except urllib.error.HTTPError as e: ck("unknown graph -> 400", e.code == 400)

    # DELETE safety rails
    try:
        req("DELETE", "/api/graph?graph=web3"); ck("delete without confirm refused", False)
    except urllib.error.HTTPError as e: ck("delete without confirm refused", e.code == 400)
    try:
        req("DELETE", "/api/graph?graph=web3&confirm=wrong"); ck("wrong confirm refused", False)
    except urllib.error.HTTPError as e: ck("wrong confirm refused", e.code == 400)
    try:
        req("DELETE", "/api/graph?graph=default&confirm=default"); ck("default protected", False)
    except urllib.error.HTTPError as e: ck("default protected (403)", e.code == 403)
    ck("web3 still on disk", os.path.isdir(os.path.join(GR, "web3")))
    s, d = req("DELETE", "/api/graph?graph=web3&confirm=web3")
    ck("correct confirm deletes", s == 200 and d["deleted"] == "web3" and d["nodes_removed"] == 1)
    ck("web3 gone from disk", not os.path.isdir(os.path.join(GR, "web3")))
    ck("default intact after delete", req("GET", "/api/graph?graph=default")[1]["count"] == 11)

    # CLI delete: refuses non-interactively without --yes, works with it
    rc, out, err = kb("delete", "scratch")
    ck("CLI delete needs confirmation", rc == 1 and "without confirmation" in err and os.path.isdir(os.path.join(GR, "scratch")))
    rc, out, err = kb("delete", "default", "--yes")
    ck("CLI refuses default", rc == 1 and "protected" in err)
    rc, out, err = kb("delete", "nope", "--yes")
    ck("CLI unknown graph", rc == 1 and "no such graph" in err)
    rc, out, err = kb("delete", "scratch", "--yes")
    ck("CLI delete --yes works", rc == 0 and "deleted graph 'scratch'" in out and not os.path.isdir(os.path.join(GR, "scratch")))
    ck("default survives CLI deletes", os.path.isdir(os.path.join(DEF, "nodes")))

    allp = True
    for n, c in ok: print(f"  [{'PASS' if c else 'FAIL'}] {n}"); allp = allp and c
    print("ALLPASS" if allp else "SOME-FAILED")
    sys.exit(0 if allp else 1)
finally:
    srv.terminate()
    try: srv.wait(timeout=3)
    except Exception: srv.kill()
    shutil.rmtree(HOME, ignore_errors=True)
