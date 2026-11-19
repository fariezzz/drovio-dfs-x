from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_uji import (  # noqa: E402
    DUMMY_DIR,
    KlienDfsx,
    RingkasanTahap,
    cetak_ringkasan,
    ringkasan_ke_dict,
    tulis_json,
)

DOCKER_BIN = os.environ.get("DOCKER_BIN", "docker")

def docker(*argumen: str) -> tuple[int, str]:
    try:
        proses = subprocess.run(
            [DOCKER_BIN, *argumen], capture_output=True, text=True, timeout=120
        )
        return proses.returncode, (proses.stdout + proses.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)

def muat_manifes(folder: str, batas: int) -> list[dict]:
    path = os.path.join(folder, "manifes.json")
    if not os.path.exists(path):
        raise SystemExit(f"Manifes tidak ada di {path}. Jalankan make_dummy_files.py.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["berkas"][:batas]

def main() -> int:
    parser = argparse.ArgumentParser(description="Uji fault tolerance dan self-healing DFS-X")
    parser.add_argument("--jumlah", type=int, default=10, help="jumlah berkas uji")
    parser.add_argument(
        "--node", default="dfsx-datanode-2", help="nama container data node yang dimatikan"
    )
    parser.add_argument("--dummy-dir", default=DUMMY_DIR)
    parser.add_argument("--mode", default="auto", choices=["auto", "ringkas", "dua_tahap"])
    parser.add_argument(
        "--batas-pemulihan",
        type=float,
        default=300.0,
        help="batas waktu menunggu pemulihan replikasi, dalam detik",
    )
    parser.add_argument(
        "--tanpa-hidupkan",
        action="store_true",
        help="jangan hidupkan kembali node setelah pengujian",
    )
    argumen = parser.parse_args()

    klien = KlienDfsx(mode=argumen.mode)
    berkas = muat_manifes(argumen.dummy_dir, argumen.jumlah)
    faktor = int(klien.konfigurasi["replication_factor"])

    print("=" * 72)
    print("UJI FAULT TOLERANCE DAN SELF-HEALING DFS-X")
    print("=" * 72)
    print(f"  Berkas uji        : {len(berkas)} @ {berkas[0]['ukuran'] / 1048576:.0f} MB")
    print(f"  Node dimatikan    : {argumen.node}")
    print(f"  Faktor replikasi  : {faktor}")
    print(f"  Ambang node mati  : {klien.konfigurasi['node_dead_threshold_seconds']} detik")
    print("-" * 72)

    print("\n[1/6] Upload berkas uji")
    klien.reset()

    def unggah(info: dict):
        return klien.unggah(info["path"], info["nama"])

    mulai = time.perf_counter()
    hasil_upload = [unggah(b) for b in berkas]
    up = RingkasanTahap(
        nama_tahap="upload_sebelum_gangguan",
        mode=klien.mode,
        paralel=1,
        waktu_total=round(time.perf_counter() - mulai, 4),
        rincian=hasil_upload,
    ).hitung()
    cetak_ringkasan(up)
    peta_id = {r.nama: r.file_id for r in hasil_upload if r.berhasil}
    if not peta_id:
        print("Upload gagal seluruhnya, pengujian dihentikan.")
        return 1

    sebelum = klien.status()
    print(
        f"  Chunk unik {sebelum['statistik']['jumlah_chunk_unik']},"
        f" chunk di bawah faktor replikasi"
        f" {sebelum['kesehatan_replikasi']['chunk_di_bawah_faktor']}"
    )

    print(f"\n[2/6] Mematikan {argumen.node}")
    t0 = time.perf_counter()
    kode, keluaran = docker("stop", argumen.node)
    if kode != 0:
        print(f"  Gagal mematikan container: {keluaran}")
        return 2
    waktu_stop = round(time.perf_counter() - t0, 2)
    print(f"  Container berhenti setelah {waktu_stop} detik")

    print("\n[3/6] Download saat 1 data node mati")
    mulai = time.perf_counter()
    hasil_unduh = [
        klien.unduh(peta_id[b["nama"]], b["nama"], hash_harapan=b["hash"])
        for b in berkas
        if b["nama"] in peta_id
    ]
    saat_mati = RingkasanTahap(
        nama_tahap="download_saat_node_mati",
        mode=klien.mode,
        paralel=1,
        waktu_total=round(time.perf_counter() - mulai, 4),
        rincian=hasil_unduh,
    ).hitung()
    cetak_ringkasan(saat_mati)
    print(
        f"  Lolos verifikasi hash: {saat_mati.hash_cocok}/{saat_mati.jumlah_berkas}"
        " (layanan baca tetap berjalan)"
    )

    print("\n[4/6] Menunggu master menandai node mati")
    waktu_deteksi = None
    node_mati: list[str] = []
    while time.perf_counter() - t0 < argumen.batas_pemulihan:
        st = klien.status()
        node_mati = [n["node_id"] for n in st["node"] if n["status"] != "hidup"]
        if node_mati:
            waktu_deteksi = round(time.perf_counter() - t0, 2)
            break
        time.sleep(0.5)
    print(
        f"  Node terdeteksi mati: {node_mati or 'belum terdeteksi'}"
        f" setelah {waktu_deteksi} detik sejak perintah stop"
    )

    print("\n[5/6] Menunggu self-healing memulihkan faktor replikasi")
    waktu_pulih = None
    kurang_awal = None
    while time.perf_counter() - t0 < argumen.batas_pemulihan:
        st = klien.status()
        kurang = st["kesehatan_replikasi"]["chunk_di_bawah_faktor"]
        if kurang_awal is None and kurang > 0:
            kurang_awal = kurang
        if kurang == 0 and kurang_awal is not None:
            waktu_pulih = round(time.perf_counter() - t0, 2)
            break
        time.sleep(1.0)

    st_pulih = klien.status()
    sh = st_pulih["self_healing"]
    print(
        f"  Chunk kehilangan salinan: {kurang_awal or 0},"
        f" dipulihkan {sh['chunk_dipulihkan']}, gagal {sh['chunk_gagal']}"
    )
    print(f"  Faktor replikasi pulih penuh pada {waktu_pulih} detik sejak perintah stop")
    print(
        f"  Chunk masih di bawah faktor replikasi:"
        f" {st_pulih['kesehatan_replikasi']['chunk_di_bawah_faktor']}"
    )

    print("\n[6/6] Download setelah pemulihan")
    mulai = time.perf_counter()
    hasil_akhir = [
        klien.unduh(peta_id[b["nama"]], b["nama"], hash_harapan=b["hash"])
        for b in berkas
        if b["nama"] in peta_id
    ]
    setelah = RingkasanTahap(
        nama_tahap="download_setelah_pemulihan",
        mode=klien.mode,
        paralel=1,
        waktu_total=round(time.perf_counter() - mulai, 4),
        rincian=hasil_akhir,
    ).hitung()
    cetak_ringkasan(setelah)

    if not argumen.tanpa_hidupkan:
        print(f"\nMenghidupkan kembali {argumen.node}")
        docker("start", argumen.node)
        time.sleep(max(8.0, float(klien.konfigurasi["heartbeat_interval_seconds"]) * 2))
        st_akhir = klien.status()
        print(f"  Ringkasan node: {st_akhir['ringkasan_node']}")
    else:
        st_akhir = st_pulih

    laporan = {
        "waktu_uji": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parameter": {
            "jumlah_berkas": len(berkas),
            "ukuran_per_berkas": berkas[0]["ukuran"],
            "node_dimatikan": argumen.node,
            "mode_klien": klien.mode,
            "konfigurasi_master": klien.konfigurasi,
        },
        "upload_sebelum_gangguan": ringkasan_ke_dict(up),
        "download_saat_node_mati": ringkasan_ke_dict(saat_mati),
        "download_setelah_pemulihan": ringkasan_ke_dict(setelah),
        "fault_recovery": {
            "waktu_perintah_stop_detik": waktu_stop,
            "waktu_deteksi_node_mati_detik": waktu_deteksi,
            "ambang_node_mati_detik": klien.konfigurasi["node_dead_threshold_seconds"],
            "node_terdeteksi_mati": node_mati,
            "chunk_kehilangan_salinan": kurang_awal or 0,
            "chunk_dipulihkan": sh["chunk_dipulihkan"],
            "chunk_gagal_dipulihkan": sh["chunk_gagal"],
            "waktu_pemulihan_penuh_detik": waktu_pulih,
            "siklus_self_healing": sh["siklus"],
        },
        "log_terkait": [
            l
            for l in st_akhir["log"]
            if l["jenis_kejadian"] in ("node_mati", "node_hidup", "self_healing")
        ][:20],
        "statistik_akhir": st_akhir["statistik"],
        "kesehatan_replikasi_akhir": st_akhir["kesehatan_replikasi"],
    }

    path = tulis_json("uji_fault_tolerance.json", laporan)
    print("\n" + "=" * 72)
    print(f"HASIL DISIMPAN: {path}")
    print("=" * 72)

    # Syarat lulus: baca tetap berhasil saat node mati, hash cocok, dan
    # replikasi kembali lengkap.
    lulus = (
        saat_mati.berkas_gagal == 0
        and saat_mati.hash_cocok == saat_mati.jumlah_berkas
        and st_pulih["kesehatan_replikasi"]["chunk_di_bawah_faktor"] == 0
    )
    print("\nHASIL UJI:", "LULUS" if lulus else "TIDAK LULUS")
    return 0 if lulus else 1

if __name__ == "__main__":
    raise SystemExit(main())
