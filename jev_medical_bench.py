"""
Decision model (Jev) vs chat LLMs on medical decision tasks.

Six task types, mapped to Jev's three primitives:
    triage      score   ESI level 1-5 (exact + within-one-level accuracy)
    ed_referral noul    does this patient need the ED today?
    specialty   choice  which specialist clinic?
    rx_safety   noul    is this prescription unsafe for this patient?
    diagnosis   choice  most likely diagnosis, 4 options
    management  choice  next best step, 4 options (hard set only)

Every case is tagged easy or hard. Hard cases bury the decisive detail
(a vital sign, a drug, a history item) under a benign-sounding story, which
tests the claim that judgment without a reasoning trace is shallow.

Models are defined in config.json (copy config.example.json). Two types:
    decision  a Jev-style decisions endpoint (state + typed questions -> answers)
    chat      any OpenAI-compatible /chat/completions endpoint

Usage:
    python jev_medical_bench.py                      # all models in config.json, basic set
    python jev_medical_bench.py --dataset hard       # the complex case set
    python jev_medical_bench.py --models jev,qwen    # subset, by config key
    python jev_medical_bench.py --limit 10           # quick smoke test
    python jev_medical_bench.py --config my.json     # another config file

Cases live in data/*.json; edit or extend them and later runs will use them.
"""

import argparse
import csv
import json
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / 'data' / 'basic.json'
HARD_PATH = HERE / 'data' / 'hard.json'
RESULTS_DIR = HERE / 'results'
CONFIG_PATH = HERE / 'config.json'


def load_config(path):
    if not path.exists():
        raise SystemExit(f'{path.name} not found. Copy config.example.json to config.json and fill in your endpoints.')
    models = json.loads(path.read_text(encoding='utf-8'))['models']
    for m in models:
        # keys are read from an environment variable named in the config, never stored in it
        env = m.get('api_key_env')
        m['api_key'] = os.environ.get(env) if env else None
        if env and not m['api_key']:
            raise SystemExit(f'Model "{m["key"]}" needs the environment variable {env} (its API key).')
    return {m['key']: m for m in models}


def usage_cost(m, reported, in_tok, out_tok):
    # prefer the cost the endpoint reports; else price_in / price_out (USD per 1M tokens) from config
    if reported is not None:
        return reported
    if 'price_in' in m and in_tok is not None:
        return (in_tok * m['price_in'] + (out_tok or 0) * m.get('price_out', 0)) / 1e6
    return None


# ---------------------------------------------------------------- questions

QUESTIONS = {
    'triage': {
        'type': 'score',
        'instructions': 'Assign the Emergency Severity Index (ESI) triage level for this emergency department patient.',
        # ordinal, least urgent first; index = 5 - ESI
        'criteria': [
            'ESI 5: non-urgent, needs no resources',
            'ESI 4: less urgent, needs one resource',
            'ESI 3: urgent, stable but needs two or more resources',
            'ESI 2: emergent, high-risk situation, confused/lethargic, severe pain, or danger-zone vital signs',
            'ESI 1: resuscitation, needs immediate life-saving intervention',
        ],
    },
    'ed_referral': {
        'type': 'noul',
        'instructions': 'Does this patient need emergency department evaluation today, rather than routine outpatient care?',
        'criteria': {
            'true': 'A time-critical or potentially life-threatening condition is plausible; send to the ED today.',
            'false': 'Safe for routine outpatient or self-care management.',
        },
    },
    'specialty': {
        'type': 'choice',
        'instructions': 'Which specialist clinic should this patient be referred to?',
        'criteria': {
            'cardiology': 'Heart and circulation',
            'neurology': 'Brain, nerves, headache, seizures',
            'gastroenterology': 'Gut, liver, oesophagus',
            'pulmonology': 'Lungs and airways',
            'endocrinology': 'Hormones, diabetes, thyroid',
            'dermatology': 'Skin, hair, nails',
            'psychiatry': 'Mental health',
            'rheumatology': 'Autoimmune and inflammatory joint disease',
            'nephrology': 'Kidney function',
        },
    },
    'rx_safety': {
        'type': 'noul',
        'instructions': 'Is the proposed prescription unsafe for this specific patient?',
        'criteria': {
            'true': 'Unsafe: contraindication, allergy, dangerous interaction, or wrong dose.',
            'false': 'Acceptable as prescribed.',
        },
    },
    'diagnosis': {
        'type': 'choice',
        'instructions': 'What is the most likely diagnosis?',
        'criteria': None,   # per case: the A-D options
    },
    'management': {
        'type': 'choice',
        'instructions': 'What is the most appropriate next step in management?',
        'criteria': None,   # per case: the A-D options
    },
}

