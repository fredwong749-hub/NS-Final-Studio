#!/bin/bash
cd "/d/NS-Final Studio"
until grep -q "PHASE men" golden/assets/run_all.log; do sleep 30; done
uv run python tools/gen_assets.py run --only items/outfit/O06_worn items/outfit/O16_worn items/outfit/O18_worn items/outfit/O20_worn --refine --seed-offset 0
uv run python tools/redo_asset.py items/nails/T2_BARE 3
rm -f assets/characters/lin_wan/expressions/cry_s0.png assets/characters/lin_wan/plates/id_front_bare_s0.png
uv run python tools/gen_assets.py run --only expressions/cry plates/id_front_bare --refine --force
echo "FIX done"
