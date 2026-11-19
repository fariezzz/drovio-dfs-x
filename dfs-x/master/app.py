from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from dfsx_core import (  # noqa: E402
    Pencatat,
    binary_request,
    env_bool,
    env_float,
    env_int,
    env_str,
    hash_valid,
    json_request,
    sekarang,
    sha256_bytes,
)
from http_mini import (  # noqa: E402
    GalatPermintaan,
    Jawaban,
    Permintaan,
    Perute,
    jalankan,
)
from metadata import Metadata  # noqa: E402

HOST = env_str("MASTER_HOST", "0.0.0.0")
PORT = env_int("MASTER_PORT", 9100)
DB_PATH = env_str("METADATA_DB", "/data/metadata.db")
CHUNK_SIZE = env_int("CHUNK_SIZE_MB", 4) * 1024 * 1024
REPLICATION_FACTOR = max(1, env_int("REPLICATION_FACTOR", 2))
# Replika minimum sebelum penulisan diakui (consistency control).
MIN_REPLICAS = max(1, min(env_int("MIN_REPLICAS", REPLICATION_FACTOR), REPLICATION_FACTOR))
HEARTBEAT_INTERVAL = env_float("HEARTBEAT_INTERVAL_SECONDS", 5.0)
NODE_DEAD_THRESHOLD = env_float("NODE_DEAD_THRESHOLD_SECONDS", 15.0)
HEAL_INTERVAL = env_float("HEAL_INTERVAL_SECONDS", 5.0)
HEAL_BATCH = env_int("HEAL_BATCH", 64)
ADAPTIVE = env_bool("ADAPTIVE_REPLICATION", True)
# Ambang node dianggap hampir penuh. Di atas ambang ini, node hanya dipakai
# kalau tidak ada pilihan lain.
CAPACITY_WARN_RATIO = env_float("CAPACITY_WARN_RATIO", 0.85)
PARALEL_IO = max(1, env_int("MASTER_IO_WORKERS", 8))
# Batas waktu baca per replika, dibuat pendek agar cepat pindah replika.
CHUNK_READ_TIMEOUT = env_float("CHUNK_READ_TIMEOUT_SECONDS", 10.0)

pencatat = Pencatat("master")
perute = Perute()
db = Metadata(DB_PATH)
_kunci_heal = threading.Lock()
_statistik_heal = {
    "siklus": 0,
    "chunk_dipulihkan": 0,
    "chunk_gagal": 0,
    "pemulihan_terakhir": None,
    "durasi_terakhir": None,
    "sedang_memulihkan": False,
}

# Beban yang sudah diarahkan ke node tapi belum masuk heartbeat terakhirnya.
# Tanpa ini, semua chunk satu unggahan menumpuk di node yang sama.
_beban_sementara: dict[str, int] = {}
_kunci_beban = threading.Lock()

def tambah_beban(node_id: str, ukuran: int) -> None:
    with _kunci_beban:
        _beban_sementara[node_id] = _beban_sementara.get(node_id, 0) + max(ukuran, 1)

def reset_beban(node_id: str) -> None:
    with _kunci_beban:
        _beban_sementara.pop(node_id, None)

def beban_node(node_id: str) -> int:
    with _kunci_beban:
        return _beban_sementara.get(node_id, 0)

def skor_node(node: dict) -> tuple:
    total = max(int(node.get("kapasitas_total") or 0), 1)
    terpakai = int(node.get("kapasitas_terpakai") or 0) + beban_node(node["node_id"])
    rasio = terpakai / total
    hampir_penuh = 1 if rasio >= CAPACITY_WARN_RATIO else 0
    tidak_sehat = 0 if node.get("status_kesehatan") == "sehat" else 1
    return (hampir_penuh, tidak_sehat, round(rasio, 6), node["node_id"])

def pilih_node(
    jumlah: int,
    kecualikan: set[str] | None = None,
    urutan_kunci: str | None = None,
    ukuran: int = 0,
) -> list[dict]:
    kecualikan = kecualikan or set()
    kandidat = [n for n in db.node_hidup() if n["node_id"] not in kecualikan]
    if not kandidat:
        return []
    if ADAPTIVE:
        kandidat.sort(key=skor_node)
    else:
        # Tanpa mode adaptif, sebaran memakai hash chunk agar tetap merata
        # dan dapat diulang untuk chunk yang sama.
        kandidat.sort(key=lambda n: n["node_id"])
        if urutan_kunci:
            geser = int(urutan_kunci[:8], 16) % len(kandidat)
            kandidat = kandidat[geser:] + kandidat[:geser]
    terpilih = kandidat[:jumlah]
    if ukuran > 0:
        for n in terpilih:
            tambah_beban(n["node_id"], ukuran)
    return terpilih

