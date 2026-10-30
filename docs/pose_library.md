# Pose library — body arrangements for the series (T35)

Fictional adults only (cast ≥ 22), all scenes consensual per the owner's script. This file is the reference for the
Blender presets (`gpu3: ns-studio/data/train/poses/`), the hard-shot ControlNet route (T27) and the pose LoRAs.
Sources: general anatomy/photography knowledge and the script text itself; no images were collected.

## 1. What the script actually needs (ep07–ep60, `为他而骚 （剧本和镜头）v2.md`)

Counted from the 359 `镜N｜img` lines. The script directs most intimate moments as **silhouettes / cropped
foregrounds** (剪影、前景含蓄裁切), so the library prioritises arrangements that read clearly in outline.

| Rank | Composition (CN / EN) | Shots | Notes |
|---|---|---|---|
| 1 | 女上跨坐 / straddle–cowgirl, face to face | ep32s1, ep36s6, ep47s1, ep47s2, ep47s3, ep47s5, ep47s6 | ep47 is the series' climax: arched back, hair flung back, bead chains between them; also "seated on his knees" (ep36) |
| 2 | 跪于男方面前 / kneeling in front of a standing or seated man | ep29s4, ep35s1, ep35s3, ep38s1, ep45s5 | Cropped: her profile + his hand in her hair / on the sofa back; ep45s5 is a 4-panel montage |
| 3 | 三人前后夹击（MFM 双重插入）/ MFM front-and-back (DP) | ep38s3, ep39s1, ep44s1, ep45s2 | Silhouette only; one man in front (face to face), one behind; she is held between them |
| 4 | 中央仰卧 + 多人环绕 / supine centre, partners around (group, ≤3 visible) | ep43s1, ep44s1, ep42s5, ep40s6/ep41s6 (diagram) | ep42–45 group of 4 men + observer in an armchair; each shot shows ≤ 3 people |
| 5 | 床边：他立床边，她仰卧 / edge of bed, he stands, she lies back | ep12s1, ep13s4 | Classic edge-of-bed missionary set-up, shot from the side or over his shoulder |
| 6 | 背后环抱于镜前 / standing, he holds her from behind, mirror | ep21s6, ep28s5, ep36s1 | Two faces in the mirror; his hands on her harness or between her legs (ep21) |
| 7 | 事后相拥 / post-coital embrace (lying, head on chest / in his arm) | ep07s5, ep12s6, ep30s1, ep48s6 | Low-key silhouettes |
| 8 | 侧卧后抱（勺子式）/ spooning, she hugs him from behind | ep13s6, ep34s6, ep52s1 | Non-explicit, recurring "secret" beat with 陈宇 |
| 9 | 单膝跪其身前 / he kneels on one knee in front of her (standing) | ep21s2 | Bead-chain fitting; jewellery close-up |
| 10 | 趴卧 / prone on a table or bed (tattoo, piercing) | ep26s1, ep28s1, ep15s1 | Procedure scenes, back to camera |

Jewellery overlaps: nprng2 (nipple rings) appears in 14 shots, lbrng9/lbrng9_beads in 11; most pose LoRA data
should therefore be renderable with the jewellery geometry attached.

## 2. Taxonomy (general reference)

Each entry: arrangement → typical cameras. "He/she" for MF; the same rigs work for any pairing.

### Two people
- **Missionary 传教士位** — she supine, legs apart or wrapped round him; he kneels/lies between her legs, chest over
  hers. Variants: legs on shoulders 腿架肩 (her calves on his shoulders, hips raised); pillow under hips; edge of bed
  床边 (she lies at the bed edge, he stands). Cameras: side (90°), over his shoulder, overhead, low between knees.
- **Cowgirl 女上位 / straddle 跨坐** — he supine or seated; she kneels astride his hips facing him, upright or leaning
  forward (hands on his chest). Seated variant: he sits on bed/chair/sofa, she sits on his thighs. Reverse cowgirl
  反向女上 — she faces his feet. Cameras: side, low from the foot of the bed, from behind her (back, hair), POV from
  below.
- **Doggy / rear-entry 后入** — she on hands and knees (or forearms), he kneels behind; **prone bone 俯卧后入** — she
  lies flat, he lies over her; **standing rear 站立后入** — she bends over a surface. Cameras: side, 3/4 rear, low.
- **Spooning 侧卧** — both on their sides, he behind her. Cameras: overhead, over the shoulder, front close.
- **Standing / against the wall 站立／抵墙** — face to face, one leg lifted, or she is lifted with legs around his waist.
- **Lotus / seated 坐莲／坐抱** — he sits cross-legged, she sits in his lap facing him, legs around him.
- **Oral 口交** — kneeling in front of a standing/seated partner; lying (cunnilingus between her legs); **69** —
  stacked head-to-foot. Cameras: side profile, over-the-head, cropped foreground (script style).
