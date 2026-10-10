"""
scan_all.py - find EVERY piece of Japanese text on the disc and say which of it is still untranslated.

  python scan_all.py <original.iso> [--known a.json b.json ...] [--min 3] [--out scan_all]
  python scan_all.py --dir <folder>  [...]        (scan loose files in a folder instead of an ISO)

What it does
  * reads every file in the ISO (skips only MOVIE / STREAM / VOICE / SOUND / NULLDATA),
  * looks inside containers: HGAR (.HAR) records, BIND sections, TEXT sections, and nested ones,
  * finds Shift-JIS (cp932) strings and UTF-16LE strings,
  * compares each string with every "ja" value in your translation JSON files
    (by default every *.json in the current folder: messages_en.json, bt_en.json, ... f2_game.json),
    so it can tell "already translated" from "still Japanese",
  * flags files that look COMPRESSED or are binary with no readable text, because text hidden
    in those would not show up in any scan.

Writes (nothing in the ISO is modified):
  <out>_report.txt   per file: strings found / still untranslated, with samples, plus compressed-looking files
  <out>_todo.json    every untranslated string, ready to translate: {file, offset, container, ja, budget, clean, en}
                     'budget' = bytes available at that spot (string + the zero padding after it);
                     'clean'  = starts after a zero byte and ends with one, so it can be patched in place.
  <out>_all.json     only with --all: everything found, translated or not (can be huge)
  --skiptodo X Y     files still counted in the report but left out of the todo (default: IMTEXT.BIN and MW*.DAT,
                     the chat system, which is a separate big job; pass --skiptodo NONE to include them)
  --utf16            also scan UTF-16 text (off by default, very noisy)

Attach <out>_report.txt (and <out>_todo.json if it is not huge) to continue.
"""
import sys, re, json, math, struct, collections, pathlib, glob

SECTOR = 2048
WANT_ALL = '--all' in sys.argv
UTF16 = '--utf16' in sys.argv          # UTF-16 scan is off by default (it is very noisy)
SKIP = ('/MOVIE/', '/STREAM/', '/VOICE/', '/SOUND/', '/NULLDATA')

PAIR = rb'(?:[\x81-\x84\x88-\x9f\xe0-\xea][\x40-\x7e\x80-\xfc])'
RUN = re.compile(rb'(?:' + PAIR + rb'|[\x20-\x7e\n]){3,}')
U16 = re.compile(rb'(?:[\x00-\xff][\x30-\x9f\xff]|[\x20-\x7e]\x00){3,}')


def is_jp(s, minjp):
    n = sum(1 for c in s if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or '＀' <= c <= '￯')
    return n >= minjp


def plausible(b, s, clean):
    """Reject machine code that happens to decode as rare kanji."""
    kana = sum(1 for c in s if '\u3040' <= c <= '\u30ff' or c in '\u3001\u3002\uff01\uff1f\u2026\u30fb\u300c\u300d\uff1a')
    kan = [c for c in s if '\u4e00' <= c <= '\u9fff']
    rare = 0
    for c in kan:                               # JIS level 2 (lead byte >= 0x98, 2nd byte >= 0x9f) = rare
        try:
            e = c.encode('cp932')
        except UnicodeEncodeError:
            rare += 1
            continue
        if e[0] > 0x98 or (e[0] == 0x98 and e[1] >= 0x73):
            rare += 1
    if kan and rare * 4 > len(kan):
        return False
    if kana == 0 and not (clean and len(kan) >= 2 and rare == 0):
        return False
    return True


def norm(s):
    s = re.sub(r'\$[A-Za-z]|%\d*[a-z]', '', s)
    return re.sub(r'\s+', '', s.replace('　', ''))


# ---------------------------------------------------------------- iso reading (same as iso_patch.scan)
def iso_files(f):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b'CD001':
        raise SystemExit('no ISO9660 primary volume descriptor at sector 16')
    rl = struct.unpack_from('<I', pvd, 158)[0]
    rs = struct.unpack_from('<I', pvd, 166)[0]
    out = {}

    def walk(lba, size, path):
        f.seek(lba * SECTOR)
        data = f.read(size)
        pos = 0
        while pos < len(data):
            n = data[pos]
            if n == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + n]
            pos += n
            e_lba = struct.unpack_from('<I', rec, 2)[0]
            e_size = struct.unpack_from('<I', rec, 10)[0]
            flags, nlen = rec[25], rec[32]
            name = rec[33:33 + nlen]
            if name in (b'\x00', b'\x01'):
                continue
            name = name.decode('ascii', 'replace').split(';')[0]
            full = path + '/' + name.upper()
            if flags & 2:
                walk(e_lba, e_size, full)
            else:
                out[full] = (e_lba, e_size)
    walk(rl, rs, '')
    return out


