"""由 parse.py 输出生成 docs/ep02_iter/workflow_library.md。

用法:
  python -I tools/workflow_lib/report.py <parsed.json> <out.md>
      [--notes tools/workflow_lib/notes_zh.md] [--weights data/ab/owner_workflows/_meta/weights_sources.tsv]
      [--sources-root data/ab/owner_workflows]
自动部分：每工作流一行、跨工作流参数分布、缺失权重清单。人工部分（推荐/排序）从 --notes 原样插入。
"""
import json, os, sys, re, argparse, collections

FOCUS = {'H3', 'QwenImage2.1', 'Krea2', 'SR', 'LipSync'}


def fnum(x):
    try:
        f = float(x)
        return ('%g' % round(f, 4))
    except Exception:
        return str(x)


def act(L):
    return [x for x in L if not isinstance(x, dict) or x.get('active', True)]


def have_str(m):
    h = m.get('have') or {}
    s = ''.join('3' if (k == 'gpu33' and v) else ('6' if (k == 'gpu36' and v) else '') for k, v in sorted(h.items()))
    return {'36': '33+36', '3': '33', '6': '36', '': '缺'}.get(s, s)


def key_params(R):
    out = []
    sch = act(R['schedulers'])
    if sch:
        out.append('/'.join(sorted(set(str(s['scheduler']) for s in sch))) + ' ' + '+'.join(fnum(s['steps']) for s in sch) + '步' +
                   ''.join(' d%s' % fnum(s['denoise']) for s in sch if s['denoise'] not in (1, 1.0, None)))
    if R['samplers']:
        out.append(','.join(sorted(set(s.replace('(bypass)', '') for s in R['samplers']))))
    cf = sorted(set(fnum(c) for c in R['cfg'] if c is not None))
    if cf:
        out.append('cfg ' + ','.join(cf))
    sh = act(R['sigma_shift'])
    if sh:
        out.append('shift ' + ','.join(sorted(set('%s/%s' % (fnum(s['video']), fnum(s['audio'])) for s in sh))))
    if R['model_sampling_shift']:
        out.append('MS-shift ' + ','.join(fnum(x) for x in R['model_sampling_shift']))
    sp = [s['step'] if isinstance(s, dict) else s for s in act(R['split_sigmas'])]
    if sp:
        out.append('split ' + ','.join(fnum(x) for x in sp))
    ms = act(R['manual_sigmas'])
    if ms:
        out.append('manualσ×%d' % len(ms))
    res = [r for r in act(R['resolution']) if r.get('w')]
    if res:
        r = res[0]
        out.append('%sx%s' % (r['w'], r['h']) + ('×%sf' % r['length'] if r.get('length') else '') +
                   (' ref=%s' % r['ref_image_size'] if r.get('ref_image_size') else ''))
    mp = [r.get('megapixels') for r in act(R['resolution']) if r.get('megapixels')]
    if mp:
        out.append('MP ' + ','.join(fnum(x) for x in mp))
    for u in act(R['upscaler']):
        if u['node'] == 'SelfLiftH3Sampler':
            out.append('SelfLift ts%s lr%s w%s-%s' % (u.get('transition_step'), fnum(u.get('lowres_scale')), fnum(u.get('w_min')), fnum(u.get('w_max'))))
        elif u['node'] == 'MinimaxH3LatentUpscaler3D':
            p = u['params']
            out.append('LU3D %s %s' % (p.get('mode'), p.get('value') or ('%sx%s' % (p.get('width'), p.get('height')))))
    for a in act(R['attention']):
        p = a['params']
        if a['node'] == 'BlockSparseAttention':
            out.append('BSA %s τ%s' % (p.get('selection'), fnum(p.get('tau'))))
        elif a['node'] == 'ModelAttentionBackend':
            out.append('attn:' + str(p.get('attention')).replace('comfy kitchen attention', 'kitchen'))
        else:
            out.append(a['node'].replace('MiniMaxH3MemoryEfficientSageAttentionPatch', 'H3Sage').replace('PathchSageAttentionKJ', 'SageKJ'))
    lo = act(R['loras'])
    if lo:
        out.append('LoRA ' + '; '.join('%s@%s' % (l['lora'][:38], fnum(l.get('strength'))) for l in lo))
    pp = sorted(set(p['node'] for p in act(R['postproc'])))
    if pp:
        out.append('后处理 ' + ','.join(pp))
    sl = R['ref_slots']
    out.append('槽 图%d音%d视%d' % (sl['image'], sl['audio'], sl['video']))
    return '；'.join(out)


def models_str(R):
    seen, out = set(), []
    for m in R['models']:
        if not m['active'] or m['file'] in seen:
            continue
        seen.add(m['file'])
        out.append('%s(%s)' % (m['file'], have_str(m)))
    return '<br>'.join(out)


def esc(s):
    return str(s).replace('|', '\\|').replace('\n', ' ')