# ---------------------------------------------------------------- built-in dataset
# gold for triage is the ESI number; for noul it is 'true'/'false'.

BUILTIN_CASES = [
    # triage
    dict(id='t01', task='triage', level='easy', gold=1,
         text='67-year-old man found unresponsive at home. Agonal respirations, SpO2 78% on room air, weak carotid pulse.'),
    dict(id='t02', task='triage', level='easy', gold=4,
         text='24-year-old woman twisted her ankle playing badminton 2 hours ago. Walks with a limp, mild swelling. HR 78, BP 118/72, pain 3/10. Wants an X-ray.'),
    dict(id='t03', task='triage', level='easy', gold=5,
         text='30-year-old man ran out of his lisinopril and wants a repeat prescription. No symptoms. BP 132/84, HR 70.'),
    dict(id='t04', task='triage', level='easy', gold=2,
         text='55-year-old man with 30 minutes of central chest pressure, sweating, nauseated. HR 98, BP 150/90, SpO2 97%.'),
    dict(id='t05', task='triage', level='easy', gold=4,
         text='19-year-old woman cut her forearm on glass. 3 cm clean laceration, bleeding controlled with pressure, needs sutures. Vitals normal.'),
    dict(id='t06', task='triage', level='easy', gold=3,
         text='45-year-old woman with 12 hours of right lower quadrant abdominal pain and nausea. Temp 38.2, HR 96, BP 124/80. Pain 6/10.'),
    dict(id='t07', task='triage', level='hard', gold=2,
         text='26-year-old woman, chatty and smiling, says she has "a bit of period-type pain" low in the abdomen and wants painkillers. Mentions her period is about 3 weeks late. HR 118, BP 96/60.'),
    dict(id='t08', task='triage', level='hard', gold=2,
         text='34-year-old man with a sore throat for 3 days, asking for antibiotics. Talks in a muffled voice, keeps spitting into a tissue because swallowing his saliva hurts too much. Temp 38.9, HR 104, SpO2 98%.'),
    dict(id='t09', task='triage', level='hard', gold=2,
         text='80-year-old woman tripped at home and "just bumped her head", small bruise on forehead, GCS 15, normal vitals. Daughter mentions she takes warfarin for atrial fibrillation.'),
    dict(id='t10', task='triage', level='hard', gold=2,
         text='40-year-old man says he only needs a sick note for work after "a bad cold" for 4 days. Speaks in short sentences. Temp 38.6, HR 112, RR 28, SpO2 89% on room air.'),

    # ED referral
    dict(id='e01', task='ed_referral', level='easy', gold='true',
         text='72-year-old man, sudden right arm weakness, right facial droop and slurred speech that began 40 minutes ago.'),
    dict(id='e02', task='ed_referral', level='easy', gold='false',
         text='28-year-old woman with 3 days of runny nose and mild dry cough. Afebrile, eating and drinking normally, no breathlessness.'),
    dict(id='e03', task='ed_referral', level='easy', gold='true',
         text='35-year-old man ate a satay sauce 15 minutes ago, now has hives, swollen lips and is wheezing. Known peanut allergy.'),
    dict(id='e04', task='ed_referral', level='easy', gold='false',
         text='50-year-old man with 6 months of right knee pain on stairs, worse after long walks. No injury, no swelling, no fever.'),
    dict(id='e05', task='ed_referral', level='easy', gold='false',
         text='16-year-old girl whose facial acne has worsened over the past year. Otherwise well.'),
    dict(id='e06', task='ed_referral', level='easy', gold='true',
         text='60-year-old man vomited a cup of bright red blood this morning and feels dizzy when standing.'),
    dict(id='e07', task='ed_referral', level='hard', gold='true',
         text='45-year-old woman had a headache start within seconds while lifting weights 6 hours ago, "the worst of my life". It has eased to a dull ache and she feels mostly fine now, just wants advice on painkillers.'),
    dict(id='e08', task='ed_referral', level='hard', gold='true',
         text='29-year-old woman, 2 weeks after a caesarean section, asking about compression socks because her left calf is swollen and sore. Mentions she gets a bit short of breath climbing stairs since yesterday.'),
    dict(id='e09', task='ed_referral', level='hard', gold='false',
         text='38-year-old man, very anxious he has a brain tumour. Band-like pressure headache across both temples, worse with work stress, same pattern for 5 years. No vomiting, no visual change, no weakness, normal neurological exam.'),
    dict(id='e10', task='ed_referral', level='hard', gold='true',
         text='8-month-old baby with fever 38.5 since this morning, a bit fussy but feeding. Mother noticed a few small purple spots on the legs that do not fade when pressed with a glass.'),

    # specialty
    dict(id='s01', task='specialty', level='easy', gold='cardiology',
         text='62-year-old man with hypertension, chest tightness on walking uphill that settles with rest within 5 minutes.'),
    dict(id='s02', task='specialty', level='easy', gold='dermatology',
         text='35-year-old with well-demarcated itchy silvery scaly plaques on elbows and knees for a year.'),
    dict(id='s03', task='specialty', level='easy', gold='endocrinology',
         text='48-year-old woman, thirst and passing urine often, HbA1c 9.1% despite metformin.'),
    dict(id='s04', task='specialty', level='easy', gold='psychiatry',
         text='27-year-old with 2 months of low mood, loss of interest in everything, early waking and thoughts that life is not worth living.'),
    dict(id='s05', task='specialty', level='easy', gold='gastroenterology',
         text='58-year-old man with years of heartburn, now food sticking in his chest when swallowing solids.'),
    dict(id='s06', task='specialty', level='easy', gold='neurology',
         text='30-year-old woman with recurrent one-sided throbbing headaches preceded by zig-zag lines in her vision.'),
    dict(id='s07', task='specialty', level='hard', gold='rheumatology',
         text='32-year-old woman worried about a red rash across her cheeks after sun exposure. Also has painful swollen finger joints on both hands with an hour of morning stiffness, mouth ulcers, and trace protein on urine dipstick.'),
    dict(id='s08', task='specialty', level='hard', gold='pulmonology',
         text='64-year-old man, breathless on exertion for a year, dry cough, finger clubbing, fine "velcro" crackles at both lung bases. Echocardiogram and BNP are normal.'),
    dict(id='s09', task='specialty', level='hard', gold='endocrinology',
         text='28-year-old woman referred for palpitations and a fast heart rate of 110. Also lost 5 kg without trying, hands tremble, always feels hot, and has a smooth swelling at the front of her neck. ECG sinus tachycardia only.'),
    dict(id='s10', task='specialty', level='hard', gold='nephrology',
         text='55-year-old man with ankle swelling and tiredness. Creatinine rose from 105 to 210 umol/L over 6 months, eGFR 28, urine frothy with 3+ protein. Heart examination and echo unremarkable.'),

    # prescription safety
    dict(id='r01', task='rx_safety', level='easy', gold='true',
         text='Patient: 40-year-old woman, allergy list: penicillin (anaphylaxis). Prescription: amoxicillin 500 mg three times daily for 7 days for sinusitis.'),
    dict(id='r02', task='rx_safety', level='easy', gold='false',
         text='Patient: healthy 30-year-old man, no allergies, no regular medicines, confirmed strep throat. Prescription: amoxicillin 500 mg three times daily for 10 days.'),
    dict(id='r03', task='rx_safety', level='easy', gold='true',
         text='Patient: 28-year-old woman, 10 weeks pregnant. Prescription: isotretinoin 20 mg daily for acne.'),
    dict(id='r04', task='rx_safety', level='easy', gold='false',
         text='Patient: 45-year-old woman with newly diagnosed hypertension, no other conditions or medicines. Prescription: amlodipine 5 mg once daily.'),
    dict(id='r05', task='rx_safety', level='hard', gold='true',
         text='Patient: 70-year-old man with a chest infection. Regular medicines: simvastatin 40 mg nightly, aspirin 75 mg. Prescription: clarithromycin 500 mg twice daily for 7 days.'),
    dict(id='r06', task='rx_safety', level='hard', gold='true',
         text='Patient: 65-year-old woman with a urinary tract infection. Regular medicines: methotrexate 15 mg once weekly for rheumatoid arthritis, folic acid. Prescription: trimethoprim-sulfamethoxazole 960 mg twice daily for 3 days.'),
    dict(id='r07', task='rx_safety', level='hard', gold='true',
         text='Patient: 58-year-old man with type 2 diabetes, latest eGFR 22 mL/min/1.73m2. Prescription: metformin 1000 mg twice daily.'),
    dict(id='r08', task='rx_safety', level='hard', gold='true',
         text='Patient: 44-year-old woman with treatment-resistant depression, currently on phenelzine 15 mg three times daily. Prescription: add sertraline 50 mg daily.'),
    dict(id='r09', task='rx_safety', level='hard', gold='false',
         text='Patient: 72-year-old woman, 64 kg, atrial fibrillation on apixaban 5 mg twice daily, normal liver function, knee osteoarthritis. Prescription: paracetamol 1 g three times daily.'),
    dict(id='r10', task='rx_safety', level='hard', gold='false',
         text='Patient: 50-year-old man with type 2 diabetes, eGFR 55 mL/min/1.73m2, stable. Prescription: metformin 500 mg twice daily.'),

    # diagnosis
    dict(id='d01', task='diagnosis', level='easy', gold='C',
         text='52-year-old man, 3 days of fever, productive cough of rusty sputum, right-sided pleuritic pain. Chest X-ray: right lower lobe consolidation.',
         options={'A': 'Asthma exacerbation', 'B': 'Pulmonary embolism', 'C': 'Community-acquired pneumonia', 'D': 'Pneumothorax'}),
    dict(id='d02', task='diagnosis', level='easy', gold='A',
         text='25-year-old woman with 2 days of burning on urination and frequency. No fever, no flank pain. Urine dipstick nitrite and leukocytes positive.',
         options={'A': 'Uncomplicated cystitis', 'B': 'Pyelonephritis', 'C': 'Renal colic', 'D': 'Chlamydia'}),
    dict(id='d03', task='diagnosis', level='easy', gold='D',
         text='Tall thin 20-year-old man, sudden sharp right chest pain and breathlessness at rest. Reduced breath sounds and hyper-resonance on the right.',
         options={'A': 'Pneumonia', 'B': 'Pericarditis', 'C': 'Costochondritis', 'D': 'Spontaneous pneumothorax'}),
    dict(id='d04', task='diagnosis', level='easy', gold='B',
         text='60-year-old man woke with an exquisitely painful, red, swollen big toe joint after a night of beer and seafood.',
         options={'A': 'Cellulitis', 'B': 'Gout', 'C': 'Osteoarthritis', 'D': 'Stress fracture'}),
    dict(id='d05', task='diagnosis', level='easy', gold='B',
         text='6-year-old with fever 38.8, sore throat, tonsillar exudate, tender anterior neck nodes, no cough.',
         options={'A': 'Viral common cold', 'B': 'Streptococcal pharyngitis', 'C': 'Epiglottitis', 'D': 'Allergic rhinitis'}),
    dict(id='d06', task='diagnosis', level='hard', gold='C',
         text='32-year-old woman says she is depressed: low mood, tired all the time, gained 6 kg, constipated. On examination dry skin, puffy face, cold hands, slow-relaxing ankle reflexes.',
         options={'A': 'Major depressive disorder', 'B': 'Iron deficiency anaemia', 'C': 'Hypothyroidism', 'D': 'Chronic fatigue syndrome'}),
    dict(id='d07', task='diagnosis', level='hard', gold='A',
         text='55-year-old man with heavy alcohol use brought in confused and unsteady. Alcohol level is low. Horizontal nystagmus and bilateral lateral gaze weakness, wide-based gait.',
         options={'A': 'Wernicke encephalopathy', 'B': 'Acute alcohol intoxication', 'C': 'Hepatic encephalopathy', 'D': 'Cerebellar stroke'}),
    dict(id='d08', task='diagnosis', level='hard', gold='D',
         text='62-year-old man with diabetes, epigastric discomfort and nausea since resting after lunch, thinks it is indigestion. Serum lipase normal. ECG: ST elevation in leads II, III and aVF.',
         options={'A': 'Acute pancreatitis', 'B': 'Peptic ulcer disease', 'C': 'Biliary colic', 'D': 'Inferior myocardial infarction'}),
    dict(id='d09', task='diagnosis', level='hard', gold='B',
         text='28-year-old woman with right lower abdominal pain and a little vaginal spotting. Urine hCG positive. Transvaginal ultrasound: no intrauterine pregnancy, free fluid in the pouch of Douglas.',
         options={'A': 'Appendicitis', 'B': 'Ectopic pregnancy', 'C': 'Ovarian torsion', 'D': 'Threatened miscarriage'}),
    dict(id='d10', task='diagnosis', level='hard', gold='A',
         text='75-year-old woman with a new headache for 3 weeks, pain in the jaw when chewing, tender scalp when brushing her hair. ESR 90 mm/h.',
         options={'A': 'Giant cell arteritis', 'B': 'Migraine', 'C': 'Trigeminal neuralgia', 'D': 'Temporomandibular joint disorder'}),
]


