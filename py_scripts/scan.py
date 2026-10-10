import sys, re, pathlib

# runs of 4+ Shift-JIS double-byte characters
pat = re.compile(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]){4,}')

for p in sorted(pathlib.Path(sys.argv[1]).rglob('*')):
    if p.is_file():
        data = p.read_bytes()
        hits = pat.findall(data)
        if hits:
            sample = hits[0].decode('shift_jis', errors='replace')[:30]
            print(f"{p.name}\t{len(data)}\t{len(hits)} runs\t{sample}")