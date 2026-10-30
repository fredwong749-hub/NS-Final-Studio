// E8 声音提示词：环境声（进 H3，docs/h3_prompt_guide_base_en.txt §4.6）+ 配乐（项目方 2026-10-30：英文进 H3 的
// non_diegetic_music，§4.7；中文提示只给后期混音）

export const AUDIO_SOURCE_LABEL: Record<string, string> = {
  edit: "人工",
  script: "剧本",
  script_h3: "剧本【H3 audio】",
  episode: "继承本集",
  none: "未设",
};

export const SOUNDSCAPE_HINT =
  "英文 1–4 句连成一段：环境声、动作声（脚步、衣料摩擦、碰撞）、呼吸 / 笑声等非语言人声；不写对白、唱歌和画内音乐（它们属于多模态描述）。只有要求全程静音才写 N/A。";
export const SOUNDSCAPE_EXAMPLE =
  "Steady rain taps against the café windows while low room ambience continues underneath. The entrance bell rings once, followed by wet footsteps and the soft scrape of a chair.";

export const EP_MUSIC_HINT =
  "本集默认配乐：英文会写进每镜 H3 的 non_diegetic_music（镜头没单独写时）。1–3 句，写乐器、速度、节奏和强弱变化，不写情绪词；没有就写 N/A。中文只作后期提示。";
export const H3_MUSIC_HINT =
  "英文 1–3 句 → 进本镜 H3 的 non_diegetic_music（覆盖本集默认）；写 N/A = 本镜不要配乐；中文 → 只给后期，不进 H3。";
export const MUSIC_SOURCE_LABEL: Record<string, string> = {
  edit: "本镜人工",
  script: "剧本 H3",
  episode: "本集默认",
  none: "无（N/A）",
  cue_silent: "配乐提示强度 0 → N/A",
  episode_invalid: "本集配乐未过 H3-S3 → N/A",
  gpu3: "gpu3 实际版本",
  owner_edit: "项目方覆盖版本",
};
export const EP_MUSIC_EXAMPLE =
  "Sparse piano notes at a slow tempo, joined by sustained low strings that gradually increase in volume before fading out.";

export const CUE_HINT = "本镜配乐提示（后期）：进入 / 延续 / 推高 / 落下 / 点题，强度 0–3，对白处是否压低（ducking）。";
export const CUE_EXAMPLE = "推高，强度 2，对白处压低";