def load_cases(path, regen=False):
    if path == DATASET_PATH and (regen or not path.exists()):
        path.write_text(json.dumps(BUILTIN_CASES, indent=2, ensure_ascii=False), encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8'))


def question_for(case):
    q = dict(QUESTIONS[case['task']])
    if 'options' in case:
        q['criteria'] = case['options']
    return q


def gold_key(case):
    # everything is compared as a string key; triage ESI -> score index
    if case['task'] == 'triage':
        return str(5 - int(case['gold']))
    return str(case['gold'])


def option_keys(q):
    if q['type'] == 'noul':
        return ['true', 'false']
    if q['type'] == 'score':
        return [str(i) for i in range(len(q['criteria']))]
    return list(q['criteria'].keys())


# ---------------------------------------------------------------- callers

def auth_headers(m):
    return {'Authorization': f'Bearer {m["api_key"]}'} if m.get('api_key') else {}


def call_decision(client, m, case):
    q = question_for(case)
    body = {'model': m['model'], 'state': {'case': case['text']}, 'questions': {'q': q}}
    r = client.post(m['url'], json=body, headers=auth_headers(m))
    r.raise_for_status()
    data = r.json()
    a = data['answers']['q']
    if a['type'] == 'noul':
        p = float(a['noul'])
        pred, conf = ('true' if p >= 0.5 else 'false'), max(p, 1 - p)
    elif a['type'] == 'choice':
        pred, conf = a['choice'], a.get('confidence')
    else:
        probs = a['probabilities']
        pred = max(probs, key=lambda k: probs[k])
        conf = a.get('confidence')
    u = data.get('usage') or {}
    in_tok, out_tok = u.get('input_tokens'), u.get('output_tokens')
    return dict(pred=str(pred), conf=conf, cost=usage_cost(m, u.get('cost'), in_tok, out_tok),
                in_tok=in_tok, out_tok=out_tok, reason_tok=0,
                raw=json.dumps(a, ensure_ascii=False))


def llm_prompt(case, think):
    q = question_for(case)
    keys = option_keys(q)
    if q['type'] == 'noul':
        opts = [f'- true: {q["criteria"]["true"]}', f'- false: {q["criteria"]["false"]}']
    elif q['type'] == 'score':
        opts = [f'- {i}: {c}' for i, c in enumerate(q['criteria'])]
    else:
        opts = [f'- {k}: {v}' for k, v in q['criteria'].items()]
    tail = ('Think it through step by step, then end with a final line exactly in the form\nANSWER: <key>'
            if think else
            'Reply with JSON only, no other text: {"answer": "<key>"}')
    return (f'You are a clinical decision assistant.\n\nCase:\n{case["text"]}\n\n'
            f'Question: {q["instructions"]}\n\nAllowed answers (use the key on the left):\n'
            + '\n'.join(opts) + f'\n\nValid keys: {", ".join(keys)}\n\n{tail}')


def parse_answer(text, keys):
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    lower = {k.lower(): k for k in keys}
    cands = re.findall(r'ANSWER:\s*"?([A-Za-z0-9_]+)', text) or re.findall(r'"answer"\s*:\s*"?([A-Za-z0-9_]+)', text)
    if not cands and text.strip('"\' .').lower() in lower:
        cands = [text.strip('"\' .')]
    if cands and cands[-1].lower() in lower:
        return lower[cands[-1].lower()]
    return None   # invalid output


def call_chat(client, m, case):
    q = question_for(case)
    think = m.get('think', False)
    body = {'model': m['model'], 'max_tokens': m.get('max_tokens', 8000 if think else 200), 'temperature': 0,
            'messages': [{'role': 'user', 'content': llm_prompt(case, think)}], **m.get('extra_body', {})}
    r = client.post(f'{m["base_url"].rstrip("/")}/chat/completions', json=body, headers=auth_headers(m))
    r.raise_for_status()
    data = r.json()
    content = data['choices'][0]['message'].get('content') or ''
    u = data.get('usage') or {}
    # output tokens include reasoning; some servers report the reasoning share separately, others do not
    reason = (u.get('completion_tokens_details') or {}).get('reasoning_tokens')
    in_tok, out_tok = u.get('prompt_tokens'), u.get('completion_tokens')
    return dict(pred=parse_answer(content, option_keys(q)), conf=None,
                cost=usage_cost(m, u.get('cost'), in_tok, out_tok),
                in_tok=in_tok, out_tok=out_tok, reason_tok=reason, raw=content[-300:])


CALLERS = {'decision': call_decision, 'chat': call_chat}


def run_model(mkey, m, cases, workers):
    client = httpx.Client(proxy=m.get('proxy') or None, timeout=m.get('timeout', 600))
    fn = CALLERS[m['type']]

    def one(case):
        err = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                out = fn(client, m, case)
                break
            except Exception as e:
                err = str(e)[:200]
                time.sleep(2 * (attempt + 1))
        else:
            out = dict(pred=None, conf=None, cost=None, in_tok=None, out_tok=None, reason_tok=None,
                       raw=f'ERROR {err}')
        latency = time.perf_counter() - t0
        gold = gold_key(case)
        correct = out['pred'] == gold
        within1 = None
        if case['task'] == 'triage' and out['pred'] is not None:
            within1 = abs(int(out['pred']) - int(gold)) <= 1
        print(f'  {m["name"]:<28} {case["id"]}  pred={out["pred"]!s:<16} gold={gold:<16} '
              f'{"OK " if correct else "XX "} {latency:6.2f}s')
        return dict(model=m['name'], model_key=mkey, id=case['id'], task=case['task'], level=case['level'],
                    gold=gold, pred=out['pred'], correct=correct, within1=within1,
                    invalid=out['pred'] is None, conf=out['conf'], latency=latency,
                    cost=out['cost'], in_tok=out['in_tok'], out_tok=out['out_tok'],
                    reason_tok=out['reason_tok'], raw=out['raw'])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, cases))
    client.close()
    return rows


