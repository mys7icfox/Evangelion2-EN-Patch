"""
scan_patch.py - write translated strings from scan_all_todo.json back into the game files, IN PLACE.

  python scan_patch.py build <translated.json> <original.iso> <outdir>
  python scan_patch.py build <translated.json> --dir <folder> <outdir>     (originals are loose files)

<translated.json> is a list of items {file, offset, ja, budget, en, also}  (as in scan_all_todo.json,
with "en" filled in).  Items with an empty "en" are skipped.  Each English string must fit in
budget-1 bytes (ASCII = 1 byte, the fullwidth slash and percent sign = 2 bytes); the build refuses
anything longer and checks that the original Japanese is really at that offset before touching it.

Patched copies are written to <outdir>/<FOLDER>/<NAME>, e.g. outdir/PROG/TITLE.BIN, outdir/EVENT/BS040.HAR,
outdir/ROOT/SLPS_252.99.  The script prints the iso_patch.py command for each folder.
"""
import sys, json, os, collections
from scan_all import iso_files, SECTOR


def enc(s):
    try:
        return s.encode('cp932')
    except UnicodeEncodeError as e:
        raise SystemExit('cannot encode %r: %s' % (s, e))


def main():
    a = sys.argv[1:]
    if len(a) < 4 or a[0] != 'build':
        sys.exit(__doc__)
    items = json.load(open(a[1], encoding='utf-8'))
    items = [i for i in items if i.get('en')]
    dirmode = a[2] == '--dir'
    src = a[3] if dirmode else a[2]
    outdir = a[4] if dirmode else a[3]
    bad = 0
    for it in items:
        n = len(enc(it['en']))
        if n > it['budget'] - 1:
            bad += 1
            print('TOO LONG (%d > %d) %s @%#x: %r' % (n, it['budget'] - 1, it['file'], it['offset'], it['en']))
    if bad:
        sys.exit('%d strings too long - nothing written.' % bad)
    byfile = collections.defaultdict(list)
    for it in items:
        byfile[it['file']].append(it)
    fh = None if dirmode else open(src, 'rb')
    iso = None if dirmode else iso_files(fh)
    done = collections.defaultdict(list)
    for path, its in sorted(byfile.items()):
        if dirmode:
            data = bytearray(open(os.path.join(src, path.lstrip('/')), 'rb').read())
        else:
            if path not in iso:
                sys.exit('%s not found in the ISO' % path)
            lba, size = iso[path]
            fh.seek(lba * SECTOR)
            data = bytearray(fh.read(size))
        for it in its:
            old = enc(it['ja'])
            e = enc(it['en'])
            for off in [it['offset']] + list(it.get('also', [])):
                if bytes(data[off:off + len(old)]) != old:
                    sys.exit('%s @%#x does not hold the expected Japanese - wrong disc version?' % (path, off))
                data[off:off + len(old) + 1] = b'\0' * (len(old) + 1)     # clear old text and its NUL
                data[off:off + len(e)] = e
        folder, name = (path.strip('/').rsplit('/', 1) + [None])[:2] if '/' in path.strip('/') else ('ROOT', path.strip('/'))
        if name is None:
            folder, name = 'ROOT', path.strip('/')
        os.makedirs(os.path.join(outdir, folder), exist_ok=True)
        open(os.path.join(outdir, folder, name), 'wb').write(bytes(data))
        done[folder].append(name)
    print('patched %d strings in %d files' % (len(items), sum(len(v) for v in done.values())))
    print('\nNext, for each folder (use "." for ROOT), write the files into a copy of your latest test ISO:')
    for folder in sorted(done):
        print('  python iso_patch.py patch <in.iso> <out.iso> %s %s --relocate' % (os.path.join(outdir, folder), '.' if folder == 'ROOT' else folder))
    print('(each command takes the previous out.iso as its in.iso)')


if __name__ == '__main__':
    main()