def alamat_node(node_id: str) -> str | None:
    baris = db.satu("SELECT alamat FROM nodes WHERE node_id=?", (node_id,))
    return baris["alamat"] if baris else None

def kirim_chunk_ke_node(node: dict, chunk_hash: str, data: bytes) -> bool:
    status, _ = binary_request(
        f"{node['alamat']}/chunks/{chunk_hash}", metode="PUT", body=data, timeout=120.0
    )
    if status in (200, 201):
        db.catat_replika(chunk_hash, node["node_id"], sekarang())
        return True
    pencatat.warn("gagal menulis chunk", node=node["node_id"], chunk=chunk_hash, status=status)
    return False

def ambil_chunk_dari_replika(chunk_hash: str) -> bytes | None:
    for node in db.node_untuk_chunk(chunk_hash):
        status, isi = binary_request(
            f"{node['alamat']}/chunks/{chunk_hash}", timeout=CHUNK_READ_TIMEOUT
        )
        if status == 200 and sha256_bytes(isi) == chunk_hash:
            return isi
        if status == 200:
            pencatat.error("isi chunk rusak di node", node=node["node_id"], chunk=chunk_hash)
            db.hapus_replika(chunk_hash, node["node_id"])
            db.catat("chunk_rusak", f"{chunk_hash[:12]} di {node['node_id']}")
    return None

# Heartbeat dan status node
@perute.post("/nodes/heartbeat")
def heartbeat(req: Permintaan) -> Jawaban:
    data = req.json()
    node_id = str(data.get("node_id") or "").strip()
    alamat = str(data.get("alamat") or "").strip().rstrip("/")
    if not node_id or not alamat:
        raise GalatPermintaan("node_id dan alamat wajib diisi")
    waktu = sekarang()
    pulih = db.catat_heartbeat(
        node_id=node_id,
        alamat=alamat,
        kapasitas_total=int(data.get("kapasitas_total") or 0),
        kapasitas_terpakai=int(data.get("kapasitas_terpakai") or 0),
        jumlah_chunk=int(data.get("jumlah_chunk") or 0),
        status_kesehatan=str(data.get("status_kesehatan") or "sehat"),
        waktu=waktu,
    )
    # Heartbeat membawa kapasitas terpakai yang sebenarnya, jadi catatan
    # beban sementara untuk node ini sudah tidak diperlukan lagi.
    reset_beban(node_id)
    if pulih:
        db.tandai_hidup_kembali(node_id)
        db.catat("node_hidup", f"{node_id} terdaftar atau pulih")
        pencatat.info("node hidup", node=node_id, alamat=alamat)
    return Jawaban.json({"node_id": node_id, "diterima_pada": waktu})

@perute.get("/health")
def health(_req: Permintaan) -> Jawaban:
    hidup = db.node_hidup()
    return Jawaban.json(
        {
            "status": "hidup",
            "peran": "master",
            "node_hidup": len(hidup),
            "node_total": len(db.semua_node()),
            "chunk_size": CHUNK_SIZE,
            "replication_factor": REPLICATION_FACTOR,
            "min_replicas": MIN_REPLICAS,
            "replikasi_adaptif": ADAPTIVE,
        }
    )

@perute.get("/config")
def konfigurasi(_req: Permintaan) -> Jawaban:
    return Jawaban.json(
        {
            "chunk_size_bytes": CHUNK_SIZE,
            "replication_factor": REPLICATION_FACTOR,
            "min_replicas": MIN_REPLICAS,
            "heartbeat_interval_seconds": HEARTBEAT_INTERVAL,
            "node_dead_threshold_seconds": NODE_DEAD_THRESHOLD,
            "replikasi_adaptif": ADAPTIVE,
        }
    )

