"""
mw_text.py - extract and rebuild the MWnnn.DAT phrase files (the story-telling fragments in GAME/).

  python mw_text.py roundtrip <MW001.DAT>                  parse and rebuild, must be byte-identical
  python mw_text.py extract <out.json> <MW001.DAT> [more files ...]
  python mw_text.py build <translated.json> <MW001.DAT> <out.DAT>      (one file at a time)

File layout (all values little-endian u32):
  [0] 0   [1] = start of the pointer area minus 12   [2] = start of the string pool minus 12
  then 17 (section id, offset) pairs, a (0, end) pair, then the pointer arrays, then the string pool.
  Pointers are offsets into the pool; the pool is a run of NUL-terminated strings.
Strings are translated by their text: every distinct Japanese string gets one English string,
used everywhere it occurs.  The pool is rebuilt in the same order and all pointers are remapped.
"""
import sys, struct, json, collections


def parse(b):
    h = struct.unpack_from('<3I', b, 0)
    dstart, pool = 12 + h[1], 12 + h[2]
    pairs, i = [], 12
    while i < dstart:
        pairs.append(struct.unpack_from('<II', b, i)); i += 8
    secs = sorted([p for p in pairs if p[0] != 0], key=lambda x: x[1])
    end = [p for p in pairs if p[0] == 0][0][1]
    sections = []
    for n, (sid, off) in enumerate(secs):
        nxt = secs[n + 1][1] if n + 1 < len(secs) else end
        sections.append((sid, off, nxt))
    return h, dstart, pool, pairs, sections, end


def strings_of(P):
    """[(offset, bytes)] for every NUL-terminated string in the pool, in order."""
    out, pos = [], 0
    while pos < len(P):
        e = P.index(b'\0', pos)
        out.append((pos, P[pos:e])); pos = e + 1
    return out


def rebuild(b, newstr):
    """newstr: {old_bytes: new_bytes}. Returns the new file."""
    h, dstart, pool, pairs, sections, end = parse(b)
    P = b[pool:]
    ss = strings_of(P)
    remap, npool = {}, bytearray()
    for off, s in ss:
        remap[off] = len(npool)
        npool += newstr.get(s, s) + b'\0'
    area = bytearray(b[dstart:dstart + end])
    for sid, off, nxt in sections:
        for k in range(off, nxt, 4):
            v = struct.unpack_from('<I', area, k)[0]
            if v not in remap: raise SystemExit('pointer %#x in section %d is not a string start' % (v, sid))
            struct.pack_into('<I', area, k, remap[v])
    gap = b[dstart + end:pool]
    head = bytearray(b[:dstart])
    struct.pack_into('<I', head, 8, (dstart + end + len(gap) - 12))
    return bytes(head) + bytes(area) + gap + bytes(npool)


def role_map(b):
    """for every string: the set of section ids that point at it (alternatives inherit from the string before)"""
    h, dstart, pool, pairs, sections, end = parse(b)
    P = b[pool:]
    ss = strings_of(P)
    sec_of = {}
    for sid, off, nxt in sections:
        for k in range(off, nxt, 4):
            sec_of.setdefault(struct.unpack_from('<I', b, dstart + k)[0], sid)
    role, cur = {}, 0
    for off, s in ss:
        if off in sec_of: cur = sec_of[off]
        role.setdefault(s, cur)
    return role


def cmd_roundtrip(path):
    b = open(path, 'rb').read()
    out = rebuild(b, {})
    print('identical' if out == b else 'DIFFERENT (%d vs %d bytes)' % (len(out), len(b)))
    sys.exit(0 if out == b else 1)


def cmd_extract(outp, paths):
    items, seen = [], {}
    for p in paths:
        b = open(p, 'rb').read()
        role = role_map(b)
        h, dstart, pool, pairs, sections, end = parse(b)
        for off, s in strings_of(b[pool:]):
            if not s or s == b'\x01' or s in seen.get(p, ()): continue
            seen.setdefault(p, set()).add(s)
            try: ja = s.decode('cp932')
            except UnicodeDecodeError: continue
            items.append(dict(file=p.replace('\\', '/').rsplit('/', 1)[-1], sec=role[s], ja=ja, en=''))
    json.dump(dict(notes=['en = English for this exact Japanese string, same for every place it occurs.'], strings=items),
              open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote %d strings -> %s' % (len(items), outp))


def cmd_build(jpath, path, outp):
    d = json.load(open(jpath, encoding='utf-8'))['strings']
    name = path.replace('\\', '/').rsplit('/', 1)[-1]
    tr = {}
    for it in d:
        if it['en'] and (it.get('file') in (None, name) or it['ja'] not in tr):
            tr[it['ja']] = it['en']
    newstr = {}
    for ja, en in tr.items():
        try: newstr[ja.encode('cp932')] = en.encode('cp932')
        except UnicodeEncodeError as e: raise SystemExit('cannot encode %r: %s' % (en, e))
    b = open(path, 'rb').read()
    out = rebuild(b, newstr)
    open(outp, 'wb').write(out)
    print('%s: %d -> %d bytes, %d strings replaced' % (name, len(b), len(out), len(newstr)))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == 'roundtrip': cmd_roundtrip(a[1])
    elif len(a) >= 3 and a[0] == 'extract': cmd_extract(a[1], a[2:])
    elif len(a) == 4 and a[0] == 'build': cmd_build(a[1], a[2], a[3])
    else: sys.exit(__doc__)
