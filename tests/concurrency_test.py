"""Finding 8: parallel writes must not lose each other, and INDEX.md must end up
consistent with the nodes on disk. Without the write lock, regenerate_index races and
INDEX.md can list fewer nodes than exist."""
import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbh-")
env = dict(os.environ, HOME=HOME)
DEF = os.path.join(HOME, ".claude/bug-bounty-knowledge")
os.makedirs(os.path.join(DEF, "nodes"), exist_ok=True)
open(os.path.join(DEF, "INDEX.md"), "w").write("# seed\n")
open(os.path.join(DEF, "JOURNAL.md"), "w").write("# seed\n")

PORT = 8833
BASE = f"http://127.0.0.1:{PORT}"
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web/server.py"), "--kb", DEF,
                        "--port", str(PORT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, env=env)
ok = []
ck = lambda n, c: ok.append((n, bool(c)))
N = 24


def create(i, errs):
    try:
        body = json.dumps({"slug": f"node-{i:02d}", "title": f"N{i}", "type": "tool"}).encode()
        r = urllib.request.Request(BASE + "/api/node", data=body, method="POST")
        r.add_header("Content-Type", "application/json")
        urllib.request.urlopen(r, timeout=20).read()
    except Exception as e:
        errs.append(f"{i}: {e}")


try:
    for _ in range(40):
        try:
            urllib.request.urlopen(BASE + "/api/ping", timeout=1); break
        except Exception:
            time.sleep(0.15)

    errs = []
    ts = [threading.Thread(target=create, args=(i, errs)) for i in range(N)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    dur = time.time() - t0

    ck(f"all {N} parallel creates succeeded", not errs)
    if errs:
        print("    errors:", errs[:3])
    files = sorted(f for f in os.listdir(os.path.join(DEF, "nodes")) if f.endswith(".md"))
    ck(f"all {N} node files on disk", len(files) == N)
    ck("no temp files left behind", not [f for f in os.listdir(os.path.join(DEF, "nodes")) if f.startswith(".tmp-")])

    idx = open(os.path.join(DEF, "INDEX.md")).read()
    listed = sum(1 for i in range(N) if f"[[node-{i:02d}]]" in idx)
    ck(f"INDEX.md lists all {N} nodes (no lost reindex)", listed == N)
    if listed != N:
        print(f"    INDEX listed only {listed}/{N}")

    g = json.load(urllib.request.urlopen(BASE + "/api/graph", timeout=5))
    ck("API agrees with disk", g["count"] == N)
    ck(f"serialised writes still fast ({dur:.1f}s)", dur < 15)

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
        print("SERVER TRACEBACK:\n", out[:1200])
    shutil.rmtree(HOME, ignore_errors=True)
