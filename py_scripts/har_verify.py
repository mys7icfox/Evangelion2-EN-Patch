"""
har_verify.py (v2) - check the HGAR / .EVS layout against every .HAR file.

Usage:
    python har_verify.py <EVENT folder>              # verify all files, print summary
    python har_verify.py <EVENT folder> BK005.HAR    # also dump that file's records

HGAR container (derived from the BK005, BA001 and a015 dumps):
    'HGAR' | u16 version | u16 count | u32 offsets[count]
    each offset points to a record:
        name[8] | ext[4] | u32 unknown | u32 size | data[size]
.EVS script chunk (the data of a '.evs' record):
    '.EVS' | u32 count | u32 offsets[count]      (offsets relative to chunk start)
    each block: u16 opcode | u16 payload_len | payload | 0-3 padding bytes (4-byte alignment)
    opcode 1 = text message; payload = u32 extra | u32 style | u32 id | Shift-JIS text | NUL
"""
import re
import sys
import struct
import pathlib
from collections import Counter, defaultdict


def read_har(data):
    if data[:4] != b'HGAR':
        raise ValueError('bad magic')
    ver, count = struct.unpack_from('<HH', data, 4)
    offs = struct.unpack_from('<%dI' % count, data, 8)
    recs = []
    for i, off in enumerate(offs):
        name = data[off:off + 8].decode('ascii', 'replace').strip()
        ext = data[off + 8:off + 12].decode('ascii', 'replace').strip().lower()
        unk, size = struct.unpack_from('<II', data, off + 12)
        start = off + 20
        nxt = offs[i + 1] if i + 1 < count else len(data)
        if start + size > nxt:
            raise ValueError('record %d overruns the next record / end of file' % i)
        recs.append(dict(name=name, ext=ext, unk=unk, size=size, start=start,
                         gap=nxt - (start + size)))
    return ver, recs


def read_evs(chunk):
    if chunk[:4] != b'.EVS':
        raise ValueError('no .EVS tag')
    n = struct.unpack_from('<I', chunk, 4)[0]
    offs = list(struct.unpack_from('<%dI' % n, chunk, 8))
    blocks = []
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < n else len(chunk)
        op, plen = struct.unpack_from('<HH', chunk, off)
        pad = (end - off) - 4 - plen
        if not 0 <= pad <= 3:
            raise ValueError('block %d (op %#x): payload %d does not fit block of %d bytes'
                             % (i, op, plen, end - off))
        payload = chunk[off + 4:off + 4 + plen]
        blk = dict(op=op, plen=plen, pad=pad, payload=payload)
        if op == 1:
            if plen < 13 or payload[-1] != 0:
                raise ValueError('block %d: malformed message payload' % i)
            blk['extra'], blk['style'], blk['id'] = struct.unpack_from('<III', payload, 0)
            blk['text'] = payload[12:-1].decode('cp932', 'replace')
        blocks.append(blk)
    return blocks


def main():
    folder = pathlib.Path(sys.argv[1])
    dump_name = sys.argv[2].upper() if len(sys.argv) > 2 else None
    if not folder.is_dir():
        sys.exit('Folder not found: %s\n(Put the path in quotes if it has spaces.)' % folder.resolve())
    files = sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() == '.har')
    print('Looked in: %s' % folder.resolve())
    print('.HAR files found: %d' % len(files))
    if not files:
        sys.exit('No .HAR files found. First items: %s' % [p.name for p in list(folder.iterdir())[:10]])

    rows = []
    exts, ext_example = Counter(), {}
    gaps, pads = Counter(), Counter()
    opinfo = defaultdict(Counter)
    styles, extras = Counter(), Counter()
    odd_text = 0
    n_msgs = 0

    for p in files:
        data = p.read_bytes()
        try:
            ver, recs = read_har(data)
            for r in recs:
                exts[r['ext']] += 1
                ext_example.setdefault(r['ext'], '%s (%s, %d bytes)' % (p.name, r['name'], r['size']))
                gaps[r['gap']] += 1
                if r['ext'] == '.evs':
                    blocks = read_evs(data[r['start']:r['start'] + r['size']])
                    for i, b in enumerate(blocks):
                        pads[b['pad']] += 1
                        if b['op'] == 1:
                            n_msgs += 1
                            styles[b['style']] += 1
                            extras[b['extra']] += 1
                            odd_text += '\ufffd' in b['text']
                        else:
                            opinfo[b['op']][b['plen']] += 1
                    if p.name.upper() == dump_name:
                        print('--- %s : record %s (%d blocks)' % (p.name, r['name'], len(blocks)))
                        for i, b in enumerate(blocks):
                            if b['op'] == 1:
                                print('[%d] MSG extra=%#x style=%#x id=%#x %r'
                                      % (i, b['extra'], b['style'], b['id'], b['text']))
                            else:
                                print('[%d] op=%#x len=%d payload=%s' % (i, b['op'], b['plen'], b['payload'].hex(' ')))
            rows.append((p.name, 'OK', '', len(data), ver, len(recs)))
        except Exception as e:
            kind = re.sub(r'\d+', 'N', str(e))
            kind = re.sub(r"b'[^']*'", "b'..'", kind)
            rows.append((p.name, 'FAIL', kind, len(data), '', ''))

    with open('har_report.tsv', 'w', encoding='utf-8') as f:
        f.write('file\tstatus\terror\tsize\tversion\trecords\n')
        for r in rows:
            f.write('\t'.join(str(x) for x in r) + '\n')

    ok = [r for r in rows if r[1] == 'OK']
    bad = [r for r in rows if r[1] == 'FAIL']
    print('files OK: %d   failed: %d   (full list in har_report.tsv)' % (len(ok), len(bad)))
    print('\nRECORD TYPES (extension: count, example):')
    for e, c in exts.most_common():
        print('  %-6s %5d   e.g. %s' % (e or '(none)', c, ext_example[e]))
    print('gap bytes between records (bytes: count):', dict(gaps.most_common(8)))
    print('padding bytes after blocks (bytes: count):', dict(pads))
    print('\nMESSAGES: %d total, %d with undecodable bytes' % (n_msgs, odd_text))
    print('  style codes:', [(hex(k), v) for k, v in styles.most_common(12)])
    print('  extra values:', [(hex(k), v) for k, v in extras.most_common(12)])
    print('\nOTHER BLOCK OPCODES (opcode: count, payload sizes):')
    for op, c in sorted(opinfo.items(), key=lambda kv: -sum(kv[1].values()))[:30]:
        print('  %#06x  %6d   sizes %s' % (op, sum(c.values()), dict(c.most_common(5))))

    groups = defaultdict(list)
    for r in bad:
        groups[r[2]].append(r)
    print('\nFAILURES BY TYPE:')
    for kind, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print('%4d x %s' % (len(rs), kind))
        for r in rs[:3]:
            print('       e.g. %s (%d bytes)' % (r[0], r[3]))


if __name__ == '__main__':
    main()
