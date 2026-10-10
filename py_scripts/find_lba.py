"""
find_lba.py - find out HOW the game locates its files on the disc.

  python find_lba.py <original.iso>

It reads the ISO directory, then searches SLPS_252.99 and the other small program/data files
for (a) file NAMES and (b) the disc positions (LBA) and sizes of real files, stored as 32-bit numbers.
If the game uses a table of positions, those numbers show up clustered in one place.
Writes find_lba_report.txt. Nothing is modified. Send me the printed summary.
"""
import sys, struct, collections
from iso_patch import scan, SECTOR

def main():
    iso = sys.argv[1]
    with open(iso, 'rb') as f:
        files = scan(f)
        print('files in ISO:', len(files))
        lbas = collections.defaultdict(list)
        for p, (lba, size, _) in files.items():
            if size: lbas[lba].append(p)
        cands = [p for p, (l, s, _) in files.items()
                 if p.endswith('SLPS_252.99') or p.startswith('/SYS/') or p.startswith('/PROG/') or p.startswith('/IOP/')
                 if s < 8_000_000]
        report = []
        for p in sorted(cands):
            lba, size, _ = files[p]
            f.seek(lba * SECTOR); data = f.read(size)
            hits = []   # (offset, kind, file)
            n = len(data) // 4
            vals = struct.unpack_from('<%dI' % n, data, 0) if n else ()
            for i, v in enumerate(vals):
                if v in lbas and v > 100:
                    hits.append((i * 4, 'lba', lbas[v][0]))
            # also 'lba' stored relative to a base is not covered; look at names
            names = {}
            for q in files:
                nm = q.rsplit('/', 1)[1].encode()
                c = data.count(nm)
                if c: names[q] = c
            # cluster: runs of hits within 64 bytes
            clusters = []
            for h in hits:
                if clusters and h[0] - clusters[-1][-1][0] <= 64: clusters[-1].append(h)
                else: clusters.append([h])
            big = [c for c in clusters if len(c) >= 5]
            line = '%s (%d bytes): %d LBA hits, %d clusters>=5, %d filenames found as text' % (p, size, len(hits), len(big), len(names))
            print(line); report.append(line)
            for c in sorted(big, key=len, reverse=True)[:3]:
                l = '   cluster at 0x%x: %d hits, e.g. %s' % (c[0][0], len(c), ', '.join('%s@%#x' % (x[2].rsplit('/',1)[1], x[0]) for x in c[:4]))
                print(l); report.append(l)
            if names:
                l = '   names as text: ' + ', '.join(list(n.rsplit('/',1)[1] for n in names)[:8])
                print(l); report.append(l)
            # directory-name strings
            for key in (b'EVENT', b'S001.HAR', b'S001', b'VOICE', b'cdrom0:', b'\\EVENT', b'EVENT\\'):
                k = data.find(key)
                if k >= 0:
                    l = '   text %r at 0x%x: %r' % (key, k, data[max(0,k-16):k+24])
                    print(l); report.append(l)
    open('find_lba_report.txt', 'w', encoding='utf-8').write('\n'.join(report))
    print('\nwrote find_lba_report.txt')
main()