# Alur simpan tahap 1: rencana penempatan
@perute.post("/files")
def rencana_simpan(req: Permintaan) -> Jawaban:
    data = req.json()
    nama = str(data.get("nama") or "").strip()
    if not nama or "/" in nama or "\\" in nama:
        raise GalatPermintaan("nama berkas wajib diisi dan tanpa pemisah path")
    hash_berkas = str(data.get("hash_berkas") or "").lower()
    if not hash_valid(hash_berkas):
        raise GalatPermintaan("hash_berkas harus hex SHA-256")
    ukuran = int(data.get("ukuran") or 0)
    daftar = data.get("chunks")
    if not isinstance(daftar, list) or not daftar:
        raise GalatPermintaan("chunks wajib berupa daftar tidak kosong")

    hidup = db.node_hidup()
    if not hidup:
        return Jawaban.json({"error": "Tidak ada data node yang hidup"}, status=503)
    if len(hidup) < MIN_REPLICAS:
        return Jawaban.json(
            {
                "error": "Node hidup lebih sedikit dari replika minimum",
                "node_hidup": len(hidup),
                "min_replicas": MIN_REPLICAS,
            },
            status=503,
        )

    waktu = sekarang()
    file_id, versi = db.siapkan_versi(nama, waktu)
    rencana = []
    jumlah_dedup = 0
    byte_dedup = 0
    for item in daftar:
        if not isinstance(item, dict):
            raise GalatPermintaan("setiap chunk harus berupa objek")
        chunk_hash = str(item.get("chunk_hash") or "").lower()
        if not hash_valid(chunk_hash):
            raise GalatPermintaan("chunk_hash harus hex SHA-256")
        urutan = int(item.get("urutan") or 0)
        ukuran_chunk = int(item.get("ukuran") or 0)
        sudah_ada = db.chunk_siap_pakai(chunk_hash)
        if sudah_ada:
            jumlah_dedup += 1
            byte_dedup += ukuran_chunk
            node_tujuan = db.node_untuk_chunk(chunk_hash)
            kurang = REPLICATION_FACTOR - len(node_tujuan)
            tambahan = (
                pilih_node(
                    kurang,
                    kecualikan={n["node_id"] for n in node_tujuan},
                    urutan_kunci=chunk_hash,
                    ukuran=ukuran_chunk,
                )
                if kurang > 0
                else []
            )
            rencana.append(
                {
                    "urutan": urutan,
                    "chunk_hash": chunk_hash,
                    "ukuran": ukuran_chunk,
                    "perlu_unggah": False,
                    "sumber_replika": [
                        {"node_id": n["node_id"], "alamat": n["alamat"]} for n in node_tujuan
                    ],
                    "node_tambahan": [
                        {"node_id": n["node_id"], "alamat": n["alamat"]} for n in tambahan
                    ],
                }
            )
        else:
            tujuan = pilih_node(
                REPLICATION_FACTOR, urutan_kunci=chunk_hash, ukuran=ukuran_chunk
            )
            if len(tujuan) < MIN_REPLICAS:
                return Jawaban.json(
                    {"error": "Node hidup tidak cukup untuk replika minimum"}, status=503
                )
            rencana.append(
                {
                    "urutan": urutan,
                    "chunk_hash": chunk_hash,
                    "ukuran": ukuran_chunk,
                    "perlu_unggah": True,
                    "node_tujuan": [
                        {"node_id": n["node_id"], "alamat": n["alamat"]} for n in tujuan
                    ],
                }
            )

    return Jawaban.json(
        {
            "file_id": file_id,
            "nama": nama,
            "versi": versi,
            "ukuran": ukuran,
            "hash_berkas": hash_berkas,
            "chunk_size": CHUNK_SIZE,
            "replication_factor": REPLICATION_FACTOR,
            "min_replicas": MIN_REPLICAS,
            "chunk_dideduplikasi": jumlah_dedup,
            "byte_dideduplikasi": byte_dedup,
            "rencana": rencana,
        },
        status=201,
    )

