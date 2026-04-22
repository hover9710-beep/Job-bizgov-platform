lines = open('pipeline/run_pipeline.py', encoding='utf-8').readlines()
out = []
for i, l in enumerate(lines):
    if 'def _to_list(val):' in l:
        out.append(l)
        out.append('    if isinstance(val, list): return val\n')
        out.append('    if isinstance(val, dict):\n')
        out.append('        return val.get("new_items") or val.get("items") or val.get("data") or val.get("results") or []\n')
        out.append('    return []\n')
        # 다음 줄들(기존 return val 2개) 스킵 표시
        skip = 2
    elif skip > 0:
        skip -= 1
    else:
        out.append(l)
open('pipeline/run_pipeline.py', 'w', encoding='utf-8').writelines(out)
print('완료')
