from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict

AKAR_HASIL = os.environ.get(
    "HASIL_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
)
DIR_MENTAH = os.path.join(AKAR_HASIL, "raw")
DIR_GRAFIK = os.path.join(AKAR_HASIL, "charts")
DIR_TANGKAPAN = os.path.join(AKAR_HASIL, "screenshots")
MASTER_URL = os.environ.get("MASTER_URL", "http://127.0.0.1:9100").rstrip("/")
DUMMY_DIR = os.environ.get("DUMMY_DIR", "/data/dummy")
BACA_BLOK = 1024 * 1024

def siapkan_folder_hasil() -> None:
    for d in (DIR_MENTAH, DIR_GRAFIK, DIR_TANGKAPAN):
        os.makedirs(d, exist_ok=True)

# HTTP dasar
def minta_json(
    url: str, metode: str = "GET", payload: object = None, timeout: float = 120.0
) -> tuple[int, object]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=metode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            isi = resp.read()
            try:
                return resp.status, json.loads(isi.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return resp.status, {}
    except urllib.error.HTTPError as exc:
        isi = exc.read()
        try:
            return exc.code, json.loads(isi.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, {"error": isi[:200].decode("utf-8", "replace")}
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": str(exc)}

def minta_biner(
    url: str, metode: str = "GET", body: bytes | None = None, timeout: float = 600.0
) -> tuple[int, bytes, float]:
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url, data=body, headers=headers, method=metode)
    mulai = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            potongan = resp.read(BACA_BLOK)
            ttfb = time.perf_counter() - mulai
            bagian = [potongan]
            while potongan:
                potongan = resp.read(BACA_BLOK)
                if potongan:
                    bagian.append(potongan)
            return resp.status, b"".join(bagian), ttfb
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:500], time.perf_counter() - mulai
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc).encode("utf-8"), time.perf_counter() - mulai

