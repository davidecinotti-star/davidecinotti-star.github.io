#!/usr/bin/env python3
import json, re, time, sys, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == 'tools' else Path.cwd()
INDEX = ROOT / 'index.html'
OUT = ROOT / 'translation-output-v493.json'
REPORT = ROOT / 'translation-report-v493.json'
API = 'https://translate.googleapis.com/translate_a/single'
MARK_RE = re.compile(r'\[\[\[SEG(\d{6})\]\]\]')

REPLACEMENTS = [
    (r'\bEuropean Court of Accounts\b', 'European Court of Auditors'),
    (r'\bCourt of Auditors European\b', 'European Court of Auditors'),
    (r'\bfinancial regulation\b', 'Financial Regulation'),
    (r'\bresponsible part\b', 'responsible party'),
    (r'\binformation on the subject\b', 'subject matter information'),
    (r'\bsubject information\b', 'subject matter information'),
    (r'\bdirect report(?:ing)?\b', 'direct reporting'),
    (r'\bcertification engagement\b', 'attestation engagement'),
    (r'\bcompliance review\b', 'compliance audit'),
    (r'\bperformance review\b', 'performance audit'),
    (r'\baudit test\b', 'audit procedure'),
    (r'\brevision evidence\b', 'audit evidence'),
    (r'\bcontrol track\b', 'audit trail'),
    (r'\bshared administration\b', 'shared management'),
    (r'\bmanagement and check system\b', 'management and control system'),
    (r'\bdeclaration of reliability\b', 'statement of assurance'),
]

ITALIAN_HINTS = re.compile(r'\b(il|lo|la|gli|le|un|una|uno|che|della|delle|degli|nel|nella|nelle|perché|quale|quali|deve|sono|può|senza|rispetto|auditore|incarico)\b', re.I)


def extract_data(html: str):
    start = html.find('const D=')
    end = html.find(';\nconst LET=', start)
    if start < 0 or end < 0:
        raise RuntimeError('Embedded data block not found')
    return json.loads(html[start + len('const D='):end])


def request_translation(text: str, attempts: int = 6) -> str:
    params = urllib.parse.urlencode({'client':'gtx','sl':'it','tl':'en','dt':'t','q':text})
    req = urllib.request.Request(API + '?' + params, headers={
        'User-Agent':'Mozilla/5.0 (compatible; EPSO-language-correction/4.9.3)',
        'Accept':'application/json,text/plain,*/*'
    })
    last = None
    for n in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode('utf-8')
            obj = json.loads(raw)
            return ''.join(seg[0] for seg in obj[0] if seg and seg[0])
        except Exception as e:
            last = e
            time.sleep(min(12, 1.5 * (2 ** n)))
    raise RuntimeError(f'Translation request failed: {last}')


