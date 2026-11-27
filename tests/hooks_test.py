"""End-to-end: run hooks/prime.py with hook JSON on stdin, check the JSON it prints."""
import json, os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="kbhooks-")
KB = os.path.join(HOME, "kb")
PROJ = os.path.join(HOME, "work", "acme")
PLAIN = os.path.join(HOME, "work", "plain")
ENV = dict(os.environ, HOME=HOME, BBK_KB=KB, CLAUDE_PLUGIN_ROOT=ROOT, TMPDIR=HOME)

ok = []
ck = lambda n, c: ok.append((n, bool(c)))


def node(slug, fm, summary="Some summary."):
    nd = os.path.join(KB, "nodes")
    os.makedirs(nd, exist_ok=True)
    lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    with open(os.path.join(nd, slug + ".md"), "w") as fh:
        fh.write(f"---\nid: {slug}\ntitle: {slug}\n{lines}\n---\n\n**Summary:** {summary}\n")


def hook(event, cwd=PROJ, session="s1", **kw):
    inp = dict(hook_event_name=event, session_id=session, cwd=cwd, **kw)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "prime.py")],
                       input=json.dumps(inp), capture_output=True, text=True, env=ENV)
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        return ""


try:
    os.makedirs(os.path.join(PROJ, ".claude")); os.makedirs(PLAIN)
    with open(os.path.join(PROJ, ".claude", "one-for-all.json"), "w") as fh:
        json.dump({"disable": ["noisy-scanner"]}, fh)
    node("coordinator-subagent-fanout", {"type": "workflow", "phase": "[all]", "pin": "true",
                                         "rule": "Delegate every task to subagents."})
    node("scope-gate", {"type": "lesson", "phase": "[scope]", "rule": "Gate scope hard."})
    node("recon-lesson", {"type": "lesson", "phase": "[recon]", "rule": "Time-box recon stages."})
    node("noisy-scanner", {"type": "tool", "phase": "[recon]", "rule": "Run the noisy scanner."})
    node("oauth-account-takeover", {"type": "technique", "phase": "[hunt]", "tags": "[oauth, sso]"},
         "OAuth redirect_uri flaws lead to account takeover.")

    node("generic-pinned", {"type": "tool", "phase": "[recon]", "pin": "true", "tags": "[crawler]"},
         "Use the tool and test the flow with the login and the redirect.")
    s = hook("SessionStart", source="startup")
    ck("opted-in SessionStart injects all+scope rules",
       "Delegate every task" in s and "Gate scope hard." in s and "Time-box" not in s)
    ck("SessionStart includes the phase spine", "scope → recon → rank → hunt → validate → report" in s)
    os.makedirs(os.path.join(PLAIN, "empty", ".claude"))
    open(os.path.join(PLAIN, "empty", ".claude", "one-for-all.json"), "w").write('{"graphs": ["nonexistent"]}')
    ck("opted-in project with no rules still gets the spine",
       "Pipeline:" in hook("SessionStart", cwd=os.path.join(PLAIN, "empty"), source="startup"))
    ck("SessionStart still carries the kb pointer note", "kb.py" in s)
    p = hook("SessionStart", cwd=PLAIN, source="startup")
    ck("non-opted-in project gets pointer note only", "kb.py" in p and "Delegate every task" not in p)

    a = hook("SubagentStart", agent_type="recon-agent", agent_id="a1")
    ck("recon-agent gets recon + all rules", "Time-box recon stages." in a and "Delegate every task" in a)
    ck("project disable applies to subagents", "noisy-scanner" not in a)
    ck("unmapped agent gets only all rules",
       (lambda x: "Delegate every task" in x and "Time-box" not in x)(hook("SubagentStart", agent_type="mystery", agent_id="a2")))
    ck("non-opted-in subagent gets nothing", hook("SubagentStart", cwd=PLAIN, agent_type="recon-agent") == "")

    u = hook("UserPromptSubmit", prompt="now test the oauth sso redirect flow")
    ck("prompt recall surfaces matching node", "oauth-account-takeover" in u)
    ck("filler words and pin boost don't drag in unrelated nodes", "generic-pinned" not in u)
    ck("prompt recall skips already-shown slugs",
       "oauth-account-takeover" not in hook("UserPromptSubmit", prompt="oauth sso again"))
    ck("low-match prompt injects nothing", hook("UserPromptSubmit", session="s2", prompt="fix the css") == "")

    outs = [hook("PostToolUse", session="n1", tool_name="Bash") for _ in range(8)]
    ck("nudge fires once on the 8th inline call", all(o == "" for o in outs[:7]) and "delegat" in outs[7].lower())
    ck("nudge does not repeat on the 9th", hook("PostToolUse", session="n1", tool_name="Read") == "")
    hook("PostToolUse", session="n1", tool_name="Agent")
    ck("Agent call resets the counter",
       all(hook("PostToolUse", session="n1", tool_name="Bash") == "" for _ in range(7)))
    ck("subagent tool calls are not counted",
       all(hook("PostToolUse", session="n2", tool_name="Bash", agent_id="x") == "" for _ in range(9)))
    ck("hostile session_id cannot escape state dir",
       hook("PostToolUse", session="../../etc/x", tool_name="Bash") == ""
       and not os.path.exists(os.path.join(HOME, "etc")))

    os.makedirs(os.path.join(HOME, ".claude"), exist_ok=True)
    with open(os.path.join(HOME, ".claude", "one-for-all.json"), "w") as fh:
        json.dump({"rules": "global"}, fh)
    ck("global flag in ~/.claude enables everywhere",
       "Delegate every task" in hook("SessionStart", cwd=PLAIN, source="startup"))
finally:
    shutil.rmtree(HOME, ignore_errors=True)

for n, c in ok:
    print(("  [PASS] " if c else "  [FAIL] ") + n)
print("ALLPASS" if all(c for _, c in ok) else "SOME-FAILED")
