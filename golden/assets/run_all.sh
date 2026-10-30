#!/bin/bash
cd "/d/NS-Final Studio"
T0=$(date +%s)
uv run python tools/gen_assets.py run --only items/ --class product
echo "PHASE products done $(( $(date +%s)-T0 ))s"
uv run python tools/gen_assets.py run --only plates/ expressions/ items/ looks/ --class identity --refine
echo "PHASE identity done $(( $(date +%s)-T0 ))s"
uv run python tools/gen_assets.py run --only ../
echo "PHASE men done $(( $(date +%s)-T0 ))s"
