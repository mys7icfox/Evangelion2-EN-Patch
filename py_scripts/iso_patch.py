"""
iso_patch.py - replace files inside a PS2 ISO IN PLACE, without rebuilding the ISO.

Every file keeps exactly the same position (LBA) on the disc, so nothing else moves.
This matters because PS2 games often read files by fixed disc position.

  python iso_patch.py list  <game.iso> <iso folder>
        List the files in a folder inside the ISO, e.g.  list game.iso EVENT

  python iso_patch.py read  <game.iso> <path in iso> <outfile>
        Copy one file out of the ISO, e.g.  read test.iso EVENT/S001.HAR from_iso.har
        so you can check what is really on the disc.

  python iso_patch.py patch <game.iso> <new.iso> <patched folder> <iso folder> [--allow-resize]
        Copy game.iso to new.iso, then write each file from <patched folder> over the file
        with the same name in <iso folder>. Your original ISO is never modified.
        e.g.  patch game.iso game_en.iso patched EVENT

  A file that is SMALLER than the original is padded with zeros to the original size, so the
  ISO directory is untouched.  A file that is LARGER is refused unless it still fits in the
  disc sectors the original already occupies and you pass --allow-resize (the directory
  entry's size is then updated).  With --relocate, a file that is too large is instead appended
  at the END of the image and its directory entry (position and size) is pointed there.
  Everything else stays where it is.  Only works if the game finds files by name.
"""
import sys
import struct
import shutil
import pathlib

SECTOR = 2048


def scan(f):
    """Return {PATH: (lba, size, record_offset)} for every file in the ISO9660 tree."""
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b'CD001':
        raise ValueError('no ISO9660 primary volume descriptor at sector 16')
    root_lba, root_size = struct.unpack_from('<I', pvd, 156 + 2)[0], struct.unpack_from('<I', pvd, 156 + 10)[0]
    out = {}

    def walk(lba, size, path):
        f.seek(lba * SECTOR)
        data = f.read(size)
        pos = 0
        while pos < len(data):
            n = data[pos]
            if n == 0:                       # records never cross a sector boundary
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + n]
            e_lba = struct.unpack_from('<I', rec, 2)[0]
            e_size = struct.unpack_from('<I', rec, 10)[0]
            flags, nlen = rec[25], rec[32]
            name = rec[33:33 + nlen]
            rec_off = lba * SECTOR + pos
            pos += n
            if name in (b'\x00', b'\x01'):
                continue
            name = name.decode('ascii', 'replace').split(';')[0]
            full = path + '/' + name.upper()
            if flags & 2:
                walk(e_lba, e_size, full)
            else:
                out[full] = (e_lba, e_size, rec_off)

    walk(root_lba, root_size, '')
    return out


def alloc(size):
    return -(-size // SECTOR) * SECTOR


def cmd_list(iso, folder):
    prefix = '/' + folder.strip('/').upper() + '/'
    with open(iso, 'rb') as f:
        files = scan(f)
    n = 0
    for path, (lba, size, _) in sorted(files.items()):
        if path.startswith(prefix):
            print('%-32s lba=%-8d size=%-10d room_to_grow=%d' % (path, lba, size, alloc(size) - size))
            n += 1
    print('%d files under %s' % (n, prefix))


def cmd_read(iso, isopath, out):
    key = '/' + isopath.replace('\\', '/').strip('/').upper()
    with open(iso, 'rb') as f:
        files = scan(f)
        if key not in files:
            sys.exit('%s not found in the ISO' % key)
        lba, size, _ = files[key]
        f.seek(lba * SECTOR)
        data = f.read(size)
    pathlib.Path(out).write_bytes(data)
    print('wrote %s (%d bytes, from lba %d)' % (out, len(data), lba))


def cmd_patch(src, dst, folder, isodir, allow_resize, relocate=False):
    prefix = '/' + isodir.strip('/').upper() + '/'
    newfiles = sorted(p for p in pathlib.Path(folder).iterdir() if p.is_file())
    with open(src, 'rb') as f:
        files = scan(f)
    plan, errors = [], []
    for p in newfiles:
        key = prefix + p.name.upper()
        if key not in files:
            errors.append('%s: not found in the ISO at %s' % (p.name, key))
            continue
        lba, size, rec_off = files[key]
        data = p.read_bytes()
        if len(data) <= size:
            plan.append((p.name, lba, data + b'\0' * (size - len(data)), None, rec_off, False))
        elif len(data) <= alloc(size) and allow_resize:
            plan.append((p.name, lba, data, len(data), rec_off, False))
        elif relocate:
            plan.append((p.name, lba, data, len(data), rec_off, True))
        elif len(data) <= alloc(size):
            errors.append('%s: %d bytes is larger than the original %d (fits in its sectors; add --allow-resize)'
                          % (p.name, len(data), size))
        else:
            errors.append('%s: %d bytes does not fit in the %d bytes the original occupies - cannot patch in place'
                          % (p.name, len(data), alloc(size)))
    if errors:
        sys.exit('Nothing written. Problems:\n  ' + '\n  '.join(errors[:25])
                 + ('\n  ... and %d more' % (len(errors) - 25) if len(errors) > 25 else ''))
    if not plan:
        sys.exit('No files to patch.')
    shutil.copyfile(src, dst)
    moved = []
    with open(dst, 'r+b') as f:
        f.seek(0, 2)
        end = -(-f.tell() // SECTOR)             # first free sector after the original image
        for i, (name, lba, data, newsize, rec_off, reloc) in enumerate(plan):
            if reloc:
                f.seek(end * SECTOR)
                f.write(data + b'\0' * (alloc(len(data)) - len(data)))
                f.seek(rec_off + 2)
                f.write(struct.pack('<I', end) + struct.pack('>I', end))
                moved.append((name, lba, end))
                plan[i] = (name, end, data, newsize, rec_off, reloc)
                end += alloc(len(data)) // SECTOR
            else:
                f.seek(lba * SECTOR)
                f.write(data)
            if newsize is not None:          # update both-endian size field in the directory record
                f.seek(rec_off + 10)
                f.write(struct.pack('<I', newsize) + struct.pack('>I', newsize))
        if moved:                            # volume size in the primary volume descriptor
            f.seek(16 * SECTOR + 80)
            f.write(struct.pack('<I', end) + struct.pack('>I', end))
    for name, old, new in moved:
        print('moved %s: lba %d -> %d' % (name, old, new))
    bad = 0
    with open(dst, 'rb') as f:
        for name, lba, data, newsize, rec_off, reloc in plan:
            f.seek(lba * SECTOR)
            bad += f.read(len(data)) != data
    print('patched %d files into %s (verify: %s)' % (len(plan), dst, 'OK' if not bad else '%d MISMATCHES' % bad))


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if x not in ('--allow-resize', '--relocate')]
    flag = '--allow-resize' in sys.argv
    if len(a) == 3 and a[0] == 'list':
        cmd_list(a[1], a[2])
    elif len(a) == 4 and a[0] == 'read':
        cmd_read(a[1], a[2], a[3])
    elif len(a) == 5 and a[0] == 'patch':
        cmd_patch(a[1], a[2], a[3], a[4], flag, '--relocate' in sys.argv)
    else:
        sys.exit(__doc__)
