"""
make_patch.py - (for the project maintainer) create a distributable patch file.

  python make_patch.py <original.iso> <translated.iso> <EVA2_EN_beta.patch>

The patch stores ONLY the bytes that differ between the two ISOs (plus a checksum of the original disc),
so it contains no game data that wasn't changed. Players apply it with apply_patch.py.
"""
import sys, struct, zlib, hashlib

MAGIC = b'EV2PATCH1\0'
SECTOR = 2048
GAP = 32          # merge changed runs closer together than this

def sha1_of(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b: break
            h.update(b)
    return h.digest()

def runs(a, b, base):
    """changed byte runs between equal-length-or-shorter a and b (b may be longer)."""
    out = []
    n = min(len(a), len(b))
    i = 0
    start = None
    last = None
    for i in range(n):
        if a[i] != b[i]:
            if start is None: start = i
            elif i - last > GAP:
                out.append((start, last + 1)); start = i
            last = i
    if start is not None: out.append((start, last + 1))
    return out

def main(orig, new, outp):
    import os
    osz, nsz = os.path.getsize(orig), os.path.getsize(new)
    recs = []  # (offset, bytes)
    with open(orig, 'rb') as fa, open(new, 'rb') as fb:
        pos = 0
        pend = None
        CH = SECTOR * 512
        while pos < nsz:
            a = fa.read(CH) if pos < osz else b''
            b = fb.read(CH)
            if a == b[:len(a)] and len(a) == len(b):
                pos += len(b); continue
            for s in range(0, len(b), SECTOR):
                sa, sb = a[s:s + SECTOR], b[s:s + SECTOR]
                if sa == sb: continue
                if len(sa) < len(sb):
                    # data past the end of the original disc: store whole
                    k = len(sa)
                    for st, en in runs(sa, sb, 0):
                        recs.append((pos + s + st, sb[st:en]))
                    recs.append((pos + s + k, sb[k:]))
                else:
                    for st, en in runs(sa, sb, 0):
                        recs.append((pos + s + st, sb[st:en]))
            pos += len(b)
    # merge adjacent / overlapping records
    recs.sort(key=lambda r: r[0])
    merged = []
    for off, d in recs:
        if merged and off <= merged[-1][0] + len(merged[-1][1]) + GAP:
            po, pd = merged[-1]
            end = po + len(pd)
            if off < end: pd = pd[:off - po]
            gap = b'' if off <= end else None
            if gap is None:
                # fill gap from new file later; simplest: store as separate record
                merged.append((off, d)); continue
            merged[-1] = (po, pd + d)
        else:
            merged.append((off, d))
    payload = b''.join(struct.pack('<QI', o, len(d)) + d for o, d in merged)
    with open(outp, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<QQI', osz, nsz, len(merged)))
        f.write(sha1_of(orig)); f.write(sha1_of(new))
        f.write(zlib.compress(payload, 9))
    print('records: %d, changed bytes: %d, patch size: %d bytes' % (len(merged), sum(len(d) for _, d in merged), os.path.getsize(outp)))

if __name__ == '__main__':
    if len(sys.argv) != 4: sys.exit(__doc__)
    main(*sys.argv[1:])
