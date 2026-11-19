from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_uji import DIR_GRAFIK, DIR_MENTAH, siapkan_folder_hasil  # noqa: E402

LEBAR = 760
TINGGI = 420
MARGIN_KIRI = 88
MARGIN_BAWAH = 62
MARGIN_ATAS = 62
MARGIN_KANAN = 150

WARNA = ["#8B7CFF", "#10B981", "#F43F5E", "#F59E0B", "#38BDF8"]
WARNA_KISI = "#2A3039"
WARNA_TEKS = "#E2E2E6"
WARNA_REDUP = "#B4B1BF"
WARNA_KANVAS = "#0D0F12"

def _esc(teks: str) -> str:
    return (
        str(teks)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def batas_bulat(nilai_maks: float) -> float:
    if nilai_maks <= 0:
        return 1.0
    for langkah in (
        0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0
    ):
        batas = langkah * 5
        if nilai_maks <= batas:
            return batas
    return float(int(nilai_maks / 500 + 1) * 500)

class Kanvas:
    def __init__(self, judul: str, label_y: str, label_x: str) -> None:
        self.bagian: list[str] = []
        self.judul = judul
        self.label_y = label_y
        self.label_x = label_x
        self.x0 = MARGIN_KIRI
        self.y0 = TINGGI - MARGIN_BAWAH
        self.x1 = LEBAR - MARGIN_KANAN
        self.y1 = MARGIN_ATAS

    def _px(self, nilai: float, maks: float) -> float:
        if maks <= 0:
            return self.y0
        return self.y0 - (nilai / maks) * (self.y0 - self.y1)

    def kerangka(
        self, maks: float, label_x: list[str], satuan: str = "", gaya_x: str = "slot"
    ) -> None:
        self.bagian.append(
            f'<rect width="{LEBAR}" height="{TINGGI}" fill="{WARNA_KANVAS}"/>'
        )
        self.bagian.append(
            f'<text x="{MARGIN_KIRI}" y="28" fill="{WARNA_TEKS}" font-size="15"'
            f' font-family="Segoe UI, sans-serif" font-weight="600">{_esc(self.judul)}</text>'
        )

        # Garis kisi horizontal dengan lima tingkat.
        for i in range(6):
            nilai = maks * i / 5
            y = self._px(nilai, maks)
            self.bagian.append(
                f'<line x1="{self.x0}" y1="{y:.1f}" x2="{self.x1}" y2="{y:.1f}"'
                f' stroke="{WARNA_KISI}" stroke-width="1"/>'
            )
            teks = f"{nilai:.2f}".rstrip("0").rstrip(".") if maks < 10 else f"{nilai:.0f}"
            self.bagian.append(
                f'<text x="{self.x0 - 8}" y="{y + 4:.1f}" fill="{WARNA_REDUP}"'
                f' font-size="11" font-family="JetBrains Mono, monospace"'
                f' text-anchor="end">{teks}</text>'
            )

        self.bagian.append(
            f'<line x1="{self.x0}" y1="{self.y0}" x2="{self.x1}" y2="{self.y0}"'
            f' stroke="{WARNA_REDUP}" stroke-width="1.5"/>'
        )
        self.bagian.append(
            f'<text x="18" y="{(self.y0 + self.y1) / 2:.0f}" fill="{WARNA_REDUP}"'
            f' font-size="11" font-family="Segoe UI, sans-serif" text-anchor="middle"'
            f' transform="rotate(-90 18 {(self.y0 + self.y1) / 2:.0f})">'
            f'{_esc(self.label_y + (" " + satuan if satuan else ""))}</text>'
        )
        self.bagian.append(
            f'<text x="{(self.x0 + self.x1) / 2:.0f}" y="{TINGGI - 16}"'
            f' fill="{WARNA_REDUP}" font-size="11" font-family="Segoe UI, sans-serif"'
            f' text-anchor="middle">{_esc(self.label_x)}</text>'
        )

        jumlah = max(len(label_x), 1)
        lebar_slot = (self.x1 - self.x0) / jumlah
        jarak_dalam = lebar_slot * 0.12
        lebar_pakai = (self.x1 - self.x0) - jarak_dalam * 2
        for i, teks in enumerate(label_x):
            if gaya_x == "titik":
                x = (
                    self.x0 + jarak_dalam + lebar_pakai * i / (jumlah - 1)
                    if jumlah > 1
                    else self.x0 + jarak_dalam + lebar_pakai / 2
                )
            else:
                x = self.x0 + lebar_slot * (i + 0.5)
            self.bagian.append(
                f'<text x="{x:.1f}" y="{self.y0 + 20}" fill="{WARNA_TEKS}" font-size="11"'
                f' font-family="JetBrains Mono, monospace" text-anchor="middle">'
                f'{_esc(teks)}</text>'
            )

    def legenda(self, nama: list[str]) -> None:
        for i, n in enumerate(nama):
            y = self.y1 + 6 + i * 20
            self.bagian.append(
                f'<rect x="{self.x1 + 16}" y="{y}" width="11" height="11" rx="2"'
                f' fill="{WARNA[i % len(WARNA)]}"/>'
            )
            self.bagian.append(
                f'<text x="{self.x1 + 33}" y="{y + 10}" fill="{WARNA_TEKS}" font-size="11"'
                f' font-family="Segoe UI, sans-serif">{_esc(n)}</text>'
            )

    def batang(
        self,
        seri: list[list[float]],
        maks: float,
        jumlah_slot: int,
        warna_per_slot: bool = False,
    ) -> None:
        lebar_slot = (self.x1 - self.x0) / max(jumlah_slot, 1)
        jumlah_seri = max(len(seri), 1)
        lebar_batang = (
            min(lebar_slot * 0.5, 72)
            if warna_per_slot
            else min(lebar_slot * 0.72 / jumlah_seri, 46)
        )

        for indeks_seri, nilai_seri in enumerate(seri):
            for indeks, nilai in enumerate(nilai_seri):
                tengah = self.x0 + lebar_slot * (indeks + 0.5)
                if warna_per_slot:
                    x = tengah - lebar_batang / 2
                    warna = WARNA[indeks % len(WARNA)]
                    lebar_isi = lebar_batang
                else:
                    x = (
                        tengah
                        - (jumlah_seri * lebar_batang) / 2
                        + indeks_seri * lebar_batang
                    )
                    warna = WARNA[indeks_seri % len(WARNA)]
                    lebar_isi = lebar_batang - 3

                y = self._px(min(nilai, maks), maks)
                tinggi = max(self.y0 - y, 0)
                self.bagian.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{lebar_isi:.1f}"'
                    f' height="{tinggi:.1f}" rx="2" fill="{warna}"/>'
                )
                teks = f"{nilai:.2f}".rstrip("0").rstrip(".") or "0"
                self.bagian.append(
                    f'<text x="{x + lebar_isi / 2:.1f}" y="{y - 6:.1f}"'
                    f' fill="{WARNA_TEKS}" font-size="10.5"'
                    f' font-family="JetBrains Mono, monospace" text-anchor="middle">'
                    f'{teks}</text>'
                )

    def garis(
        self, seri: list[list[float]], maks: float, jumlah_slot: int, putus: int = -1
    ) -> None:
        lebar_slot = (self.x1 - self.x0) / max(jumlah_slot, 1)
        # Sisakan jarak dalam agar titik pertama dan terakhir tidak
        # menempel ke tepi area gambar.
        jarak_dalam = lebar_slot * 0.12
        lebar_pakai = (self.x1 - self.x0) - jarak_dalam * 2

        def koordinat_x(i: int) -> float:
            if jumlah_slot <= 1:
                return self.x0 + lebar_pakai / 2 + jarak_dalam
            return self.x0 + jarak_dalam + lebar_pakai * i / (jumlah_slot - 1)

        semua_titik: list[list[tuple[float, float]]] = []
        for indeks_seri, nilai_seri in enumerate(seri):
            titik = [
                (koordinat_x(i), self._px(min(n, maks), maks))
                for i, n in enumerate(nilai_seri)
            ]
            semua_titik.append(titik)
            jalur = " ".join(f"{x:.1f},{y:.1f}" for x, y in titik)
            gaya = ' stroke-dasharray="6 4"' if indeks_seri == putus else ""
            self.bagian.append(
                f'<polyline points="{jalur}" fill="none"'
                f' stroke="{WARNA[indeks_seri % len(WARNA)]}" stroke-width="2.2"{gaya}/>'
            )

        # Marker digambar setelah semua garis, agar tidak tertimpa garis
        # seri berikutnya.
        for indeks_seri, titik in enumerate(semua_titik):
            bentuk_kotak = indeks_seri % 2 == 1
            for x, y in titik:
                warna = WARNA[indeks_seri % len(WARNA)]
                if bentuk_kotak:
                    self.bagian.append(
                        f'<rect x="{x - 3.4:.1f}" y="{y - 3.4:.1f}" width="6.8"'
                        f' height="6.8" rx="1" fill="{warna}"/>'
                    )
                else:
                    self.bagian.append(
                        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="{warna}"/>'
                    )

        # Label digeser ke samping, bukan ditumpuk, agar urutannya tidak terbalik.
        JARAK_MINIMUM = 13.0
        for indeks in range(max((len(s) for s in seri), default=0)):
            kandidat = []
            for indeks_seri, nilai_seri in enumerate(seri):
                if indeks >= len(nilai_seri):
                    continue
                x, y = semua_titik[indeks_seri][indeks]
                kandidat.append((y, x, nilai_seri[indeks], indeks_seri))
            kandidat.sort()

            # Kelompokkan label yang posisi vertikalnya berdekatan.
            klaster: list[list[tuple[float, float, float, int]]] = []
            for item in kandidat:
                if klaster and abs(item[0] - klaster[-1][-1][0]) < JARAK_MINIMUM:
                    klaster[-1].append(item)
                else:
                    klaster.append([item])

            for kelompok in klaster:
                jumlah_label = len(kelompok)
                for posisi, (y, x, nilai, indeks_seri) in enumerate(kelompok):
                    if jumlah_label == 1:
                        dx, jangkar = 0.0, "middle"
                    else:
                        # Sebarkan label ke kiri dan kanan titiknya.
                        geser = posisi - (jumlah_label - 1) / 2
                        dx = geser * 34.0
                        jangkar = (
                            "middle" if abs(geser) < 0.01 else ("end" if geser < 0 else "start")
                        )
                    y_label = max(y - 11, self.y1 + 10)
                    x_label = min(max(x + dx, self.x0 + 4), self.x1 - 4)
                    self.bagian.append(
                        f'<text x="{x_label:.1f}" y="{y_label:.1f}"'
                        f' fill="{WARNA[indeks_seri % len(WARNA)]}"'
                        f' font-size="10.5" font-family="JetBrains Mono, monospace"'
                        f' text-anchor="{jangkar}">{nilai:.2f}</text>'
                    )

    def catatan(self, teks: str) -> None:
        self.bagian.append(
            f'<text x="{MARGIN_KIRI}" y="44" fill="{WARNA_REDUP}" font-size="10.5"'
            f' font-family="Segoe UI, sans-serif">{_esc(teks)}</text>'
        )

    def simpan(self, nama: str) -> str:
        siapkan_folder_hasil()
        path = os.path.join(DIR_GRAFIK, nama)
        isi = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{LEBAR}"'
            f' height="{TINGGI}" viewBox="0 0 {LEBAR} {TINGGI}">'
            + "".join(self.bagian)
            + "</svg>"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(isi)
        return path

