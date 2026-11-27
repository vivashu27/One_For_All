"""In-process tests for phase:/rule: — kb filtering and the inject_block text builder."""
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbphase-")
os.environ["HOME"] = HOME
os.environ["BBK_KB"] = os.path.join(HOME, "kb")
sys.path.insert(0, os.path.join(ROOT, "web"))
import kb

ok = []
ck = lambda n, c: ok.append((n, bool(c)))


def node(slug, fm, summary="Some summary."):
    nd = kb.nodes_dir(kb.DEFAULT_KB)
    os.makedirs(nd, exist_ok=True)
    lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    with open(os.path.join(nd, slug + ".md"), "w") as fh:
        fh.write(f"---\nid: {slug}\n{lines}\n---\n\n# {slug}\n\n**Summary:** {summary}\n")


def cli(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "web", "kb.py"), *args],
                          capture_output=True, text=True, env=os.environ).stdout


try:
    node("recon-trick", {"type": "technique", "phase": "[recon]", "confidence": "high"})
    node("hunt-trick", {"type": "technique", "phase": "[hunt, validate]"})
    node("untagged", {"type": "technique"})
    node("fanout", {"type": "workflow", "phase": "[all]", "pin": "true",
                    "rule": "Delegate every task to subagents."})

    # ---- seam 1: phase parsing + filtering
    ns = {n["slug"]: n for n in kb.load_nodes(kb.DEFAULT_KB)}
    ck("untagged node counts as phase all", kb.node_phases(ns["untagged"]) == ["all"])
    ck("in_phase matches own phase, all-nodes, and rejects others",
       kb.in_phase(ns["recon-trick"], ["recon"]) and kb.in_phase(ns["fanout"], ["recon"])
       and not kb.in_phase(ns["hunt-trick"], ["recon"]))
    out = cli("manifest", "--phase", "recon")
    ck("manifest --phase recon lists recon + all nodes only",
       "recon-trick" in out and "fanout" in out and "untagged" in out and "hunt-trick" not in out)
    out = cli("query", "trick", "--phase", "hunt")
    ck("query --phase hunt filters", "hunt-trick" in out and "recon-trick" not in out)
    ck("node_rule prefers rule:, falls back to summary",
       kb.node_rule(ns["fanout"]) == "Delegate every task to subagents."
       and kb.node_rule(ns["untagged"]) == "Some summary.")

    # ---- seam 2: inject_block
    nodes = kb.load_nodes(kb.DEFAULT_KB)
    blk = kb.inject_block(nodes, ["recon"])
    ck("rules tier carries pinned rule text", "Delegate every task to subagents." in blk)
    ck("pointer tier lists in-phase non-rule nodes", "recon-trick" in blk and "hunt-trick" not in blk)
    ck("header frames rules as explicit user instruction", "user" in blk.lower() and "override" in blk.lower())
    blk = kb.inject_block(nodes, ["recon"], {"disable": ["fanout"], "pin": ["recon-trick"]})
    ck("project disable drops a node", "Delegate every task" not in blk)
    ck("project pin promotes a node to the rules tier",
       blk.index("recon-trick") < blk.index("Pointers") if "Pointers" in blk else "recon-trick" in blk)
    for i in range(40):
        node(f"rule-{i:02d}", {"type": "lesson", "phase": "[recon]", "rule": "x" * 300})
    blk = kb.inject_block(kb.load_nodes(kb.DEFAULT_KB), ["recon"])
    ck("cap holds and warns when rules are cut", len(blk) <= kb.INJECT_BUDGET and "cut" in blk.lower())
    ck("cut warning gives a runnable command", "python3 kb.py manifest --phase recon" in blk
       and "--phase all" not in kb.inject_block(kb.load_nodes(kb.DEFAULT_KB), ["all"]))
    ck("no nodes in phase -> empty block", kb.inject_block([], ["report"]) == "")
finally:
    shutil.rmtree(HOME, ignore_errors=True)

for n, c in ok:
    print(("  [PASS] " if c else "  [FAIL] ") + n)
print("ALLPASS" if all(c for _, c in ok) else "SOME-FAILED")
