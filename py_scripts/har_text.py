"""
har_text.py - extract and rebuild the dialogue in the game's .HAR files.

  python har_text.py roundtrip <EVENT folder>
        Rebuild every file with NO edits and check the bytes match the originals.
        Run this first; all files should be identical.
  python har_text.py extract <EVENT folder> <messages.json>
        Write every dialogue message to a JSON file (fill in the "en" fields).
  python har_text.py build <EVENT folder> <messages.json> <output folder>
        Write patched .HAR files for every message whose "en" is filled in.
        Untouched files are copied unchanged.

  python har_text.py markers <EVENT folder> <markers.json> [file prefix ...]
        Same as extract, but each "en" is set to the message's own key (e.g. A015:0:5), so
        you can see in-game which file a scene comes from. Optional prefixes limit it to
        files whose name starts with them (e.g. S A BB). Then run "build" as usual.

  python har_text.py ruler <EVENT folder> <ruler.json> [file prefix ...]
        Layout test. Cycles four test texts through the messages (a character ruler for line
        width, extra lines for page height, a page-break marker test, an A-Z/a-z/punctuation
        glyph test, and the message key). Run "build", play, and tell me what you see.

  python har_text.py probe <EVENT folder> <probe.json> <key or FILE> [key or FILE ...]
        Puts layout tests (an 80-character ruler with 5 lines, a page-break test, a long sentence)
        into the messages you name, e.g. S001:0:61 S001:0:62 S001:0:63. Every other message in
        the same file shows its own key, so the file shrinks and always fits on the disc.
        Add  --tests 4,5,6,2  to choose which tests to use and in what order (numbers as printed).
        A bare file name such as S001 means every message in that file, each given a different
        test (ruler, page break, sentence, narrow, wide and word-wrap tests, repeating).
        Then run "build" and patch the ISO as usual.

  python har_text.py show <file.har> <key>
        Print one message from a .HAR file, e.g.  show patched\\S001.HAR S001:0:61
        Use it to check what a patched file (or a file pulled from the ISO) really contains.

  python har_text.py list <EVENT folder or file.har> [file prefix]
        Print the text messages with their keys, e.g.  list EVENT S001
  python har_text.py stats <EVENT folder>
        How the original Japanese uses line widths, page markers and lines per page.
  python har_text.py fit <source.json> <game.json>
        Reflow every "en" into game format: at most 34 cells per line, 3 lines per page, a page
        marker between pages. Write plain English in "en"; this does the line breaks for you.
        Put | where you want a forced line break, or the page marker where you want a new page.
        Your source file is never changed; build from the game.json it writes.

Format: see har_verify.py. Only opcode-1 text messages are ever modified;
all other script commands and all other records (.zpt, .hpt, ...) are copied byte for byte.
"""
import sys
import json
import struct
import shutil
import pathlib


def har_files(folder):
    return sorted(p for p in pathlib.Path(folder).rglob('*') if p.is_file() and p.suffix.lower() == '.har')


def parse_har(data):
    if data[:4] != b'HGAR':
        raise ValueError('bad magic')
    ver, count = struct.unpack_from('<HH', data, 4)
    offs = struct.unpack_from('<%dI' % count, data, 8)
    recs = []
    for i, off in enumerate(offs):
        nxt = offs[i + 1] if i + 1 < count else len(data)
        unk, size = struct.unpack_from('<II', data, off + 12)
        end = off + 20 + size
        # the last record may be followed by zero padding (iso_patch.py pads shrunken files)
        if end != nxt and not (i + 1 == count and end < nxt and not data[end:].strip(b'\0')):
            raise ValueError('record %d is not tightly packed' % i)
        recs.append(dict(name=data[off:off + 8], ext=data[off + 8:off + 12], unk=unk,
                         body=data[off + 20:off + 20 + size]))
    return ver, recs


