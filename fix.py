f = open('pipeline/run_pipeline.py', encoding='utf-8').read()
old = "return val.get('items') or val.get('data') or val.get('results') or []"
new = "return val.get('new_items') or val.get('items') or val.get('data') or val.get('results') or []"
if old in f:
    open('pipeline/run_pipeline.py', 'w', encoding='utf-8').write(f.replace(old, new))
    print('수정 완료')
else:
    print('못찾음')
    for i,l in enumerate(f.splitlines(),1):
        if '_to_list' in l or 'return val' in l:
            print(i, l)