@perute.post("/files/{file_id}/commit")
def commit_versi(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id)
    if berkas is None:
        return Jawaban.json({"error": "file_id tidak dikenal"}, status=404)

    data = req.json()
    versi = int(data.get("versi") or 0)
    if versi <= 0:
        raise GalatPermintaan("versi wajib diisi")
    hash_berkas = str(data.get("hash_berkas") or "").lower()
    if not hash_valid(hash_berkas):
        raise GalatPermintaan("hash_berkas harus hex SHA-256")
    ukuran = int(data.get("ukuran") or 0)
    daftar = data.get("chunks")
    if not isinstance(daftar, list) or not daftar:
        raise GalatPermintaan("chunks wajib berupa daftar tidak kosong")

    laporan = data.get("replika_tertulis")
    if isinstance(laporan, dict):
        waktu_lapor = sekarang()
        for chunk_hash, node_list in laporan.items():
            if not hash_valid(chunk_hash) or not isinstance(node_list, list):
                continue
            for node_id in node_list:
                if isinstance(node_id, str) and node_id:
                    db.catat_replika(chunk_hash, node_id, waktu_lapor)

    kurang: list[dict] = []
    susunan: list[tuple[int, str, int]] = []
    for item in sorted(daftar, key=lambda x: int(x.get("urutan", 0))):
        chunk_hash = str(item.get("chunk_hash") or "").lower()
        if not hash_valid(chunk_hash):
            raise GalatPermintaan("chunk_hash harus hex SHA-256")
        ukuran_chunk = int(item.get("ukuran") or 0)
        aktif = db.node_untuk_chunk(chunk_hash)
        if len(aktif) < MIN_REPLICAS:
            kurang.append(
                {
                    "chunk_hash": chunk_hash,
                    "replika_aktif": len(aktif),
                    "min_replicas": MIN_REPLICAS,
                }
            )
        susunan.append((int(item.get("urutan", 0)), chunk_hash, ukuran_chunk))

    if kurang:
        db.catat(
            "tulis_ditolak",
            f"{berkas['nama']} v{versi}: {len(kurang)} chunk di bawah replika minimum",
        )
        return Jawaban.json(
            {
                "error": "Penulisan ditolak, replika minimum belum terpenuhi",
                "chunk_kurang": kurang[:20],
                "jumlah_chunk_kurang": len(kurang),
            },
            status=409,
        )

    waktu = sekarang()
    db.simpan_versi(file_id, versi, hash_berkas, ukuran, susunan, waktu)
    db.catat("versi_disimpan", f"{berkas['nama']} v{versi}, {len(susunan)} chunk")
    pencatat.info("versi disimpan", berkas=berkas["nama"], versi=versi, chunk=len(susunan))
    return Jawaban.json(
        {
            "file_id": file_id,
            "nama": berkas["nama"],
            "versi": versi,
            "ukuran": ukuran,
            "hash_berkas": hash_berkas,
            "jumlah_chunk": len(susunan),
            "versi_aktif": versi,
        },
        status=201,
    )

# Jalur ringkas: master melakukan chunking sendiri
def sebar_chunk(chunk_hash: str, data: bytes) -> tuple[list[str], bool]:
    sudah = db.node_untuk_chunk(chunk_hash)
    if db.chunk_siap_pakai(chunk_hash) and len(sudah) >= REPLICATION_FACTOR:
        return [n["node_id"] for n in sudah], True

    dipakai_ulang = len(sudah) > 0
    terpakai = {n["node_id"] for n in sudah}
    sukses = list(terpakai)
    kurang = REPLICATION_FACTOR - len(terpakai)
    if kurang <= 0:
        return sukses, dipakai_ulang

    tujuan = pilih_node(
        kurang, kecualikan=terpakai, urutan_kunci=chunk_hash, ukuran=len(data)
    )
    for node in tujuan:
        if kirim_chunk_ke_node(node, chunk_hash, data):
            sukses.append(node["node_id"])
    return sukses, dipakai_ulang

