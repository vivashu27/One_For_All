"""In-process tests at the kb module seam: node store, INDEX regeneration, graph registry."""
import os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbstore-")
os.environ["HOME"] = HOME                       # sandbox: graph paths resolve at import
os.environ["BBK_KB"] = os.path.join(HOME, "custom-kb")
sys.path.insert(0, os.path.join(ROOT, "web"))
import kb

ok = []
ck = lambda n, c: ok.append((n, bool(c)))

DEF = kb.DEFAULT_KB
shutil.copytree(os.path.join(ROOT, "knowledge-seed"), DEF, dirs_exist_ok=True)
NODE = os.path.join(DEF, "nodes", "burp-autorize.md")

try:
    # ---- node store: set_meta updates frontmatter and keeps the body
    before = open(NODE).read()
    kb.set_meta(NODE, {"pin": "true"})
    after = open(NODE).read()
    meta, body = kb.parse_frontmatter(after)
    ck("set_meta writes the key", meta.get("pin") is True)
    ck("set_meta keeps the body", body == kb.parse_frontmatter(before)[1])

    # ---- node store: a failed write leaves the node intact (atomic replace)
    real = os.replace
    def boom(*a):
        raise OSError("disk full")
    os.replace = boom
    try:
        kb.set_meta(NODE, {"uses": "99"})
    except OSError:
        pass
    finally:
        os.replace = real
    ck("failed write leaves node intact", open(NODE).read() == after)
    ck("failed write leaves no temp file",
       not [f for f in os.listdir(os.path.dirname(NODE)) if f.startswith(".tmp-")])

    # ---- INDEX: regenerated from nodes, including disabled ones and the link map
    kb.set_meta(os.path.join(DEF, "nodes", "portswigger-academy.md"), {"enabled": "false"})
    kb.reindex(DEF, "default")
    idx = open(os.path.join(DEF, "INDEX.md")).read()
    lines = idx.split("\n")
    ck("INDEX header names the graph", lines[0] == "# Knowledge Graph: default — Index")
    ck("INDEX groups by type heading", "## Tools" in lines and "## Vuln Classes (hubs)" in lines)
    ck("INDEX lists every node", sum(l.startswith("- [[") for l in lines) == 11)
    ck("INDEX marks disabled nodes",
       any(l.startswith("- [[portswigger-academy]]") and l.endswith("_(disabled)_") for l in lines))
    ck("INDEX has the link map",
       "## Link map" in lines and any(l.startswith("- burp-autorize → ") for l in lines))

    # ---- registry: BBK_KB moves the default graph (the hook already honoured it)
    ck("BBK_KB sets the default graph", DEF == os.path.join(HOME, "custom-kb"))
    ck("default resolves to BBK_KB", kb.resolve_graph("default") == DEF)
    import argparse
    ck("--kb on a known graph keeps its graph name",
       kb.roots(argparse.Namespace(kb=DEF, graph=None)) == [("default", DEF)])

    # ---- registry: remove_graph deletes graphs under the root, refuses anything else
    ok_new, _, gp = kb.create_graph("scratch", seed=True)
    ck("remove_graph deletes a graph and counts its nodes",
       ok_new and kb.remove_graph(gp) == 11 and not os.path.exists(gp))
    try:
        kb.remove_graph(DEF)
        ck("remove_graph refuses a dir outside the graphs root", False)
    except ValueError:
        ck("remove_graph refuses a dir outside the graphs root", os.path.isdir(DEF))
finally:
    shutil.rmtree(HOME, ignore_errors=True)

for n, c in ok:
    print(("  [PASS] " if c else "  [FAIL] ") + n)
print("ALLPASS" if all(c for _, c in ok) else "SOME-FAILED")
