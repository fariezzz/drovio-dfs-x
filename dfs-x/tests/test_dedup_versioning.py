from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_uji import KlienDfsx, tulis_json  # noqa: E402

BLOK = 1024 * 1024

def tulis_berkas(path: str, bagian: list[bytes]) -> str:
    h = hashlib.sha256()
    with open(path, "wb") as f:
        for b in bagian:
            f.write(b)
            h.update(b)
    return h.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser(description="Uji deduplikasi dan versioning DFS-X")
    parser.add_argument("--ukuran-mb", type=int, default=16, help="ukuran berkas dasar")
    parser.add_argument("--ulangi", type=int, default=3, help="berapa kali berkas sama diunggah")
    parser.add_argument("--mode", default="auto", choices=["auto", "ringkas", "dua_tahap"])
    argumen = parser.parse_args()

    klien = KlienDfsx(mode=argumen.mode)
    chunk_mb = klien.chunk_size // BLOK
    print("=" * 72)
    print("UJI DEDUPLIKASI DAN VERSIONING DFS-X")
    print("=" * 72)
    print(f"  Ukuran berkas dasar : {argumen.ukuran_mb} MB")
    print(f"  Ukuran chunk        : {chunk_mb} MB")
    print(f"  Mode klien          : {klien.mode}")
    print("-" * 72)

    klien.reset()
    kerja = tempfile.mkdtemp(prefix="dfsx-dedup-")
    laporan: dict = {"waktu_uji": time.strftime("%Y-%m-%dT%H:%M:%S")}

    try:
        # Potongan selaras batas chunk agar hash chunk yang sama benar cocok.
        jumlah_chunk = max(2, argumen.ukuran_mb // chunk_mb)
        chunk_a = [os.urandom(klien.chunk_size) for _ in range(jumlah_chunk)]
        # Dibuat terpisah agar berkas pembanding tidak ikut terdeduplikasi.
        chunk_campuran = [os.urandom(klien.chunk_size) for _ in range(jumlah_chunk)]
        chunk_unik = [os.urandom(klien.chunk_size) for _ in range(jumlah_chunk)]

        path_a = os.path.join(kerja, "dedup-asal.bin")
        hash_a = tulis_berkas(path_a, chunk_a)

        # ---------------- Pola 1: berkas sama diunggah berulang ----------------
        print(f"\n[1/5] Mengunggah berkas yang sama {argumen.ulangi} kali")
        pola1 = []
        for i in range(1, argumen.ulangi + 1):
            hasil = klien.unggah(path_a, f"dedup-salinan-{i}.bin")
            st = klien.status()["statistik"]
            pola1.append(
                {
                    "unggahan": i,
                    "nama": f"dedup-salinan-{i}.bin",
                    "berhasil": hasil.berhasil,
                    "jumlah_chunk": hasil.jumlah_chunk,
                    "chunk_dideduplikasi": hasil.chunk_dedup,
                    "ukuran_logis": st["ukuran_logis"],
                    "ukuran_fisik_unik": st["ukuran_fisik_unik"],
                    "hemat_deduplikasi": st["hemat_deduplikasi"],
                    "chunk_unik_total": st["jumlah_chunk_unik"],
                }
            )
            print(
                f"  Unggahan {i}: {hasil.jumlah_chunk} chunk,"
                f" {hasil.chunk_dedup} terdeduplikasi,"
                f" fisik unik {st['ukuran_fisik_unik'] / BLOK:.0f} MB,"
                f" hemat {st['hemat_deduplikasi'] / BLOK:.0f} MB"
            )
        laporan["pola_berkas_identik"] = pola1

        # ---------------- Pola 2: berkas berbeda, sebagian isi sama ----------------
        print("\n[2/5] Mengunggah berkas berbeda yang separuh isinya sama")
        batas = jumlah_chunk // 2
        campuran = chunk_a[:batas] + chunk_campuran[batas:]
        path_b = os.path.join(kerja, "dedup-campuran.bin")
        tulis_berkas(path_b, campuran)
        hasil_b = klien.unggah(path_b, "dedup-campuran.bin")
        st_b = klien.status()["statistik"]
        print(
            f"  {hasil_b.jumlah_chunk} chunk, {hasil_b.chunk_dedup} terdeduplikasi"
            f" (chunk yang isinya sama dengan berkas sebelumnya)"
        )
        laporan["pola_isi_sebagian_sama"] = {
            "jumlah_chunk": hasil_b.jumlah_chunk,
            "chunk_dideduplikasi": hasil_b.chunk_dedup,
            "chunk_baru": hasil_b.jumlah_chunk - hasil_b.chunk_dedup,
            "statistik": st_b,
        }

        # ---------------- Pola 3: berkas unik sebagai pembanding ----------------
        print("\n[3/5] Mengunggah berkas yang seluruh isinya unik")
        path_c = os.path.join(kerja, "dedup-unik.bin")
        tulis_berkas(path_c, chunk_unik)
        hasil_c = klien.unggah(path_c, "dedup-unik.bin")
        st_c = klien.status()["statistik"]
        print(
            f"  {hasil_c.jumlah_chunk} chunk, {hasil_c.chunk_dedup} terdeduplikasi,"
            f" rasio deduplikasi keseluruhan {st_c['rasio_deduplikasi']}x"
        )
        laporan["pola_berkas_unik"] = {
            "jumlah_chunk": hasil_c.jumlah_chunk,
            "chunk_dideduplikasi": hasil_c.chunk_dedup,
            "statistik": st_c,
        }
        laporan["ringkasan_deduplikasi"] = {
            "ukuran_logis": st_c["ukuran_logis"],
            "ukuran_chunk_direferensikan": st_c["ukuran_chunk_direferensikan"],
            "ukuran_fisik_unik": st_c["ukuran_fisik_unik"],
            "hemat_deduplikasi": st_c["hemat_deduplikasi"],
            "rasio_deduplikasi": st_c["rasio_deduplikasi"],
            "persen_hemat": (
                round(
                    st_c["hemat_deduplikasi"] / st_c["ukuran_chunk_direferensikan"] * 100, 2
                )
                if st_c["ukuran_chunk_direferensikan"]
                else 0.0
            ),
        }

        # ---------------- Versioning ----------------
        print("\n[4/5] Menguji versioning dan rollback")
        nama_versi = "uji-versi.bin"
        versi_dibuat = []
        hash_per_versi: dict[int, str] = {}
        file_id = ""
        for i in range(1, 4):
            bagian = [os.urandom(klien.chunk_size) for _ in range(max(1, jumlah_chunk - i + 1))]
            path_v = os.path.join(kerja, f"versi-{i}.bin")
            h = tulis_berkas(path_v, bagian)
            hasil = klien.unggah(path_v, nama_versi)
            if not hasil.berhasil:
                print(f"  Simpan versi {i} gagal: {hasil.galat}")
                return 1
            file_id = hasil.file_id
            hash_per_versi[hasil.versi] = h
            versi_dibuat.append(
                {"versi": hasil.versi, "ukuran": hasil.ukuran, "hash": h}
            )
            print(f"  Simpan ulang nama sama -> versi {hasil.versi} ({hasil.ukuran / BLOK:.0f} MB)")

        unduh_versi = []
        for versi, h in sorted(hash_per_versi.items()):
            hasil = klien.unduh(file_id, nama_versi, hash_harapan=h, versi=versi)
            unduh_versi.append(
                {
                    "versi": versi,
                    "berhasil": hasil.berhasil,
                    "hash_cocok": hasil.hash_cocok,
                    "durasi": hasil.durasi,
                }
            )
            print(
                f"  Unduh versi {versi}: berhasil {hasil.berhasil},"
                f" hash cocok {hasil.hash_cocok}"
            )

        from lib_uji import minta_json  # impor lokal agar tetap ringkas

        status_rb, balasan_rb = minta_json(
            f"{klien.master}/files/{file_id}/rollback", "POST", {"versi": 1}, timeout=60.0
        )
        hasil_setelah = klien.unduh(file_id, nama_versi, hash_harapan=hash_per_versi[1])
        print(
            f"  Rollback ke versi 1: status {status_rb},"
            f" unduhan tanpa nomor versi cocok dengan v1: {hasil_setelah.hash_cocok}"
        )

        laporan["versioning"] = {
            "nama_berkas": nama_versi,
            "file_id": file_id,
            "versi_dibuat": versi_dibuat,
            "unduh_per_versi": unduh_versi,
            "rollback": {
                "status": status_rb,
                "balasan": balasan_rb,
                "unduhan_versi_aktif_cocok_v1": hasil_setelah.hash_cocok,
            },
        }

        # Pastikan hemat ruang berasal dari chunk bersama, bukan chunk hilang.
        print("\n[5/5] Verifikasi keutuhan berkas yang terdeduplikasi")
        salinan = pola1[-1]
        unggah_verifikasi = klien.unggah(path_a, "dedup-verifikasi.bin")
        unduh_dedup = klien.unduh(
            unggah_verifikasi.file_id, "dedup-verifikasi.bin", hash_harapan=hash_a
        )
        print(
            f"  Seluruh {unggah_verifikasi.chunk_dedup} chunk dipakai ulang,"
            f" hash berkas hasil rakitan cocok: {unduh_dedup.hash_cocok}"
        )
        laporan["verifikasi_keutuhan_dedup"] = {
            "chunk_dipakai_ulang": unggah_verifikasi.chunk_dedup,
            "hash_cocok": unduh_dedup.hash_cocok,
            "ukuran": unduh_dedup.ukuran,
            "hemat_setelah_salinan_terakhir": salinan["hemat_deduplikasi"],
        }

        path = tulis_json("uji_dedup_versioning.json", laporan)
        print("\n" + "=" * 72)
        print(f"HASIL DISIMPAN: {path}")
        print("=" * 72)

        lulus = (
            laporan["ringkasan_deduplikasi"]["hemat_deduplikasi"] > 0
            and all(u["hash_cocok"] for u in unduh_versi)
            and hasil_setelah.hash_cocok is True
            and unduh_dedup.hash_cocok is True
        )
        print("\nHASIL UJI:", "LULUS" if lulus else "TIDAK LULUS")
        return 0 if lulus else 1
    finally:
        import shutil

        shutil.rmtree(kerja, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