# ---------------------------------------------------------------- container map
def containers(data, base=0, label='', depth=0):
    """Yield (start, end, label) for every nested container member, so a string can be named."""
    out = []
    if depth > 4 or len(data) < 16:
        return out
    try:
        if data[:4] == b'HGAR':
            ver, n = struct.unpack_from('<HH', data, 4)
            offs = struct.unpack_from('<%dI' % n, data, 8)
            for off in offs:
                if off + 20 > len(data):
                    continue
                name = data[off:off + 8].split(b'\0')[0].decode('ascii', 'replace')
                ext = data[off + 8:off + 12].split(b'\0')[0].decode('ascii', 'replace').lower()
                size = struct.unpack_from('<I', data, off + 16)[0]
                s, e = off + 20, min(off + 20 + size, len(data))
                lab = '%s/%s%s' % (label, name, ext)
                out.append((base + s, base + e, lab))
                out += containers(data[s:e], base + s, lab, depth + 1)
        elif data[:4] == b'BIND':
            magic, ver, n = struct.unpack_from('<4sHH', data, 0)
            align, start = struct.unpack_from('<II', data, 8)
            fmt = '<%dH' if ver == 2 else '<%dI'
            sizes = struct.unpack_from(fmt % n, data, 0x10)
            pos = start
            a = max(align, 1)
            for i, sz in enumerate(sizes):
                lab = '%s/#%d' % (label, i)
                s, e = pos, min(pos + sz, len(data))
                if sz:
                    out.append((base + s, base + e, lab))
                    out += containers(data[s:e], base + s, lab, depth + 1)
                pos += -(-sz // a) * a
    except Exception:
        pass
    return out


def entropy(b):
    if not b:
        return 0
    c = collections.Counter(b)
    n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def find_runs(data, minjp):
    res = []
    for m in RUN.finditer(data):
        b = m.group()
        if not re.search(PAIR, b):
            continue
        try:
            s = b.decode('cp932')
        except UnicodeDecodeError:
            # trim a dangling lead byte and retry
            try:
                s = b[:-1].decode('cp932')
                b = b[:-1]
            except UnicodeDecodeError:
                continue
        if not is_jp(s, minjp):
            continue
        st, en = m.start(), m.start() + len(b)
        before = data[st - 1] if st > 0 else 0
        j = en
        while j < len(data) and data[j] == 0:
            j += 1
        after = data[en] if en < len(data) else 0
        clean = before == 0 and after == 0
        if not plausible(b, s, clean):
            continue
        nk = sum(1 for c in s if '\u3040' <= c <= '\u30ff')
        if not clean and (len(s) < 5 or nk < 2):          # loose fragments inside binary data are noise
            continue
        res.append(dict(offset=st, ja=s, bytes=len(b), budget=(j - st) if after == 0 else len(b), clean=clean, enc='cp932'))
    for m in (U16.finditer(data) if UTF16 else ()):
        b = m.group()
        if len(b) % 2 or m.start() % 2:
            continue
        try:
            s = b.decode('utf-16le')
        except UnicodeDecodeError:
            continue
        if is_jp(s, minjp):
            res.append(dict(offset=m.start(), ja=s, bytes=len(b), budget=len(b), clean=False, enc='utf-16le'))
    return res


# ---------------------------------------------------------------- known (already translated) text
def collect_ja(obj, out):
    if isinstance(obj, dict):
        translated = not ('en' in obj and not str(obj.get('en') or '').strip())   # empty en = not translated yet
        for k, v in obj.items():
            if k == 'ja' and isinstance(v, str):
                if translated:
                    out.append(v)
            else:
                collect_ja(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_ja(v, out)


def load_known(paths):
    ja = []
    used = []
    for p in paths:
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        before = len(ja)
        collect_ja(d, ja)
        if len(ja) > before:
            used.append((p, len(ja) - before))
    segs = set()
    for s in ja:
        for part in re.split(r'\n|\$n', s):
            n = norm(part)
            if len(n) >= 2:
                segs.add(n)
        segs.add(norm(s))
    return segs, used


def covered(text, segs):
    parts = [norm(p) for p in re.split(r'\n|\$n|[ 　]{2,}', text)]
    parts = [p for p in parts if p]
    if not parts:
        return True
    return all(p in segs for p in parts) or norm(text) in segs


# ---------------------------------------------------------------- main
def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)

    def opt(name, default=None, many=False):
        if name not in a:
            return default
        i = a.index(name)
        vals = []
        for x in a[i + 1:]:
            if x.startswith('--'):
                break
            vals.append(x)
        return vals if many else (vals[0] if vals else default)
    minjp = int(opt('--min', 3))
    out = opt('--out', 'scan_all')
    known_paths = opt('--known', None, many=True)
    dirmode = '--dir' in a
    SKIP_TODO = opt('--skiptodo', ['/IMTEXT.BIN', '/MW0', '/MW1'], many=True) if '--skiptodo' in a else ['/IMTEXT.BIN', '/MW0', '/MW1']
    src = a[1] if dirmode else a[0]
    if known_paths is None:
        known_paths = [x for x in sorted(glob.glob('*.json'))
                       if not re.search(r'(scan_all|text_scan|_todo|_all)', x, re.I) and not x.lower().startswith(out.lower())]
    segs, used = load_known(known_paths)
    print('known translated text from: ' + ', '.join('%s (%d)' % u for u in used) if used else
          'WARNING: no translation JSON found, everything will count as untranslated')

    entries = []          # (path, size, data-getter)
    if dirmode:
        for p in sorted(pathlib.Path(src).rglob('*')):
            if p.is_file():
                entries.append(('/' + p.relative_to(src).as_posix().upper(), p.stat().st_size, p))
        fh = None
    else:
        fh = open(src, 'rb')
        for path, (lba, size) in sorted(iso_files(fh).items()):
            entries.append((path, size, (lba, size)))

    allr, todo, rep, compressed = [], [], [], []
    for path, size, ref in entries:
        if any(path.startswith(s) for s in SKIP) or size == 0:
            continue
        if fh is None:
            data = ref.read_bytes()
        else:
            fh.seek(ref[0] * SECTOR)
            data = fh.read(ref[1])
        cmap = containers(data)
        cmap.sort(key=lambda t: t[1] - t[0])          # innermost (smallest) first
        found = find_runs(data, minjp)
        nt = 0
        for r in found:
            lab = ''
            for s, e, l in cmap:
                if s <= r['offset'] < e:
                    lab = l
                    break
            r['file'] = path
            r['container'] = lab
            r['covered'] = covered(r['ja'], segs)
            if WANT_ALL:
                allr.append(r)
            if not r['covered']:
                nt += 1
                if any(k in path for k in SKIP_TODO if k != 'NONE'):
                    continue
                todo.append(dict(file=path, offset=r['offset'], container=lab, enc=r['enc'], ja=r['ja'],
                                 budget=r['budget'], clean=r['clean'], en=''))
        rep.append((nt, len(found), path, size, found))
        if size >= 0x2000 and len(found) < 3 and not path.endswith(('.PSS', '.STR')):
            head = data[:4]
            ent = entropy(data[:65536])
            if ent > 7.2 or head[:2] in (b'\x1f\x8b',) or head in (b'LZSS', b'LZ77', b'\x10\x00\x00\x00'):
                compressed.append((path, size, round(ent, 2), head.hex()))
    if fh:
        fh.close()

    rep.sort(key=lambda r: (-r[0], r[2]))
    with open(out + '_report.txt', 'w', encoding='utf-8') as o:
        tot_t = sum(r[0] for r in rep)
        tot_f = sum(r[1] for r in rep)
        o.write('strings found: %d   still untranslated: %d   already translated: %d\n' % (tot_f, tot_t, tot_f - tot_t))
        o.write('files with untranslated text: %d\n\n' % sum(1 for r in rep if r[0]))
        for nt, nf, path, size, found in rep:
            if not nt:
                continue
            o.write('%5d untranslated / %5d found   %s  (%d bytes)\n' % (nt, nf, path, size))
            k = 0
            for r in found:
                if r['covered']:
                    continue
                o.write('        @%#x %-3s %s  [%s]\n' % (r['offset'], 'ok' if r['clean'] else '?',
                                                          r['ja'][:60].replace('\n', ' / '), r['container']))
                k += 1
                if k >= 4:
                    break
        o.write('\n--- files that look compressed / opaque (text inside them is invisible to this scan) ---\n')
        bydir = collections.defaultdict(list)
        for p, sz, ent, h in compressed:
            bydir[(p.rsplit('/', 1)[0], p.rsplit('.', 1)[-1])].append((p, sz))
        for (d, ext), L in sorted(bydir.items()):
            o.write('  %-20s *.%-4s %4d files, e.g. %s\n' % (d, ext, len(L), ', '.join(x[0].rsplit('/', 1)[1] for x in L[:3])))
        o.write('\n--- fully translated files (for reference) ---\n')
        for nt, nf, path, size, found in rep:
            if nf and not nt:
                o.write('  %5d  %s\n' % (nf, path))
    # de-duplicate identical text within a file (keep every offset) so the todo stays small
    seen, slim = {}, []
    for t in todo:
        k = (t['file'], t['ja'])
        if k in seen:
            seen[k]['also'].append(t['offset'])
        else:
            t['also'] = []
            seen[k] = t
            slim.append(t)
    json.dump(slim, open(out + '_todo.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    if WANT_ALL:
        json.dump(allr, open(out + '_all.json', 'w', encoding='utf-8'), ensure_ascii=False)
    todo = slim
    print(open(out + '_report.txt', encoding='utf-8').read()[:5000])
    import os
    print('\nwrote %s_report.txt and %s_todo.json (%d distinct strings, %.1f MB)' % (out, out, len(todo), os.path.getsize(out + '_todo.json') / 1e6))


if __name__ == '__main__':
    main()
