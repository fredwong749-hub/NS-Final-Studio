import os

# 测试里不在后台重建 data/state_timeline.json（需要时由测试自己打开）
os.environ.setdefault("NS_TIMELINE_AUTOBUILD", "0")