def build_har(ver, recs):
    n = len(recs)
    pos, offs, out = 8 + 4 * n, [], []
    for r in recs:
        offs.append(pos)
        rec = r['name'] + r['ext'] + struct.pack('<II', r['unk'], len(r['body'])) + r['body']
        out.append(rec)
        pos += len(rec)
    return b'HGAR' + struct.pack('<HH', ver, n) + struct.pack('<%dI' % n, *offs) + b''.join(out)


def parse_evs(chunk):
    if chunk[:4] != b'.EVS':
        raise ValueError('no .EVS tag')
    n = struct.unpack_from('<I', chunk, 4)[0]
    offs = struct.unpack_from('<%dI' % n, chunk, 8)
    if offs and offs[0] != 8 + 4 * n:
        raise ValueError('unexpected first block offset')
    blocks = []
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < n else len(chunk)
        raw = chunk[off:end]
        op, plen = struct.unpack_from('<HH', raw, 0)
        blk = dict(raw=raw, op=op, plen=plen)
        if op == 1:
            payload = raw[4:4 + plen]
            blk['extra'], blk['style'], blk['id'] = struct.unpack_from('<III', payload, 0)
            blk['text'] = payload[12:-1].decode('cp932')
        blocks.append(blk)
    return blocks


def build_evs(blocks):
    n = len(blocks)
    pos, offs = 8 + 4 * n, []
    for b in blocks:
        offs.append(pos)
        pos += len(b['raw'])
    return (b'.EVS' + struct.pack('<I', n) + struct.pack('<%dI' % n, *offs)
            + b''.join(b['raw'] for b in blocks))


def encode_block(blk, text):
    payload = struct.pack('<III', blk['extra'], blk['style'], blk['id']) + text.encode('cp932') + b'\0'
    if len(payload) > 0xFFFF:
        raise ValueError('message too long')
    raw = struct.pack('<HH', 1, len(payload)) + payload
    return raw + b'\0' * (-len(raw) % 4)


def messages(folder):
    """yield (path, version, records, record_index, blocks) for each .evs record"""
    for p in har_files(folder):
        ver, recs = parse_har(p.read_bytes())
        for ri, r in enumerate(recs):
            if r['ext'] == b'.evs':
                yield p, ver, recs, ri, parse_evs(r['body'])


def cmd_roundtrip(folder):
    same = diff = msgs = enc_ok = 0
    for p in har_files(folder):
        raw = p.read_bytes()
        ver, recs = parse_har(raw)
        for r in recs:
            if r['ext'] == b'.evs':
                blocks = parse_evs(r['body'])
                for b in blocks:
                    if b['op'] == 1:
                        msgs += 1
                        e = encode_block(b, b['text'])
                        # equal apart from the leftover bytes in the 0-3 padding bytes
                        enc_ok += len(e) == len(b['raw']) and e[:4 + b['plen']] == b['raw'][:4 + b['plen']]
                r['body'] = build_evs(blocks)
        if build_har(ver, recs) == raw:
            same += 1
        else:
            diff += 1
            print('MISMATCH', p.name)
    print('rebuilt identical: %d   different: %d' % (same, diff))
    print('messages re-encoded identically (ignoring padding): %d of %d' % (enc_ok, msgs))


def cmd_extract(folder, outpath):
    out = []
    for p, ver, recs, ri, blocks in messages(folder):
        for bi, b in enumerate(blocks):
            if b['op'] == 1:
                out.append(dict(key='%s:%d:%d' % (p.stem, ri, bi), extra=b['extra'], style=b['style'],
                                id=b['id'], ja=b['text'], en=''))
    doc = dict(notes=['Fill in "en". Leave "en" empty to keep the Japanese.',
                      'Keep \\n line breaks (the game does not wrap lines) and the page-wait marker.',
                      'Do not change key, extra, style or id.'],
               messages=out)
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('wrote %d messages to %s' % (len(out), outpath))


