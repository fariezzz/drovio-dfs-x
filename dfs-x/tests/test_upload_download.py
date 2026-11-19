from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_uji import (  # noqa: E402
    DUMMY_DIR,
    HasilBerkas,
    KlienDfsx,
    RingkasanTahap,
    cetak_ringkasan,
    ringkasan_ke_dict,
    tulis_csv,
    tulis_json,
)

def muat_manifes(folder: str, batas: int) -> list[dict]:
    path = os.path.join(folder, "manifes.json")
    if not os.path.exists(path):
        raise SystemExit(
            f"Manifes tidak ada di {path}. Jalankan make_dummy_files.py lebih dulu."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    berkas = data["berkas"][:batas]
    if not berkas:
        raise SystemExit("Manifes kosong.")
    return berkas

def jalankan_paralel(fungsi, item: list, paralel: int) -> tuple[list[HasilBerkas], float]:
    mulai = time.perf_counter()
    if paralel <= 1:
        hasil = [fungsi(x) for x in item]
    else:
        with ThreadPoolExecutor(max_workers=paralel) as kolam:
            hasil = list(kolam.map(fungsi, item))
    return hasil, round(time.perf_counter() - mulai, 4)

def tahap_upload(
    klien: KlienDfsx, berkas: list[dict], paralel: int, label: str
) -> RingkasanTahap:
    def kerjakan(info: dict) -> HasilBerkas:
        return klien.unggah(info["path"], info["nama"])

    hasil, waktu = jalankan_paralel(kerjakan, berkas, paralel)
    ringkasan = RingkasanTahap(
        nama_tahap=label, mode=klien.mode, paralel=paralel, waktu_total=waktu, rincian=hasil
    )
    return ringkasan.hitung()

def tahap_download(
    klien: KlienDfsx,
    berkas: list[dict],
    peta_id: dict[str, str],
    paralel: int,
    label: str,
) -> RingkasanTahap:
    def kerjakan(info: dict) -> HasilBerkas:
        file_id = peta_id.get(info["nama"], "")
        if not file_id:
            return HasilBerkas(
                nama=info["nama"],
                ukuran=0,
                berhasil=False,
                galat="file_id tidak diketahui, upload berkas ini gagal",
            )
        return klien.unduh(file_id, info["nama"], hash_harapan=info["hash"])

    hasil, waktu = jalankan_paralel(kerjakan, berkas, paralel)
    ringkasan = RingkasanTahap(
        nama_tahap=label, mode=klien.mode, paralel=paralel, waktu_total=waktu, rincian=hasil
    )
    return ringkasan.hitung()

def main() -> int:
    parser = argparse.ArgumentParser(description="Uji upload dan download massal DFS-X")
    parser.add_argument("--jumlah", type=int, default=100, help="jumlah berkas yang diuji")
    parser.add_argument("--paralel", type=int, default=4, help="tingkat paralelisme klien")
    parser.add_argument("--dummy-dir", default=DUMMY_DIR)
    parser.add_argument("--mode", default="auto", choices=["auto", "ringkas", "dua_tahap"])
    parser.add_argument(
        "--lewati-speedup",
        action="store_true",
        help="lewati pengukuran sekuensial (uji speedup) agar lebih cepat",
    )
    parser.add_argument(
        "--contoh-speedup",
        type=int,
        default=10,
        help="jumlah berkas untuk pembanding sekuensial (bawaan 10)",
    )
    parser.add_argument("--awalan-hasil", default="uji_massal")
    argumen = parser.parse_args()

    klien = KlienDfsx(mode=argumen.mode)
    berkas = muat_manifes(argumen.dummy_dir, argumen.jumlah)
    node_awal = klien.node_hidup()
    jumlah_node = len(node_awal)

    print("=" * 72)
    print("UJI UPLOAD DAN DOWNLOAD MASSAL DFS-X")
    print("=" * 72)
    print(f"  Berkas            : {len(berkas)} @ {berkas[0]['ukuran'] / 1048576:.0f} MB")
    print(f"  Data node aktif   : {jumlah_node}")
    print(f"  Mode klien        : {klien.mode}")
    print(f"  Ukuran chunk      : {klien.chunk_size / 1048576:.0f} MB")
    print(f"  Faktor replikasi  : {klien.konfigurasi['replication_factor']}")
    print(f"  Paralelisme uji   : {argumen.paralel}")
    print("-" * 72)

    print("\n[1/4] Membersihkan metadata agar pengujian mulai dari nol")
    klien.reset()

    print("\n[2/4] Upload massal")
    up = tahap_upload(klien, berkas, argumen.paralel, "upload_paralel")
    cetak_ringkasan(up)
    peta_id = {r.nama: r.file_id for r in up.rincian if r.berhasil}

    print("\n[3/4] Download massal dengan verifikasi hash SHA-256")
    down = tahap_download(klien, berkas, peta_id, argumen.paralel, "download_paralel")
    cetak_ringkasan(down)
    print(
        f"  Lolos verifikasi hash: {down.hash_cocok}/{down.berkas_berhasil}"
        f" berkas yang terunduh"
    )

    # Speedup memakai subset berkas supaya tahap sekuensial tidak memakan
    # waktu berjam-jam pada 100 berkas 50 MB.
    speedup: dict = {"dijalankan": False}
    if not argumen.lewati_speedup:
        contoh = berkas[: min(argumen.contoh_speedup, len(berkas))]
        print(
            f"\n[4/4] Pengukuran speedup atas {len(contoh)} berkas"
            f" (sekuensial dibanding paralel {argumen.paralel})"
        )

        klien.reset()
        up_seq = tahap_upload(klien, contoh, 1, "upload_sekuensial")
        cetak_ringkasan(up_seq)
        peta_seq = {r.nama: r.file_id for r in up_seq.rincian if r.berhasil}
        down_seq = tahap_download(klien, contoh, peta_seq, 1, "download_sekuensial")
        cetak_ringkasan(down_seq)

        klien.reset()
        up_par = tahap_upload(klien, contoh, argumen.paralel, "upload_paralel_contoh")
        cetak_ringkasan(up_par)
        peta_par = {r.nama: r.file_id for r in up_par.rincian if r.berhasil}
        down_par = tahap_download(
            klien, contoh, peta_par, argumen.paralel, "download_paralel_contoh"
        )
        cetak_ringkasan(down_par)

        def hitung(seq: RingkasanTahap, par: RingkasanTahap) -> dict:
            s = round(seq.waktu_total / par.waktu_total, 4) if par.waktu_total > 0 else 0.0
            return {
                "waktu_sekuensial": seq.waktu_total,
                "waktu_paralel": par.waktu_total,
                "speedup": s,
                "efisiensi": round(s / jumlah_node, 4) if jumlah_node else 0.0,
                "throughput_sekuensial_mbps": seq.throughput_mbps,
                "throughput_paralel_mbps": par.throughput_mbps,
            }

        speedup = {
            "dijalankan": True,
            "jumlah_berkas_contoh": len(contoh),
            "jumlah_node": jumlah_node,
            "paralelisme": argumen.paralel,
            "upload": hitung(up_seq, up_par),
            "download": hitung(down_seq, down_par),
        }

        print("\n  Ringkasan speedup dan efisiensi")
        for jenis in ("upload", "download"):
            d = speedup[jenis]
            print(
                f"    {jenis:<9} S={d['speedup']:.3f}  E={d['efisiensi']:.3f}"
                f"  ({d['waktu_sekuensial']:.2f}s sekuensial,"
                f" {d['waktu_paralel']:.2f}s paralel)"
            )

    status_akhir = klien.status()
    laporan = {
        "waktu_uji": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parameter": {
            "jumlah_berkas": len(berkas),
            "ukuran_per_berkas": berkas[0]["ukuran"],
            "paralelisme": argumen.paralel,
            "mode_klien": klien.mode,
            "jumlah_node": jumlah_node,
            "konfigurasi_master": klien.konfigurasi,
        },
        "upload_massal": ringkasan_ke_dict(up),
        "download_massal": ringkasan_ke_dict(down),
        "speedup_efisiensi": speedup,
        "statistik_akhir": status_akhir["statistik"],
        "kesehatan_replikasi": status_akhir["kesehatan_replikasi"],
    }

    path_json = tulis_json(f"{argumen.awalan_hasil}_n{jumlah_node}.json", laporan)
    path_csv = tulis_csv(
        f"{argumen.awalan_hasil}_n{jumlah_node}_rincian.csv",
        [
            {"tahap": "upload", **vars(r)}
            for r in up.rincian
        ]
        + [{"tahap": "download", **vars(r)} for r in down.rincian],
        kolom=[
            "tahap",
            "nama",
            "ukuran",
            "berhasil",
            "durasi",
            "ttfb",
            "hash_cocok",
            "jumlah_chunk",
            "chunk_dedup",
            "galat",
        ],
    )

    print("\n" + "=" * 72)
    print("HASIL DISIMPAN")
    print(f"  {path_json}")
    print(f"  {path_csv}")
    print("=" * 72)

    gagal = up.berkas_gagal + down.berkas_gagal
    hash_tidak_cocok = down.berkas_berhasil - down.hash_cocok
    if gagal or hash_tidak_cocok:
        print(
            f"\nPERINGATAN: {gagal} berkas gagal,"
            f" {hash_tidak_cocok} berkas tidak lolos verifikasi hash"
        )
        return 1
    print("\nSemua berkas berhasil dan lolos verifikasi hash SHA-256.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
