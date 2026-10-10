"""
apply_patch.py - apply the Evangelion 2 English patch to YOUR OWN dump of the Japanese game.

  python apply_patch.py <your_japanese.iso> <EVA2_EN_beta.patch> [output.iso]

Your original ISO is never modified; a new, patched ISO is written next to it.
"""
import sys, os, struct, zlib, hashlib, shutil

MAGIC = b'EV2PATCH1\0'

def sha1_of(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b: break
            h.update(b)
    return h.digest()

def main(iso, patch, out=None):
    if out is None:
        base, ext = os.path.splitext(iso)
        out = base + '_EN' + (ext or '.iso')
    p = open(patch, 'rb').read()
    if not p.startswith(MAGIC): sys.exit('That is not a patch file for this project.')
    o = len(MAGIC)
    osz, nsz, n = struct.unpack_from('<QQI', p, o); o += 20
    osha, nsha = p[o:o + 20], p[o + 20:o + 40]; o += 40
    payload = zlib.decompress(p[o:])
    if os.path.getsize(iso) != osz:
        sys.exit('Wrong ISO: size is %d bytes, expected %d.\nYou need a clean dump of Shinseiki Evangelion 2 (SLPS-25299), not a modified or compressed one.' % (os.path.getsize(iso), osz))
    print('Checking your ISO...')
    if sha1_of(iso) != osha:
        sys.exit('Wrong ISO: the checksum does not match.\nYou need a clean dump of Shinseiki Evangelion 2 (SLPS-25299).')
    if os.path.abspath(out) == os.path.abspath(iso): sys.exit('Output must be a different file.')
    print('Copying to %s ...' % out)
    shutil.copyfile(iso, out)
    print('Patching...')
    with open(out, 'r+b') as f:
        q = 0
        for _ in range(n):
            off, ln = struct.unpack_from('<QI', payload, q); q += 12
            f.seek(off); f.write(payload[q:q + ln]); q += ln
        f.truncate(nsz)
    print('Verifying...')
    if sha1_of(out) != nsha:
        os.remove(out); sys.exit('Verification failed, patch not applied correctly.')
    print('Done! Patched game: %s' % out)

if __name__ == '__main__':
    if len(sys.argv) not in (3, 4): sys.exit(__doc__)
    try: main(*sys.argv[1:])
    except Exception as e: sys.exit('Error: %s' % e)
