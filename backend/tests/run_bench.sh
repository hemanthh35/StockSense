#!/bin/sh
# Times each endpoint in its own process with a 60 s cap, so one pathological request can't hang the run.
# usage: sh tests/run_bench.sh [label]
echo "== ${1:-benchmark} =="
for p in "/api/products" "/api/stock" "/api/operations" "/api/moves" "/api/parties" "/api/dashboard" \
         "/api/reports/valuation" "/api/reports/margin?days=365" "/api/reorder/suggestions" \
         "/api/products?page=1&page_size=25" "/api/stock?page=1&page_size=25" "/api/operations?page=1&page_size=25" \
         "/api/moves?page=1&page_size=25" "/api/parties?page=1&page_size=25" \
         "/api/reports/valuation?page=1&page_size=25" "/api/reports/margin?days=365&page=1&page_size=25"; do
  case "$p" in *page=*) [ -n "$LEGACY_ONLY" ] && continue;; esac
  out=$(timeout 60 python tests/bench_scale.py --only "$p" 2>&1 | tail -1)
  [ -z "$out" ] && out="> 60000 ms  (gave up)"
  printf "  %-46s %s\n" "$p" "$out"
done
