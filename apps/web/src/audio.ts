// E8 声音提示词：环境声（进 H3，docs/h3_prompt_guide_base_en.txt §4.6）+ 背景音乐 / 配乐提示（后期混音，不进 H3）

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
  "后期混音用（H3 的 non_diegetic_music 保持 N/A）。写乐器、速度、节奏和强弱变化，不写情绪词；没有就写 N/A。";
export const EP_MUSIC_EXAMPLE =
  "Sparse piano notes at a slow tempo, joined by sustained low strings that gradually increase in volume before fading out.";

export const CUE_HINT = "本镜配乐提示（后期）：进入 / 延续 / 推高 / 落下 / 点题，强度 0–3，对白处是否压低（ducking）。";
export const CUE_EXAMPLE = "推高，强度 2，对白处压低";
