import json
import unicodedata
import statistics

with open('cases/kx_vi_design_20260713/runs/20260713_165424_271117/timing_lock.json', 'r', encoding='utf-8') as f:
    timing = json.load(f)

with open('cases/kx_vi_design_20260713/input/narration.json', 'r', encoding='utf-8') as f:
    narration = json.load(f)

beats = {b['beat_id']: b for b in narration['beats']}

print('=' * 80)
print('逐Beat语速分析')
print('=' * 80)

for span in timing['beat_spans']:
    bid = span['beat_id']
    beat = beats[bid]
    toks = [t for t in timing['tokens'] if t['beat_id'] == bid]
    start_ms = toks[0]['start_ms']
    end_ms = toks[-1]['end_ms']
    dur_s = (end_ms - start_ms) / 1000
    text = beat['spoken_text']
    units = 0.0
    for ch in text:
        if ch.isspace():
            continue
        w = unicodedata.east_asian_width(ch)
        units += 1.0 if w in ('W', 'F', 'A') else 0.5
    rate = units / dur_s
    print(f'\n[{bid}] "{text}"')
    print(f'  字数: {units:.1f} | 时长: {dur_s:.3f}s | 语速: {rate:.2f} 字/秒')

print()
print('=' * 80)
print('逐字时长分析')
print('=' * 80)

toks = timing['tokens']
durations = []
for i, t in enumerate(toks):
    dur = t['end_ms'] - t['start_ms']
    durations.append((dur, t['text'], t['beat_id'], t['token_id']))

print('\n--- 字间停顿 (>300ms) ---')
for i in range(1, len(toks)):
    gap = toks[i]['start_ms'] - toks[i - 1]['end_ms']
    if gap > 300:
        print(f'  {toks[i-1]["text"]} -> {toks[i]["text"]}: GAP={gap}ms  (beat:{toks[i]["beat_id"]})')

print('\n--- 最慢的10个字 ---')
durations_sorted = sorted(durations, reverse=True)
for dur, text, bid, tid in durations_sorted[:10]:
    print(f'  "{text}" {dur}ms  ({bid})')

print('\n--- 最快的10个字 ---')
durations_fast = sorted(durations)
for dur, text, bid, tid in durations_fast[:10]:
    print(f'  "{text}" {dur}ms  ({bid})')

print()
print('=' * 80)
print('逐Beat内字时长变异系数')
print('=' * 80)
for span in timing['beat_spans']:
    bid = span['beat_id']
    toks_b = [t for t in toks if t['beat_id'] == bid]
    durs = [t['end_ms'] - t['start_ms'] for t in toks_b]
    mean_d = statistics.mean(durs)
    stdev_d = statistics.stdev(durs) if len(durs) > 1 else 0
    cv = stdev_d / mean_d * 100 if mean_d > 0 else 0
    beat = beats[bid]
    print(f'  [{bid}] "{beat["spoken_text"]}"')
    print(f'    均值={mean_d:.0f}ms  标准差={stdev_d:.0f}ms  CV={cv:.1f}%  范围={min(durs)}-{max(durs)}ms')