def cmd_markers(folder, outpath, prefixes):
    """Like extract, but fills each "en" with the message's own key (e.g. A015:0:5)."""
    cmd_extract(folder, outpath)
    with open(outpath, encoding='utf-8') as f:
        doc = json.load(f)
    prefixes = [x.upper() for x in prefixes]
    n = 0
    for m in doc['messages']:
        if not prefixes or any(m['key'].upper().startswith(x) for x in prefixes):
            m['en'] = m['key']
            n += 1
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('marked %d messages (en = key). Run "build" next, then play and note the keys you see.' % n)


RULER = ''.join(chr(65 + i) + '123456789' for i in range(5))   # A123456789B123456789...E123456789


def cmd_ruler(folder, outpath, prefixes):
    """Layout test: cycles four test texts through the messages of the chosen files."""
    cmd_extract(folder, outpath)
    with open(outpath, encoding='utf-8') as f:
        doc = json.load(f)
    tests = [
        RULER + '\nLINE 2\nLINE 3\nLINE 4\nLINE 5\n',                                  # line width / lines per page
        'PAGE 1 LINE 1\nPAGE 1 LINE 2▽\nPAGE 2 LINE 1\nPAGE 2 LINE 2\nPAGE 2 LINE 3\n',  # page-break marker
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ\nabcdefghijklmnopqrstuvwxyz\n0123456789 .,!?\'"-:;()\n',  # glyphs
        None,                                                                           # None = the message's key
    ]
    prefixes = [x.upper() for x in prefixes]

    def size(text):                      # bytes a message block occupies, padding included
        n = 4 + 12 + len(text.encode('cp932')) + 1
        return n + (-n % 4)

    n = skipped = 0
    for m in doc['messages']:
        if prefixes and not any(m['key'].upper().startswith(x) for x in prefixes):
            continue
        room = size(m['ja'])             # never exceed the original size: files must not grow
        for k in range(len(tests)):
            t = tests[(n + k) % len(tests)]
            t = m['key'] if t is None else t
            if size(t) <= room:
                m['en'] = t
                n += 1
                break
        else:
            skipped += 1                 # too short even for the key: leave the Japanese
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('wrote layout tests into %d messages (%d too short to hold a test, left in Japanese).'
          % (n, skipped))
    print('Every test fits inside its original message, so no file grows. Run "build" next.')


RULER_LONG = ''.join(chr(65 + i) + '123456789' for i in range(8))   # 80 characters