def sha256_berkas(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            blok = f.read(BACA_BLOK)
            if not blok:
                break
            h.update(blok)
    return h.hexdigest()

# Hasil per berkas
@dataclass
class HasilBerkas:
    nama: str
    ukuran: int
    berhasil: bool
    durasi: float = 0.0
    ttfb: float = 0.0
    file_id: str = ""
    versi: int = 0
    hash_cocok: bool | None = None
    jumlah_chunk: int = 0
    chunk_dedup: int = 0
    galat: str = ""

@dataclass
class RingkasanTahap:
    nama_tahap: str
    mode: str
    jumlah_berkas: int = 0
    berkas_berhasil: int = 0
    berkas_gagal: int = 0
    hash_cocok: int = 0
    total_byte: int = 0
    waktu_total: float = 0.0
    throughput_mbps: float = 0.0
    latensi_rata: float = 0.0
    latensi_terburuk: float = 0.0
    ttfb_rata: float = 0.0
    paralel: int = 1
    rincian: list[HasilBerkas] = field(default_factory=list)

    def hitung(self) -> "RingkasanTahap":
        sukses = [r for r in self.rincian if r.berhasil]
        self.jumlah_berkas = len(self.rincian)
        self.berkas_berhasil = len(sukses)
        self.berkas_gagal = self.jumlah_berkas - self.berkas_berhasil
        self.hash_cocok = sum(1 for r in self.rincian if r.hash_cocok)
        self.total_byte = sum(r.ukuran for r in sukses)
        if self.waktu_total > 0:
            self.throughput_mbps = round(
                (self.total_byte / (1024 * 1024)) / self.waktu_total, 3
            )
        if sukses:
            durasi = [r.durasi for r in sukses]
            self.latensi_rata = round(sum(durasi) / len(durasi), 4)
            self.latensi_terburuk = round(max(durasi), 4)
            self.ttfb_rata = round(sum(r.ttfb for r in sukses) / len(sukses), 4)
        return self

# Klien DFS-X
class KlienDfsx:
    def __init__(self, master_url: str = MASTER_URL, mode: str = "auto") -> None:
        self.master = master_url.rstrip("/")
        self.konfigurasi = self._ambil_konfigurasi()
        self.chunk_size = int(self.konfigurasi.get("chunk_size_bytes") or 4 * 1024 * 1024)
        self.mode = self._tentukan_mode(mode)

    def _ambil_konfigurasi(self) -> dict:
        status, data = minta_json(f"{self.master}/config", timeout=15.0)
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"Master tidak menjawab /config (status {status})")
        return data

    def _tentukan_mode(self, diminta: str) -> str:
        if diminta in ("ringkas", "dua_tahap"):
            return diminta
        # Mode dua tahap hanya dipakai bila alamat data node terjangkau.
        for node in self.node_hidup():
            status, _ = minta_json(f"{node['alamat']}/health", timeout=3.0)
            if status == 200:
                return "dua_tahap"
            break
        return "ringkas"

    def node_hidup(self) -> list[dict]:
        status, data = minta_json(f"{self.master}/status", timeout=20.0)
        if status != 200 or not isinstance(data, dict):
            return []
        return [n for n in data.get("node", []) if n.get("status") == "hidup"]

    def status(self) -> dict:
        status, data = minta_json(f"{self.master}/status", timeout=30.0)
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"Status master gagal dibaca (status {status})")
        return data

    def reset(self) -> None:
        minta_json(f"{self.master}/maintenance/reset", "POST", {}, timeout=300.0)

    # ---------------- unggah ----------------
    def unggah(self, path: str, nama: str | None = None) -> HasilBerkas:
        nama = nama or os.path.basename(path)
        ukuran = os.path.getsize(path)
        mulai = time.perf_counter()
        try:
            if self.mode == "dua_tahap":
                hasil = self._unggah_dua_tahap(path, nama)
            else:
                hasil = self._unggah_ringkas(path, nama)
        except Exception as exc:  # noqa: BLE001
            return HasilBerkas(
                nama=nama,
                ukuran=ukuran,
                berhasil=False,
                durasi=time.perf_counter() - mulai,
                galat=str(exc)[:200],
            )
        hasil.durasi = round(time.perf_counter() - mulai, 4)
        hasil.ukuran = ukuran
        return hasil

    def _unggah_ringkas(self, path: str, nama: str) -> HasilBerkas:
        with open(path, "rb") as f:
            isi = f.read()
        url = f"{self.master}/files/content?nama={urllib.parse.quote(nama)}"
        status, balasan, ttfb = minta_biner(url, "PUT", isi, timeout=900.0)
        if status != 201:
            pesan = balasan[:200].decode("utf-8", "replace")
            return HasilBerkas(nama=nama, ukuran=len(isi), berhasil=False, galat=pesan)
        data = json.loads(balasan.decode("utf-8"))
        return HasilBerkas(
            nama=nama,
            ukuran=len(isi),
            berhasil=True,
            ttfb=round(ttfb, 4),
            file_id=data["file_id"],
            versi=int(data["versi"]),
            jumlah_chunk=int(data["jumlah_chunk"]),
            chunk_dedup=int(data.get("chunk_dideduplikasi") or 0),
        )

    def _unggah_dua_tahap(self, path: str, nama: str) -> HasilBerkas:
        # Tahap 1: potong berkas dan hitung hash tiap chunk.
        potongan: list[tuple[int, str, bytes]] = []
        h_berkas = hashlib.sha256()
        with open(path, "rb") as f:
            urutan = 0
            while True:
                blok = f.read(self.chunk_size)
                if not blok:
                    break
                h_berkas.update(blok)
                potongan.append((urutan, hashlib.sha256(blok).hexdigest(), blok))
                urutan += 1
        ukuran = sum(len(p[2]) for p in potongan)

        status, rencana = minta_json(
            f"{self.master}/files",
            "POST",
            {
                "nama": nama,
                "ukuran": ukuran,
                "hash_berkas": h_berkas.hexdigest(),
                "chunks": [
                    {"urutan": u, "chunk_hash": h, "ukuran": len(d)} for u, h, d in potongan
                ],
            },
            timeout=120.0,
        )
        if status != 201 or not isinstance(rencana, dict):
            return HasilBerkas(
                nama=nama, ukuran=ukuran, berhasil=False, galat=str(rencana)[:200]
            )

        isi_per_hash = {h: d for _, h, d in potongan}
        tertulis: dict[str, list[str]] = {}

        def kirim(item: dict) -> tuple[str, list[str]]:
            chunk_hash = item["chunk_hash"]
            tujuan = item.get("node_tujuan") or item.get("node_tambahan") or []
            sukses: list[str] = []
            if not item["perlu_unggah"] and not tujuan:
                return chunk_hash, [n["node_id"] for n in item.get("sumber_replika", [])]
            data = isi_per_hash[chunk_hash]
            for node in tujuan:
                st, _, _ = minta_biner(
                    f"{node['alamat']}/chunks/{chunk_hash}", "PUT", data, timeout=600.0
                )
                if st in (200, 201):
                    sukses.append(node["node_id"])
            sukses += [n["node_id"] for n in item.get("sumber_replika", [])]
            return chunk_hash, sukses

        # Unggahan chunk berjalan paralel: inilah sumber paralelisme yang
        # diukur pada pengujian speedup.
        with ThreadPoolExecutor(max_workers=8) as kolam:
            for chunk_hash, node_list in kolam.map(kirim, rencana["rencana"]):
                tertulis.setdefault(chunk_hash, [])
                tertulis[chunk_hash] = sorted(set(tertulis[chunk_hash] + node_list))

        # Tahap 2: master memverifikasi replika minimum sebelum mencatat versi.
        status, balasan = minta_json(
            f"{self.master}/files/{rencana['file_id']}/commit",
            "POST",
            {
                "versi": rencana["versi"],
                "hash_berkas": rencana["hash_berkas"],
                "ukuran": ukuran,
                "chunks": [
                    {"urutan": u, "chunk_hash": h, "ukuran": len(d)} for u, h, d in potongan
                ],
                "replika_tertulis": tertulis,
            },
            timeout=300.0,
        )
        if status != 201 or not isinstance(balasan, dict):
            return HasilBerkas(
                nama=nama, ukuran=ukuran, berhasil=False, galat=str(balasan)[:200]
            )
        return HasilBerkas(
            nama=nama,
            ukuran=ukuran,
            berhasil=True,
            file_id=balasan["file_id"],
            versi=int(balasan["versi"]),
            jumlah_chunk=int(balasan["jumlah_chunk"]),
            chunk_dedup=int(rencana.get("chunk_dideduplikasi") or 0),
        )

    # ---------------- unduh ----------------
    def unduh(
        self, file_id: str, nama: str, hash_harapan: str | None = None, versi: int | None = None
    ) -> HasilBerkas:
        kueri = f"?version={versi}" if versi else ""
        mulai = time.perf_counter()
        status, isi, ttfb = minta_biner(
            f"{self.master}/files/{file_id}/content{kueri}", timeout=900.0
        )
        durasi = round(time.perf_counter() - mulai, 4)
        if status != 200:
            return HasilBerkas(
                nama=nama,
                ukuran=0,
                berhasil=False,
                durasi=durasi,
                ttfb=round(ttfb, 4),
                file_id=file_id,
                galat=isi[:200].decode("utf-8", "replace"),
            )
        cocok = None
        if hash_harapan:
            cocok = hashlib.sha256(isi).hexdigest() == hash_harapan
        return HasilBerkas(
            nama=nama,
            ukuran=len(isi),
            berhasil=True,
            durasi=durasi,
            ttfb=round(ttfb, 4),
            file_id=file_id,
            hash_cocok=cocok,
        )

