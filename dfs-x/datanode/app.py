from __future__ import annotations

import os
import shutil
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from dfsx_core import (  # noqa: E402
    Pencatat,
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

NODE_ID = env_str("NODE_ID", "datanode-1")
PORT = env_int("NODE_PORT", 9101)
HOST = env_str("NODE_HOST", "0.0.0.0")
DATA_DIR = env_str("DATA_DIR", "/data/chunks")
MASTER_URL = env_str("MASTER_URL", "http://master:9100").rstrip("/")
ADVERTISE_URL = env_str("ADVERTISE_URL", f"http://{NODE_ID}:{PORT}").rstrip("/")
HEARTBEAT_INTERVAL = env_float("HEARTBEAT_INTERVAL_SECONDS", 5.0)
# Kapasitas logis per node, dipakai replikasi adaptif menilai kelegaan node.
CAPACITY_BYTES = env_int("NODE_CAPACITY_MB", 4096) * 1024 * 1024

pencatat = Pencatat(NODE_ID)
perute = Perute()
_kunci_tulis = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)

def path_chunk(chunk_hash: str) -> str:
    return os.path.join(DATA_DIR, chunk_hash[:2], chunk_hash)

def ambil_hash(req: Permintaan) -> str:
    chunk_hash = (req.params.get("chunk_hash") or "").lower()
    if not hash_valid(chunk_hash):
        raise GalatPermintaan("chunk_hash harus hex SHA-256 64 karakter")
    return chunk_hash

def pakai_disk() -> tuple[int, int]:
    jumlah = 0
    total = 0
    for akar, _, berkas in os.walk(DATA_DIR):
        for nama in berkas:
            if nama.endswith(".tmp"):
                continue
            try:
                total += os.path.getsize(os.path.join(akar, nama))
                jumlah += 1
            except OSError:
                continue
    return jumlah, total

def tulis_chunk(chunk_hash: str, data: bytes) -> bool:
    hash_asli = sha256_bytes(data)
    if hash_asli != chunk_hash:
        raise GalatPermintaan("Isi chunk tidak cocok dengan chunk_hash")

    tujuan = path_chunk(chunk_hash)
    if os.path.exists(tujuan):
        return False

    os.makedirs(os.path.dirname(tujuan), exist_ok=True)
    sementara = f"{tujuan}.{os.getpid()}.tmp"
    with _kunci_tulis:
        if os.path.exists(tujuan):
            return False
        with open(sementara, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(sementara, tujuan)
    return True

@perute.put("/chunks/{chunk_hash}")
def simpan(req: Permintaan) -> Jawaban:
    chunk_hash = ambil_hash(req)
    if not req.body:
        raise GalatPermintaan("Body chunk kosong")
    baru = tulis_chunk(chunk_hash, req.body)
    return Jawaban.json(
        {
            "node_id": NODE_ID,
            "chunk_hash": chunk_hash,
            "ukuran": len(req.body),
            "baru_ditulis": baru,
        },
        status=201 if baru else 200,
    )

@perute.get("/chunks/{chunk_hash}")
def baca(req: Permintaan) -> Jawaban:
    chunk_hash = ambil_hash(req)
    tujuan = path_chunk(chunk_hash)
    if not os.path.exists(tujuan):
        return Jawaban.json({"error": "Chunk tidak ada di node ini"}, status=404)
    try:
        with open(tujuan, "rb") as f:
            return Jawaban.biner(f.read())
    except OSError as exc:
        pencatat.error("gagal membaca chunk", chunk=chunk_hash, detail=str(exc))
        return Jawaban.json({"error": "Chunk gagal dibaca"}, status=500)

@perute.delete("/chunks/{chunk_hash}")
def hapus(req: Permintaan) -> Jawaban:
    chunk_hash = ambil_hash(req)
    tujuan = path_chunk(chunk_hash)
    if not os.path.exists(tujuan):
        return Jawaban.json({"error": "Chunk tidak ada di node ini"}, status=404)
    try:
        os.remove(tujuan)
    except OSError as exc:
        pencatat.error("gagal menghapus chunk", chunk=chunk_hash, detail=str(exc))
        return Jawaban.json({"error": "Chunk gagal dihapus"}, status=500)
    return Jawaban.json({"node_id": NODE_ID, "chunk_hash": chunk_hash, "dihapus": True})

@perute.post("/chunks/{chunk_hash}/tarik")
def tarik(req: Permintaan) -> Jawaban:
    chunk_hash = ambil_hash(req)
    data = req.json()
    sumber = str(data.get("sumber_url") or "").rstrip("/")
    if not sumber.startswith("http://"):
        raise GalatPermintaan("sumber_url wajib berupa URL http internal")

    if os.path.exists(path_chunk(chunk_hash)):
        return Jawaban.json({"chunk_hash": chunk_hash, "sudah_ada": True})

    from dfsx_core import binary_request  # impor lokal agar modul tetap ringan

    status, isi = binary_request(f"{sumber}/chunks/{chunk_hash}", timeout=120.0)
    if status != 200:
        return Jawaban.json(
            {"error": "Gagal menarik chunk dari sumber", "status_sumber": status},
            status=502,
        )
    baru = tulis_chunk(chunk_hash, isi)
    pencatat.info("chunk dipulihkan", chunk=chunk_hash, sumber=sumber, baru=baru)
    return Jawaban.json(
        {"chunk_hash": chunk_hash, "ukuran": len(isi), "baru_ditulis": baru},
        status=201,
    )

@perute.get("/health")
def health(_req: Permintaan) -> Jawaban:
    jumlah, terpakai = pakai_disk()
    bebas_host = None
    try:
        bebas_host = shutil.disk_usage(DATA_DIR).free
    except OSError:
        pass
    return Jawaban.json(
        {
            "node_id": NODE_ID,
            "status": "hidup",
            "alamat": ADVERTISE_URL,
            "jumlah_chunk": jumlah,
            "kapasitas_total": CAPACITY_BYTES,
            "kapasitas_terpakai": terpakai,
            "kapasitas_bebas_host": bebas_host,
            "waktu": sekarang(),
        }
    )

@perute.get("/chunks")
def daftar(_req: Permintaan) -> Jawaban:
    daftar_hash: list[str] = []
    for akar, _, berkas in os.walk(DATA_DIR):
        for nama in berkas:
            if not nama.endswith(".tmp"):
                daftar_hash.append(nama)
    return Jawaban.json({"node_id": NODE_ID, "jumlah": len(daftar_hash), "chunks": daftar_hash})

def kirim_heartbeat() -> None:
    while True:
        jumlah, terpakai = pakai_disk()
        status, _ = json_request(
            f"{MASTER_URL}/nodes/heartbeat",
            metode="POST",
            payload={
                "node_id": NODE_ID,
                "alamat": ADVERTISE_URL,
                "kapasitas_total": CAPACITY_BYTES,
                "kapasitas_terpakai": terpakai,
                "jumlah_chunk": jumlah,
                "status_kesehatan": "sehat" if terpakai < CAPACITY_BYTES else "penuh",
            },
            timeout=max(3.0, HEARTBEAT_INTERVAL),
        )
        if status == 0:
            pencatat.warn("heartbeat gagal, master belum siap")
        threading.Event().wait(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    pencatat.info(
        "data node mulai",
        data_dir=DATA_DIR,
        master=MASTER_URL,
        kapasitas_mb=CAPACITY_BYTES // (1024 * 1024),
    )
    threading.Thread(target=kirim_heartbeat, daemon=True).start()
    jalankan(perute, HOST, PORT, pencatat=pencatat)
