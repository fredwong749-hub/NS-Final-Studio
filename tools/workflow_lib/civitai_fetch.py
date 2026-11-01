"""Civitai 公开 API 抓取器（不登录、不用 key、不执行任何下载内容）。

用法:
  python -I tools/workflow_lib/civitai_fetch.py catalog   [--root <civitai目录>]
  python -I tools/workflow_lib/civitai_fetch.py workflows [--root ...] [--max-mb 60]
  python -I tools/workflow_lib/civitai_fetch.py sidefiles [--root ...]   # LoRA 页附带的 json/zip 工作流
  python -I tools/workflow_lib/civitai_fetch.py images    [--root ...]   # LoRA/工作流版本示例图 meta
  python -I tools/workflow_lib/civitai_fetch.py media     [--root ...]   # 示例图/视频原件里内嵌的工作流（匿名 API 的 meta 为空时用）
  python -I tools/workflow_lib/civitai_fetch.py summary   [--root ...]

catalog   : 跑预设查询集（QUERY_SETS），分页收集模型，写 _catalog/models.json（每个模型带 category 标签）
workflows : 对 catalog 中 type=Workflows 的模型，下载各版本文件（≤3 个版本）；zip 只解压 json/png/txt/md；
            写 meta.json（链接/作者/版本/下载数/评分/许可/触发词/描述）
images    : 对每个模型的首版本拉 /api/v1/images 示例图 meta（生成参数；若含 ComfyUI 工作流则另存 json）
summary   : 打印 catalog 的简表（给人看）

只做 HTTP GET；下载内容只当数据读。
"""
import json, os, re, sys, time, zipfile, io, argparse, hashlib, html
import urllib.request, urllib.parse, urllib.error

API = 'https://civitai.com/api/v1'
UA = 'Mozilla/5.0 (NS-Final-Studio civitai study; read-only)'
DEFAULT_ROOT = r'D:\NS-Final Studio\data\ab\owner_workflows\civitai'
SAFE_EXT = ('.json', '.png', '.txt', '.md')

# (category, params, max_items)
QUERY_SETS = [
    # 1. MiniMax H3：基模全量
    ('h3', {'baseModels': 'MiniMax H3', 'types': 'Workflows'}, 400),
    ('h3', {'baseModels': 'MiniMax H3', 'types': 'LORA'}, 400),
    ('h3', {'baseModels': 'MiniMax H3', 'types': 'Checkpoint'}, 60),
    ('h3', {'baseModels': 'MiniMax H3', 'types': 'UNet'}, 30),
    ('h3', {'query': 'minimax h3', 'types': 'Workflows'}, 200),
    # 2. Qwen-Image 2.1 全量 + 老 Qwen 中相关主题
    ('qwen21', {'baseModels': 'Qwen 2.1', 'types': 'Workflows'}, 300),
    ('qwen21', {'baseModels': 'Qwen 2.1', 'types': 'LORA'}, 300),
    ('qwen21', {'baseModels': 'Qwen 2.1', 'types': 'Checkpoint'}, 30),
    ('qwen', {'query': 'qwen character consistency'}, 40),
    ('qwen', {'query': 'qwen multi angle'}, 40),
    ('qwen', {'query': 'qwen character sheet'}, 40),
    ('qwen', {'query': 'qwen edit skin'}, 30),
    ('qwen', {'query': 'qwen realism'}, 40),
    ('qwen', {'query': 'qwen outfit'}, 30),
    ('qwen', {'query': 'qwen face swap'}, 30),
    ('qwen', {'query': 'qwen next scene'}, 20),
    ('qwen', {'query': 'qwen relight'}, 20),
    # 3. 通用环节
    ('post', {'query': 'RIFE interpolation', 'types': 'Workflows'}, 25),
    ('post', {'query': 'GIMM', 'types': 'Workflows'}, 15),
    ('post', {'query': 'FILM interpolation', 'types': 'Workflows'}, 15),
    ('post', {'query': 'seedvr2', 'types': 'Workflows'}, 30),
    ('post', {'query': 'flashvsr', 'types': 'Workflows'}, 20),
    ('post', {'query': 'reactor face swap video', 'types': 'Workflows'}, 20),
    ('post', {'query': 'facedetailer video', 'types': 'Workflows'}, 20),
    ('post', {'query': 'pulid', 'types': 'Workflows'}, 20),
    ('post', {'query': 'latentsync', 'types': 'Workflows'}, 20),
    ('post', {'query': 'infinitetalk', 'types': 'Workflows'}, 20),
    ('post', {'query': 'lip sync', 'types': 'Workflows'}, 20),
    ('post', {'query': 'color grading LUT', 'types': 'Workflows'}, 20),
    ('post', {'query': 'film grain', 'types': 'Workflows'}, 15),
    ('post', {'query': 'vertical 9:16 video', 'types': 'Workflows'}, 15),
    ('post', {'query': 'cinematic lighting', 'types': 'LORA'}, 20),
    ('post', {'query': 'camera motion', 'types': 'LORA'}, 20),
    # 4. 同类视频模型（只记要点，量小）
    ('wanltx', {'query': 'wan 2.2', 'types': 'Workflows'}, 25),
    ('wanltx', {'query': 'ltx 2.3', 'types': 'Workflows'}, 20),
    ('wanltx', {'query': 'ltx 2.5', 'types': 'Workflows'}, 15),
]


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            raise
        except Exception:
            if i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            raise


