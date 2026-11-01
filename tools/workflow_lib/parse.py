"""ComfyUI 工作流解析器（UI 格式 + API 格式）。

用法:
  python -I tools/workflow_lib/parse.py <工作流根目录> [--out parsed.json]
        [--inv gpu33=<models.tsv>,gpu36=<models.tsv>]
        [--nodes gpu33=<object_info 节点名.txt>,gpu36=...]

只读解析 json，不执行任何东西。对每个工作流抽取：
  模型文件 / LoRA+权重 / 采样器-调度器-步数-CFG-guider / sigma shift / SplitSigmas /
  ManualSigmas / 放大器参数 / 分辨率-帧长-fps / 注意力后端 / 提示词模板 /
  参考图-音频-视频槽位 / 后处理（face refine、插帧、超分、口型）/ 作者备注（Note/MarkdownNote）
  以及（若给了 --inv/--nodes）模型在各机器上是否已有、缺哪些节点类型。
"""
import json, os, re, sys, argparse, hashlib

MODEL_EXT = ('.safetensors', '.pt', '.pth', '.gguf', '.ckpt', '.bin', '.onnx', '.sft')
CTRL = {'fixed', 'randomize', 'increment', 'decrement'}
FRONTEND_ONLY = {'Reroute', 'Note', 'MarkdownNote', 'PrimitiveNode', 'GetNode', 'SetNode',
                 'Label (rgthree)', 'Fast Groups Bypasser (rgthree)', 'Fast Groups Muter (rgthree)',
                 'Fast Bypasser (rgthree)', 'Fast Muter (rgthree)', 'Bookmark (rgthree)',
                 'Display Any (rgthree)', 'Any Switch (rgthree)', 'Context (rgthree)', 'Note Plus (mtb)'}

