from __future__ import annotations

import os
import sqlite3
import threading
import uuid

SKEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_id        TEXT PRIMARY KEY,
    nama           TEXT NOT NULL UNIQUE,
    versi_aktif    INTEGER NOT NULL DEFAULT 0,
    dibuat_pada    REAL NOT NULL,
    diperbarui_pada REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS file_versions (
    file_id       TEXT NOT NULL,
    versi         INTEGER NOT NULL,
    hash_berkas   TEXT NOT NULL,
    ukuran        INTEGER NOT NULL,
    jumlah_chunk  INTEGER NOT NULL,
    dibuat_pada   REAL NOT NULL,
    PRIMARY KEY (file_id, versi),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_hash       TEXT PRIMARY KEY,
    ukuran           INTEGER NOT NULL,
    jumlah_referensi INTEGER NOT NULL DEFAULT 0,
    dibuat_pada      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS file_chunks (
    file_id    TEXT NOT NULL,
    versi      INTEGER NOT NULL,
    urutan     INTEGER NOT NULL,
    chunk_hash TEXT NOT NULL,
    PRIMARY KEY (file_id, versi, urutan)
);

CREATE TABLE IF NOT EXISTS replicas (
    chunk_hash      TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'aktif',
    diperbarui_pada REAL NOT NULL,
    PRIMARY KEY (chunk_hash, node_id)
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id            TEXT PRIMARY KEY,
    alamat             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'hidup',
    kapasitas_total    INTEGER NOT NULL DEFAULT 0,
    kapasitas_terpakai INTEGER NOT NULL DEFAULT 0,
    jumlah_chunk       INTEGER NOT NULL DEFAULT 0,
    status_kesehatan   TEXT NOT NULL DEFAULT 'sehat',
    heartbeat_terakhir REAL NOT NULL DEFAULT 0,
    pertama_terlihat   REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu          REAL NOT NULL,
    jenis_kejadian TEXT NOT NULL,
    detail         TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_file_chunks_hash ON file_chunks(chunk_hash);
CREATE INDEX IF NOT EXISTS idx_replicas_node ON replicas(node_id);
CREATE INDEX IF NOT EXISTS idx_log_waktu ON activity_log(waktu DESC);
"""

MAKS_LOG = 500

class Metadata:
    def __init__(self, path_db: str) -> None:
        direktori = os.path.dirname(os.path.abspath(path_db))
        if direktori:
            os.makedirs(direktori, exist_ok=True)
        self.path_db = path_db
        self._kunci = threading.RLock()
        self._koneksi = sqlite3.connect(path_db, check_same_thread=False)
        self._koneksi.row_factory = sqlite3.Row
        with self._kunci:
            self._koneksi.execute("PRAGMA journal_mode=WAL")
            self._koneksi.execute("PRAGMA synchronous=NORMAL")
            self._koneksi.execute("PRAGMA foreign_keys=ON")
            self._koneksi.executescript(SKEMA)
            self._koneksi.commit()

    # Dasar
    def eksekusi(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._kunci:
            kursor = self._koneksi.execute(sql, params)
            self._koneksi.commit()
            return kursor

    def satu(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._kunci:
            return self._koneksi.execute(sql, params).fetchone()

    def banyak(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._kunci:
            return self._koneksi.execute(sql, params).fetchall()

    def catat(self, jenis: str, detail: str = "") -> None:
        with self._kunci:
            self._koneksi.execute(
                "INSERT INTO activity_log (waktu, jenis_kejadian, detail) VALUES (?,?,?)",
                (__import__("time").time(), jenis, detail),
            )
            self._koneksi.execute(
                "DELETE FROM activity_log WHERE id NOT IN "
                "(SELECT id FROM activity_log ORDER BY id DESC LIMIT ?)",
                (MAKS_LOG,),
            )
            self._koneksi.commit()

    def log_terbaru(self, batas: int = 50) -> list[dict]:
        baris = self.banyak(
            "SELECT waktu, jenis_kejadian, detail FROM activity_log ORDER BY id DESC LIMIT ?",
            (batas,),
        )
        return [dict(b) for b in baris]

    # Node
    def catat_heartbeat(
        self,
        node_id: str,
        alamat: str,
        kapasitas_total: int,
        kapasitas_terpakai: int,
        jumlah_chunk: int,
        status_kesehatan: str,
        waktu: float,
    ) -> bool:
        with self._kunci:
            lama = self._koneksi.execute(
                "SELECT status FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            baru_atau_pulih = lama is None or lama["status"] != "hidup"
            self._koneksi.execute(
                """
                INSERT INTO nodes (node_id, alamat, status, kapasitas_total,
                                   kapasitas_terpakai, jumlah_chunk, status_kesehatan,
                                   heartbeat_terakhir, pertama_terlihat)
                VALUES (?,?,'hidup',?,?,?,?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET
                    alamat=excluded.alamat,
                    status='hidup',
                    kapasitas_total=excluded.kapasitas_total,
                    kapasitas_terpakai=excluded.kapasitas_terpakai,
                    jumlah_chunk=excluded.jumlah_chunk,
                    status_kesehatan=excluded.status_kesehatan,
                    heartbeat_terakhir=excluded.heartbeat_terakhir
                """,
                (
                    node_id,
                    alamat,
                    kapasitas_total,
                    kapasitas_terpakai,
                    jumlah_chunk,
                    status_kesehatan,
                    waktu,
                    waktu,
                ),
            )
            self._koneksi.commit()
        return baru_atau_pulih

    def node_hidup(self) -> list[dict]:
        return [dict(b) for b in self.banyak("SELECT * FROM nodes WHERE status='hidup'")]

    def semua_node(self) -> list[dict]:
        return [dict(b) for b in self.banyak("SELECT * FROM nodes ORDER BY node_id")]

    def tandai_mati(self, node_id: str) -> None:
        self.eksekusi("UPDATE nodes SET status='mati' WHERE node_id=?", (node_id,))
        self.eksekusi(
            "UPDATE replicas SET status='hilang', diperbarui_pada=? WHERE node_id=?",
            (__import__("time").time(), node_id),
        )

    def tandai_hidup_kembali(self, node_id: str) -> None:
        self.eksekusi(
            "UPDATE replicas SET status='aktif', diperbarui_pada=? WHERE node_id=?",
            (__import__("time").time(), node_id),
        )

    # Berkas dan versi
    def file_dari_nama(self, nama: str) -> dict | None:
        baris = self.satu("SELECT * FROM files WHERE nama=?", (nama,))
        return dict(baris) if baris else None

    def file_dari_id(self, file_id: str) -> dict | None:
        baris = self.satu("SELECT * FROM files WHERE file_id=?", (file_id,))
        return dict(baris) if baris else None

    def siapkan_versi(self, nama: str, waktu: float) -> tuple[str, int]:
        with self._kunci:
            baris = self._koneksi.execute(
                "SELECT file_id FROM files WHERE nama=?", (nama,)
            ).fetchone()
            if baris is None:
                file_id = uuid.uuid4().hex[:16]
                self._koneksi.execute(
                    "INSERT INTO files (file_id, nama, versi_aktif, dibuat_pada, diperbarui_pada)"
                    " VALUES (?,?,0,?,?)",
                    (file_id, nama, waktu, waktu),
                )
            else:
                file_id = baris["file_id"]
            tertinggi = self._koneksi.execute(
                "SELECT COALESCE(MAX(versi), 0) AS v FROM file_versions WHERE file_id=?",
                (file_id,),
            ).fetchone()["v"]
            self._koneksi.commit()
            return file_id, int(tertinggi) + 1

    def simpan_versi(
        self,
        file_id: str,
        versi: int,
        hash_berkas: str,
        ukuran: int,
        daftar_chunk: list[tuple[int, str, int]],
        waktu: float,
    ) -> None:
        with self._kunci:
            self._koneksi.execute(
                "INSERT OR REPLACE INTO file_versions"
                " (file_id, versi, hash_berkas, ukuran, jumlah_chunk, dibuat_pada)"
                " VALUES (?,?,?,?,?,?)",
                (file_id, versi, hash_berkas, ukuran, len(daftar_chunk), waktu),
            )
            self._koneksi.execute(
                "DELETE FROM file_chunks WHERE file_id=? AND versi=?", (file_id, versi)
            )
            for urutan, chunk_hash, ukuran_chunk in daftar_chunk:
                self._koneksi.execute(
                    "INSERT INTO chunks (chunk_hash, ukuran, jumlah_referensi, dibuat_pada)"
                    " VALUES (?,?,0,?)"
                    " ON CONFLICT(chunk_hash) DO NOTHING",
                    (chunk_hash, ukuran_chunk, waktu),
                )
                self._koneksi.execute(
                    "INSERT INTO file_chunks (file_id, versi, urutan, chunk_hash)"
                    " VALUES (?,?,?,?)",
                    (file_id, versi, urutan, chunk_hash),
                )
                self._koneksi.execute(
                    "UPDATE chunks SET jumlah_referensi=jumlah_referensi+1 WHERE chunk_hash=?",
                    (chunk_hash,),
                )
            self._koneksi.execute(
                "UPDATE files SET versi_aktif=?, diperbarui_pada=? WHERE file_id=?",
                (versi, waktu, file_id),
            )
            self._koneksi.commit()

    def daftar_versi(self, file_id: str) -> list[dict]:
        return [
            dict(b)
            for b in self.banyak(
                "SELECT versi, hash_berkas, ukuran, jumlah_chunk, dibuat_pada"
                " FROM file_versions WHERE file_id=? ORDER BY versi",
                (file_id,),
            )
        ]

    def versi_tertentu(self, file_id: str, versi: int) -> dict | None:
        baris = self.satu(
            "SELECT * FROM file_versions WHERE file_id=? AND versi=?", (file_id, versi)
        )
        return dict(baris) if baris else None

    def chunk_versi(self, file_id: str, versi: int) -> list[dict]:
        return [
            dict(b)
            for b in self.banyak(
                "SELECT fc.urutan, fc.chunk_hash, c.ukuran FROM file_chunks fc"
                " JOIN chunks c ON c.chunk_hash = fc.chunk_hash"
                " WHERE fc.file_id=? AND fc.versi=? ORDER BY fc.urutan",
                (file_id, versi),
            )
        ]

    def set_versi_aktif(self, file_id: str, versi: int, waktu: float) -> None:
        self.eksekusi(
            "UPDATE files SET versi_aktif=?, diperbarui_pada=? WHERE file_id=?",
            (versi, waktu, file_id),
        )

    def daftar_berkas(self) -> list[dict]:
        return [
            dict(b)
            for b in self.banyak(
                """
                SELECT f.file_id, f.nama, f.versi_aktif, f.dibuat_pada, f.diperbarui_pada,
                       v.ukuran, v.hash_berkas, v.jumlah_chunk,
                       (SELECT COUNT(*) FROM file_versions x WHERE x.file_id=f.file_id)
                           AS jumlah_versi
                FROM files f
                LEFT JOIN file_versions v
                       ON v.file_id = f.file_id AND v.versi = f.versi_aktif
                ORDER BY f.diperbarui_pada DESC
                """
            )
        ]

    def hapus_berkas(self, file_id: str) -> list[str]:
        with self._kunci:
            baris = self._koneksi.execute(
                "SELECT chunk_hash FROM file_chunks WHERE file_id=?", (file_id,)
            ).fetchall()
            for b in baris:
                self._koneksi.execute(
                    "UPDATE chunks SET jumlah_referensi=MAX(jumlah_referensi-1,0)"
                    " WHERE chunk_hash=?",
                    (b["chunk_hash"],),
                )
            self._koneksi.execute("DELETE FROM file_chunks WHERE file_id=?", (file_id,))
            self._koneksi.execute("DELETE FROM file_versions WHERE file_id=?", (file_id,))
            self._koneksi.execute("DELETE FROM files WHERE file_id=?", (file_id,))
            yatim = self._koneksi.execute(
                "SELECT chunk_hash FROM chunks WHERE jumlah_referensi<=0"
            ).fetchall()
            self._koneksi.commit()
            return [b["chunk_hash"] for b in yatim]

    def buang_chunk(self, chunk_hash: str) -> None:
        self.eksekusi("DELETE FROM replicas WHERE chunk_hash=?", (chunk_hash,))
        self.eksekusi("DELETE FROM chunks WHERE chunk_hash=?", (chunk_hash,))

    # Chunk dan replika
    def chunk_ada(self, chunk_hash: str) -> bool:
        return self.satu("SELECT 1 FROM chunks WHERE chunk_hash=?", (chunk_hash,)) is not None

    def chunk_siap_pakai(self, chunk_hash: str) -> bool:
        baris = self.satu(
            "SELECT COUNT(*) AS n FROM replicas r JOIN nodes n ON n.node_id=r.node_id"
            " WHERE r.chunk_hash=? AND r.status='aktif' AND n.status='hidup'",
            (chunk_hash,),
        )
        return bool(baris and baris["n"] > 0)

    def catat_replika(self, chunk_hash: str, node_id: str, waktu: float) -> None:
        self.eksekusi(
            "INSERT INTO replicas (chunk_hash, node_id, status, diperbarui_pada)"
            " VALUES (?,?,'aktif',?)"
            " ON CONFLICT(chunk_hash, node_id) DO UPDATE SET status='aktif',"
            " diperbarui_pada=excluded.diperbarui_pada",
            (chunk_hash, node_id, waktu),
        )

    def hapus_replika(self, chunk_hash: str, node_id: str) -> None:
        self.eksekusi(
            "DELETE FROM replicas WHERE chunk_hash=? AND node_id=?", (chunk_hash, node_id)
        )

    def node_untuk_chunk(self, chunk_hash: str, hanya_hidup: bool = True) -> list[dict]:
        sql = (
            "SELECT n.node_id, n.alamat, n.status, n.heartbeat_terakhir,"
            " r.status AS status_replika"
            " FROM replicas r JOIN nodes n ON n.node_id = r.node_id"
            " WHERE r.chunk_hash=?"
        )
        if hanya_hidup:
            sql += " AND n.status='hidup' AND r.status='aktif'"
        sql += " ORDER BY n.heartbeat_terakhir DESC"
        return [dict(b) for b in self.banyak(sql, (chunk_hash,))]

    def chunk_kurang_replika(self, faktor: int) -> list[dict]:
        return [
            dict(b)
            for b in self.banyak(
                """
                SELECT c.chunk_hash, c.ukuran, COUNT(r.node_id) AS jumlah_replika
                FROM chunks c
                LEFT JOIN replicas r
                       ON r.chunk_hash = c.chunk_hash AND r.status='aktif'
                      AND r.node_id IN (SELECT node_id FROM nodes WHERE status='hidup')
                WHERE c.jumlah_referensi > 0
                GROUP BY c.chunk_hash
                HAVING jumlah_replika < ?
                ORDER BY jumlah_replika ASC, c.ukuran DESC
                """,
                (faktor,),
            )
        ]

    def peta_replika(self, batas: int = 50) -> list[dict]:
        return [
            dict(b)
            for b in self.banyak(
                """
                SELECT c.chunk_hash, c.ukuran, c.jumlah_referensi,
                       GROUP_CONCAT(r.node_id) AS node_list,
                       COUNT(r.node_id) AS jumlah_replika
                FROM chunks c
                LEFT JOIN replicas r
                       ON r.chunk_hash = c.chunk_hash AND r.status='aktif'
                GROUP BY c.chunk_hash
                ORDER BY c.dibuat_pada DESC
                LIMIT ?
                """,
                (batas,),
            )
        ]

    # Statistik
    def _angka(self, sql: str, kolom: str = "n", params: tuple = ()) -> int:
        baris = self.satu(sql, params)
        if baris is None:
            return 0
        return int(baris[kolom] or 0)

    def statistik(self) -> dict:
        logis = self._angka("SELECT COALESCE(SUM(ukuran),0) AS n FROM file_versions")
        unik_byte = self._angka(
            "SELECT COALESCE(SUM(ukuran),0) AS n FROM chunks WHERE jumlah_referensi > 0"
        )
        unik_jumlah = self._angka(
            "SELECT COUNT(*) AS n FROM chunks WHERE jumlah_referensi > 0"
        )
        referensi = self._angka(
            "SELECT COALESCE(SUM(c.ukuran),0) AS n FROM file_chunks fc"
            " JOIN chunks c ON c.chunk_hash = fc.chunk_hash"
        )
        fisik_replika = self._angka(
            "SELECT COALESCE(SUM(c.ukuran),0) AS n FROM replicas r"
            " JOIN chunks c ON c.chunk_hash = r.chunk_hash WHERE r.status='aktif'"
        )
        return {
            "jumlah_berkas": self._angka("SELECT COUNT(*) AS n FROM files"),
            "jumlah_versi": self._angka("SELECT COUNT(*) AS n FROM file_versions"),
            "jumlah_chunk_unik": unik_jumlah,
            "ukuran_logis": logis,
            "ukuran_chunk_direferensikan": referensi,
            "ukuran_fisik_unik": unik_byte,
            "ukuran_fisik_dengan_replika": fisik_replika,
            "hemat_deduplikasi": max(referensi - unik_byte, 0),
            "rasio_deduplikasi": (
                round(referensi / unik_byte, 4) if unik_byte > 0 else 1.0
            ),
        }

    def tutup(self) -> None:
        with self._kunci:
            self._koneksi.close()