@perute.put("/files/content")
def simpan_langsung(req: Permintaan) -> Jawaban:
    import urllib.parse

    nama = urllib.parse.unquote(req.query.get("nama", "")).strip()
    if not nama or "/" in nama or "\\" in nama:
        raise GalatPermintaan("query nama wajib diisi dan tanpa pemisah path")
    if not req.body:
        raise GalatPermintaan("Body berkas kosong")

    hidup = db.node_hidup()
    if len(hidup) < MIN_REPLICAS:
        return Jawaban.json(
            {"error": "Node hidup lebih sedikit dari replika minimum"}, status=503
        )

    isi = req.body
    hash_berkas = sha256_bytes(isi)
    waktu = sekarang()
    file_id, versi = db.siapkan_versi(nama, waktu)

    potongan: list[tuple[int, str, bytes]] = []
    for indeks, mulai in enumerate(range(0, len(isi), CHUNK_SIZE)):
        bagian = isi[mulai : mulai + CHUNK_SIZE]
        potongan.append((indeks, sha256_bytes(bagian), bagian))

    susunan: list[tuple[int, str, int]] = []
    kurang: list[str] = []
    dedup_jumlah = 0
    dedup_byte = 0

    def kerjakan(item: tuple[int, str, bytes]):
        urutan, chunk_hash, data = item
        sukses, dipakai_ulang = sebar_chunk(chunk_hash, data)
        return urutan, chunk_hash, len(data), sukses, dipakai_ulang

    with ThreadPoolExecutor(max_workers=PARALEL_IO) as kolam:
        for urutan, chunk_hash, ukuran_chunk, sukses, dipakai_ulang in kolam.map(
            kerjakan, potongan
        ):
            if dipakai_ulang:
                dedup_jumlah += 1
                dedup_byte += ukuran_chunk
            if len(sukses) < MIN_REPLICAS:
                kurang.append(chunk_hash)
            susunan.append((urutan, chunk_hash, ukuran_chunk))

    if kurang:
        db.catat("tulis_ditolak", f"{nama} v{versi}: {len(kurang)} chunk di bawah minimum")
        return Jawaban.json(
            {
                "error": "Penulisan ditolak, replika minimum belum terpenuhi",
                "jumlah_chunk_kurang": len(kurang),
                "min_replicas": MIN_REPLICAS,
            },
            status=409,
        )

    susunan.sort(key=lambda x: x[0])
    db.simpan_versi(file_id, versi, hash_berkas, len(isi), susunan, waktu)
    db.catat(
        "versi_disimpan",
        f"{nama} v{versi}, {len(susunan)} chunk, dedup {dedup_jumlah}",
    )
    return Jawaban.json(
        {
            "file_id": file_id,
            "nama": nama,
            "versi": versi,
            "ukuran": len(isi),
            "hash_berkas": hash_berkas,
            "jumlah_chunk": len(susunan),
            "chunk_dideduplikasi": dedup_jumlah,
            "byte_dideduplikasi": dedup_byte,
        },
        status=201,
    )

# Alur ambil berkas
def tentukan_versi(berkas: dict, query: dict) -> int:
    nilai = query.get("version") or query.get("versi")
    if nilai:
        try:
            return int(nilai)
        except ValueError as exc:
            raise GalatPermintaan("Parameter versi harus angka") from exc
    return int(berkas["versi_aktif"])

@perute.get("/files/{file_id}")
def metadata_berkas(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id) or db.file_dari_nama(file_id)
    if berkas is None:
        return Jawaban.json({"error": "Berkas tidak ditemukan"}, status=404)

    versi = tentukan_versi(berkas, req.query)
    info_versi = db.versi_tertentu(berkas["file_id"], versi)
    if info_versi is None:
        return Jawaban.json({"error": f"Versi {versi} tidak ada"}, status=404)

    daftar_chunk = []
    for c in db.chunk_versi(berkas["file_id"], versi):
        replika = db.node_untuk_chunk(c["chunk_hash"], hanya_hidup=False)
        daftar_chunk.append(
            {
                "urutan": c["urutan"],
                "chunk_hash": c["chunk_hash"],
                "ukuran": c["ukuran"],
                "replika": [
                    {
                        "node_id": r["node_id"],
                        "alamat": r["alamat"],
                        "status_node": r["status"],
                        "status_replika": r["status_replika"],
                    }
                    for r in replika
                ],
            }
        )

    return Jawaban.json(
        {
            "file_id": berkas["file_id"],
            "nama": berkas["nama"],
            "versi_aktif": berkas["versi_aktif"],
            "versi_diminta": versi,
            "hash_berkas": info_versi["hash_berkas"],
            "ukuran": info_versi["ukuran"],
            "daftar_versi": db.daftar_versi(berkas["file_id"]),
            "chunks": daftar_chunk,
        }
    )