def dist(vals, top=8):
    c = collections.Counter(vals)
    n = sum(c.values())
    return ', '.join('%s ×%d' % (k, v) for k, v in c.most_common(top)) + ('（n=%d）' % n if n else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('parsed')
    ap.add_argument('out')
    ap.add_argument('--notes')
    ap.add_argument('--weights')
    ap.add_argument('--sources-root', default='data/ab/owner_workflows')
    a = ap.parse_args()
    P = json.load(open(a.parsed, encoding='utf-8'))
    # 去重（同 md5 只留第一份）
    seen, U = set(), []
    for R in P:
        if R['md5'] in seen:
            continue
        seen.add(R['md5'])
        U.append(R)
    foc = [R for R in U if set(R['family']) & FOCUS]
    rest = [R for R in U if not (set(R['family']) & FOCUS)]
    L = []
    L.append('# 社区工作流库（ep02 迭代用）\n')
    L.append('生成：`python -I tools/workflow_lib/parse.py data/ab/owner_workflows --out data/ab/owner_workflows/_meta/parsed.json --inv … --nodes …` → '
             '`python -I tools/workflow_lib/report.py …`。库：`data/ab/owner_workflows/`（ganloss/ = amao2001/ganloss-latent-space，community/ = 其他作者，来源与提交哈希见各目录 `_sources.json` / `_source.json`）。\n')
    L.append('机器侧：模型清单由 `ssh gpu33/gpu36 find -L models custom_nodes` 只读获取（`_meta/gpu33.tsv`、`_meta/gpu36.tsv`），节点清单为运行中 ComfyUI 的 `/object_info` 键（`_meta/*.nodes.txt`，两台同为 1262 类）。表中 (33+36)=两台都有，(33)=仅 gpu33，(缺)=都没有。\n')
    L.append('统计：解析 %d 个工作流 json（去重后 %d），其中与目标相关（H3 / Qwen-Image 2.1 / Krea2 / 视频超分 / 口型）%d 个。\n' % (len(P), len(U), len(foc)))
    if a.notes and os.path.exists(a.notes):
        L.append(open(a.notes, encoding='utf-8').read().rstrip() + '\n')
    # 参数分布
    h3 = [R for R in foc if 'H3' in R['family']]
    qi = [R for R in foc if 'QwenImage2.1' in R['family'] or 'Krea2' in R['family']]
    L.append('\n## 跨工作流参数分布（社区常用值）\n')
    L.append('只统计启用（未 bypass）的节点；同一工作流内多个同类节点各算一次。\n')
    COMM = ('community/', 'civitai/', 'runninghub/')
    h3g = [R for R in h3 if not R['rel'].startswith(COMM)]
    h3c = [R for R in h3 if R['rel'].startswith(COMM)]
    nauth = len(set('/'.join(R['rel'].split('/')[:2]) for R in h3c))
    L.append('| 参数 | H3 · ganloss + 项目方示例（n=%d） | H3 · 社区（community/ + civitai/ + runninghub/，n=%d，%d 个来源） | Qwen-Image 2.1 / Krea2 出图（n=%d） |' % (len(h3g), len(h3c), nauth, len(qi)))
    L.append('|---|---|---|---|')

    def col(G, f):
        vals = []
        for R in G:
            vals += f(R)
        return esc(dist(vals))
    rows = [
        ('调度器', lambda R: [str(s['scheduler']) for s in act(R['schedulers'])]),
        ('步数（每段）', lambda R: [fnum(s['steps']) for s in act(R['schedulers'])]),
        ('二段 denoise', lambda R: [fnum(s['denoise']) for s in act(R['schedulers']) if s['denoise'] not in (1, 1.0, None)]),
        ('采样器', lambda R: [s.replace('(bypass)', '') for s in R['samplers'] if '(bypass)' not in s]),
        ('CFG', lambda R: [fnum(c) for c in R['cfg'] if c is not None]),
        ('Guider', lambda R: [g for g in R['guiders'] if '(bypass)' not in g]),
        ('SigmaShift video/audio', lambda R: ['%s/%s' % (fnum(s['video']), fnum(s['audio'])) for s in act(R['sigma_shift'])] or ['（不接）']),
        ('ModelSampling shift', lambda R: [fnum(x) for x in R['model_sampling_shift']]),
        ('SplitSigmas', lambda R: [fnum(s['step'] if isinstance(s, dict) else s) for s in act(R['split_sigmas'])]),
        ('ManualSigmas', lambda R: [re.sub(r'\s+', '', str(s['sigmas'] if isinstance(s, dict) else s)) for s in act(R['manual_sigmas'])]),
        ('宽×高', lambda R: ['%sx%s' % (r['w'], r['h']) for r in act(R['resolution']) if r.get('w')]),
        ('帧长', lambda R: [str(r['length']) for r in act(R['resolution']) if r.get('length')]),
        ('ref_image_size', lambda R: [str(r['ref_image_size']) for r in act(R['resolution']) if r.get('ref_image_size')]),
        ('ResolutionSelector MP', lambda R: [fnum(r['megapixels']) for r in act(R['resolution']) if r.get('megapixels')]),
        ('fps', lambda R: [fnum(x) for x in R['fps'] if x is not None]),
        ('注意力', lambda R: [(a['node'] + ':' + str(a['params'].get('selection') or a['params'].get('attention') or a['params'].get('sage_attention') or '')).rstrip(':') for a in act(R['attention'])]),
        ('BlockSparse tau / end', lambda R: ['%s τ%s end%s' % (a['params'].get('selection'), fnum(a['params'].get('tau')), fnum(a['params'].get('end_percent'))) for a in act(R['attention']) if a['node'] == 'BlockSparseAttention']),
        ('LatentUpscaler3D', lambda R: ['%s %s' % (u['params'].get('mode'), u['params'].get('value') or '%sx%s' % (u['params'].get('width'), u['params'].get('height'))) for u in act(R['upscaler']) if u['node'] == 'MinimaxH3LatentUpscaler3D']),
        ('Upscaler 权重', lambda R: [str(u['params'].get('model_name')) for u in act(R['upscaler']) if u['node'] == 'MinimaxH3LatentUpscaler3D'] + [str(u.get('upscaler_model')) for u in act(R['upscaler']) if u['node'] == 'SelfLiftH3Sampler']),
        ('SelfLift ts/lowres/w', lambda R: ['ts%s lr%s w%s-%s' % (u.get('transition_step'), fnum(u.get('lowres_scale')), fnum(u.get('w_min')), fnum(u.get('w_max'))) for u in act(R['upscaler']) if u['node'] == 'SelfLiftH3Sampler']),
        ('LoRA@强度', lambda R: ['%s@%s' % (l['lora'], fnum(l.get('strength'))) for l in act(R['loras'])]),
        ('底模（diffusion）', lambda R: [m['file'] for m in R['models'] if m['active'] and m['kind'] == 'diffusion']),
        ('文本编码器', lambda R: [m['file'] for m in R['models'] if m['active'] and m['kind'] == 'text_encoder']),
        ('VAE', lambda R: [m['file'] for m in R['models'] if m['active'] and m['kind'] == 'vae']),
        ('后处理节点', lambda R: sorted(set(p['node'] for p in act(R['postproc'])))),
    ]
    for name, f in rows:
        L.append('| %s | %s | %s | %s |' % (name, col(h3g, f), col(h3c, f), col(qi, f)))
    # 每工作流一行
    L.append('\n## 工作流清单（目标相关，每个一行）\n')
    L.append('用途列：族 + 任务标签（parse.py 按节点/文件名推断）。缺节点列只列我们两台 ComfyUI 都没注册的后端节点（VHS_VideoCombine 可用内置 SaveVideo/CreateVideo 替换，不算硬缺）。\n')
    L.append('| # | 工作流 | 用途 | 关键参数 | 模型（机器上是否已有） | 缺节点 |')
    L.append('|---|---|---|---|---|---|')

    def sk(R):
        r = R['rel']
        return (0 if r.startswith('ganloss') else 1 if '/' not in r or r.startswith(('singularity_v2', 'aisley')) else 2 if r.startswith('community') else 3, r)
    for i, R in enumerate(sorted(foc, key=sk), 1):
        miss = [t for t in (R.get('missing_nodes') or {}).get('gpu33', []) if t != 'VHS_VideoCombine']
        L.append('| %d | `%s` | %s | %s | %s | %s |' % (i, esc(R['rel']), esc('/'.join(R['family']) + ' · ' + ','.join(R['task'])),
                                                     esc(key_params(R)), esc(models_str(R)), esc(', '.join(miss[:12]) + (' …' if len(miss) > 12 else ''))))
    L.append('\n### 其余（与目标弱相关，仅列名）\n')
    L.append(', '.join('`%s`' % R['rel'] for R in sorted(rest, key=sk)) + '\n')
    # 缺失权重
    L.append('\n## 缺失权重清单（两台机器都没有；未下载，>5GB 需批准）\n')
    if a.weights and os.path.exists(a.weights):
        L.append(open(a.weights, encoding='utf-8').read().rstrip() + '\n')
    cnt = collections.defaultdict(set)
    for R in foc:
        for m in R['models']:
            if m['active'] and not any((m.get('have') or {}).values()):
                cnt[m['file']].add(R['rel'])
    L.append('\n全部缺失文件及引用次数（自动）：\n')
    L.append('| 文件 | 引用工作流数 | 示例 |')
    L.append('|---|---|---|')
    for f, s in sorted(cnt.items(), key=lambda x: (-len(x[1]), x[0])):
        L.append('| %s | %d | %s |' % (esc(f), len(s), esc(sorted(s)[0])))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('wrote', a.out, len(foc), 'focus rows')


if __name__ == '__main__':
    main()