def baca_json(nama: str) -> dict | None:
    path = os.path.join(DIR_MENTAH, nama)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None

def grafik_skalabilitas(dibuat: list[str]) -> None:
    data = baca_json("uji_skalabilitas.json")
    if not data or not data.get("hasil"):
        return
    baris = data["hasil"]
    label = [f"{b['jumlah_node_hidup']} node" for b in baris]
    up_tp = [b["upload_throughput_mbps"] for b in baris]
    down_tp = [b["download_throughput_mbps"] for b in baris]
    s_up = [b["speedup_upload"] for b in baris]
    s_down = [b["speedup_download"] for b in baris]
    e_up = [b["efisiensi_upload"] for b in baris]
    e_down = [b["efisiensi_download"] for b in baris]

    k = Kanvas("Throughput per Jumlah Data Node", "Throughput", "Konfigurasi node")
    maks_tp = batas_bulat(max(up_tp + down_tp + [1]) * 1.15)
    k.kerangka(maks_tp, label, "(MB/s)")
    k.batang([up_tp, down_tp], maks_tp, len(baris))
    k.legenda(["Upload", "Download"])
    dibuat.append(k.simpan("skalabilitas_throughput.svg"))

    # Garis ideal ikut menentukan batas atas sumbu, supaya garis itu tidak
    # menembus kerangka grafik saat jumlah node besar.
    ideal = [float(b["jumlah_node_hidup"]) for b in baris]
    maks_s = batas_bulat(max(s_up + s_down + ideal + [1]) * 1.1)
    k = Kanvas("Speedup per Jumlah Data Node", "Speedup S", "Konfigurasi node")
    k.kerangka(maks_s, label, "(kali)", gaya_x="titik")
    k.catatan("S = T sekuensial / T paralel. Garis putus-putus adalah speedup ideal.")
    k.garis([s_up, s_down, ideal], maks_s, len(baris), putus=2)
    k.legenda(["Upload", "Download", "Ideal (linear)"])
    dibuat.append(k.simpan("skalabilitas_speedup.svg"))

    maks_e = batas_bulat(max(e_up + e_down + [1.0]) * 1.1)
    k = Kanvas("Efisiensi per Jumlah Data Node", "Efisiensi E", "Konfigurasi node")
    k.kerangka(maks_e, label, "(E = S / P)", gaya_x="titik")
    k.catatan("E = S / P, dengan P adalah jumlah data node aktif.")
    k.garis([e_up, e_down], maks_e, len(baris))
    k.legenda(["Upload", "Download"])
    dibuat.append(k.simpan("skalabilitas_efisiensi.svg"))

