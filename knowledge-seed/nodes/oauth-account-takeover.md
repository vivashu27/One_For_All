---
id: oauth-account-takeover
title: OAuth / SSO account takeover patterns
type: technique
tags: [oauth, sso, account-takeover, redirect-uri, open-redirect, auth]
vuln_class: [broken-authentication, account-takeover]
related: [broken-access-control, payloadsallthethings, impact-first-reporting]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# OAuth / SSO account takeover patterns

**Summary:** OAuth flows have recurring implementation flaws that lead directly to
account takeover — most hinge on `redirect_uri` handling, `state`, and how the app
links a social identity to a local account.

## When to use
Any "Log in with Google/Facebook/GitHub/Apple" or enterprise SSO flow.

## Steps / checks
1. **redirect_uri laxity:** try appended paths, open-redirect on an allowed host,
   `@`-tricks, subdomains, and `/../` — can the `code`/`token` be sent to you?
2. **Missing/forgeable `state`:** no `state` → CSRF on the OAuth callback → attacker
   links victim to attacker's social account, or forces victim into attacker session.
3. **Email trust / pre-account-takeover:** sign up locally with victim's email, then
   victim "logs in with Google" and gets merged into your account (or vice versa).
   Check whether email verification gates the link.
4. **Code/token leakage:** `code` in Referer to third-party scripts, or reusable
   `code` (no single-use / no PKCE).
5. **Account linking with no re-auth:** add attacker identity to victim session.

## Gotchas
- A working ATO here usually chains with an [[broken-access-control]] or open-redirect
  primitive — build the chain before reporting.

## Related
[[broken-access-control]] — adjacent auth boundary bugs · [[payloadsallthethings]]
— OAuth/redirect payloads · [[impact-first-reporting]] — demonstrate full takeover.