def strip_html(s, n=4000):
    if not s:
        return ''
    s = re.sub(r'<br\s*/?>|</p>|</li>|</h\d>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s[:n]


def slim_model(m):
    vs = []
    for v in m.get('modelVersions', []) or []:
        vs.append({
            'id': v.get('id'), 'name': v.get('name'), 'baseModel': v.get('baseModel'),
            'createdAt': v.get('createdAt'), 'publishedAt': v.get('publishedAt'),
            'trainedWords': v.get('trainedWords') or [],
            'availability': v.get('availability'), 'earlyAccess': v.get('earlyAccessConfig') or v.get('earlyAccessTimeFrame'),
            'stats': v.get('stats'),
            'description': strip_html(v.get('description'), 3000),
            'files': [{'name': f.get('name'), 'type': f.get('type'), 'sizeKB': f.get('sizeKB'),
                       'format': (f.get('metadata') or {}).get('format'), 'fp': (f.get('metadata') or {}).get('fp'),
                       'sha256': (f.get('hashes') or {}).get('SHA256'), 'pickleScan': f.get('pickleScanResult'),
                       'virusScan': f.get('virusScanResult'), 'downloadUrl': f.get('downloadUrl'),
                       'primary': f.get('primary')} for f in v.get('files', []) or []],
            'downloadUrl': v.get('downloadUrl'),
        })
    return {
        'id': m['id'], 'name': m.get('name'), 'type': m.get('type'), 'nsfw': m.get('nsfw'),
        'creator': (m.get('creator') or {}).get('username'), 'tags': m.get('tags') or [],
        'stats': m.get('stats') or {}, 'allowCommercialUse': m.get('allowCommercialUse'),
        'allowNoCredit': m.get('allowNoCredit'), 'allowDerivatives': m.get('allowDerivatives'),
        'allowDifferentLicense': m.get('allowDifferentLicense'), 'mode': m.get('mode'),
        'url': f"https://civitai.com/models/{m['id']}",
        'description': strip_html(m.get('description'), 6000), 'versions': vs,
    }


def cmd_catalog(root):
    cat_dir = os.path.join(root, '_catalog'); os.makedirs(cat_dir, exist_ok=True)
    path = os.path.join(cat_dir, 'models.json')
    models = {}
    if os.path.exists(path):
        models = {int(k): v for k, v in json.load(open(path, encoding='utf-8')).items()}
    for cat, params, cap in QUERY_SETS:
        p = dict(params); p.update({'sort': 'Most Downloaded', 'period': 'AllTime', 'limit': 100 if 'query' not in p else 50})
        url = API + '/models?' + urllib.parse.urlencode(p)
        got = 0
        while url and got < cap:
            try:
                d = get_json(url)
            except Exception as e:
                print('ERR', cat, params, e); break
            items = d.get('items', [])
            for m in items:
                if got >= cap:
                    break
                got += 1
                sm = slim_model(m)
                old = models.get(sm['id'])
                sm['categories'] = sorted(set((old or {}).get('categories', [])) | {cat})
                sm['queries'] = sorted(set((old or {}).get('queries', [])) | {json.dumps(params, ensure_ascii=False)})
                models[sm['id']] = sm
            url = (d.get('metadata') or {}).get('nextPage')
            if not items:
                break
            time.sleep(0.6)
        print(f'{cat:7s} {json.dumps(params, ensure_ascii=False)} -> {got}')
    json.dump({str(k): v for k, v in models.items()}, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('total models', len(models))


def safe_name(s, n=60):
    s = re.sub(r'[^\w\-\. ]+', '_', s or '', flags=re.UNICODE).strip(' ._')
    s = re.sub(r'\s+', '_', s)
    return s[:n] or 'noname'


def model_dir(root, m):
    return os.path.join(root, f"{m['id']}__{safe_name(m['name'])}")


def write_meta(d, m, extra=None):
    meta = {k: m[k] for k in ('id', 'name', 'type', 'url', 'creator', 'tags', 'stats', 'nsfw', 'allowCommercialUse',
                              'allowNoCredit', 'allowDerivatives', 'allowDifferentLicense', 'categories', 'description')}
    meta['license_no_commercial'] = (not m.get('allowCommercialUse')) or m.get('allowCommercialUse') in ('None', [])
    meta['versions'] = m['versions']
    if extra:
        meta.update(extra)
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def download_bytes(url, max_bytes):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        final = r.geturl()
        cl = r.headers.get('Content-Length')
        if cl and int(cl) > max_bytes:
            return None, final, f'too_big:{cl}'
        data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None, final, 'too_big'
        cd = r.headers.get('Content-Disposition') or ''
        return data, final, cd


def save_payload(d, vid, fname, data, log):
    low = fname.lower()
    if low.endswith('.zip') or data[:2] == b'PK':
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except Exception as e:
            log.append(f'{fname}: bad zip {e}'); return
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename.replace('\\', '/'))
            if not base.lower().endswith(SAFE_EXT) or base.startswith('.') or '__MACOSX' in info.filename:
                log.append(f'skip-in-zip {info.filename}'); continue
            if info.file_size > 80 * 1024 * 1024:
                log.append(f'skip-big-in-zip {info.filename}'); continue
            out = os.path.join(d, f'v{vid}__{safe_name(base, 120)}')
            with open(out, 'wb') as f:
                f.write(z.read(info))
            log.append(f'extracted {info.filename}')
    elif low.endswith(SAFE_EXT):
        with open(os.path.join(d, f'v{vid}__{safe_name(fname, 120)}'), 'wb') as f:
            f.write(data)
        log.append(f'saved {fname}')
    else:
        log.append(f'skip-ext {fname}')


def cmd_workflows(root, max_mb):
    cat = json.load(open(os.path.join(root, '_catalog', 'models.json'), encoding='utf-8'))
    status = {}
    for k, m in cat.items():
        if m['type'] != 'Workflows':
            continue
        d = model_dir(root, m); os.makedirs(d, exist_ok=True)
        log, done_marker = [], os.path.join(d, '.done')
        if os.path.exists(done_marker):
            status[k] = 'cached'; continue
        for v in m['versions'][:3]:
            for f in v['files']:
                name = f.get('name') or 'file'
                if (f.get('sizeKB') or 0) > max_mb * 1024:
                    log.append(f'v{v["id"]} {name}: skip size {f.get("sizeKB")}KB'); continue
                if not name.lower().endswith(SAFE_EXT + ('.zip',)):
                    log.append(f'v{v["id"]} {name}: skip ext'); continue
                url = f.get('downloadUrl') or v.get('downloadUrl')
                try:
                    data, final, info = download_bytes(url, max_mb * 1024 * 1024)
                    if data is None:
                        log.append(f'v{v["id"]} {name}: {info}'); continue
                    if data[:15].lower().startswith(b'<!doctype html') or data[:6].lower() == b'<html>':
                        log.append(f'v{v["id"]} {name}: got html (login?)'); continue
                    save_payload(d, v['id'], name, data, log)
                except urllib.error.HTTPError as e:
                    log.append(f'v{v["id"]} {name}: HTTP {e.code} (需登录/付费?)')
                except Exception as e:
                    log.append(f'v{v["id"]} {name}: ERR {e}')
                time.sleep(0.5)
        write_meta(d, m, {'download_log': log})
        open(done_marker, 'w').write('1')
        status[k] = 'ok' if any(x.startswith(('extracted', 'saved')) for x in log) else 'nofile'
        print(k, status[k], m['name'][:60])
    json.dump(status, open(os.path.join(root, '_catalog', 'wf_status.json'), 'w'), indent=1)


def cmd_sidefiles(root, max_mb=20):
    """LoRA/Checkpoint 页面附带的示例工作流（.json/.zip 附件，非权重）。"""
    cat = json.load(open(os.path.join(root, '_catalog', 'models.json'), encoding='utf-8'))
    for k, m in cat.items():
        if m['type'] == 'Workflows' or not set(m.get('categories', [])) & {'h3', 'qwen21', 'qwen', 'post'}:
            continue
        cand = [(v, f) for v in m['versions'][:3] for f in v['files']
                if (f.get('name') or '').lower().endswith(SAFE_EXT + ('.zip',)) and (f.get('sizeKB') or 0) <= max_mb * 1024]
        if not cand:
            continue
        d = model_dir(root, m); os.makedirs(d, exist_ok=True)
        if os.path.exists(os.path.join(d, '.done')):
            continue
        log = []
        for v, f in cand:
            try:
                data, final, info = download_bytes(f['downloadUrl'], max_mb * 1024 * 1024)
                if data is None:
                    log.append(f"{f['name']}: {info}"); continue
                if data[:15].lower().startswith(b'<!doctype html'):
                    log.append(f"{f['name']}: got html (login?)"); continue
                save_payload(d, v['id'], f['name'], data, log)
            except urllib.error.HTTPError as e:
                log.append(f"{f['name']}: HTTP {e.code}")
            except Exception as e:
                log.append(f"{f['name']}: ERR {e}")
            time.sleep(0.5)
        write_meta(d, m, {'download_log': log, 'note': 'LoRA/模型页附带的工作流附件；权重本身不在此目录'})
        open(os.path.join(d, '.done'), 'w').write('1')
        print(k, m['type'], m['name'][:60], len(log))


def cmd_images(root, per=12):
    cat = json.load(open(os.path.join(root, '_catalog', 'models.json'), encoding='utf-8'))
    out_dir = os.path.join(root, '_catalog', 'images'); os.makedirs(out_dir, exist_ok=True)
    for k, m in cat.items():
        if not m['versions'] or not set(m.get('categories', [])) & {'h3', 'qwen21', 'qwen', 'post'}:
            continue
        if m['type'] not in ('LORA', 'Workflows', 'Checkpoint', 'UNet', 'LoCon', 'DoRA'):
            continue
        v = m['versions'][0]
        fp = os.path.join(out_dir, f"{k}.json")
        if os.path.exists(fp):
            continue
        try:
            d = get_json(f"{API}/images?" + urllib.parse.urlencode({'modelVersionId': v['id'], 'limit': per, 'sort': 'Most Reactions'}))
        except Exception as e:
            print('ERR', k, e); continue
        recs = []
        for it in d.get('items', []):
            meta = it.get('meta') or {}
            rec = {'id': it.get('id'), 'url': it.get('url'), 'type': it.get('type'), 'w': it.get('width'), 'h': it.get('height'),
                   'nsfwLevel': it.get('nsfwLevel'), 'stats': it.get('stats'), 'meta': meta}
            recs.append(rec)
            wf = meta.get('comfy') or meta.get('workflow')
            if wf and m['type'] == 'Workflows' or wf:
                try:
                    obj = json.loads(wf) if isinstance(wf, str) else wf
                    md = model_dir(root, m) if m['type'] == 'Workflows' else os.path.join(out_dir, 'wf')
                    os.makedirs(md, exist_ok=True)
                    json.dump(obj, open(os.path.join(md, f"img{it.get('id')}__{k}__workflow.json"), 'w', encoding='utf-8'), ensure_ascii=False)
                except Exception:
                    pass
        json.dump(recs, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        time.sleep(0.4)
    print('images done')


def _png_texts(b):
    out = {}
    if not b.startswith(b'\x89PNG'):
        return out
    i = 8
    while i + 8 <= len(b):
        ln = int.from_bytes(b[i:i + 4], 'big'); typ = b[i + 4:i + 8]; data = b[i + 8:i + 8 + ln]
        if typ == b'tEXt' and b'\x00' in data:
            k, v = data.split(b'\x00', 1); out[k.decode('latin1')] = v.decode('utf-8', 'replace')
        elif typ == b'iTXt' and b'\x00' in data:
            k, rest = data.split(b'\x00', 1)
            if rest[:1] == b'\x00':  # 未压缩
                parts = rest[2:].split(b'\x00', 2)
                if len(parts) == 3:
                    out[k.decode('latin1')] = parts[2].decode('utf-8', 'replace')
        if typ == b'IEND':
            break
        i += 12 + ln
    return out


def _scan_json(b):
    """在任意二进制里找 ComfyUI 工作流 JSON（UI 格式含 "nodes"，API 格式含 "class_type"）。只解析，不执行。"""
    found, dec = [], json.JSONDecoder()
    s = b.decode('latin1')
    for key in ('"last_node_id"', '"class_type"'):
        start = 0
        while True:
            j = s.find(key, start)
            if j < 0:
                break
            # 回溯到最近的 '{' 起点，逐个尝试
            k = j
            for _ in range(400):
                k = s.rfind('{', 0, k)
                if k < 0:
                    break
                try:
                    txt = b[k:k + 8_000_000].decode('utf-8', 'ignore')
                    obj, end = dec.raw_decode(txt)
                    if isinstance(obj, dict) and (('nodes' in obj) or any(isinstance(v, dict) and 'class_type' in v for v in obj.values())):
                        found.append(obj); start = j + 1; break
                except Exception:
                    pass
            else:
                pass
            start = max(start, j + 1)
            if len(found) >= 4:
                break
    return found


def _fetch(url, rng=None, cap=45 * 1024 * 1024):
    h = {'User-Agent': UA}
    if rng:
        h['Range'] = f'bytes=0-{rng}'
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(cap + 1)


def _media_one(root, k, m, rec):
    url = rec.get('url') or ''
    if not url:
        return []
    try:
        b = _fetch(url, rng=3_000_000)
        objs = []
        if b.startswith(b'\x89PNG'):
            if len(b) >= 3_000_000:
                b = _fetch(url)
            t = _png_texts(b)
            for key in ('workflow', 'prompt'):
                if key in t:
                    try:
                        objs.append(json.loads(t[key]))
                    except Exception:
                        pass
        else:
            objs = _scan_json(b)
            if not objs and len(b) >= 3_000_000:
                # moov 在文件尾（非 faststart）时，只取尾部 4MB，不拉整片
                req = urllib.request.Request(url, headers={'User-Agent': UA, 'Range': 'bytes=-4000000'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    objs = _scan_json(r.read(4_100_000))
        return objs
    except Exception as e:
        return [{'__error__': str(e)}]


def cmd_media(root, per_wf=3, per_other=2, workers=16, min_dl=3000, keep=()):
    keep = set(map(str, keep))
    """下载示例图/视频原件（只读字节），抽出内嵌的 ComfyUI 工作流 JSON；媒体本身不落盘。"""
    from concurrent.futures import ThreadPoolExecutor
    cat = json.load(open(os.path.join(root, '_catalog', 'models.json'), encoding='utf-8'))
    img_dir = os.path.join(root, '_catalog', 'images')
    jobs = []
    for k, m in cat.items():
        fp = os.path.join(img_dir, f'{k}.json')
        if not os.path.exists(fp):
            continue
        d = model_dir(root, m)
        if os.path.exists(os.path.join(d, '.media_done')):
            continue
        if m['type'] != 'Workflows' and str(k) not in keep and (m['stats'].get('downloadCount') or 0) < min_dl:
            continue  # 非工作流、非重点、下载量低的 LoRA/模型跳过（多为风格/人物 LoRA）
        recs = json.load(open(fp, encoding='utf-8'))
        n = per_wf if m['type'] == 'Workflows' else per_other
        jobs.append((k, m, recs[:n]))
    lock_count = {'wf': 0}

    def work(job):
        k, m, recs = job
        d = model_dir(root, m); os.makedirs(d, exist_ok=True)
        seen, saved, errs = set(), [], []
        for rec in recs:
            for obj in _media_one(root, k, m, rec):
                if '__error__' in obj:
                    errs.append(obj['__error__']); continue
                txt = json.dumps(obj, ensure_ascii=False, sort_keys=True)
                h = hashlib.sha1(txt.encode()).hexdigest()[:10]
                if h in seen:
                    continue
                seen.add(h)
                kind = 'ui' if 'nodes' in obj else 'api'
                fn = f"media{rec.get('id')}__{kind}_{h}.json"
                json.dump(obj, open(os.path.join(d, fn), 'w', encoding='utf-8'), ensure_ascii=False)
                saved.append({'file': fn, 'source': rec.get('url'), 'type': rec.get('type'), 'w': rec.get('w'), 'h': rec.get('h')})
        if not os.path.exists(os.path.join(d, 'meta.json')):
            write_meta(d, m)
        json.dump({'saved': saved, 'errors': errs}, open(os.path.join(d, 'media_workflows.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        open(os.path.join(d, '.media_done'), 'w').write('1')
        return k, len(saved), len(errs)

    with ThreadPoolExecutor(workers) as ex:
        for k, ns, ne in ex.map(work, jobs):
            if ns:
                lock_count['wf'] += 1
            print(k, ns, ne, flush=True)
    print('models with media workflows:', lock_count['wf'], '/', len(jobs))


def cmd_summary(root):
    cat = json.load(open(os.path.join(root, '_catalog', 'models.json'), encoding='utf-8'))
    rows = sorted(cat.values(), key=lambda m: -(m['stats'].get('downloadCount') or 0))
    for m in rows:
        v = m['versions'][0] if m['versions'] else {}
        print(f"{m['id']}\t{m['type']}\t{v.get('baseModel')}\t{m['stats'].get('downloadCount')}\t{m['stats'].get('thumbsUpCount')}\t{','.join(m['categories'])}\t{m['name'][:80]}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['catalog', 'workflows', 'sidefiles', 'images', 'media', 'summary'])
    ap.add_argument('--root', default=DEFAULT_ROOT)
    ap.add_argument('--max-mb', type=int, default=60)
    ap.add_argument('--keep', default='', help='media: 必抽的 modelId 列表（逗号分隔）')
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    {'catalog': lambda: cmd_catalog(a.root), 'workflows': lambda: cmd_workflows(a.root, a.max_mb),
     'images': lambda: cmd_images(a.root), 'sidefiles': lambda: cmd_sidefiles(a.root), 'media': lambda: cmd_media(a.root, keep=[x for x in a.keep.split(',') if x]), 'summary': lambda: cmd_summary(a.root)}[a.cmd]()