def grafik_deduplikasi(dibuat: list[str]) -> None:
    data = baca_json("uji_dedup_versioning.json")
    if not data or "ringkasan_deduplikasi" not in data:
        return
    r = data["ringkasan_deduplikasi"]
    mb = 1024 * 1024
    nilai = [
        r["ukuran_chunk_direferensikan"] / mb,
        r["ukuran_fisik_unik"] / mb,
        r["hemat_deduplikasi"] / mb,
    ]
    k = Kanvas(
        "Dampak Deduplikasi Konten", "Ukuran", "Jenis pengukuran"
    )
    maks = batas_bulat(max(nilai + [1]) * 1.15)
    k.kerangka(maks, ["Direferensikan", "Fisik unik", "Dihemat"], "(MB)")
    k.catatan(
        f"Rasio deduplikasi {r['rasio_deduplikasi']}x,"
        f" penghematan {r['persen_hemat']}% dari total chunk direferensikan."
    )
    # Satu batang per kategori, masing-masing warna sendiri. Legenda tidak
    # diperlukan karena nama kategori sudah tertulis di sumbu X.
    k.batang([nilai], maks, 3, warna_per_slot=True)
    dibuat.append(k.simpan("deduplikasi_ruang.svg"))

def grafik_fault_tolerance(dibuat: list[str]) -> None:
    data = baca_json("uji_fault_tolerance.json")
    if not data or "fault_recovery" not in data:
        return
    fr = data["fault_recovery"]
    deteksi = float(fr.get("waktu_deteksi_node_mati_detik") or 0)
    pulih = float(fr.get("waktu_pemulihan_penuh_detik") or 0)
    ambang = float(fr.get("ambang_node_mati_detik") or 0)
    nilai = [ambang, deteksi, pulih]
    k = Kanvas(
        "Waktu Deteksi dan Pemulihan Kegagalan Node", "Waktu", "Tahap"
    )
    maks = batas_bulat(max(nilai + [1]) * 1.15)
    k.kerangka(maks, ["Ambang mati", "Deteksi", "Pemulihan penuh"], "(detik)")
    k.catatan(
        f"{fr.get('chunk_dipulihkan', 0)} chunk dipulihkan otomatis,"
        f" {fr.get('chunk_gagal_dipulihkan', 0)} gagal."
        " Diukur sejak perintah mematikan container."
    )
    # Satu batang per tahap, nama tahapnya sudah ada di sumbu X.
    k.batang([nilai], maks, 3, warna_per_slot=True)
    dibuat.append(k.simpan("fault_tolerance_waktu.svg"))

