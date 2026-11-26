#!/usr/bin/env python3
"""Setara `zipalign -p 4`: menyelaraskan entri APK ke batas 4 byte.

Dipakai karena Android SDK build-tools (zipalign) tidak tersedia untuk
aarch64/Termux. Berkas resources.arsc selalu disimpan tanpa kompresi.
"""
import struct
import sys
import zipfile
import zlib

ALIGN = 4
ALWAYS_STORED = {"resources.arsc"}


def main(src, dst):
    zin = zipfile.ZipFile(src)
    infos = zin.infolist()

    with open(dst, "wb") as out:
        central = []
        for info in infos:
            raw = zin.read(info.filename)
            name = info.filename.encode("utf-8")
            stored = info.compress_type == zipfile.ZIP_STORED or info.filename in ALWAYS_STORED
            if stored:
                method = zipfile.ZIP_STORED
                blob = raw
            else:
                method = zipfile.ZIP_DEFLATED
                # ZIP memakai DEFLATE mentah (tanpa header zlib).
                compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
                blob = compressor.compress(raw) + compressor.flush()
            crc = zlib.crc32(raw) & 0xFFFFFFFF

            offset = out.tell()
            rem = (offset + 30 + len(name) + 4) % ALIGN
            pad = (ALIGN - rem) % ALIGN
            extra = struct.pack("<HH", 0xD935, pad) + b"\x00" * pad

            out.write(
                struct.pack(
                    "<IHHHHHIIIHH",
                    0x04034B50,
                    20,
                    0,
                    method,
                    info.date_time[3] << 11 | info.date_time[4] << 5 | info.date_time[5] // 2,
                    (info.date_time[0] - 1980) << 9 | info.date_time[1] << 5 | info.date_time[2],
                    crc,
                    len(blob),
                    len(raw),
                    len(name),
                    len(extra),
                )
            )
            out.write(name)
            out.write(extra)
            out.write(blob)

            central.append(
                (name, method, crc, len(blob), len(raw), len(extra), offset, info)
            )

        cd_start = out.tell()
        for name, method, crc, csize, usize, extralen, offset, info in central:
            out.write(
                struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    20,
                    20,
                    0,
                    method,
                    info.date_time[3] << 11 | info.date_time[4] << 5 | info.date_time[5] // 2,
                    (info.date_time[0] - 1980) << 9 | info.date_time[1] << 5 | info.date_time[2],
                    crc,
                    csize,
                    usize,
                    len(name),
                    extralen,
                    0,
                    0,
                    0,
                    info.external_attr,
                    offset,
                )
            )
            out.write(name)
            out.write(struct.pack("<HH", 0xD935, extralen - 4) + b"\x00" * (extralen - 4))
        cd_size = out.tell() - cd_start

        out.write(
            struct.pack(
                "<IHHHHIIH",
                0x06054B50,
                0,
                0,
                len(central),
                len(central),
                cd_size,
                cd_start,
                0,
            )
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("pemakaian: zipalign.py <masukan.apk> <keluaran.apk>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
