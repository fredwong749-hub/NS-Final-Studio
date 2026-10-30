#!/bin/bash
# usage: run_stage.sh <stage>   (starts asset_gen detached; one runner per stage)
cd /root/claude-kimi-ns-studio-v1/nsfs_assets
setsid nohup /root/claude-kimi-ns-studio-v1/env/comfy/bin/python -u tools/asset_gen.py jobs/$1.jsonl out/$1 >> logs/$1.log 2>&1 < /dev/null &
