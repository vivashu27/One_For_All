# Bug Bounty Knowledge Graph — Index

_Last updated: 2026-10-11 · 11 nodes (seed)_

This is the hub of the compounding knowledge graph. Each entry links to a node in
`nodes/`. Grow it with `/build-knowledge`; load it with `/induce-knowledge`.

## Techniques
- [[idor-id-enumeration]] — swap/enumerate object IDs to cross account & tenant boundaries (seed · 0)
- [[ssrf-cloud-metadata]] — coerce server-side fetches to cloud metadata / internal services (seed · 0)
- [[oauth-account-takeover]] — recurring OAuth/SSO flaws leading to ATO (seed · 0)

## Tools
- [[burp-autorize]] — passive authorization/IDOR testing in Burp (seed · 0)
- [[projectdiscovery-suite]] — subfinder/httpx/katana/nuclei recon toolchain (seed · 0)

## References
- [[portswigger-academy]] — free, authoritative web-security labs & write-ups (seed · 0)
- [[payloadsallthethings]] — payloads, bypasses, methodology per class (seed · 0)

## Lessons
- [[verify-scope-before-testing]] — confirm scope & rules before any testing (seed · 0)

## Workflows
- [[recon-attack-surface-workflow]] — scope → recon → ranked hitlist (seed · 0)

## Reporting
- [[impact-first-reporting]] — lead with impact + reproducible PoC, no hedging (seed · 0)

## Vuln Classes (hubs)
- [[broken-access-control]] — #1 class; IDOR/BOLA, function- & field-level (seed · 0)

## Link map
- broken-access-control → idor-id-enumeration, oauth-account-takeover, burp-autorize
- idor-id-enumeration → broken-access-control, burp-autorize, impact-first-reporting
- ssrf-cloud-metadata → recon-attack-surface-workflow, payloadsallthethings, impact-first-reporting
- oauth-account-takeover → broken-access-control, payloadsallthethings, impact-first-reporting
- burp-autorize → idor-id-enumeration, broken-access-control
- projectdiscovery-suite → recon-attack-surface-workflow
- portswigger-academy → payloadsallthethings, impact-first-reporting
- payloadsallthethings → portswigger-academy, ssrf-cloud-metadata, oauth-account-takeover
- verify-scope-before-testing → recon-attack-surface-workflow, impact-first-reporting
- recon-attack-surface-workflow → projectdiscovery-suite, verify-scope-before-testing, broken-access-control
- impact-first-reporting → idor-id-enumeration, oauth-account-takeover, ssrf-cloud-metadata, verify-scope-before-testing

_Format per entry: `[[slug]] — summary (confidence · reinforced-count)`._
