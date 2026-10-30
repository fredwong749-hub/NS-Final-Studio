"""T06 golden snapshot: compile every shot of the pinned script (tests/fixtures/t06_golden/data/import/script_v2.json)
and record every prompt-bearing field. The before-snapshot (prompts_before.json) was written with the pre-T06 compiler
(rules as Python constants); tests/test_t06_bible.py recompiles with rules read from the pinned visual_bible.toml and
asserts byte-identical output.

    uv run python tests/fixtures/t06_golden/snapshot.py            # print a summary of the current compile
    uv run python tests/fixtures/t06_golden/snapshot.py --write    # (re)write prompts_before.json — only before T06!
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "data" / "import" / "script_v2.json"
BEFORE = HERE / "prompts_before.json"


def snapshot(compile_kw: dict | None = None, spec_kw: dict | None = None) -> dict:
    from ns_agent import compiler as C
    from ns_agent import frame_spec as F
    from ns_schema.script import ScriptImport
    compile_kw, spec_kw = compile_kw or {}, spec_kw or {}
    script = ScriptImport.model_validate_json(SCRIPT.read_text(encoding="utf-8"))
    g = script.globals
    all_files = {t.file for t in g.lora_triggers if t.file}
    all_trig = {t.trigger for t in g.lora_triggers if t.file}
    out = {}
    for ep in script.episodes:
        prev_male = None
        for s in ep.shots:
            row = {}
            for tag, loras in (("none", set()), ("all", all_files)):
                c = C.compile_shot(ep, s, g, loras, **compile_kw)
                row[tag] = {k: getattr(c, k) for k in (
                    "adult", "adult_reasons", "image_prompt", "image_negative", "image_loras", "video_prompt",
                    "video_negative", "video_loras", "dropped_triggers", "last_prompt", "end_state", "image_body",
                    "dark", "video_soundscape")}
                # 2026-10-30（SOP §9A）：video_prompt 改为 H3 官方四块提示词；旧版中文拼接保留在 legacy_video_prompt，
                # 金标准比的是旧版拼接（字节一致），H3 提示词由 tests/test_h3_prompt.py 单独检查
                row[tag]["video_prompt"] = getattr(c, "legacy_video_prompt", "") or c.video_prompt
                row[tag]["image_loras"] = [list(x) for x in c.image_loras]
                row[tag]["video_loras"] = [list(x) for x in c.video_loras]
            for tag, trig in (("spec_none", set()), ("spec_all", all_trig)):
                sp = F.build_spec(ep, s, g, available_triggers=trig, prev_male=prev_male, **spec_kw)
                row[tag] = {"qwen": sp.model_prompt.qwen, "qwen_last": sp.model_prompt.qwen_last,
                            "facts": [[f.text, f.kind, f.must, f.frame] for f in sp.facts],
                            "characters": [c.name for c in sp.characters], "validation": sp.validation}
            out[s.id] = row
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    snap = snapshot()
    if "--write" in sys.argv:
        BEFORE.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {BEFORE} ({len(snap)} shots)")
    else:
        print(f"{len(snap)} shots")
