---
id: burp-autorize
title: Burp Suite + Autorize (authorization testing)
type: tool
tags: [burp, autorize, idor, access-control, automation]
vuln_class: [idor, bola, broken-access-control]
related: [idor-id-enumeration, broken-access-control]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# Burp Suite + Autorize

**Summary:** Autorize (free BApp) replays every request with a low-priv user's
session and flags where the response matches the high-priv one — turning tedious
manual IDOR/authorization testing into a passive, as-you-browse scan.

## What it does
Holds a second user's session cookies/headers; for each request you make as user A,
it re-sends it as user B and as unauthenticated, then colour-codes
Enforced / Bypassed / Is enforced?? per request.

## Best for
Object- and function-level [[broken-access-control]] at scale across a whole app or
API, including multi-tenant boundary testing.

## Key setup
1. Install via BApp Store. Open Autorize tab.
2. Paste the **low-privilege** user's `Cookie`/`Authorization` header into the config.
3. Enable interception, then browse the app as the **high-privilege** user.
4. Review "Bypassed!" rows — those are candidate IDORs; confirm manually.
5. Use filters to cut noise (static assets, logout, etc.).

## Pairs with
[[idor-id-enumeration]] — Autorize finds candidates, you confirm by swapping IDs.
Burp Intruder/Repeater for enumeration and verb-tampering follow-up.

## Related
[[broken-access-control]] · [[idor-id-enumeration]]