def grafik_massal(dibuat: list[str]) -> None:
    berkas = [f for f in os.listdir(DIR_MENTAH) if f.startswith("uji_massal")] if os.path.isdir(DIR_MENTAH) else []
    data = None
    for nama in sorted(berkas):
        if nama.endswith(".json"):
            data = baca_json(nama)
            break
    if not data:
        return
    up = data["upload_massal"]
    down = data["download_massal"]

    k = Kanvas(
        "Throughput dan Latency Upload Dibanding Download",
        "Nilai terukur",
        "Metrik",
    )
    nilai_tp = [up["throughput_mbps"], down["throughput_mbps"]]
    nilai_lat = [up["latensi_rata"], down["latensi_rata"]]
    maks = batas_bulat(max(nilai_tp + nilai_lat + [1]) * 1.15)
    k.kerangka(maks, ["Throughput (MB/s)", "Latency rata (detik)"], "")
    k.catatan(
        f"{up['jumlah_berkas']} berkas, {down['hash_cocok']} lolos verifikasi hash SHA-256."
    )
    k.batang([[nilai_tp[0], nilai_lat[0]], [nilai_tp[1], nilai_lat[1]]], maks, 2)
    k.legenda(["Upload", "Download"])
    dibuat.append(k.simpan("massal_throughput_latency.svg"))

def main() -> int:
    siapkan_folder_hasil()
    dibuat: list[str] = []
    grafik_massal(dibuat)
    grafik_skalabilitas(dibuat)
    grafik_deduplikasi(dibuat)
    grafik_fault_tolerance(dibuat)

    if not dibuat:
        print(
            "Belum ada berkas hasil pengujian di"
            f" {DIR_MENTAH}. Jalankan skrip pengujian lebih dulu."
        )
        return 1

    print(f"{len(dibuat)} grafik dibuat:")
    for p in dibuat:
        print(f"  {p}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
