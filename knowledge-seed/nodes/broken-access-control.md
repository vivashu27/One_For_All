---
id: broken-access-control
title: Broken Access Control (hub)
type: vuln-class
tags: [access-control, authorization, idor, bola, privilege-escalation]
vuln_class: [idor, bola, broken-access-control]
related: [idor-id-enumeration, oauth-account-takeover, burp-autorize]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# Broken Access Control (hub)

**Summary:** The #1 class on the OWASP Top 10 and consistently the highest-paying,
highest-volume bug family in bug bounty. The app authenticates you but fails to
check *authorization* — whether *you* may act on *this* object or reach *this*
function.

## What it is
Enforcement gaps where a user accesses data/actions outside their permissions:
object-level (IDOR/BOLA), function-level (hidden admin routes/verbs), and
field-level (mass assignment, over-broad responses).

## Where it hides
- Numeric/UUID/slug IDs in URLs, bodies, and JSON (`/api/users/{id}`, `?orderId=`).
- Multi-step flows where step N doesn't re-check the owner of step N-1.
- Role/tenant boundaries (user→admin, org A→org B) in SaaS and multi-tenant APIs.
- HTTP method/verb mismatches (`GET` blocked but `PUT`/`DELETE` allowed).
- GraphQL where node-level auth is missing on nested resolvers.

## Techniques
[[idor-id-enumeration]] · [[oauth-account-takeover]] (auth boundary bypass)

## Impact
Account takeover, cross-tenant data read/write, privilege escalation to admin.
Almost always High/Critical when a boundary is actually crossed — see
[[impact-first-reporting]].

## Related
[[idor-id-enumeration]] — the core probing technique · [[burp-autorize]] — automates
detection · [[verify-scope-before-testing]] — confirm these objects are in scope first.
