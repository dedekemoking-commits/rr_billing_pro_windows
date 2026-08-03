"""Ekstrak modul dari PYZ di dalam EXE PyInstaller 6 (onedir: PYZ embedded di EXE).

Cara pakai:
  python scripts/pyz_verify.py <path_exe> <nama_modul>
Contoh:
  python scripts/pyz_verify.py dist\\RRBILLINGPRO\\RRBILLINGPRO.exe tv_media_server
"""
import struct
import sys
import zlib

COOKIE_MAGIC = b"MEI\x0c\x0b\x0a\x0e\x02\x0c"
COOKIE_STRUCT = struct.Struct("!8siiii64s")  # magic,len,TOC,TOClen,pyvers,pylibname


def find_cookie(data: bytes):
    # Magic bervariasi antar versi PyInstaller ("MEI\x0c\x0b\x0a\x0b\x0e" dll);
    # cari 8 byte terakhir yang dimulai "MEI" dekat akhir file.
    for pos in range(len(data) - 8, max(len(data) - 4096, 0), -1):
        if data[pos : pos + 3] == b"MEI" and pos + 88 <= len(data):
            magic, alen, _, _, pyver, _ = COOKIE_STRUCT.unpack_from(data, pos)
            if alen and 0 < alen < len(data) and pos - alen >= 0:
                return pos
    return None


def parse_carchive_toc(data: bytes, archive_start: int, toc_pos: int, toc_len: int):
    entries = {}
    p = archive_start + toc_pos
    end = p + toc_len
    while p < end:
        (offset, size, compressed, typ, nlen) = struct.unpack_from("!iiiBB", data, p)
        p += 14
        name = data[p : p + nlen].decode("utf-8", "replace")
        p += nlen
        if (nlen & 1) == 0:
            p += 1  # padding agar genap
        entries[name] = (offset, size, compressed, typ)
    return entries


def extract_entry(data: bytes, archive_start: int, offset: int, size: int, compressed: int):
    chunk = data[archive_start + offset : archive_start + offset + size]
    if compressed and chunk[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
        try:
            return zlib.decompress(chunk)
        except Exception:
            pass
    return chunk


def parse_pyz(data: bytes):
    assert data[:4] == b"PYZ\x00", "bukan arsip PYZ"
    # header PYZ: magic(4) + posisi TOC(4) [PyInstaller 6]
    toc_pos = struct.unpack_from("!i", data, 8)[0]
    modules = {}
    p = toc_pos
    while p + 14 <= len(data):
        (offset, length, ulength, typ, nlen) = struct.unpack_from("!iiiBB", data, p)
        p += 14
        name = data[p : p + nlen].decode("utf-8", "replace")
        p += nlen
        if (nlen & 1) == 0:
            p += 1
        if offset == 0 and length == 0:
            break
        if name.endswith("(crypto)") or typ == ord("c"):
            modules[name] = b"<crypto>"
            continue
        raw = data[offset : offset + length]
        try:
            modules[name] = zlib.decompress(raw)
        except Exception:
            modules[name] = raw
    return modules


def main():
    exe_path = sys.argv[1]
    module_name = sys.argv[2]
    data = open(exe_path, "rb").read()
    cookie_pos = find_cookie(data)
    if cookie_pos is None:
        print("COOKIE TIDAK DITEMUKAN")
        return 1
    magic, alen, toc_off, toc_len, pyver, _ = COOKIE_STRUCT.unpack_from(data, cookie_pos)
    archive_start = cookie_pos - alen
    print(f"cookie@{cookie_pos} arsip_len={alen} pyver={pyver} toc_len={toc_len}")

    entries = parse_carchive_toc(data, archive_start, toc_off, toc_len)
    pyz_name = next((n for n in entries if n.upper().startswith("PYZ")), None)
    if pyz_name is None:
        print("ENTRY PYZ TIDAK DITEMUKAN; entries:", list(entries)[:20])
        return 1
    print(f"entry PYZ: {pyz_name!r}")
    off, size, comp, _ = entries[pyz_name]
    pyz = extract_entry(data, archive_start, off, size, comp)
    modules = parse_pyz(pyz)
    print(f"modul di PYZ: {len(modules)}")

    hits = [n for n in modules if module_name in n]
    print(f"modul cocok: {hits}")
    for h in hits:
        body = modules[h]
        if body == b"<crypto>":
            print(f"{h}: (crypto)")
            continue
        for pat in (b"do_HEAD", b"Content-Range", b"protocol_version", b"keep-alive",
                    b"Accept-Ranges", b"HTTP/1.1"):
            print(f"{h}: {pat.decode()} -> {body.count(pat)}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
