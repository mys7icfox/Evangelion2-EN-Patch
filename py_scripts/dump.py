import sys, re, pathlib

pat = re.compile(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc])+')

with open('dump.tsv', 'w', encoding='utf-8') as out:
    for p in sorted(pathlib.Path(sys.argv[1]).glob('*.HAR')):
        data = p.read_bytes()
        for m in pat.finditer(data):
            raw = m.group()
            if len(raw) < 4:
                continue
            try:
                s = raw.decode('shift_jis')
            except UnicodeDecodeError:
                continue
            before = data[max(0, m.start() - 8):m.start()].hex()
            after = data[m.end():m.end() + 4].hex()
            out.write(f"{p.name}\t{m.start():#x}\t{len(raw)}\t{before}\t{after}\t{s}\n")