# 已知节点的位置参数表（widgets_values 顺序）。'*ctrl' 表示 seed 之后的 control_after_generate。
SCHEMA = {
    'UNETLoader': ['unet_name', 'weight_dtype'],
    'CLIPLoader': ['clip_name', 'type', 'device'],
    'DualCLIPLoader': ['clip_name1', 'clip_name2', 'type', 'device'],
    'VAELoader': ['vae_name'],
    'VAELoaderKJ': ['vae_name', 'device', 'weight_dtype'],
    'CheckpointLoaderSimple': ['ckpt_name'],
    'LoraLoaderModelOnly': ['lora_name', 'strength_model'],
    'LoraLoader': ['lora_name', 'strength_model', 'strength_clip'],
    'KSamplerSelect': ['sampler_name'],
    'BasicScheduler': ['scheduler', 'steps', 'denoise'],
    'SplitSigmas': ['step'],
    'SplitSigmasDenoise': ['denoise'],
    'ManualSigmas': ['sigmas'],
    'CFGGuider': ['cfg'],
    'RandomNoise': ['noise_seed', '*ctrl'],
    'KSampler': ['seed', '*ctrl', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise'],
    'KSamplerAdvanced': ['add_noise', 'noise_seed', '*ctrl', 'steps', 'cfg', 'sampler_name', 'scheduler',
                         'start_at_step', 'end_at_step', 'return_with_leftover_noise'],
    'MiniMaxH3SigmaShift': ['shift_video', 'shift_audio'],
    'MiniMaxH3ReferenceToVideo': ['prompt', 'width', 'height', 'length', 'ref_image_size'],
    'MiniMaxH3ImageToVideo': ['prompt', 'width', 'height', 'length'],
    'ModelAttentionBackend': ['attention'],
    'ModelSamplingSD3': ['shift'],
    'ModelSamplingAuraFlow': ['shift'],
    'LatentUpscaleModelLoader': ['model_name'],
    'SelfLiftH3Sampler': ['seed', '*ctrl', 'cfg', 'transition_step', 'lowres_scale', 'rho', 'w_min', 'w_max',
                          'upscaler_model', 'highres_tiling', 'upscaler_unload'],
    'MiniMaxH3PDDAccApply': ['pdd_file', 'nfe', 'lora_strength', 'head_strength', 'on_off_grid', 'partition'],
    'VedaSparseAttention': ['model_file', 'a', 'b', 'c', 'd', 'e'],
    'BlockSparseAttention': ['selection', 'tau', 'start_percent', 'end_percent', 'dense_blocks', 'min_tokens',
                             'extra_tokens', 'sink_conditioning', 'verbose'],
    'SolAttnPatch': ['tau', 'start_percent', 'end_percent', 'min_tokens', 'int8_qk', 'sink_conditioning',
                     'morton', 'morton_curve', 'verbose'],
    'EasyCache': ['reuse_threshold', 'start_percent', 'end_percent', 'verbose'],
    'MiniMaxH3MotionContext': ['context_frames', 'fps'],
    'MiniMaxH3AddGuide': ['frame_idx'],
    'SeedVR2': ['model', 'seed', '*ctrl', 'new_resolution', 'batch_size', 'preserve_vram'],
    'LatentSyncNode': ['seed', '*ctrl', 'lips_expression', 'inference_steps'],
    'H3PerFrameDenoise': ['denoise_multiplier_small_face', 'denoise_multiplier_large_face', 'scale_mode',
                          'face_px_small', 'face_px_large', 'gamma', 'smooth_frames'],
    'H3FaceStitch': ['paste_region', 'mask_dilation', 'feather', 'colour_match', 'blend', 'undetected_frames',
                     'feather_scales_with_crop'],
    'VOSR2Upscale': ['upscale', 'seed', '*ctrl', 'color_alignment', 'tile_size', 'tile_overlap', 'vae_tile_size',
                     'vae_tile_overlap'],
    'CreateVideo': ['fps', 'bit_depth'],
    'EmptyLatentImage': ['width', 'height', 'batch_size'],
    'EmptySD3LatentImage': ['width', 'height', 'batch_size'],
    'ResolutionSelector': ['aspect_ratio', 'megapixels', 'multiple'],
    'TextEncodeQwenImage21': ['prompt'],
    'CLIPTextEncode': ['text'],
    'PrimitiveStringMultiline': ['value'],
    'UltralyticsDetectorProvider': ['model_name'],
    'SAMLoader': ['model_name', 'device_mode'],
    'PathchSageAttentionKJ': ['sage_attention'],
}

FACE_REFINE = ('FaceDetailer', 'H3FaceTrackCrop', 'H3FaceStitch', 'H3PerFrameDenoise', 'ReActor', 'FaceRestore',
               'LTXFaceDetector', 'LTXLikeness')
INTERP = ('RIFE', 'FILM', 'Interpolat', 'GIMM')
SR = ('SeedVR2', 'VOSR2', 'RTXVideoSuperResolution', 'FlashVSR', 'Upscal', 'ESRGAN', 'ImageScaleBy')
LIPSYNC = ('LatentSync', 'MultiTalk', 'InfiniteTalk', 'Sonic', 'FantasyTalking', 'Wav2Lip', 'NativeAudioLock')
ATTN = ('Attention', 'SolAttn', 'Veda', 'SLA', 'Sage', 'EasyCache', 'TeaCache', 'MagCache', 'NABLA')


def load_json(p):
    for enc in ('utf-8', 'utf-8-sig', 'gbk'):
        try:
            with open(p, encoding=enc) as f:
                return json.load(f)
        except UnicodeDecodeError:
            continue
        except Exception:
            return None
    return None


def iter_nodes(d):
    """返回 [(node_dict, where)]；UI 格式含子图，API 格式转换为伪 UI 节点。"""
    out = []
    if isinstance(d, dict) and isinstance(d.get('nodes'), list):
        for n in d['nodes']:
            out.append((n, 'main'))
        defs = d.get('definitions') or {}
        for sg in defs.get('subgraphs') or []:
            for n in sg.get('nodes') or []:
                out.append((n, 'subgraph:' + str(sg.get('name') or sg.get('id'))[:40]))
        return out, 'ui'
    if isinstance(d, dict) and d and all(isinstance(v, dict) and 'class_type' in v for v in d.values()):
        for k, v in d.items():
            ins = {a: b for a, b in (v.get('inputs') or {}).items() if not isinstance(b, list)}
            out.append(({'type': v['class_type'], 'id': k, 'api_inputs': ins, 'mode': 0,
                         'title': (v.get('_meta') or {}).get('title')}, 'api'))
        return out, 'api'
    return [], None


def node_params(n):
    """把 widgets_values 映射为 {名字: 值}。"""
    t = n.get('type')
    if 'api_inputs' in n:
        return dict(n['api_inputs'])
    wv = n.get('widgets_values')
    if isinstance(wv, dict):
        return dict(wv)
    if not isinstance(wv, list):
        return {}
    if t == 'MinimaxH3LatentUpscaler3D':
        return parse_h3_upscaler(wv)
    names = SCHEMA.get(t)
    if names is None:
        names = [i.get('name') for i in (n.get('inputs') or []) if i.get('widget')]
        # 名字表里不含 control_after_generate，遇到 seed 类自动插入
        fixed = []
        for nm in names:
            fixed.append(nm)
            if nm and ('seed' in nm) and nm != 'seed_mode':
                fixed.append('*ctrl')
        names = fixed
    p = {}
    vi = 0
    for nm in names:
        if vi >= len(wv):
            break
        if nm == '*ctrl':
            if isinstance(wv[vi], str) and wv[vi] in CTRL:
                vi += 1
            continue
        p[nm] = wv[vi]
        vi += 1
    if vi < len(wv):
        p['_extra'] = wv[vi:]
    if not names:
        p = {'_raw': wv}
    return p


def parse_h3_upscaler(wv):
    """[model, mode, (megapixels | width,height | scale), align, device, precision, ...]；model 可能不在首位。"""
    p = {'_raw': wv}
    w = list(wv)
    m = next((x for x in w if isinstance(x, str) and x.lower().endswith(MODEL_EXT)), None)
    if m:
        p['model_name'] = m
        w.remove(m)
    mode = next((x for x in w if isinstance(x, str) and x in ('megapixels', 'target dimensions', 'scale', 'scale_by', 'multiplier')), None)
    if mode:
        p['mode'] = mode
        i = w.index(mode)
        nums = [x for x in w[i + 1:] if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if mode == 'target dimensions' and len(nums) >= 2:
            p['width'], p['height'] = nums[0], nums[1]
        elif nums:
            p['value'] = nums[0]
    for x in w:
        if x in ('fp16', 'bf16', 'fp32'):
            p['precision'] = x
    return p


def short(s, n=400):
    s = str(s)
    return s if len(s) <= n else s[:n] + '…'


def basename(x):
    return re.split(r'[\\/]', str(x))[-1]


def collect_model_strings(n):
    vals = []
    wv = n.get('widgets_values')
    if 'api_inputs' in n:
        wv = list(n['api_inputs'].values())
    if isinstance(wv, dict):
        wv = list(wv.values())
    if isinstance(wv, list):
        for v in wv:
            if isinstance(v, str) and v.lower().endswith(MODEL_EXT):
                vals.append(v)
    return vals


def model_kind(t, fname):
    f = fname.lower()
    if 'lora' in t.lower():
        return 'lora'
    if t in ('UNETLoader', 'CheckpointLoaderSimple') or 'ModelLoader' in t and 'Upscale' not in t:
        return 'diffusion'
    if 'CLIP' in t or 'TextEncoder' in t:
        return 'text_encoder'
    if 'VAE' in t:
        return 'vae'
    if 'Upscal' in t or 'upscaler' in f or 'SelfLift' in t:
        return 'upscaler'
    if 'PDD' in t or 'Veda' in t:
        return 'acc_patch'
    if 'SeedVR' in t or 'VOSR' in t or 'FlashVSR' in t:
        return 'sr'
    if 'Ultralytics' in t or 'Face' in t or 'SAM' in t or 'Dino' in t or 'yolo' in f:
        return 'detector'
    return 'other'


def classify(types, models, path):
    s = ' '.join(types) + ' ' + ' '.join(m['file'] for m in models) + ' ' + path
    sl = s.lower()
    fam = []
    if 'minimaxh3' in sl or 'minimax_h3' in sl or 'fasth3' in sl or 'h3face' in sl or 'selflifth3' in sl or 'eros_max_h3' in sl:
        fam.append('H3')
    if 'qwenimage21' in sl or 'qwen_image_2.1' in sl or 'qwen_image_2_1' in sl:
        fam.append('QwenImage2.1')
    if 'krea2' in sl:
        fam.append('Krea2')
    if 'ltx' in sl and 'H3' not in fam:
        fam.append('LTX')
    if 'wanvideo' in sl or 'wan2' in sl:
        fam.append('Wan')
    if 'seedvr2' in sl or 'vosr2' in sl or 'flashvsr' in sl:
        fam.append('SR')
    if 'latentsync' in sl:
        fam.append('LipSync')
    task = []
    pl = path.lower()
    if 'MiniMaxH3ReferenceToVideo' in types or 'r2v' in pl or 'ref2v' in pl:
        task.append('ref2va')
    if 'MiniMaxH3ImageToVideo' in types:
        task.append('i2v/fl2v/t2v')
    if 'fl2v' in pl or 'flf' in pl:
        task.append('fl2v')
    if 'MinimaxH3LatentUpscaler3D' in types or 'SelfLiftH3Sampler' in types or 'latent_upscale' in pl or 'latent upscale' in pl:
        task.append('latent-upscale')
    if any(t.startswith('H3Face') for t in types) or 'FaceDetailer' in types or 'face_refine' in pl:
        task.append('face-refine')
    if 'MiniMaxH3MotionContext' in types or 'MiniMaxH3MotionContextChain' in types:
        task.append('long-video/motion-context')
    if 'MiniMaxH3AddGuide' in types:
        task.append('multi-keyframe')
    if 'MiniMaxH3PDDAccApply' in types:
        task.append('PDD-acc')
    if 'swap' in pl:
        task.append('character-swap')
    if 'edit' in pl:
        task.append('edit')
    if 'character_sheet' in pl or 'charsheet' in pl or 'charactor_sheet' in pl or 'character sheet' in pl:
        task.append('character-sheet')
    if 'storyboard' in pl or 'story_board' in pl:
        task.append('storyboard')
    if 'LatentSyncNode' in types:
        task.append('lipsync')
    if 'SeedVR2' in types or 'VOSR2Upscale' in types or any('FlashVSR' in t for t in types):
        task.append('video-SR')
    return fam, task


def parse_workflow(p):
    d = load_json(p)
    if d is None:
        return {'path': p, 'error': 'json load failed'}
    nodes, fmt = iter_nodes(d)
    if not fmt:
        return {'path': p, 'error': 'not a comfyui workflow'}
    R = {'path': p, 'format': fmt, 'md5': hashlib.md5(open(p, 'rb').read()).hexdigest(),
         'n_nodes': len(nodes), 'node_types': {}, 'models': [], 'loras': [], 'samplers': [], 'schedulers': [],
         'cfg': [], 'guiders': [], 'sigma_shift': [], 'model_sampling_shift': [], 'split_sigmas': [],
         'manual_sigmas': [], 'upscaler': [], 'resolution': [], 'fps': [], 'attention': [], 'prompts': [],
         'ref_slots': {'image': 0, 'audio': 0, 'video': 0}, 'postproc': [], 'notes': [], 'h3_special': [],
         'muted_types': []}
    seen_models = set()
    for n, where in nodes:
        t = n.get('type') or ''
        mode = n.get('mode', 0)
        active = mode in (0, None)
        R['node_types'][t] = R['node_types'].get(t, 0) + 1
        if not active:
            R['muted_types'].append(t)
        prm = node_params(n)
        tag = '' if active else '(bypass)'
        # 备注
        if t in ('Note', 'MarkdownNote', 'Note Plus (mtb)') or 'Note' in t and isinstance(n.get('widgets_values'), list):
            wv = n.get('widgets_values') or []
            txt = '\n'.join(str(x) for x in wv if isinstance(x, str))
            if txt.strip():
                R['notes'].append(short(txt.strip(), 3000))
            continue
        # 模型
        for f in collect_model_strings(n):
            key = (t, f)
            if key in seen_models:
                continue
            seen_models.add(key)
            k = model_kind(t, f)
            R['models'].append({'file': basename(f), 'raw': f, 'node': t, 'kind': k, 'active': active})
        if 'Lora' in t or 'LoRA' in t:
            name = prm.get('lora_name') or prm.get('lora') or next((v for v in prm.values() if isinstance(v, str) and v.lower().endswith(MODEL_EXT)), None)
            st = prm.get('strength_model', prm.get('strength', prm.get('lora_strength')))
            if name:
                R['loras'].append({'lora': basename(name), 'strength': st, 'node': t, 'active': active})
            # Power Lora Loader (rgthree) 等：dict 列表
            wv = n.get('widgets_values')
            if isinstance(wv, list):
                for v in wv:
                    if isinstance(v, dict) and v.get('lora'):
                        R['loras'].append({'lora': basename(v['lora']), 'strength': v.get('strength'),
                                           'on': v.get('on'), 'node': t, 'active': active})
        if t == 'MiniMaxH3PDDAccApply':
            R['loras'].append({'lora': basename(prm.get('pdd_file', '')), 'strength': prm.get('lora_strength'),
                               'node': t, 'nfe': prm.get('nfe'), 'active': active})
        # 采样
        if t == 'KSamplerSelect':
            R['samplers'].append(str(prm.get('sampler_name')) + tag)
        if t == 'BasicScheduler':
            R['schedulers'].append({'scheduler': prm.get('scheduler'), 'steps': prm.get('steps'),
                                    'denoise': prm.get('denoise'), 'active': active})
        if t in ('KSampler', 'KSamplerAdvanced'):
            R['samplers'].append(str(prm.get('sampler_name')) + tag)
            R['schedulers'].append({'scheduler': prm.get('scheduler'), 'steps': prm.get('steps'),
                                    'denoise': prm.get('denoise'), 'active': active})
            R['cfg'].append(prm.get('cfg'))
        if t == 'CFGGuider':
            R['cfg'].append(prm.get('cfg'))
        if 'Guider' in t:
            R['guiders'].append(t + tag)
        if t == 'SelfLiftH3Sampler':
            R['cfg'].append(prm.get('cfg'))
            R['upscaler'].append({'node': t, **{k: prm.get(k) for k in ('transition_step', 'lowres_scale', 'rho', 'w_min', 'w_max', 'upscaler_model', 'highres_tiling')}, 'active': active})
            R['samplers'].append('SelfLiftH3Sampler' + tag)
        if t == 'MiniMaxH3SigmaShift':
            R['sigma_shift'].append({'video': prm.get('shift_video'), 'audio': prm.get('shift_audio'), 'active': active})
        if t in ('ModelSamplingSD3', 'ModelSamplingAuraFlow', 'ModelSamplingFlux'):
            R['model_sampling_shift'].append(prm.get('shift', prm.get('max_shift')))
        if t == 'SplitSigmas':
            R['split_sigmas'].append({'step': prm.get('step'), 'active': active})
        if t == 'ManualSigmas':
            R['manual_sigmas'].append({'sigmas': prm.get('sigmas'), 'active': active})
        if t == 'MinimaxH3LatentUpscaler3D' or t == 'MinimaxH3LatentUpscalerNode2D' or t == 'LatentUpscaleModelLoader':
            R['upscaler'].append({'node': t, 'params': prm, 'active': active})
        # 分辨率/帧长
        if t in ('MiniMaxH3ReferenceToVideo', 'MiniMaxH3ImageToVideo'):
            R['resolution'].append({'node': t, 'w': prm.get('width'), 'h': prm.get('height'), 'length': prm.get('length'),
                                    'ref_image_size': prm.get('ref_image_size'), 'active': active})
            if prm.get('prompt'):
                R['prompts'].append({'node': t, 'text': short(prm['prompt'], 1500)})
        if t in ('EmptyLatentImage', 'EmptySD3LatentImage', 'EmptyFlux2LatentImage', 'EmptyMiniMaxH3LatentAV', 'EmptyLTXVLatentVideo'):
            R['resolution'].append({'node': t, 'w': prm.get('width'), 'h': prm.get('height'), 'length': prm.get('length'), 'active': active})
        if t == 'ResolutionSelector':
            R['resolution'].append({'node': t, 'aspect': prm.get('aspect_ratio'), 'megapixels': prm.get('megapixels'), 'active': active})
        if t == 'VHS_VideoCombine':
            R['fps'].append(prm.get('frame_rate'))
        if t == 'CreateVideo':
            R['fps'].append(prm.get('fps'))
        if t == 'MiniMaxH3MotionContext':
            R['h3_special'].append({'node': t, **prm})
        # 注意力
        if any(a in t for a in ATTN) and 'Guidance' not in t:
            R['attention'].append({'node': t, 'params': {k: v for k, v in prm.items() if not str(k).startswith('_')} or prm, 'active': active})
        # 提示词
        if t in ('CLIPTextEncode', 'TextEncodeQwenImage21', 'PrimitiveStringMultiline', 'TextEncodeQwenImageEditPlus',
                 'MiniMaxH3RefModTextEncode', 'TextEncodeJoyImageEdit', 'Krea2EditGroundedEncode'):
            txt = prm.get('text') or prm.get('prompt') or prm.get('value')
            if not txt and isinstance(n.get('widgets_values'), list):
                txt = next((x for x in n['widgets_values'] if isinstance(x, str) and len(x) > 20), None)
            if txt and isinstance(txt, str) and txt.strip():
                R['prompts'].append({'node': t, 'title': n.get('title'), 'text': short(txt, 1500)})
        # 槽位
        if t in ('LoadImage', 'LoadImageMask', 'LoadImageFromUrl', 'Image Load'):
            R['ref_slots']['image'] += 1
        if t in ('LoadAudio', 'VHS_LoadAudio', 'VHS_LoadAudioUpload'):
            R['ref_slots']['audio'] += 1
        if t in ('VHS_LoadVideo', 'LoadVideo', 'VHS_LoadVideoPath'):
            R['ref_slots']['video'] += 1
        # 后处理
        for grp, keys in (('face-refine', FACE_REFINE), ('interp', INTERP), ('SR', SR), ('lipsync', LIPSYNC)):
            if any(k in t for k in keys):
                R['postproc'].append({'kind': grp, 'node': t, 'params': {k: v for k, v in prm.items() if k != '_raw'} if prm else {}, 'active': active})
        # 其他 H3 专用
        if t in ('MiniMaxH3AddGuide', 'MiniMaxH3PDDAccApply', 'MiniMaxH3NativeAudioLock', 'MiniMaxH3MotionContextTrim',
                 'MiniMaxH3MotionContextChain', 'MiniMaxH3RefModsLoader', 'MiniMaxH3FunControlNetApply', 'H3InjectVideoLatent',
                 'SelfLiftH3TST', 'MMH3SplitUpscale'):
            R['h3_special'].append({'node': t, 'params': prm, 'active': active})
    R['family'], R['task'] = classify(list(R['node_types']), R['models'], p)
    return R


def load_inventory(spec):
    inv = {}
    if not spec:
        return inv
    for part in spec.split(','):
        host, path = part.split('=', 1)
        files = {}
        for line in open(path, encoding='utf-8'):
            if '\t' not in line:
                continue
            sz, fp = line.rstrip('\n').split('\t', 1)
            files[basename(fp).lower()] = (int(sz), fp)
        inv[host] = files
    return inv


def load_nodes(spec):
    out = {}
    if not spec:
        return out
    for part in spec.split(','):
        host, path = part.split('=', 1)
        out[host] = set(x.strip() for x in open(path, encoding='utf-8') if x.strip())
    return out


def annotate(R, inv, nodesets):
    for m in R.get('models', []):
        m['have'] = {h: (m['file'].lower() in files) for h, files in inv.items()}
    for l in R.get('loras', []):
        l['have'] = {h: (str(l['lora']).lower() in files) for h, files in inv.items()}
    miss = {}
    for h, ns in nodesets.items():
        miss[h] = sorted(t for t in R.get('node_types', {}) if t and t not in ns and t not in FRONTEND_ONLY
                         and not re.fullmatch(r'[0-9a-f\-]{36}', t))
    R['missing_nodes'] = miss
    # 子图实例节点类型为 uuid，忽略


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--out', default=None)
    ap.add_argument('--inv', default=None)
    ap.add_argument('--nodes', default=None)
    a = ap.parse_args()
    inv, nodesets = load_inventory(a.inv), load_nodes(a.nodes)
    res = []
    for r, ds, fs in os.walk(a.root):
        ds.sort()
        for f in sorted(fs):
            if f.lower().endswith('.json') and not f.startswith('_'):
                R = parse_workflow(os.path.join(r, f))
                if 'error' in R:
                    continue
                R['rel'] = os.path.relpath(R['path'], a.root).replace(os.sep, '/')
                annotate(R, inv, nodesets)
                res.append(R)
    out = a.out or os.path.join(a.root, '_parsed.json')
    with open(out, 'w', encoding='utf-8') as fo:
        json.dump(res, fo, ensure_ascii=False, indent=1, default=str)
    print('parsed', len(res), '->', out)


if __name__ == '__main__':
    main()