def cmd_probe(folder, outpath, keys):
    """Put layout tests into specific messages you can reach, and shrink every other message
    in the same file to its key, so the file can never grow past its original size."""
    order = None
    if '--tests' in keys:                    # --tests 4,5,6,2 : which tests to use, in this order
        i = keys.index('--tests')
        try:
            order = [int(x) - 1 for x in keys[i + 1].split(',')]
            keys = keys[:i] + keys[i + 2:]
        except (IndexError, ValueError):
            sys.exit('--tests needs a list like 4,5,6,2')
    cmd_extract(folder, outpath)
    with open(outpath, encoding='utf-8') as f:
        doc = json.load(f)
    tests = [
        RULER_LONG + '\nLINE 2\nLINE 3\nLINE 4\nLINE 5\n',
        'PAGE 1 LINE 1\nPAGE 1 LINE 2\u25bd\nPAGE 2 LINE 1\nPAGE 2 LINE 2\nPAGE 2 LINE 3\n',
        'I wonder if this line is too long to fit\nin the box, or if it runs right off the\n'
        'edge of the screen like this one does.\n',
        'T4 NARROW\n' + ''.join('i' * 9 + str(n) for n in range(1, 7)) + '\n',
        'T5 WIDE\n' + ''.join('W' * 9 + str(n) for n in range(1, 7)) + '\n',
        'T6 WORDS\nPlease remember to bring your umbrella tomorrow morning okay\n',
    ]
    names = ['ruler', 'page break', 'sentence', 'narrow letters', 'wide letters', 'word wrap']
    if order is None:
        order = list(range(len(tests)))
    if any(not 0 <= x < len(tests) for x in order):
        sys.exit('--tests numbers must be between 1 and %d' % len(tests))
    expanded = []
    for k in keys:
        if k.startswith('--'):
            sys.exit('unknown option %s (only --tests is supported)' % k)
        if ':' in k:
            expanded.append(k)
        else:                              # a bare file name: every text message in it, in order
            found = [m['key'] for m in doc['messages'] if m['key'].upper().startswith(k.upper() + ':')]
            if not found:
                sys.exit('No messages found for file %s' % k)
            expanded.extend(found)
    keys = expanded
    want = {k.upper(): i for i, k in enumerate(keys)}
    by_key = {m['key'].upper(): m for m in doc['messages']}
    missing = [k for k in want if k not in by_key]
    if missing:
        sys.exit('No such message key(s): %s\n(keys look like S001:0:61 and are shown in-game by the markers test)'
                 % ', '.join(missing))
    files = {k.split(':')[0] for k in want}

    def size(text):
        n = 4 + 12 + len(text.encode('cp932')) + 1
        return n + (-n % 4)

    def test_for(key):
        return tests[order[want[key] % len(order)]]

    def marker(m):                           # short, so more room is left for tests
        return '#' + m['key'].split(':')[-1]

    active = set(want)                       # keys that currently get a test
    dropped = []
    for f in sorted(files):
        msgs = [m for m in doc['messages'] if m['key'].upper().split(':')[0] == f]
        old = sum(size(m['ja']) for m in msgs)
        while True:
            new = sum(size(test_for(m['key'].upper()) if m['key'].upper() in active else marker(m)) for m in msgs)
            if new <= old:
                break
            mine = sorted((k for k in active if k.split(':')[0] == f), key=lambda k: want[k])
            if not mine:
                sys.exit('%s: even the key markers alone would grow the file by %d bytes.' % (f, new - old))
            active.discard(mine[-1])         # drop the last test until the file fits
            dropped.append(mine[-1])
    for m in doc['messages']:
        k = m['key'].upper()
        if k.split(':')[0] in files:
            m['en'] = test_for(k) if k in active else marker(m)
    with open(outpath, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print('probe set on %d message(s) in %s; every other message shows #<number> (its block number).'
          % (len(active), ', '.join(sorted(files))))
    for k, i in sorted(want.items(), key=lambda kv: kv[1]):
        if k in active:
            print('  %s -> test %d (%s)' % (k, order[i % len(order)] + 1, names[order[i % len(order)]]))
    if dropped:
        print('NOT PLACED (no room in the original file, so they show #<number>): %s'
              % ', '.join(sorted(dropped, key=lambda k: want[k])))


def cmd_show(path, key):
    """Print one message from a .HAR file, e.g.  show patched/S001.HAR S001:0:61"""
    parts = key.split(':')
    try:
        ri, bi = int(parts[-2]), int(parts[-1])
    except (ValueError, IndexError):
        sys.exit('key must look like S001:0:61')
    ver, recs = parse_har(pathlib.Path(path).read_bytes())
    if ri >= len(recs) or recs[ri]['ext'] != b'.evs':
        sys.exit('record %d is not a script record' % ri)
    blocks = parse_evs(recs[ri]['body'])
    if bi >= len(blocks):
        sys.exit('only %d blocks in that record' % len(blocks))
    b = blocks[bi]
    if b['op'] != 1:
        sys.exit('block %d is a script command (opcode %#x), not a text message' % (bi, b['op']))
    print('%s  extra=%#x style=%#x id=%#x' % (key, b['extra'], b['style'], b['id']))
    print(repr(b['text']))


WIDTH = 34          # character cells per line (measured in-game: narrow and wide letters both wrap at 34)
PAGE_LINES = 3      # lines in the message box
MARK = '▽'     # page-break marker (waits for a button press)


def cells(text):
    """Cells a string occupies: 1 per ASCII character, 2 per Japanese character (= its Shift-JIS size)."""
    return len(text.encode('cp932'))


def cmd_list(path, prefix):
    """List every text message of a file, or of the files whose name starts with <prefix>."""
    p = pathlib.Path(path)
    if p.is_file():
        files = [p]
    else:
        files = [f for f in har_files(p) if not prefix or f.stem.upper().startswith(prefix.upper())]
    n = 0
    for f in files:
        ver, recs = parse_har(f.read_bytes())
        for ri, r in enumerate(recs):
            if r['ext'] != b'.evs':
                continue
            for bi, b in enumerate(parse_evs(r['body'])):
                if b['op'] == 1:
                    n += 1
                    print('%s:%d:%d  extra=%d style=%#x' % (f.stem, ri, bi, b['extra'], b['style']))
                    print('   ' + b['text'].rstrip('\n').replace('\n', ' / '))
    print('%d messages' % n)


def cmd_stats(folder):
    """Measure how the original Japanese script uses lines and pages."""
    from collections import Counter
    plain, marked, page_lines = Counter(), Counter(), Counter()
    msgs = mid = 0
    for p, ver, recs, ri, blocks in messages(folder):
        for b in blocks:
            if b['op'] != 1:
                continue
            msgs += 1
            lines = b['text'].split('\n')
            if lines and lines[-1] == '':
                lines.pop()
            cur = 0
            for l in lines:
                cur += 1
                if MARK in l[:-1]:
                    mid += 1
                if l.endswith(MARK):
                    marked[cells(l[:-1])] += 1
                    page_lines[cur] += 1
                    cur = 0
                else:
                    plain[cells(l)] += 1
            if cur:
                page_lines[cur] += 1
    def tail(c):
        return ', '.join('%d: %d' % (k, c[k]) for k in sorted(c)[-5:])
    print('%d messages' % msgs)
    print('line width in cells, lines WITHOUT the page marker (largest 5 widths: count)  %s' % tail(plain))
    print('line width in cells, lines WITH the page marker, marker not counted           %s' % tail(marked))
    print('lines per page (pages with N lines: count)  %s' % dict(sorted(page_lines.items())))
    print('marker found in the middle of a line: %d' % mid)
    over = sum(v for k, v in plain.items() if k > WIDTH) + sum(v for k, v in marked.items() if k > WIDTH)
    print('lines wider than %d cells: %d' % (WIDTH, over))


_TYPO = {'’': "'", '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-',
         '…': '...', ' ': ' '}


def wrap_words(text, warn):
    lines, cur = [], ''
    for w in text.split():
        while cells(w) > WIDTH:                         # a single word wider than a line
            warn('word longer than %d cells was cut: %s' % (WIDTH, w))
            if cur:
                lines.append(cur)
                cur = ''
            lines.append(w[:WIDTH])
            w = w[WIDTH:]
        if not cur:
            cur = w
        elif cells(cur) + 1 + cells(w) <= WIDTH:
            cur += ' ' + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def format_message(text, warn):
    for a, b in _TYPO.items():
        text = text.replace(a, b)
    pages = []
    for seg in text.split(MARK):                         # a marker you typed forces a page break
        lines = []
        for chunk in seg.split('|'):                     # a | you typed forces a line break
            chunk = ' '.join(chunk.split())
            if chunk:
                lines.extend(wrap_words(chunk, warn))
        pages.extend(lines[i:i + PAGE_LINES] for i in range(0, len(lines), PAGE_LINES))
    out = []
    for pi, page in enumerate(pages):
        for li, line in enumerate(page):
            if li == len(page) - 1 and pi < len(pages) - 1:
                line += MARK
            out.append(line)
    return '\n'.join(out) + '\n'


def cmd_fit(inpath, outpath):
    """Reflow every "en" into game format: <=34 cells per line, 3 lines per page, page marker between pages.
    Reads your source JSON and writes a NEW file; your source text is never changed."""
    if pathlib.Path(inpath).resolve() == pathlib.Path(outpath).resolve():
        sys.exit('Give a different output file; fit never overwrites your source text.')
    with open(inpath, encoding='utf-8') as f:
        doc = json.load(f)
    n = changed = warns = 0
    for m in doc['messages']:
        if not m['en']:
            continue
        msgs = []
        new = format_message(m['en'], msgs.append)
        for ch in set(new):
            if ch in '();' and ch not in msgs:
                msgs.append("'%s' rendered oddly in the first font test; consider rewording" % ch)
        for w in msgs:
            print('%s: %s' % (m['key'], w))
            warns += 1
        n += 1
        if new != m['en']:
            m['en'] = new
            changed += 1
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('fitted %d message(s), %d changed, %d warning(s) -> %s' % (n, changed, warns, outpath))


def cmd_build(folder, jsonpath, outdir):
    with open(jsonpath, encoding='utf-8') as f:
        doc = json.load(f)
    edits, problems = {}, []
    for m in doc['messages']:
        if m['en'] and m['en'] != m['ja']:
            try:
                m['en'].encode('cp932')
            except UnicodeEncodeError as e:
                problems.append('%s: cannot encode %r' % (m['key'], m['en'][e.start:e.end]))
            edits[m['key']] = m['en']
    if not edits:
        sys.exit('Nothing to build: no "en" text in %s.\n'
                 'The step that writes this JSON (probe, markers, ruler or your translation) probably failed -\n'
                 'scroll up and read its message. Nothing was written.' % jsonpath)
    if problems:
        sys.exit('Fix these first:\n  ' + '\n  '.join(problems))
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    used, changed_files, grew = set(), 0, []
    for p in har_files(folder):
        raw = p.read_bytes()
        ver, recs = parse_har(raw)
        changed = False
        for ri, r in enumerate(recs):
            if r['ext'] != b'.evs':
                continue
            blocks = parse_evs(r['body'])
            hit = False
            for bi, b in enumerate(blocks):
                key = '%s:%d:%d' % (p.stem, ri, bi)
                if b['op'] == 1 and key in edits:
                    b['raw'] = encode_block(b, edits[key])
                    used.add(key)
                    hit = True
            if hit:
                r['body'] = build_evs(blocks)
                changed = True
        newdata = build_har(ver, recs) if changed else raw
        if len(newdata) > len(raw):
            print('WARNING: %s grows by %d bytes (%d -> %d); it will not fit in place on the disc.'
                  % (p.name, len(newdata) - len(raw), len(raw), len(newdata)))
            grew.append(p.name)
        (out / p.name).write_bytes(newdata)
        changed_files += changed
    missing = set(edits) - used
    print('patched %d files (%d messages) into %s' % (changed_files, len(used), out.resolve()))
    if missing:
        print('WARNING: %d keys in the JSON matched no message: %s' % (len(missing), sorted(missing)[:5]))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == 'roundtrip':
        cmd_roundtrip(a[1])
    elif len(a) == 3 and a[0] == 'extract':
        cmd_extract(a[1], a[2])
    elif len(a) == 4 and a[0] == 'build':
        cmd_build(a[1], a[2], a[3])
    elif len(a) >= 3 and a[0] == 'markers':
        cmd_markers(a[1], a[2], a[3:])
    elif len(a) >= 3 and a[0] == 'ruler':
        cmd_ruler(a[1], a[2], a[3:])
    elif len(a) in (2, 3) and a[0] == 'list':
        cmd_list(a[1], a[2] if len(a) == 3 else None)
    elif len(a) == 2 and a[0] == 'stats':
        cmd_stats(a[1])
    elif len(a) == 3 and a[0] == 'fit':
        cmd_fit(a[1], a[2])
    elif len(a) == 3 and a[0] == 'show':
        cmd_show(a[1], a[2])
    elif len(a) >= 4 and a[0] == 'probe':
        cmd_probe(a[1], a[2], a[3:])
    else:
        sys.exit(__doc__)