# Penulis hasil
def tulis_json(nama_berkas: str, data: object) -> str:
    siapkan_folder_hasil()
    path = os.path.join(DIR_MENTAH, nama_berkas)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path

def tulis_csv(nama_berkas: str, baris: list[dict], kolom: list[str] | None = None) -> str:
    siapkan_folder_hasil()
    path = os.path.join(DIR_MENTAH, nama_berkas)
    if not baris:
        open(path, "w", encoding="utf-8").close()
        return path
    kolom = kolom or list(baris[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        penulis = csv.DictWriter(f, fieldnames=kolom, extrasaction="ignore")
        penulis.writeheader()
        penulis.writerows(baris)
    return path

def ringkasan_ke_dict(r: RingkasanTahap, sertakan_rincian: bool = False) -> dict:
    data = asdict(r)
    if not sertakan_rincian:
        data.pop("rincian", None)
    return data

def cetak_ringkasan(r: RingkasanTahap) -> None:
    print(
        f"  {r.nama_tahap:<28} mode={r.mode:<10} paralel={r.paralel:<3}"
        f" berhasil={r.berkas_berhasil}/{r.jumlah_berkas}"
        f" waktu={r.waktu_total:.2f}s"
        f" throughput={r.throughput_mbps:.2f} MB/s"
        f" latensi_rata={r.latensi_rata:.3f}s"
    )
