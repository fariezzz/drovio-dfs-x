from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_uji import DUMMY_DIR, sha256_berkas, tulis_json  # noqa: E402

BLOK = 1024 * 1024

def buat_satu(path: str, ukuran_mb: int, benih: int) -> dict:
    mulai = time.perf_counter()
    tersisa = ukuran_mb * BLOK
    with open(path, "wb") as f:
        # Awalan unik memastikan tidak ada dua berkas dummy yang identik,
        # sehingga deduplikasi tidak mengaburkan hasil uji throughput.
        awalan = f"DFSX-DUMMY-{benih:06d}-".encode("ascii")
        f.write(awalan)
        tersisa -= len(awalan)
        while tersisa > 0:
            n = min(BLOK, tersisa)
            f.write(os.urandom(n))
            tersisa -= n
    return {
        "nama": os.path.basename(path),
        "path": path,
        "ukuran": os.path.getsize(path),
        "hash": sha256_berkas(path),
        "durasi_buat": round(time.perf_counter() - mulai, 3),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Buat berkas dummy untuk pengujian DFS-X")
    parser.add_argument("--jumlah", type=int, default=100, help="jumlah berkas (bawaan 100)")
    parser.add_argument(
        "--ukuran-mb", type=int, default=50, help="ukuran tiap berkas dalam MB (bawaan 50)"
    )
    parser.add_argument("--keluaran", default=DUMMY_DIR, help="folder keluaran")
    parser.add_argument(
        "--bersihkan", action="store_true", help="hapus berkas dummy lama lebih dulu"
    )
    parser.add_argument("--awalan", default="dummy", help="awalan nama berkas")
    argumen = parser.parse_args()

    folder = argumen.keluaran
    if argumen.bersihkan and os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)

    butuh = argumen.jumlah * argumen.ukuran_mb * BLOK
    try:
        bebas = shutil.disk_usage(folder).free
        if bebas < butuh * 1.1:
            print(
                f"Ruang disk tidak cukup: butuh sekitar {butuh / BLOK / 1024:.1f} GB,"
                f" tersedia {bebas / BLOK / 1024:.1f} GB",
                file=sys.stderr,
            )
            return 2
    except OSError:
        pass

    print(
        f"Membuat {argumen.jumlah} berkas dummy @ {argumen.ukuran_mb} MB"
        f" ({butuh / BLOK / 1024:.2f} GB total) di {folder}"
    )
    mulai = time.perf_counter()
    manifes = []
    for i in range(1, argumen.jumlah + 1):
        nama = f"{argumen.awalan}-{i:03d}-{argumen.ukuran_mb}mb.bin"
        info = buat_satu(os.path.join(folder, nama), argumen.ukuran_mb, i)
        manifes.append(info)
        if i % 10 == 0 or i == argumen.jumlah:
            print(f"  {i}/{argumen.jumlah} berkas selesai")

    total = round(time.perf_counter() - mulai, 2)
    path_manifes = os.path.join(folder, "manifes.json")
    with open(path_manifes, "w", encoding="utf-8") as f:
        import json

        json.dump(
            {
                "jumlah": len(manifes),
                "ukuran_mb_per_berkas": argumen.ukuran_mb,
                "total_byte": sum(m["ukuran"] for m in manifes),
                "durasi_pembuatan": total,
                "berkas": manifes,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    tulis_json(
        "dummy_manifes.json",
        {
            "jumlah": len(manifes),
            "ukuran_mb_per_berkas": argumen.ukuran_mb,
            "total_byte": sum(m["ukuran"] for m in manifes),
            "durasi_pembuatan": total,
            "folder": folder,
        },
    )

    print(f"Selesai dalam {total} detik. Manifes: {path_manifes}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