def normalize(text: str) -> str:
    text = text.replace('Audit auditor', 'Auditor').replace('audit auditor', 'auditor')
    for pat, repl in REPLACEMENTS:
        text = re.sub(pat, repl, text, flags=re.I)
    text = re.sub(r'\s+([,.;:?!])', r'\1', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def batch_translate(unique_texts):
    translations = {}
    batches = []
    current = []
    current_len = 0
    for idx, text in enumerate(unique_texts):
        marker = f'[[[SEG{idx:06d}]]]'
        piece = marker + '\n' + text + '\n'
        if current and current_len + len(piece) > 3500:
            batches.append(current)
            current, current_len = [], 0
        current.append((idx, text, piece))
        current_len += len(piece)
    if current:
        batches.append(current)

    for bi, batch in enumerate(batches, 1):
        payload = '\n'.join(x[2] for x in batch)
        translated = request_translation(payload)
        matches = list(MARK_RE.finditer(translated))
        parsed = {}
        if len(matches) == len(batch):
            for mi, m in enumerate(matches):
                st = m.end()
                en = matches[mi+1].start() if mi+1 < len(matches) else len(translated)
                parsed[int(m.group(1))] = translated[st:en].strip()
        for idx, original, _ in batch:
            candidate = parsed.get(idx)
            if not candidate:
                candidate = request_translation(original)
                time.sleep(0.12)
            translations[original] = normalize(candidate)
        print(f'batch {bi}/{len(batches)} translated ({len(batch)} segments)', flush=True)
        time.sleep(0.2)
    return translations


def gather_paths(data):
    paths = []
    def add(container, key):
        v = container.get(key) if isinstance(container, dict) else None
        if isinstance(v, str) and v.strip():
            paths.append((container, key, v))

    for q in data['quesiti']:
        for k in ('ctx','stem','why'):
            add(q, k)
        for i, v in enumerate(q.get('opts', [])):
            if isinstance(v, str) and v.strip():
                paths.append((q['opts'], i, v))
        for k, v in q.get('notes', {}).items():
            if isinstance(v, str) and v.strip():
                paths.append((q['notes'], k, v))

    dossier_sets = []
    if isinstance(data.get('eufte'), dict): dossier_sets.append(data['eufte'])
    dossier_sets.extend(data.get('eufte_sims', []))
    for d in dossier_sets:
        for k in ('title','assignment','model','format','recipient'):
            add(d, k)
        for doc in d.get('docs', []):
            add(doc, 't'); add(doc, 'b')
        for row in d.get('rubric', []):
            for i, v in enumerate(row):
                if isinstance(v, str) and v.strip(): paths.append((row, i, v))
        for lst_key in ('checklist','output_requirements'):
            lst = d.get(lst_key, [])
            for i, v in enumerate(lst):
                if isinstance(v, str) and v.strip(): paths.append((lst, i, v))
    return paths


def main():
    html = INDEX.read_text(encoding='utf-8')
    data = extract_data(html)
    paths = gather_paths(data)
    unique = list(dict.fromkeys(v for _,_,v in paths))
    print(f'{len(paths)} fields, {len(unique)} unique strings', flush=True)
    trans = batch_translate(unique)
    for container, key, original in paths:
        container[key] = trans[original]

    data['meta']['versione'] = '4.9.3-lingue-it-en'
    data['meta']['version'] = '4.9.3'
    data['meta']['build'] = 'language-profile-it-en'
    data['meta']['nota'] = ('Language profile corrected: Language 1 Italian for verbal, numerical and abstract reasoning; '
                            'Language 2 English for the field-related MCQ and EUFTE.')
    data['meta']['language_profile'] = {
        'language_1': {'code':'it','label':'Italiano','tests':['verbal reasoning','numerical reasoning','abstract reasoning']},
        'language_2': {'code':'en','label':'English','tests':['field-related MCQ','EUFTE']}
    }
    data['exam_spec']['language_profile'] = data['meta']['language_profile']
    for i, s in enumerate(data.get('specialist_sims', []), 1):
        s['title'] = f'Field-related MCQ {i}'
        s['language'] = 'English (Language 2)'
    for d in data.get('eufte_sims', []):
        d['language'] = 'English (Language 2)'
    for i, fd in enumerate(data.get('full_days', []), 1):
        fd['title'] = f'Complete simulation {i} — IT/EN language profile'
        fd['language_profile'] = 'Reasoning in Italian; field-related MCQ and EUFTE in English'

    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',',':')), encoding='utf-8')
    residuals = []
    for q in data['quesiti']:
        for k in ('ctx','stem','why'):
            if ITALIAN_HINTS.search(q.get(k,'')): residuals.append({'id':q['id'],'field':k,'text':q[k]})
        for i,v in enumerate(q.get('opts', [])):
            if ITALIAN_HINTS.search(v): residuals.append({'id':q['id'],'field':f'opts[{i}]','text':v})
    report = {
        'status':'completed',
        'version':'4.9.3',
        'translated_fields':len(paths),
        'unique_source_strings':len(unique),
        'questions':len(data['quesiti']),
        'eufte_dossiers':len(data.get('eufte_sims', [])),
        'residual_italian_hints_count':len(residuals),
        'residual_italian_hints_sample':residuals[:50]
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