- **Manual / embrace** — partners standing or sitting close, hands only; mirror compositions.

### Three people (MFM / FFM)
- **Front-and-back (spit-roast style 前后)** — she on hands and knees or kneeling, one partner behind, one in front
  (oral). Cameras: side profile (all three in line), 3/4.
- **Double penetration 双重插入 (DP)** — she straddles one partner (cowgirl) while the second kneels behind her; or
  standing/sandwich (三明治) held between two standing partners (the ep38 "架在两人之间"). Cameras: side silhouette
  (script default), low 3/4.
- **"Seagull"-style 海鸥式** — she supine, each partner holds one leg up and apart from either side; or one partner
  between her legs and one at her head. Cameras: overhead, low between the knees.
- **FFM** — two women in 69 or kissing while one partner joins from behind / beside.

### Groups (script ep42–45: 1 woman, 4 men, 1 observer)
- **Centre-supine ring 中央仰卧环绕** — she lies centre of a mat, partners at her head, sides and between her legs;
  the observer sits in a single armchair at the edge of frame. **Kneeling ring** — she kneels centre, partners stand
  around. Shots never show more than 3 people; use cropping, silhouettes and depth of field.

## 3. Blender presets (gpu3 `ns-studio/data/train/hardshots/`)

`hs_scene.py` builds a shot from a JSON spec: up to 3 MPFB adult bodies (林晚: G-cup, long legs, light-blue
waist-length hair + blunt bangs as coarse hair geometry; men: adult male MPFB bodies per the character locks), the
pose library (per-bone world-axis rotations), optional exact jewellery (nprng2 / lbrng9 / lbrng9_beads 4+1+4,
5 mm balls), and the camera. It exports `depth.png` (near = white), `pose.png` (OpenPose COCO-18), `coarse.png`,
`mask.png` (jewellery) and `meta.json` (2D keypoints). `hs_generate.py` / `hs_showcase.py` turn that into a first
frame with NoctQ V4 + the Qwen-Image 2.1 Fun ControlNet (depth or pose), and paste the jewellery back exactly.

Planned presets (ranked as in §1): `straddle_face`, `straddle_seated`, `kneel_front`, `mfm_sandwich_standing`,
`mfm_cowgirl_dp`, `supine_ring`, `edge_of_bed`, `mirror_behind`, `embrace_lying`, `spoon`, `kneel_one_knee`, `prone`.
Each preset carries 6 standard cameras: close, medium, wide, low angle, overhead, POV; plus an `align` parameter
(hip offset in cm) for contact alignment.

## 4. Pose LoRAs (queued after the jewellery LoRAs)

