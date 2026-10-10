"""
bind_text.py - read, translate and rebuild the BIND/TEXT files (GAME/IMTEXT.BIN, BTL/BTIMTEXT.BIN).

  python bind_text.py roundtrip <file.BIN>
  python bind_text.py extract   <file.BIN> <out.json>
  python bind_text.py build     <file.BIN> <translated.json> <out.BIN>
  python bind_text.py stats     <file.BIN>
  python bind_text.py fit       <in.json> <out.json> [--width 30] [--lines 3]

A file that starts directly with 'TEXT' (FREE/F2INFO.BIN) is a single section without the BIND wrapper.
BIND layout (found by analysis):
  'BIND' u16 version u16 count | u32 alignment | u32 data_start | size table at 0x10
  size table: count entries, u16 each (version 2) or u32 each (version 4)
  section i starts at data_start + sum of aligned sizes before it; each section is 'TEXT':
    'TEXT' u32 n | u32 table_off | u32 first_msg_off | n x (u32 id, u32 msg_off) | messages
    message = u32 voice_id | u32 style | Shift-JIS text | NUL | pad to 4
  several ids can point to the same message.
"""
import sys, struct, json, re, collections

def load(path):
    b = open(path, 'rb').read()
    magic, ver, n = struct.unpack_from('<4sHH', b, 0)
    if magic == b'TEXT':                 # a bare TEXT section with no BIND wrapper (e.g. FREE/F2INFO.BIN)
        return b, 0, 1, 1, 0, [len(b)]
    if magic != b'BIND': raise SystemExit('not a BIND or TEXT file')
    align, start = struct.unpack_from('<II', b, 8)
    fmt, w = ('<%dH', 2) if ver == 2 else ('<%dI', 4)
    sizes = list(struct.unpack_from(fmt % n, b, 0x10))
    return b, ver, n, align, start, sizes

def sections(b, align, start, sizes):
    pos, out = start, []
    for s in sizes:
        out.append((pos, s))
        pos += (s + align - 1) // align * align
    return out

def parse_text(b, p, s):
    """returns (entries[(id, off)], msgs{off:(vid,style,textbytes)}) or None if not a TEXT section"""
    if b[p:p+4] != b'TEXT': return None
    n, toff, doff = struct.unpack_from('<III', b, p + 4)
    ents = [struct.unpack_from('<II', b, p + toff + 8 * i) for i in range(n)]
    msgs = {}
    for _, o in ents:
        if o in msgs: continue
        vid, st = struct.unpack_from('<II', b, p + o)
        e = b.index(b'\0', p + o + 8)
        msgs[o] = (vid, st, b[p + o + 8:e])
    return ents, msgs

def pack_text(ents, msgs_new, order):
    """msgs_new: {old_off: (vid, style, textbytes)}; order: list of old offsets in file order"""
    n = len(ents)
    toff = 0x10
    pos = toff + 8 * n
    newoff, body = {}, bytearray()
    for o in order:
        vid, st, t = msgs_new[o]
        newoff[o] = pos + len(body)
        m = struct.pack('<II', vid, st) + t + b'\0'
        m += b'\0' * (-len(m) % 4)
        body += m
    head = b'TEXT' + struct.pack('<III', n, toff, pos)
    tab = b''.join(struct.pack('<II', i, newoff[o]) for i, o in ents)
    return head + tab + bytes(body)

def rebuild(b, ver, n, align, start, sizes, edits):
    secs = sections(b, align, start, sizes)
    out = bytearray(b[:start])
    newsizes = []
    for si, (p, s) in enumerate(secs):
        chunk = b[p:p + s]
        r = parse_text(b, p, s)
        if r is not None and r[0]:
            ents, msgs = r
            order = sorted(msgs)
            new = {o: (v, st, edits.get((si, o), t)) for o, (v, st, t) in msgs.items()}
            chunk = pack_text(ents, new, order)
            if not edits and chunk != b[p:p + s]:
                tail = b[p + len(chunk):p + s]
                if chunk + tail != b[p:p + s]:
                    raise SystemExit('roundtrip mismatch in section %d' % si)
                chunk = chunk + tail
        newsizes.append(len(chunk))
        out += chunk + b'\0' * (-len(chunk) % align)
    if ver != 0:
        fmt = '<%dH' if ver == 2 else '<%dI'
        struct.pack_into(fmt % n, out, 0x10, *newsizes)
    return bytes(out)

def cells(s):
    return sum(2 if ord(c) > 0xff else 1 for c in s)

def cmd_roundtrip(path):
    b, ver, n, align, start, sizes = load(path)
    out = rebuild(b, ver, n, align, start, sizes, {})
    print('rebuilt identical:', out == b, '(%d vs %d bytes)' % (len(out), len(b)))