@perute.get("/files/{file_id}/content")
def ambil_berkas(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id) or db.file_dari_nama(file_id)
    if berkas is None:
        return Jawaban.json({"error": "Berkas tidak ditemukan"}, status=404)

    versi = tentukan_versi(berkas, req.query)
    info_versi = db.versi_tertentu(berkas["file_id"], versi)
    if info_versi is None:
        return Jawaban.json({"error": f"Versi {versi} tidak ada"}, status=404)

    daftar = db.chunk_versi(berkas["file_id"], versi)
    hasil: dict[int, bytes] = {}

    def tarik(c: dict):
        return c["urutan"], ambil_chunk_dari_replika(c["chunk_hash"]), c["chunk_hash"]

    with ThreadPoolExecutor(max_workers=PARALEL_IO) as kolam:
        for urutan, isi, chunk_hash in kolam.map(tarik, daftar):
            if isi is None:
                db.catat("baca_gagal", f"{berkas['nama']} v{versi} chunk {chunk_hash[:12]}")
                return Jawaban.json(
                    {
                        "error": "Chunk tidak dapat diambil dari replika mana pun",
                        "chunk_hash": chunk_hash,
                    },
                    status=503,
                )
            hasil[urutan] = isi

    utuh = b"".join(hasil[i] for i in sorted(hasil))
    hash_hasil = sha256_bytes(utuh)
    if hash_hasil != info_versi["hash_berkas"]:
        db.catat("hash_tidak_cocok", f"{berkas['nama']} v{versi}")
        pencatat.error("hash rakitan tidak cocok", berkas=berkas["nama"], versi=versi)
        return Jawaban.json(
            {
                "error": "Hash berkas hasil rakitan tidak cocok",
                "diharapkan": info_versi["hash_berkas"],
                "didapat": hash_hasil,
            },
            status=500,
        )

    import urllib.parse

    nama_aman = urllib.parse.quote(berkas["nama"])
    return Jawaban(
        status=200,
        body=utuh,
        tipe="application/octet-stream",
        header={
            "Content-Disposition": f"attachment; filename*=UTF-8''{nama_aman}",
            "X-DFSX-Versi": str(versi),
            "X-DFSX-Hash": hash_hasil,
        },
    )

@perute.get("/chunks/{chunk_hash}/locations")
def lokasi_chunk(req: Permintaan) -> Jawaban:
    chunk_hash = req.params["chunk_hash"].lower()
    if not hash_valid(chunk_hash):
        raise GalatPermintaan("chunk_hash harus hex SHA-256")
    return Jawaban.json(
        {
            "chunk_hash": chunk_hash,
            "replika": db.node_untuk_chunk(chunk_hash, hanya_hidup=False),
        }
    )

@perute.get("/files")
def daftar_berkas(_req: Permintaan) -> Jawaban:
    return Jawaban.json({"berkas": db.daftar_berkas()})

@perute.delete("/files/{file_id}")
def hapus_berkas(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id) or db.file_dari_nama(file_id)
    if berkas is None:
        return Jawaban.json({"error": "Berkas tidak ditemukan"}, status=404)
    yatim = db.hapus_berkas(berkas["file_id"])
    dihapus = 0
    for chunk_hash in yatim:
        for node in db.node_untuk_chunk(chunk_hash, hanya_hidup=True):
            json_request(f"{node['alamat']}/chunks/{chunk_hash}", metode="DELETE", timeout=20.0)
        db.buang_chunk(chunk_hash)
        dihapus += 1
    db.catat("berkas_dihapus", f"{berkas['nama']}, {dihapus} chunk dibuang")
    return Jawaban.json(
        {"file_id": berkas["file_id"], "nama": berkas["nama"], "chunk_dibuang": dihapus}
    )

# Versioning
@perute.get("/files/{file_id}/versions")
def daftar_versi(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id) or db.file_dari_nama(file_id)
    if berkas is None:
        return Jawaban.json({"error": "Berkas tidak ditemukan"}, status=404)
    return Jawaban.json(
        {
            "file_id": berkas["file_id"],
            "nama": berkas["nama"],
            "versi_aktif": berkas["versi_aktif"],
            "versi": db.daftar_versi(berkas["file_id"]),
        }
    )