Top candidates by script need: `pose_straddle` (cowgirl/seated straddle), `pose_kneel_front`, `pose_mfm_dp`,
`pose_supine_ring`, `pose_edge_of_bed`, `pose_mirror_behind`. 40–60 Blender-posed + photorealised images each,
faces out of frame or invented, trained on NoctQ V4 like the jewellery LoRAs; registered in
`ComfyUI/models/LORA_REGISTRY.json`; copies + README in `D:\NS-Final Studio\assets\pose\`; previews in
`D:\NS-Final Studio\previews\poses\`.

## 5. Trigger names (fixed; the v3 script references them)

One LoRA per trigger, file `pose_<name>_v1.safetensors` in `ComfyUI/models/loras/` (copies in
`D:\NS-Final Studio\assets\pose\`), registered trigger → file → strength in `ComfyUI/models/loras/LORA_REGISTRY.json`.
Training order follows script need (§1); status is updated here as each LoRA lands.

| Trigger | Position | Script priority | File | Strength | Status |
|---|---|---|---|---|---|
| `pose_cowgirl` | straddle / cowgirl, face to face (incl. seated straddle) | 1 | pose_cowgirl_v1.safetensors | 0.8 (planned) | queued |
| `pose_oral` | kneeling in front of a partner (cropped, script style) | 2 | pose_oral_v1.safetensors | 0.8 | queued |
| `pose_dp` | MMF double penetration (sandwich / cowgirl + behind) | 3 | pose_dp_v1.safetensors | 0.8 | queued |
| `pose_group` | centre-supine or kneeling ring, ≤3 visible, partial bodies | 4 | pose_group_v1.safetensors | 0.8 | queued |
| `pose_edge_of_bed` | she lies at the bed edge, he stands | 5 | pose_edge_of_bed_v1.safetensors | 0.8 | queued |
| `pose_spitroast` | MMF front (oral) + behind | 6 | pose_spitroast_v1.safetensors | 0.8 | queued |
| `pose_mmf_seagull` | supine, a partner on each side holding her legs | 7 | pose_mmf_seagull_v1.safetensors | 0.8 | queued |
| `pose_missionary` | missionary | 8 | pose_missionary_v1.safetensors | 0.8 | queued |
| `pose_spoon` | spooning | 9 | pose_spoon_v1.safetensors | 0.8 | queued |
| `pose_prone` | prone / prone bone | 10 | pose_prone_v1.safetensors | 0.8 | queued |
| `pose_standing` | standing, face to face / from behind | 11 | pose_standing_v1.safetensors | 0.8 | queued |
| `pose_wall` | against the wall, leg lifted / lifted | 12 | pose_wall_v1.safetensors | 0.8 | queued |
| `pose_doggy` | rear entry on hands and knees | 13 | pose_doggy_v1.safetensors | 0.8 | queued |
| `pose_reverse_cowgirl` | reverse cowgirl | 14 | pose_reverse_cowgirl_v1.safetensors | 0.8 | queued |
| `pose_lotus` | lotus / seated face to face | 15 | pose_lotus_v1.safetensors | 0.8 | queued |
| `pose_legs_on_shoulders` | missionary, her legs on his shoulders | 16 | pose_legs_on_shoulders_v1.safetensors | 0.8 | queued |
| `pose_69` | 69 | 17 | pose_69_v1.safetensors | 0.8 | queued |

## 6. Expanded canonical list (all common position names, deduplicated)

Built from general, publicly documented sex-position vocabulary (glossaries such as Wikipedia's *Sex position* article
and the position names commonly used as category/tag words on adult sites). No adult-site pages, videos,
thumbnails or images were downloaded or viewed. Real performers are never used as data or references. Synonyms
used on sites are folded into one canonical entry. Rank (a) = need in our script (§1; "—" means not in the script),
rank (b) = general frequency (H/M/L). The Blender spec states who is where, the contact point, and limb placement.
F is the woman (林晚 body) and M1–M4 are adult male bodies. Every pose preset gets the 6 standard cameras.

### Two-person

| Trigger | Canonical name (EN / CN) — common synonyms | (a) | (b) | Blender arrangement spec |
|---|---|---|---|---|
| `pose_missionary` | Missionary 传教士 — "man on top" | 8 | H | F supine, knees bent ~60°, thighs abducted 35°; M prone/kneeling between thighs, hips aligned at F pelvis, forearms planted beside F shoulders |
| `pose_legs_on_shoulders` | Legs on shoulders 腿架肩 — "deep missionary", "anvil" | 16 | M | as missionary, F hips flexed 100°, calves resting on M shoulders; M kneeling upright |
| `pose_edge_of_bed` | Edge of bed 床边 — "butterfly" (hips at the edge) | 5 | M | F supine with pelvis at bed edge, legs raised/held; M standing at bed edge, hips at F pelvis height |
| `pose_mating_press` | Mating press 压腿 — folded missionary | — | M | F supine, knees pressed toward shoulders; M on top, weight on hands |
| `pose_cowgirl` | Cowgirl 女上 / straddle 跨坐 — "riding", "woman on top" | 1 | H | M supine (or seated); F kneeling astride M pelvis facing him, torso upright or leaning 20–40° forward, hands on M chest |
| `pose_reverse_cowgirl` | Reverse cowgirl 反向女上 | 14 | H | as cowgirl, F facing M feet; hands on M thighs |
| `pose_lotus` | Lotus / seated face-to-face 坐莲 — "lap dance" sitting | 15 | M | M seated cross-legged or on chair; F seated on M thighs facing him, legs around his waist |
| `pose_reverse_lap` | Reverse seated 反向坐抱 — "reverse lap" | — | M | M seated on chair/bed edge; F seated on M lap facing away, feet on floor |
| `pose_doggy` | Doggy / rear entry 后入 — "doggystyle", "from behind" | 13 | H | F on hands and knees (or forearms), back arched; M kneeling behind, hips at F pelvis |
| `pose_prone` | Prone bone 俯卧后入 — "flat doggy" | 10 | M | F prone, legs together or slightly apart; M lying over F back, hands planted |
| `pose_spoon` | Spooning 侧卧 | 9 | M | both lying on left side, M behind F, knees bent in parallel |
| `pose_standing` | Standing 站立 — face to face, or from behind / "bent over" | 11 | H | standing, either facing (F one leg lifted on M hip) or M behind F who leans on a table |
| `pose_wall` | Against the wall 抵墙 — "wall sex" | 12 | M | F back (or front) against the wall, one leg lifted; M facing her |
| `pose_lift` | Standing carry 抱起 — "stand and carry", "suspended" | — | M | M standing, F lifted with legs around his waist, arms around his neck |
| `pose_sideways` | Side-entry / scissors 剪刀 | — | L | F on side, upper leg raised; M kneeling, straddling her lower thigh |
| `pose_piledriver` | Pile-driver 倒立 | — | L | F supine on shoulders, hips up; M standing/squatting over her |
| `pose_69` | 69 | 17 | M | head-to-foot, one on top (or both on sides); each face at the other's pelvis |
| `pose_oral` | Kneeling oral 跪姿口交 — "blowjob", "kneeling" | 2 | H | M standing or seated; F kneeling in front, head at M pelvis height (script: cropped foreground) |
| `pose_cunnilingus` | Cunnilingus 舔阴 — "eating out" | — | H | F supine, legs apart (or seated at edge); M prone/kneeling, head between F thighs |
| `pose_facesitting` | Face-sitting 坐脸 | — | M | M supine; F kneeling astride his head, facing his feet or his torso |
| `pose_handjob` | Manual 手 — "handjob", "fingering" | (ep45s4) | H | partners seated or lying side by side; contact at hand |
| `pose_titjob` | Breast sex 乳交 | — | M | F kneeling or supine; M straddling her chest |

### Three or more people (MMF focus, per the owner)

| Trigger | Canonical name (EN / CN) — synonyms | (a) | (b) | Blender arrangement spec |
|---|---|---|---|---|
| `pose_dp` | Double penetration 双重插入 — "DP", "sandwich" | 3 | H | variant A: M1 supine, F cowgirl on M1, M2 kneeling behind F. Variant B (script ep38): standing sandwich, F held between M1 (front, facing) and M2 (behind) |
| `pose_spitroast` | Spit-roast 前后 — "MMF front and back" | 6 | H | F on hands and knees; M1 kneeling behind at F pelvis; M2 kneeling/standing in front at F head |
| `pose_mmf_seagull` | "Seagull" 海鸥式 | 7 | M | F supine; M1 between thighs (missionary); M2 kneeling at F head side, holding her legs back, or M1 and M2 kneeling at either side, each holding one leg up |
| `pose_mmf_oral` | Double oral 双口 — "two men one woman kneeling" | (ep44s1) | M | F kneeling; M1 and M2 standing either side in front of her |
| `pose_mfm_cowgirl_oral` | Cowgirl + oral 女上+口 | — | M | F cowgirl on supine M1; M2 standing/kneeling beside F head |
| `pose_group` | Group 群体 — "gangbang"; ≤3 visible, partial bodies | 4 | M | F centre (supine or kneeling) on a mat; M1–M4 placed around (head, sides, between legs); camera keeps ≤3 bodies, others cropped to partial limbs/silhouettes |
| `pose_mff` | MFF / FFM 两女一男 | — | M | F1 cowgirl on supine M; F2 kneeling over M face, or F1/F2 side by side |
| `pose_bukkake_ring` | Kneeling ring 跪中央环绕 — "circle" | (ep45s5) | L | F kneeling centre; M1–M3 standing in a semicircle, cropped at the waist |

### Furniture / location variants (combine with any pose above)
Edge of bed, chair/armchair (script: observer's single chair), sofa back, desk/table (bent over), mirror (script
ep21/28/36), shower, floor mat (script ep38–45 soft-mat circle), car seat. Encoded as preset parameters, not triggers.

### Camera tags (separate, not poses)

| Tag | Meaning | Blender camera |
|---|---|---|
| `cam_pov_m` | POV from the male partner's eyes | camera at M head, looking along his gaze |
| `cam_pov_f` | POV from her eyes | camera at F head |
| `cam_close` | close-up of the contact / jewellery | 0.3–0.4 m frame |
| `cam_side` | profile / silhouette (script default) | 90° to the body axis, backlit |
| `cam_low` | low angle from the foot of the bed | 0.3 m height, looking up |
| `cam_overhead` | top-down | above the bed, looking down |
| `cam_wide` | establishing wide | whole bodies plus room |
| `cam_mirror` | through a mirror | camera facing a mirror plane |

### Build order
Presets for the top ~30 entries above (script-needed first: cowgirl, oral, dp, group, edge_of_bed, spitroast,
mmf_seagull, mmf_oral, missionary, spoon, prone, standing, wall, doggy, reverse_cowgirl, lotus,
legs_on_shoulders, 69, then the general-frequency ones). LoRAs are trained in the same order, after the jewellery
LoRAs.
