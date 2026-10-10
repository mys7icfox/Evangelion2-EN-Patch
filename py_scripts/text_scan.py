"""
text_scan.py - find where the remaining Japanese text lives on the disc.

  python text_scan.py <original.iso>

Reads every file in the ISO except the big audio/video folders (MOVIE, STREAM, VOICE, SOUND),
and looks for Shift-JIS Japanese text. For HGAR (.HAR) files it also looks inside each record.
Writes:
  text_scan_report.txt   one line per file: how many text runs, plus samples
  text_scan.json         every run found outside the already-translated .EVS scripts
Nothing is modified. Attach text_scan_report.txt (and text_scan.json if it is under a few MB).
"""
import sys, re, json, struct, collections
from iso_patch import scan, SECTOR

SKIP = ('/MOVIE/', '/STREAM/', '/VOICE/', '/SOUND/', '/NULLDATA')
# a run of Shift-JIS double-byte characters (lead 81-84, 88-9f, e0-ea) with optional ASCII between
PAIR = rb'(?:[\x81-\x84\x88-\x9f\xe0-\xea][\x40-\x7e\x80-\xfc])'
RUN = re.compile(rb'(?:' + PAIR + rb'|[\x20-\x7e\n]){4,}')

def is_jp(s):
    return sum(1 for c in s if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or c in '＀￯') >= 3

def runs(data, base=0):
    out = []
    for m in RUN.finditer(data):
        b = m.group()
        if not re.search(PAIR, b): continue
        try: s = b.decode('cp932')
        except UnicodeDecodeError: continue
        if is_jp(s): out.append((base + m.start(), s.strip()))
    return out

def har_records(data):
    if data[:4] != b'HGAR': return None
    try:
        ver, n = struct.unpack_from('<HH', data, 4)
        offs = struct.unpack_from('<%dI' % n, data, 8)
        recs = []
        for off in offs:
            name = data[off:off+8].split(b'\0')[0].decode('ascii', 'replace')
            ext = data[off+8:off+12].split(b'\0')[0].decode('ascii', 'replace').lower()
            size = struct.unpack_from('<I', data, off+16)[0]
            recs.append((name, ext, off + 20, size))
        return recs
    except Exception:
        return None

def main():
    iso = sys.argv[1]
    rep, allruns = [], {}
    with open(iso, 'rb') as f:
        files = scan(f)
        for path, (lba, size, _) in sorted(files.items()):
            if any(path.startswith(s) for s in SKIP) or size == 0: continue
            f.seek(lba * SECTOR); data = f.read(size)
            recs = har_records(data)
            found, kinds = [], collections.Counter()
            if recs is not None:
                for name, ext, start, sz in recs:
                    kinds[ext] += 1
                    if ext == '.evs': continue          # already handled by har_text.py
                    r = runs(data[start:start+sz], start)
                    found += r
            else:
                found = runs(data)
            if found:
                allruns[path] = found
            rep.append((len(found), path, size, dict(kinds) if recs is not None else 'raw', found[:3]))
    rep.sort(key=lambda r: (-r[0], r[1]))
    tot = sum(r[0] for r in rep)
    with open('text_scan_report.txt', 'w', encoding='utf-8') as o:
        o.write('files with untranslated-looking Japanese: %d, runs: %d\n\n' % (sum(1 for r in rep if r[0]), tot))
        for n, p, sz, k, sample in rep:
            if not n: continue
            o.write('%5d runs  %s  (%d bytes, %s)\n' % (n, p, sz, k))
            for off, s in sample: o.write('         @%#x %s\n' % (off, s[:60].replace('\n', ' / ')))
    json.dump({p: [(o, s) for o, s in r] for p, r in allruns.items()}, open('text_scan.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print(open('text_scan_report.txt', encoding='utf-8').read()[:6000])
    print('\nwrote text_scan_report.txt and text_scan.json')

main()