def cmd_extract(path, outp):
    b, ver, n, align, start, sizes = load(path)
    items = []
    for si, (p, s) in enumerate(sections(b, align, start, sizes)):
        r = parse_text(b, p, s)
        if not r or not r[0]: continue
        ents, msgs = r
        users = collections.defaultdict(list)
        for i, o in ents: users[o].append(i)
        for o in sorted(msgs):
            v, st, t = msgs[o]
            ja = t.decode('cp932')
            items.append(dict(key='%d:%d' % (si, o), voice=v, style=st, ids=[hex(x) for x in users[o][:6]], ja=ja, en=''))
    json.dump(dict(notes=['Fill in "en". "$n" and other $ codes must be kept. Leave "en" empty to keep Japanese.'], messages=items),
              open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote %d messages (%d distinct texts)' % (len(items), len({i['ja'] for i in items})))

def cmd_build(path, jpath, outp):
    b, ver, n, align, start, sizes = load(path)
    d = json.load(open(jpath, encoding='utf-8'))['messages']
    edits = {}
    for it in d:
        if not it['en'].strip(): continue
        si, o = map(int, it['key'].split(':'))
        try: edits[(si, o)] = it['en'].encode('cp932')
        except UnicodeEncodeError as e: raise SystemExit('cannot encode %r in %s: %s' % (it['en'][:30], it['key'], e))
    out = rebuild(b, ver, n, align, start, sizes, edits)
    open(outp, 'wb').write(out)
    print('edited %d messages; %d -> %d bytes' % (len(edits), len(b), len(out)))


def wrap_words(text, width):
    out, cur = [], ''
    for w in text.split(' '):
        while cells(re.sub(r'\$[A-Za-z]', '', w)) > width:       # break an over-long word
            k = width - len(cur) - (1 if cur else 0)
            if k < 6 and cur: out.append(cur); cur = ''; continue
            cut = w[:max(k, 1)]; out.append((cur + ' ' + cut).strip()); cur = ''; w = w[len(cut):]
        trial = (cur + ' ' + w) if cur else w
        if cells(trial.replace('%s', 'X' * 10)) <= width: cur = trial
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    return out

def fit_text(text, width):
    """'|' forces a line break; '$n' (page break) stays at the end of its line."""
    parts = re.split(r'(\$n)', text)
    lines, cur = [], []
    for part in parts:
        if part == '$n':
            if lines: lines[-1] += '$n'
            else: lines.append('$n')
            continue
        for chunk in part.split('|'):
            chunk = ' '.join(chunk.split())
            if chunk: lines.extend(wrap_words(chunk, width))
    return '\n'.join(lines)

def cmd_fit(inp, outp, width, maxlines):
    d = json.load(open(inp, encoding='utf-8'))
    n = warn = 0
    for it in d['messages']:
        if not it['en'].strip(): continue
        t = fit_text(it['en'].replace('\n', ' '), width)
        pages = t.split('$n\n') if '$n' in t else [t]
        for pg in pages:
            if pg.count('\n') + 1 > maxlines:
                warn += 1; print('WARNING %s: %d lines on one page: %r' % (it['key'], pg.count('\n') + 1, pg[:50]))
        it['en'] = t; n += 1
    json.dump(d, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('fitted %d messages, %d warnings -> %s' % (n, warn, outp))

def cmd_stats(path):
    b, ver, n, align, start, sizes = load(path)
    codes, widths, nl = collections.Counter(), collections.Counter(), collections.Counter()
    tot = 0
    for si, (p, s) in enumerate(sections(b, align, start, sizes)):
        r = parse_text(b, p, s)
        if not r: continue
        for o, (v, st, t) in r[1].items():
            ja = t.decode('cp932'); tot += 1
            for c in re.findall(r'\$[A-Za-z]|%\d*[a-z]', ja): codes[c] += 1
            lines = ja.split('\n'); nl[len(lines)] += 1
            for l in lines: widths[cells(re.sub(r'\$[A-Za-z]|%\d*[a-z]', '', l))] += 1
    print('messages', tot); print('codes', codes.most_common(20))
    print('lines per message', sorted(nl.items()))
    print('max line cells', max(widths), sorted(widths.items())[-8:])

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == 'roundtrip': cmd_roundtrip(a[1])
    elif len(a) == 3 and a[0] == 'extract': cmd_extract(a[1], a[2])
    elif len(a) == 4 and a[0] == 'build': cmd_build(a[1], a[2], a[3])
    elif len(a) == 2 and a[0] == 'stats': cmd_stats(a[1])
    elif len(a) >= 3 and a[0] == 'fit':
        w = int(a[a.index('--width')+1]) if '--width' in a else 30
        ml = int(a[a.index('--lines')+1]) if '--lines' in a else 3
        cmd_fit(a[1], a[2], w, ml)
    else: sys.exit(__doc__)
