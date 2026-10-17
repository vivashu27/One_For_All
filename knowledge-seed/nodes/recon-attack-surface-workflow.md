---
id: recon-attack-surface-workflow
title: Recon → prioritized attack surface workflow
type: workflow
tags: [recon, methodology, attack-surface, prioritization, process]
vuln_class: []
related: [projectdiscovery-suite, verify-scope-before-testing, broken-access-control]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# Recon → prioritized attack surface workflow

**Summary:** A repeatable pipeline from a target's scope to a ranked list of what to
test first — so time goes to high-signal surface, not random clicking.

## Goal
Turn "here's a domain" into "here are the 10 endpoints/features most likely to pay".

## Steps
1. **Scope gate** — confirm in-scope assets and rules first ([[verify-scope-before-testing]]).
2. **Enumerate** — subdomains + live hosts + crawl with [[projectdiscovery-suite]];
   add `gau`/`waybackurls` for historical URLs and params.
3. **Fingerprint** — tech stack, frameworks, auth model, API style (REST/GraphQL),
   CDN/WAF. Note anything matching your past wins.
4. **Map features** — auth, object references (IDs), file upload/fetch, webhooks,
   payment, admin, import/export, SSO. Flag anything that fetches URLs (SSRF) or
   carries object IDs (access control).
5. **Rank** — prioritize by likely-impact × likely-exploitable: object references
   → [[broken-access-control]]; URL fetchers → SSRF; auth/SSO → takeover; new or
   recently-changed features (less hardened).
6. **Hunt** — work top-down; log every interesting request for later chaining.

## Tools used
[[projectdiscovery-suite]], Burp, `gau`/`waybackurls`, `ffuf` for content discovery.

## Output
A short, ranked hitlist + a request log — the input to focused manual testing.

## Related
[[projectdiscovery-suite]] · [[verify-scope-before-testing]] · [[broken-access-control]]
