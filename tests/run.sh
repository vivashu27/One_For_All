#!/usr/bin/env bash
# Run every test. No framework, no dependencies: python3 + node.
# Each test prints PASS/FAIL lines and ends with ALLPASS or SOME-FAILED.
cd "$(dirname "$0")" || exit 1
fail=0
for t in *.py; do
  [ -e "$t" ] || continue
  printf '%-26s ' "$t"
  out=$(python3 "$t" 2>&1) || true
  echo "$out" | tail -1
  echo "$out" | grep -q ALLPASS || { fail=1; echo "$out" | grep -E '^\s*\[FAIL\]' ; }
done
for t in *.js; do
  [ -e "$t" ] || continue
  printf '%-26s ' "$t"
  out=$(node "$t" 2>&1) || true
  echo "$out" | tail -1
  echo "$out" | grep -q ALLPASS || { fail=1; echo "$out" | grep -E '^\s*\[FAIL\]' ; }
done
[ "$fail" = 0 ] && echo "== all suites passed ==" || echo "== FAILURES =="
exit "$fail"
