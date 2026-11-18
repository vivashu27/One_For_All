# Product

<!-- impeccable:product-schema 1 -->

> Written by `/impeccable init` without a live interview (it ran as a sub-agent with no way to ask questions). Facts tagged _(inferred)_ come from the repository and should be confirmed or corrected by the owner. Untagged facts are stated in the README, the code, or the owner's own requests.

## Platform

web

## Users

- **Primary:** an individual security researcher or bug-bounty hunter who uses Claude Code agents across many assessments. They open the web UI (`/serve-knowledge`) to see, curate and fix what their agents have learned. _(inferred: single-owner use is the default; LAN sharing behind a token is optional)_
- **Secondary:** AI agents, which read and write the same graph through `web/kb.py` and the knowledge-graph skill and never see the web UI.
- **Optional:** teammates on the same LAN viewing a shared graph through `--host 0.0.0.0 --token`.

## Product Purpose

One_For_All is a Claude Code plugin that gives agents a compounding knowledge graph for bug bounty and security work. Techniques, tools, references, lessons, workflows and reporting insights from each session are captured, deduplicated, linked and reused. The web UI is where a human views, edits, enables or disables, exports and imports that graph, and manages several separate graphs.

Success for the web UI: the owner can understand the shape of the graph at a glance, find and fix a node quickly, and keep the graph clean as it grows.

## Positioning

Agent memory that compounds across engagements, stored as plain markdown files the owner fully controls. Retrieval is priority-ranked and just-in-time, so agent context stays flat as the graph grows. The web UI is a local, dependency-free control room for that memory, not a hosted service.

## Operating Context

- Runs locally (`python3 web/server.py`, default `127.0.0.1:8787`), usually alongside an active assessment in a terminal and browser. _(inferred)_
- Data lives in markdown files with frontmatter (`nodes/*.md`, `INDEX.md`, `JOURNAL.md`) under `~/.claude/bug-bounty-knowledge` (or `$BBK_KB`) and `~/.claude/knowledge-graphs/<name>`.
- Agents change the same files between UI visits, so the UI must cope with nodes appearing, changing or being disabled behind its back.

## Capabilities and Constraints

- **Domain terms:**
  - **graph:** a separate knowledge base.
  - **node:** one markdown file.
  - **slug:** a node's kebab-case id.
  - **type:** one of technique, tool, reference, lesson, workflow, reporting, or vuln-class (vuln-class nodes are the hub nodes).
  - **related:** the edges between nodes.
  - **confidence, reinforced, uses, pin:** the inputs to a node's priority score.
  - **enabled / disabled:** whether a node is in use or retired.
  - **INDEX / JOURNAL:** the generated hub file and the change log.
- **Web UI today:**
  - Static graph clustered under one hub per type: drag to arrange, Tidy to re-lay, Fit, zoom and pan.
  - Type filter through the legend; search; sorting.
  - Node viewer and editor (raw markdown with frontmatter).
  - Create, delete and enable/disable nodes.
  - Create, rename, delete and switch graphs.
  - Journal view.
  - Export as zip or JSON, and import.
- **Hard constraints:**
  - Offline and dependency-free: a stdlib Python server and static HTML/CSS/JS with no CDN, framework or build step.
  - Localhost by default.
  - Token auth and a cross-site-write (CSRF) check when shared.
  - All file access is confined to the graph folder.
- **Requested direction** (owner's request, 2026-11-18):
  - Graph nodes must not bounce.
  - Nodes keep their position.
  - The user can drag nodes to reduce clutter, and the positions persist.
  - A "tidy" action re-lays the graph cleanly, in the spirit of the layout options in BloodHound-style graph tools.
- **Decided (2026-11-18):** node positions are saved in a `layout.json` per graph on disk (beside `nodes/`), served by `/api/layout`. Saves merge per id, so two tabs or LAN viewers don't overwrite each other. The zip and JSON exports carry it, and import restores it.
- **Tests:** UI behaviour is tested headlessly in Node (`tests/cluster_harness.js`, `tests/ui_flow_harness.js`) through `bash tests/run.sh`.

## Brand Commitments

- **Product name:** One_For_All. The web UI's title reads "Knowledge Graph" / "Bug Bounty Knowledge Graph".
- No other binding brand assets, voice or identity rules have been confirmed. _(inferred: none exist)_

## Evidence on Hand

- `knowledge-seed/nodes/` holds 11 generic seed nodes (real content, safe to show).
- `docs/showcase.png` is a screenshot of the current graph view (README says node titles there are generic examples).
- There are no testimonials, user counts or benchmarks. Do not invent any.
- Real users' graphs may hold sensitive assessment notes. Never put real graph content in screenshots or demos; use the seed nodes.

## Product Principles

1. **The owner stays in control.** Plain files, local by default, nothing leaves the machine unless the owner shares it.
2. **Calm over spectacle.** The graph is a working map to scan and curate, not an animation. Stable positions beat physics.
3. **Agents and humans share one source of truth.** The UI never keeps its own copy of node data that can drift from the files.
4. **Zero dependencies.** Anything the UI needs ships in the repo and works offline.
5. **Scale without clutter.** Views and layouts must stay legible as the graph grows from tens to hundreds of nodes. _(inferred from the compounding-graph purpose)_
