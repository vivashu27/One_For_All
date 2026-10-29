import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KBPY = os.path.join(ROOT, "web/kb.py")
# Sandbox HOME so we never touch the real graphs
HOME = tempfile.mkdtemp(prefix="kbhome-")
env = dict(os.environ, HOME=HOME)
DEF = os.path.join(HOME, ".claude/bug-bounty-knowledge")
os.makedirs(DEF, exist_ok=True)
shutil.copytree(os.path.join(ROOT, "knowledge-seed"), DEF, dirs_exist_ok=True)

def run(*args):
    r = subprocess.run([sys.executable, KBPY, *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr

def nodefile(graph, slug):
    p = DEF if graph == "default" else os.path.join(HOME, ".claude/knowledge-graphs", graph)
    return open(os.path.join(p, "nodes", slug + ".md")).read()

ok = []
ck = lambda n, c: ok.append((n, bool(c)))

# default graph still works with no flags (back-compat)
rc, out, _ = run("manifest", "--top", "3")
ck("default graph works with no flags", rc == 0 and "idor-id-enumeration" in out and "graphs: default" in out)

# create a new, separate, EMPTY graph
rc, out, err = run("new", "web3")
ck("new graph created", rc == 0 and "created graph 'web3'" in out)
ck("new graph is empty (separate mapping)", run("--graph", "web3", "manifest")[1].count("\n") < 6)
ck("new graph has INDEX+JOURNAL", os.path.exists(os.path.join(HOME, ".claude/knowledge-graphs/web3/INDEX.md")))
rc, _, err = run("new", "web3")
ck("duplicate graph rejected", rc == 1 and "already exists" in err)
rc, _, err = run("new", "Bad Name")
ck("invalid graph name rejected", rc == 1 and "invalid graph name" in err)
rc, _, err = run("new", "default")
ck("cannot clobber default", rc == 1)

# seeded graph
rc, out, _ = run("new", "seeded", "--seed")
ck("seeded graph copies seeds", rc == 0 and "idor-id-enumeration" in run("--graph", "seeded", "manifest")[1])

# graphs listing
rc, out, _ = run("graphs")
ck("graphs lists default+new", rc == 0 and "default" in out and "web3" in out and "seeded" in out)

# isolation: a node written into web3 must NOT appear in default
os.makedirs(os.path.join(HOME, ".claude/knowledge-graphs/web3/nodes"), exist_ok=True)
open(os.path.join(HOME, ".claude/knowledge-graphs/web3/nodes/reentrancy-guard.md"), "w").write(
    "---\nid: reentrancy-guard\ntitle: Reentrancy guard\ntype: technique\ntags: [reentrancy]\n"
    "vuln_class: []\nrelated: []\nconfidence: high\nreinforced: 2\nuses: 0\nenabled: true\n"
    "created: 2026-10-29\nupdated: 2026-10-29\nsource: assessment\n---\n\n"
    "# Reentrancy guard\n\n**Summary:** check-effects-interactions ordering.\n")
ck("web3 node visible in web3", "reentrancy-guard" in run("--graph", "web3", "manifest")[1])
ck("web3 node NOT visible in default", "reentrancy-guard" not in run("manifest")[1])
ck("default node NOT visible in web3", "idor-id-enumeration" not in run("--graph", "web3", "manifest")[1])

# multi-graph read: union + graph:slug refs
rc, out, _ = run("--graph", "default,web3", "manifest", "--top", "40")
ck("multi-graph unions both", rc == 0 and "web3:reentrancy-guard" in out and "default:idor-id-enumeration" in out)
ck("multi-graph header lists both", "graphs: default, web3" in out)
rc, out, _ = run("--graph", "default,web3", "query", "reentrancy")
ck("multi-graph query finds web3 node", "web3:reentrancy-guard" in out)

# get across graphs, by graph:slug and by bare slug
rc, out, _ = run("--graph", "default,web3", "get", "web3:reentrancy-guard")
ck("get by graph:slug", rc == 0 and "check-effects-interactions" in out)
ck("get bumped uses in the right graph", "uses: 1" in nodefile("web3", "reentrancy-guard"))
ck("default graph untouched by that get", "uses: 1" not in nodefile("default", "idor-id-enumeration"))
rc, out, _ = run("--graph", "web3", "get", "reentrancy-guard", "--peek")
ck("peek does not bump", rc == 0 and "uses: 1" in nodefile("web3", "reentrancy-guard"))

# pin targets the right graph
rc, out, _ = run("--graph", "web3", "pin", "reentrancy-guard")
ck("pin writes into web3", "pin: true" in nodefile("web3", "reentrancy-guard"))

# missing node reports clearly
rc, out, err = run("--graph", "web3", "get", "nope-not-here")
ck("missing node reported", "not found" in err)

# --kb still overrides --graph (server/prime compatibility)
rc, out, _ = run("--kb", DEF, "manifest", "--top", "5")
ck("--kb still works and overrides", rc == 0 and "idor-id-enumeration" in out)

allp = True
for n, c in ok:
    print(f"  [{'PASS' if c else 'FAIL'}] {n}"); allp = allp and c
print("ALLPASS" if allp else "SOME-FAILED")
shutil.rmtree(HOME, ignore_errors=True)
sys.exit(0 if allp else 1)
