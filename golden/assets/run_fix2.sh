#!/bin/bash
cd "/d/NS-Final Studio"
until grep -q "FIX done" golden/assets/run_fix.log; do sleep 30; done
uv run python tools/redo_asset.py looks/REF-LW-02_back 1 --refine
uv run python tools/redo_asset.py items/makeup/L6_tears_on_L4 1 --refine
uv run python tools/redo_asset.py items/makeup/L6_tears_on_L1 1 --refine
echo "FIX2 done"
