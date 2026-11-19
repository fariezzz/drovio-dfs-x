from __future__ import annotations

import argparse
import json
import os
import subprocess
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
    minta_json,
    ringkasan_ke_dict,
    tulis_csv,
    tulis_json,
)

DOCKER_BIN = os.environ.get("DOCKER_BIN", "docker")
DIR_COMPOSE = os.environ.get(
    "COMPOSE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

def _env_file_relatif() -> str:
    diminta = os.environ.get("COMPOSE_ENV")
    if not diminta:
        return os.path.join("config", ".env")
    if not os.path.isabs(diminta):
        return diminta
    try:
        return os.path.relpath(diminta, DIR_COMPOSE)
    except ValueError:
        return diminta

ENV_FILE = _env_file_relatif()
# Profil compose yang menyediakan jumlah node tertentu.
PROFIL_PER_JUMLAH = {2: None, 3: None, 4: "n4", 8: "n8", 16: "n16"}

def compose(*argumen: str, profil: str | None = None, timeout: int = 600) -> tuple[int, str]:
    perintah = [DOCKER_BIN, "compose", "--env-file", ENV_FILE]
    if profil:
        perintah += ["--profile", profil]
    perintah += list(argumen)
    try:
        proses = subprocess.run(
            perintah, capture_output=True, text=True, timeout=timeout, cwd=DIR_COMPOSE
        )
        return proses.returncode, (proses.stdout + proses.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)

def atur_jumlah_node(target: int, master_url: str, batas_tunggu: float = 180.0) -> int:
    profil = PROFIL_PER_JUMLAH.get(target)
    if profil:
        kode, keluaran = compose("up", "-d", profil=profil)
        if kode != 0:
            print(f"  Peringatan saat menaikkan node: {keluaran[:200]}")

    # Hentikan node di luar jangkauan target, dan hidupkan yang di dalamnya.
    for i in range(1, 17):
        nama = f"dfsx-datanode-{i}"
        if i <= target:
            subprocess.run([DOCKER_BIN, "start", nama], capture_output=True, text=True)
        else:
            subprocess.run([DOCKER_BIN, "stop", nama], capture_output=True, text=True)

    # Node mati perlu waktu melewati ambang heartbeat sebelum master
    # menandainya, jadi tunggu sampai hitungan node hidup benar-benar pas.
    mulai = time.perf_counter()
    terakhir = 0
    while time.perf_counter() - mulai < batas_tunggu:
        status, data = minta_json(f"{master_url}/status", timeout=20.0)
        if status == 200 and isinstance(data, dict):
            terakhir = data["ringkasan_node"]["hidup"]
            if terakhir == target:
                return terakhir
        time.sleep(2.0)
    return terakhir

def muat_manifes(folder: str, batas: int) -> list[dict]:
    path = os.path.join(folder, "manifes.json")
    if not os.path.exists(path):
        raise SystemExit(f"Manifes tidak ada di {path}. Jalankan make_dummy_files.py.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["berkas"][:batas]

def jalankan_tahap(
    klien: KlienDfsx, berkas: list[dict], paralel: int, label: str, unduh: bool = False,
    peta_id: dict[str, str] | None = None
) -> RingkasanTahap:
    if unduh:
        peta = peta_id or {}

        def kerja(info: dict) -> HasilBerkas:
            fid = peta.get(info["nama"], "")
            if not fid:
                return HasilBerkas(
                    nama=info["nama"], ukuran=0, berhasil=False, galat="upload gagal"
                )
            return klien.unduh(fid, info["nama"], hash_harapan=info["hash"])
    else:
        def kerja(info: dict) -> HasilBerkas:
            return klien.unggah(info["path"], info["nama"])

    mulai = time.perf_counter()
    if paralel <= 1:
        hasil = [kerja(b) for b in berkas]
    else:
        with ThreadPoolExecutor(max_workers=paralel) as kolam:
            hasil = list(kolam.map(kerja, berkas))
    return RingkasanTahap(
        nama_tahap=label,
        mode=klien.mode,
        paralel=paralel,
        waktu_total=round(time.perf_counter() - mulai, 4),
        rincian=hasil,
    ).hitung()

def main() -> int:
    parser = argparse.ArgumentParser(description="Uji skalabilitas DFS-X per jumlah node")
    parser.add_argument("--jumlah", type=int, default=10, help="jumlah berkas per konfigurasi")
    parser.add_argument(
        "--node-list", default="2,4,8,16", help="daftar jumlah node yang diuji"
    )
    parser.add_argument("--paralel", type=int, default=4, help="paralelisme klien")
    parser.add_argument("--dummy-dir", default=DUMMY_DIR)
    parser.add_argument("--mode", default="auto", choices=["auto", "ringkas", "dua_tahap"])
    parser.add_argument(
        "--kembalikan",
        type=int,
        default=3,
        help="jumlah node yang dihidupkan kembali setelah pengujian",
    )
    argumen = parser.parse_args()

    daftar_node = [int(x) for x in argumen.node_list.split(",") if x.strip()]
    berkas = muat_manifes(argumen.dummy_dir, argumen.jumlah)
    master_url = os.environ.get("MASTER_URL", "http://127.0.0.1:9100").rstrip("/")

    print("=" * 72)
    print("UJI SKALABILITAS DFS-X")
    print("=" * 72)
    print(f"  Konfigurasi node  : {daftar_node}")
    print(f"  Berkas per uji    : {len(berkas)} @ {berkas[0]['ukuran'] / 1048576:.0f} MB")
    print(f"  Paralelisme klien : {argumen.paralel}")
    print("-" * 72)

    hasil_per_konfigurasi = []
    dasar: dict | None = None

    for target in daftar_node:
        print(f"\n### Konfigurasi {target} data node ###")
        hidup = atur_jumlah_node(target, master_url)
        if hidup != target:
            print(
                f"  Peringatan: master melihat {hidup} node hidup, bukan {target}."
                " Hasil dicatat sesuai keadaan sebenarnya."
            )
        klien = KlienDfsx(master_url=master_url, mode=argumen.mode)
        print(f"  Node hidup menurut master: {hidup}, mode klien {klien.mode}")

        # Waktu sekuensial diukur sekali pada konfigurasi pertama, lalu
        # dipakai sebagai pembanding tetap untuk semua konfigurasi.
        if dasar is None:
            klien.reset()
            up_seq = jalankan_tahap(klien, berkas, 1, f"upload_sekuensial_n{hidup}")
            cetak_ringkasan(up_seq)
            peta_seq = {r.nama: r.file_id for r in up_seq.rincian if r.berhasil}
            down_seq = jalankan_tahap(
                klien, berkas, 1, f"download_sekuensial_n{hidup}", unduh=True, peta_id=peta_seq
            )
            cetak_ringkasan(down_seq)
            dasar = {
                "jumlah_node": hidup,
                "upload_detik": up_seq.waktu_total,
                "download_detik": down_seq.waktu_total,
                "upload_throughput_mbps": up_seq.throughput_mbps,
                "download_throughput_mbps": down_seq.throughput_mbps,
            }

        klien.reset()
        up = jalankan_tahap(klien, berkas, argumen.paralel, f"upload_n{hidup}")
        cetak_ringkasan(up)
        peta = {r.nama: r.file_id for r in up.rincian if r.berhasil}
        down = jalankan_tahap(
            klien, berkas, argumen.paralel, f"download_n{hidup}", unduh=True, peta_id=peta
        )
        cetak_ringkasan(down)

        s_up = round(dasar["upload_detik"] / up.waktu_total, 4) if up.waktu_total else 0.0
        s_down = (
            round(dasar["download_detik"] / down.waktu_total, 4) if down.waktu_total else 0.0
        )
        st = klien.status()

        baris = {
            "jumlah_node_diminta": target,
            "jumlah_node_hidup": hidup,
            "mode_klien": klien.mode,
            "paralelisme": argumen.paralel,
            "upload_detik": up.waktu_total,
            "upload_throughput_mbps": up.throughput_mbps,
            "upload_berhasil": up.berkas_berhasil,
            "upload_gagal": up.berkas_gagal,
            "download_detik": down.waktu_total,
            "download_throughput_mbps": down.throughput_mbps,
            "download_berhasil": down.berkas_berhasil,
            "download_hash_cocok": down.hash_cocok,
            "upload_latensi_rata": up.latensi_rata,
            "upload_latensi_terburuk": up.latensi_terburuk,
            "download_latensi_rata": down.latensi_rata,
            "download_latensi_terburuk": down.latensi_terburuk,
            "download_ttfb_rata": down.ttfb_rata,
            "speedup_upload": s_up,
            "efisiensi_upload": round(s_up / hidup, 4) if hidup else 0.0,
            "speedup_download": s_down,
            "efisiensi_download": round(s_down / hidup, 4) if hidup else 0.0,
            "chunk_unik": st["statistik"]["jumlah_chunk_unik"],
            "chunk_di_bawah_faktor": st["kesehatan_replikasi"]["chunk_di_bawah_faktor"],
        }
        hasil_per_konfigurasi.append(baris)
        print(
            f"  S upload {s_up:.3f} (E {baris['efisiensi_upload']:.3f}),"
            f" S download {s_down:.3f} (E {baris['efisiensi_download']:.3f})"
        )

        tulis_json(
            f"uji_skalabilitas_n{hidup}_rincian.json",
            {
                "konfigurasi": baris,
                "upload": ringkasan_ke_dict(up, sertakan_rincian=True),
                "download": ringkasan_ke_dict(down, sertakan_rincian=True),
            },
        )

    print(f"\nMengembalikan konfigurasi ke {argumen.kembalikan} data node")
    atur_jumlah_node(argumen.kembalikan, master_url, batas_tunggu=120.0)

    laporan = {
        "waktu_uji": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pembanding_sekuensial": dasar,
        "parameter": {
            "jumlah_berkas": len(berkas),
            "ukuran_per_berkas": berkas[0]["ukuran"],
            "paralelisme": argumen.paralel,
            "daftar_node": daftar_node,
        },
        "hasil": hasil_per_konfigurasi,
    }
    path_json = tulis_json("uji_skalabilitas.json", laporan)
    path_csv = tulis_csv("uji_skalabilitas.csv", hasil_per_konfigurasi)

    print("\n" + "=" * 72)
    print("TABEL SKALABILITAS")
    print(
        f"{'Node':>5} {'Up (s)':>9} {'Down (s)':>9} {'Up MB/s':>9}"
        f" {'Down MB/s':>10} {'S up':>7} {'E up':>7} {'S down':>8} {'E down':>8}"
    )
    for b in hasil_per_konfigurasi:
        print(
            f"{b['jumlah_node_hidup']:>5} {b['upload_detik']:>9.2f}"
            f" {b['download_detik']:>9.2f} {b['upload_throughput_mbps']:>9.2f}"
            f" {b['download_throughput_mbps']:>10.2f} {b['speedup_upload']:>7.3f}"
            f" {b['efisiensi_upload']:>7.3f} {b['speedup_download']:>8.3f}"
            f" {b['efisiensi_download']:>8.3f}"
        )
    print("=" * 72)
    print(f"HASIL DISIMPAN:\n  {path_json}\n  {path_csv}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