# ---------------------------------------------------------------- reporting

def pct(xs):
    xs = list(xs)
    return f'{100 * sum(xs) / len(xs):.0f}%' if xs else '-'


def md_table(headers, rows):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    line = lambda cells: '| ' + ' | '.join(str(c).ljust(w) for c, w in zip(cells, widths)) + ' |'
    return '\n'.join([line(headers), '|' + '|'.join('-' * (w + 2) for w in widths) + '|']
                     + [line(r) for r in rows])


def report(all_rows, model_order, n_cases, decision_keys=()):
    out = []
    by_model = {k: [r for r in all_rows if r['model_key'] == k] for k in model_order}

    rows = []
    for k, rs in by_model.items():
        lat = sorted(r['latency'] for r in rs)
        costs = [r['cost'] for r in rs if r['cost'] is not None]
        cost_1k = f'${1000 * sum(costs) / len(rs):.3f}' if costs else '-'
        rows.append([rs[0]['model'], pct(r['correct'] for r in rs),
                     pct(r['correct'] for r in rs if r['level'] == 'easy'),
                     pct(r['correct'] for r in rs if r['level'] == 'hard'),
                     pct(r['invalid'] for r in rs),
                     f'{statistics.mean(lat):.2f}s', f'{statistics.median(lat):.2f}s',
                     f'{lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.2f}s', cost_1k])
    out.append(f'## Overall ({n_cases} cases)\n\n' + md_table(
        ['Model', 'Accuracy', 'Easy', 'Hard', 'Invalid', 'Avg latency', 'p50', 'p95', 'Cost / 1000 calls'], rows))

    def avg(rs, f):
        xs = [r[f] for r in rs if r[f] is not None]
        return f'{statistics.mean(xs):,.0f}' if xs else '-'

    def total(rs, f):
        xs = [r[f] for r in rs if r[f] is not None]
        return sum(xs) if xs else None

    rows = []
    for k, rs in by_model.items():
        tin, tout, cost = total(rs, 'in_tok'), total(rs, 'out_tok'), total(rs, 'cost')
        rows.append([rs[0]['model'], avg(rs, 'in_tok'), avg(rs, 'out_tok'), avg(rs, 'reason_tok'),
                     f'{(tin or 0) + (tout or 0):,}' if tin is not None else '-',
                     f'${cost:.4f}' if cost is not None else '-'])
    out.append(f'## Tokens and cost (this run, {n_cases} calls per model)\n\n' + md_table(
        ['Model', 'Avg input tokens', 'Avg output tokens', 'Avg reasoning tokens', 'Total tokens', 'Total cost'], rows)
        + '\n\nOutput tokens include reasoning tokens. "-" means the server did not report that number '
          '(set price_in / price_out in config.json to compute cost from tokens).')

    tasks = [t for t in QUESTIONS if any(r['task'] == t for r in all_rows)]
    rows = []
    for k, rs in by_model.items():
        cells = [rs[0]['model']]
        for t in tasks:
            cells.append(pct(r['correct'] for r in rs if r['task'] == t))
        cells.append(pct(r['within1'] for r in rs if r['task'] == 'triage' and r['within1'] is not None))
        rows.append(cells)
    out.append('## Accuracy by task\n\n' + md_table(['Model'] + tasks + ['triage within 1'], rows))

    for k in decision_keys:
        jev = by_model[k]
        rows = []
        for th in (0.0, 0.6, 0.7, 0.8, 0.9):
            kept = [r for r in jev if r['conf'] is not None and r['conf'] >= th]
            rows.append([f'>= {th:.1f}', pct([True] * len(kept) + [False] * (len(jev) - len(kept))),
                         pct(r['correct'] for r in kept), len(jev) - len(kept)])
        out.append(f'## {jev[0]["model"]} as a gate (confident answers kept, the rest escalate to a reasoning model)\n\n'
                   + md_table(['Confidence', 'Coverage', 'Accuracy on kept', 'Escalated'], rows))

    rows = []
    ids = sorted({r['id'] for r in all_rows})
    for cid in ids:
        rs = {r['model_key']: r for r in all_rows if r['id'] == cid}
        first = next(iter(rs.values()))
        rows.append([cid, first['task'], first['level'], first['gold']]
                    + [('ok' if rs[k]['correct'] else f'x {rs[k]["pred"]}') if k in rs else '-' for k in model_order])
    out.append('## Per case\n\n' + md_table(['Case', 'Task', 'Level', 'Gold'] + [by_model[k][0]['model'] for k in model_order], rows))
    return '\n\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(CONFIG_PATH))
    ap.add_argument('--models', default='', help='comma-separated config keys; default all')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--regen', action='store_true')
    ap.add_argument('--dataset', default='basic',
                    help='basic (data/basic.json), hard (data/hard.json), or a json path')
    args = ap.parse_args()

    ds_path = {'basic': DATASET_PATH, 'hard': HARD_PATH}.get(args.dataset, Path(args.dataset))
    cases = load_cases(ds_path, args.regen)
    if args.limit:
        cases = cases[:args.limit]
    models = load_config(Path(args.config))
    order = [k.strip() for k in args.models.split(',') if k.strip()] or list(models)
    bad = [k for k in order if k not in models]
    if bad:
        raise SystemExit(f'unknown model keys: {bad}; choose from {list(models)}')

    all_rows = []
    for k in order:
        print(f'\n== {models[k]["name"]} ({len(cases)} cases)')
        all_rows += run_model(k, models[k], cases, args.workers)

    text = report(all_rows, order, len(cases), [k for k in order if models[k]['type'] == 'decision'])
    print('\n' + text)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir = RESULTS_DIR / f'{stamp}_{ds_path.stem}'   # e.g. results/20260927_044302_basic
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'summary.md').write_text(
        f'# Decision model vs LLMs: medical decisions\n\nRun {stamp}, dataset={ds_path.name}, workers={args.workers}\n\n{text}\n', encoding='utf-8')
    with open(out_dir / 'details.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print(f'\nSaved: {out_dir}')


if __name__ == '__main__':
    main()