@perute.post("/files/{file_id}/rollback")
def rollback(req: Permintaan) -> Jawaban:
    file_id = req.params["file_id"]
    berkas = db.file_dari_id(file_id) or db.file_dari_nama(file_id)
    if berkas is None:
        return Jawaban.json({"error": "Berkas tidak ditemukan"}, status=404)

    data = req.json()
    try:
        tujuan = int(data.get("versi"))
    except (TypeError, ValueError) as exc:
        raise GalatPermintaan("versi tujuan wajib berupa angka") from exc

    if db.versi_tertentu(berkas["file_id"], tujuan) is None:
        return Jawaban.json({"error": f"Versi {tujuan} tidak ada"}, status=404)

    sebelum = berkas["versi_aktif"]
    db.set_versi_aktif(berkas["file_id"], tujuan, sekarang())
    db.catat("rollback", f"{berkas['nama']} v{sebelum} menjadi v{tujuan}")
    pencatat.info("rollback versi", berkas=berkas["nama"], dari=sebelum, ke=tujuan)
    return Jawaban.json(
        {
            "file_id": berkas["file_id"],
            "nama": berkas["nama"],
            "versi_aktif_sebelumnya": sebelum,
            "versi_aktif": tujuan,
        }
    )

# Status untuk dashboard
@perute.get("/status")
def status_sistem(_req: Permintaan) -> Jawaban:
    waktu = sekarang()
    node_list = []
    for n in db.semua_node():
        total = max(int(n["kapasitas_total"] or 0), 1)
        node_list.append(
            {
                "node_id": n["node_id"],
                "alamat": n["alamat"],
                "status": n["status"],
                "status_kesehatan": n["status_kesehatan"],
                "kapasitas_total": n["kapasitas_total"],
                "kapasitas_terpakai": n["kapasitas_terpakai"],
                "rasio_terpakai": round(int(n["kapasitas_terpakai"] or 0) / total, 4),
                "jumlah_chunk": n["jumlah_chunk"],
                "heartbeat_terakhir": n["heartbeat_terakhir"],
                "jeda_heartbeat": round(waktu - float(n["heartbeat_terakhir"] or 0), 2),
                "hampir_penuh": (int(n["kapasitas_terpakai"] or 0) / total)
                >= CAPACITY_WARN_RATIO,
            }
        )

    kurang = db.chunk_kurang_replika(REPLICATION_FACTOR)
    return Jawaban.json(
        {
            "waktu": waktu,
            "konfigurasi": {
                "chunk_size_bytes": CHUNK_SIZE,
                "replication_factor": REPLICATION_FACTOR,
                "min_replicas": MIN_REPLICAS,
                "heartbeat_interval_seconds": HEARTBEAT_INTERVAL,
                "node_dead_threshold_seconds": NODE_DEAD_THRESHOLD,
                "replikasi_adaptif": ADAPTIVE,
                "ambang_hampir_penuh": CAPACITY_WARN_RATIO,
            },
            "ringkasan_node": {
                "total": len(node_list),
                "hidup": sum(1 for n in node_list if n["status"] == "hidup"),
                "mati": sum(1 for n in node_list if n["status"] != "hidup"),
            },
            "node": node_list,
            "statistik": db.statistik(),
            "kesehatan_replikasi": {
                "chunk_di_bawah_faktor": len(kurang),
                "chunk_tanpa_replika": sum(1 for c in kurang if c["jumlah_replika"] == 0),
                "contoh": kurang[:10],
            },
            "self_healing": dict(_statistik_heal),
            "peta_replika": db.peta_replika(30),
            "berkas": db.daftar_berkas()[:30],
            "log": db.log_terbaru(40),
        }
    )

# Self-healing dan pengawas node
def pulihkan_chunk(chunk_hash: str) -> bool:
    sumber = db.node_untuk_chunk(chunk_hash)
    if not sumber:
        return False
    terpakai = {n["node_id"] for n in sumber}
    baris = db.satu("SELECT ukuran FROM chunks WHERE chunk_hash=?", (chunk_hash,))
    ukuran_chunk = int(baris["ukuran"]) if baris else 0
    tujuan = pilih_node(
        1, kecualikan=terpakai, urutan_kunci=chunk_hash, ukuran=ukuran_chunk
    )
    if not tujuan:
        return False

    node = tujuan[0]
    status, balasan = json_request(
        f"{node['alamat']}/chunks/{chunk_hash}/tarik",
        metode="POST",
        payload={"sumber_url": sumber[0]["alamat"]},
        timeout=180.0,
    )
    if status in (200, 201):
        db.catat_replika(chunk_hash, node["node_id"], sekarang())
        return True
    pencatat.warn(
        "pemulihan chunk gagal",
        chunk=chunk_hash[:12],
        tujuan=node["node_id"],
        status=status,
        detail=balasan,
    )
    return False

