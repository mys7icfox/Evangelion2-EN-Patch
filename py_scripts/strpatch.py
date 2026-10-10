"""
strpatch.py - translate fixed Japanese strings inside program files (menus, option text, help text)
IN PLACE: each English string must fit in the bytes the Japanese string (plus the zero padding after it) used.

  python strpatch.py extract <iso> <out.json>             find strings in SLPS_252.99 and PROG/*.BIN
  python strpatch.py extract-files <out.json> <file> ...  same, for loose files
  python strpatch.py check <strings.json>                 list translations that are too long
  python strpatch.py build <strings.json> <srcdir> <outdir>
        srcdir holds the original program files; patched copies go to outdir/root (SLPS_252.99)
        and outdir/PROG (the .BIN files).

Each item: ja, budget (max bytes of English incl. line breaks), places [[file, offset], ...], en.
A string used in several places gets the smallest budget of them.
"""
import sys, re, json, os, collections

PAIR = rb'(?:[\x81-\x84\x88-\x9f\xe0-\xea][\x40-\x7e\x80-\xfc])'
RX = re.compile(rb'(?:' + PAIR + rb'|[\x20-\x7e\n])+\x00')

def good(s):
    if len(s) < 2 or '�' in s: return False
    kana = sum(1 for c in s if '぀' <= c <= 'ヿ')
    cjk = sum(1 for c in s if '一' <= c <= '鿿')
    other = sum(1 for c in s if not (c.isascii() or '぀' <= c <= 'ヿ' or '一' <= c <= '鿿'
                                      or '　' <= c <= '〿' or '＀' <= c <= '￯' or c in '─□△▽○◎●◆◇★☆←↑→↓…―‘’“”×ΑΤΣΘ'))
    if other: return False
    if kana == 0 and cjk < 2: return False
    jp = kana + cjk
    return jp * 2 >= len(s) * 0.6 or kana >= 2

def extract_file(path, name):
    b = open(path, 'rb').read()
    out = []
    for m in RX.finditer(b):
        o = m.start()
        if o > 0 and b[o - 1] != 0: continue
        raw = m.group()[:-1]
        try: s = raw.decode('cp932')
        except UnicodeDecodeError: continue
        if not good(s): continue
        e = m.end()
        while e < len(b) and b[e] == 0 and e - m.end() < 64: e += 1
        out.append((name, o, s, e - o - 0 - 0))   # bytes available from start, incl. NUL and zero padding
    return out

def merge(items):
    by = collections.OrderedDict()
    for name, o, s, avail in items:
        it = by.setdefault(s, dict(ja=s, budget=10**9, places=[], en=''))
        it['places'].append([name, o])
        it['budget'] = min(it['budget'], avail - 1)         # keep one NUL
    return list(by.values())

def save(items, out):
    json.dump(dict(notes=['en must fit in "budget" bytes (ASCII = 1 byte). Keep %s and \\n codes.'], strings=items),
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote %d distinct strings (%d places) -> %s' % (len(items), sum(len(i['places']) for i in items), out))

def cmd_extract_iso(iso, out):
    from iso_patch import scan, SECTOR
    items = []
    with open(iso, 'rb') as f:
        files = scan(f)
        for p, (lba, size, _) in sorted(files.items()):
            if p == '/SLPS_252.99' or (p.startswith('/PROG/') and p.upper().endswith('.BIN')):
                f.seek(lba * SECTOR); data = f.read(size)
                tmp = '_tmp_extract.bin'; open(tmp, 'wb').write(data)
                name = p.rsplit('/', 1)[1]
                items += extract_file(tmp, name); os.remove(tmp)
    save(merge(items), out)

def cmd_extract_files(out, files):
    items = []
    for p in files: items += extract_file(p, os.path.basename(p))
    save(merge(items), out)

def enc(en):
    try: return en.encode('cp932')
    except UnicodeEncodeError as e: raise SystemExit('cannot encode %r: %s' % (en, e))

def cmd_check(path):
    d = json.load(open(path, encoding='utf-8'))['strings']
    bad = 0
    for it in d:
        if it['en'] and len(enc(it['en'])) > it['budget']:
            bad += 1; print('TOO LONG (%d > %d): %r -> %r' % (len(enc(it['en'])), it['budget'], it['ja'][:30], it['en']))
    print('translated %d of %d, too long: %d' % (sum(1 for i in d if i['en']), len(d), bad))
    return bad

def cmd_build(path, src, outdir):
    if cmd_check(path): raise SystemExit('Fix the too-long strings first.')
    d = json.load(open(path, encoding='utf-8'))['strings']
    os.makedirs(outdir, exist_ok=True)
    files = {}
    n = 0
    for it in d:
        if not it['en']: continue
        e = enc(it['en'])
        for name, off in it['places']:
            if name not in files: files[name] = bytearray(open(os.path.join(src, name), 'rb').read())
            b = files[name]
            old = it['ja'].encode('cp932')
            if bytes(b[off:off + len(old)]) != old: raise SystemExit('%s @%#x does not hold the expected Japanese' % (name, off))
            b[off:off + len(old) + 1] = b'\0' * (len(old) + 1)
            b[off:off + len(e)] = e
            n += 1
    for name, b in files.items():
        sub = 'root' if name == 'SLPS_252.99' else 'PROG'      # root = disc root, PROG = the PROG folder
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
        open(os.path.join(outdir, sub, name), 'wb').write(bytes(b))
    print('patched %d places in %d files -> %s (subfolders root and PROG)' % (n, len(files), outdir))

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == 'extract': cmd_extract_iso(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'extract-files': cmd_extract_files(a[1], a[2:])
    elif len(a) == 2 and a[0] == 'check': sys.exit(1 if cmd_check(a[1]) else 0)
    elif len(a) == 4 and a[0] == 'build': cmd_build(a[1], a[2], a[3])
    else: sys.exit(__doc__)
