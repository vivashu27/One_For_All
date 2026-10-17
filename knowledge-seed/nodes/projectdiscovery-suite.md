---
id: projectdiscovery-suite
title: ProjectDiscovery suite (subfinder, httpx, nuclei, katana)
type: tool
tags: [recon, subdomains, nuclei, httpx, subfinder, katana, automation]
vuln_class: []
related: [recon-attack-surface-workflow]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# ProjectDiscovery suite

**Summary:** A fast, composable CLI toolchain that covers most of recon end-to-end:
enumerate subdomains, probe which are live, crawl them, and template-scan for known
issues.

## What it does
- `subfinder` — passive subdomain enumeration from many sources.
- `httpx` — probe hosts for live HTTP(S), titles, status, tech, CDN.
- `katana` — fast crawler to pull endpoints/JS/params.
- `nuclei` — templated scanner for known CVEs, misconfigs, exposures.
- `dnsx` — fast DNS resolution/bruteforce; `naabu` — port scan.

## Best for
Standing up a target's attack surface quickly and re-running it for change
monitoring. See [[recon-attack-surface-workflow]].

## Key commands
```bash
subfinder -d target.com -all -silent \
  | httpx -silent -title -tech-detect -status-code \
  | tee live.txt
katana -list live.txt -silent -jc -o endpoints.txt
nuclei -l live.txt -severity medium,high,critical -o nuclei.txt
```

## Pairs with
`gau` / `waybackurls` for historical URLs; Burp for manual follow-up on anything
interesting. Keep `nuclei-templates` updated.

## Related
[[recon-attack-surface-workflow]] — where this toolchain plugs in.