def siklus_self_healing() -> dict:
    if not _kunci_heal.acquire(blocking=False):
        return {"dilewati": True}
    mulai = sekarang()
    dipulihkan = 0
    gagal = 0
    try:
        hidup = db.node_hidup()
        if len(hidup) < 2:
            return {"dilewati": True, "alasan": "node hidup kurang dari 2"}

        kurang = db.chunk_kurang_replika(REPLICATION_FACTOR)[:HEAL_BATCH]
        if not kurang:
            _statistik_heal["siklus"] += 1
            return {"chunk_dipulihkan": 0, "chunk_gagal": 0}

        _statistik_heal["sedang_memulihkan"] = True
        with ThreadPoolExecutor(max_workers=min(PARALEL_IO, 4)) as kolam:
            for berhasil in kolam.map(lambda c: pulihkan_chunk(c["chunk_hash"]), kurang):
                if berhasil:
                    dipulihkan += 1
                else:
                    gagal += 1

        _statistik_heal["siklus"] += 1
        _statistik_heal["chunk_dipulihkan"] += dipulihkan
        _statistik_heal["chunk_gagal"] = gagal
        _statistik_heal["pemulihan_terakhir"] = sekarang()
        _statistik_heal["durasi_terakhir"] = round(sekarang() - mulai, 3)
        if dipulihkan or gagal:
            db.catat(
                "self_healing",
                f"{dipulihkan} chunk dipulihkan, {gagal} gagal,"
                f" {round(sekarang() - mulai, 2)} detik",
            )
            pencatat.info("siklus self-healing", dipulihkan=dipulihkan, gagal=gagal)
        return {
            "chunk_dipulihkan": dipulihkan,
            "chunk_gagal": gagal,
            "durasi": round(sekarang() - mulai, 3),
        }
    finally:
        _statistik_heal["sedang_memulihkan"] = False
        _kunci_heal.release()

@perute.post("/maintenance/heal")
def heal_manual(_req: Permintaan) -> Jawaban:
    return Jawaban.json(siklus_self_healing())

@perute.post("/maintenance/reset")
def reset_metadata(_req: Permintaan) -> Jawaban:
    berkas = db.daftar_berkas()
    for b in berkas:
        yatim = db.hapus_berkas(b["file_id"])
        for chunk_hash in yatim:
            for node in db.node_untuk_chunk(chunk_hash, hanya_hidup=True):
                json_request(
                    f"{node['alamat']}/chunks/{chunk_hash}", metode="DELETE", timeout=20.0
                )
            db.buang_chunk(chunk_hash)
    db.catat("reset_metadata", f"{len(berkas)} berkas dibersihkan")
    return Jawaban.json({"berkas_dibersihkan": len(berkas)})

def pengawas_node() -> None:
    while True:
        waktu = sekarang()
        for node in db.node_hidup():
            jeda = waktu - float(node["heartbeat_terakhir"] or 0)
            if jeda > NODE_DEAD_THRESHOLD:
                db.tandai_mati(node["node_id"])
                db.catat(
                    "node_mati",
                    f"{node['node_id']} tidak mengirim heartbeat {round(jeda, 1)} detik",
                )
                pencatat.warn("node ditandai mati", node=node["node_id"], jeda=round(jeda, 1))
        threading.Event().wait(max(1.0, HEARTBEAT_INTERVAL / 2))

def penjaga_replikasi() -> None:
    while True:
        try:
            siklus_self_healing()
        except Exception as exc:  # noqa: BLE001
            pencatat.error("siklus self-healing galat", detail=str(exc))
        threading.Event().wait(HEAL_INTERVAL)

if __name__ == "__main__":
    pencatat.info(
        "master mulai",
        db=DB_PATH,
        chunk_size_mb=CHUNK_SIZE // (1024 * 1024),
        replication_factor=REPLICATION_FACTOR,
        min_replicas=MIN_REPLICAS,
        adaptif=ADAPTIVE,
    )
    db.catat("master_mulai", f"chunk {CHUNK_SIZE // (1024 * 1024)} MB, RF {REPLICATION_FACTOR}")
    threading.Thread(target=pengawas_node, daemon=True).start()
    threading.Thread(target=penjaga_replikasi, daemon=True).start()
    jalankan(perute, HOST, PORT, pencatat=pencatat)
