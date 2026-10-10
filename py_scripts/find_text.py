"""
find_text.py - find where a piece of text lives on the disc.

  python find_text.py <iso> <text> [<text> ...]

Searches every file in the ISO (except the big audio/video folders) for each text, encoded as
Shift-JIS, and also as UTF-16.  For files in the HGAR format it also says which record the hit is in.
Example:  python find_text.py original.iso エリアに移動 "移動して！"
"""
import sys, struct
from iso_patch import scan, SECTOR

SKIP = ('/MOVIE/', '/STREAM/', '/VOICE/', '/SOUND/', '/NULLDATA')

def har_record(data, off):
    if data[:4] != b'HGAR': return ''
    try:
        n = struct.unpack_from('<H', data, 6)[0]
        offs = struct.unpack_from('<%dI' % n, data, 8)
        for i, o in enumerate(offs):
            nxt = offs[i + 1] if i + 1 < n else len(data)
            if o <= off < nxt:
                name = data[o:o+8].split(b'\0')[0].decode('ascii', 'replace')
                ext = data[o+8:o+12].split(b'\0')[0].decode('ascii', 'replace')
                return ' [record %d: %s%s]' % (i, name, ext)
    except Exception:
        pass
    return ''

def main():
    iso, texts = sys.argv[1], sys.argv[2:]
    pats = []
    for t in texts:
        pats.append((t, 'sjis', t.encode('cp932', 'replace')))
        pats.append((t, 'utf16', t.encode('utf-16-le')))
    total = 0
    with open(iso, 'rb') as f:
        files = scan(f)
        for path, (lba, size, _) in sorted(files.items()):
            if any(path.startswith(s) for s in SKIP) or size == 0: continue
            f.seek(lba * SECTOR); data = f.read(size)
            for t, enc, p in pats:
                pos, hits = 0, []
                while True:
                    i = data.find(p, pos)
                    if i < 0: break
                    hits.append(i); pos = i + 1
                if hits:
                    total += len(hits)
                    print('%s: %r (%s) x%d, first at %#x%s' % (path, t, enc, len(hits), hits[0], har_record(data, hits[0])))
    print('total hits:', total)

main()