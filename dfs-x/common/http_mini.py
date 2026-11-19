from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

MAX_BODY_BYTES = 256 * 1024 * 1024

class Permintaan:
    def __init__(
        self,
        metode: str,
        path: str,
        params: dict[str, str],
        query: dict[str, str],
        body: bytes,
    ) -> None:
        self.metode = metode
        self.path = path
        self.params = params
        self.query = query
        self.body = body

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GalatPermintaan(f"Body JSON tidak valid: {exc}") from exc
        if not isinstance(data, dict):
            raise GalatPermintaan("Body JSON harus berupa objek")
        return data

class GalatPermintaan(Exception):
    def __init__(self, pesan: str, status: int = 400) -> None:
        super().__init__(pesan)
        self.pesan = pesan
        self.status = status

class Jawaban:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        tipe: str = "application/json",
        header: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.tipe = tipe
        self.header = header or {}

    @staticmethod
    def json(data: object, status: int = 200) -> "Jawaban":
        mentah = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        return Jawaban(status=status, body=mentah, tipe="application/json")

    @staticmethod
    def biner(data: bytes, status: int = 200) -> "Jawaban":
        return Jawaban(status=status, body=data, tipe="application/octet-stream")

    @staticmethod
    def teks(data: str, status: int = 200, tipe: str = "text/plain; charset=utf-8") -> "Jawaban":
        return Jawaban(status=status, body=data.encode("utf-8"), tipe=tipe)

Penangan = Callable[[Permintaan], Jawaban]

class Perute:
    def __init__(self) -> None:
        self._rute: list[tuple[str, re.Pattern[str], Penangan]] = []

    def tambah(self, metode: str, pola: str, penangan: Penangan) -> None:
        regex = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"(?P<\1>[^/]+)", pola)
        self._rute.append((metode.upper(), re.compile(f"^{regex}$"), penangan))

    def get(self, pola: str):
        def bungkus(fn: Penangan) -> Penangan:
            self.tambah("GET", pola, fn)
            return fn

        return bungkus

    def post(self, pola: str):
        def bungkus(fn: Penangan) -> Penangan:
            self.tambah("POST", pola, fn)
            return fn

        return bungkus

    def put(self, pola: str):
        def bungkus(fn: Penangan) -> Penangan:
            self.tambah("PUT", pola, fn)
            return fn

        return bungkus

    def delete(self, pola: str):
        def bungkus(fn: Penangan) -> Penangan:
            self.tambah("DELETE", pola, fn)
            return fn

        return bungkus

    def cari(self, metode: str, path: str) -> tuple[Penangan | None, dict[str, str], bool]:
        path_dikenal = False
        for m, regex, penangan in self._rute:
            cocok = regex.match(path)
            if cocok:
                path_dikenal = True
                if m == metode.upper():
                    return penangan, cocok.groupdict(), True
        return None, {}, path_dikenal

class _Penangan(BaseHTTPRequestHandler):
    server_version = "DFSX/1.0"
    protocol_version = "HTTP/1.1"
    perute: Perute = Perute()
    pencatat = None
    diam_log = True

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if not self.diam_log and self.pencatat is not None:
            self.pencatat.info("http", pesan=format % args)

    def _tangani(self, metode: str) -> None:
        path, _, query_mentah = self.path.partition("?")
        query: dict[str, str] = {}
        for bagian in query_mentah.split("&"):
            if not bagian:
                continue
            kunci, _, nilai = bagian.partition("=")
            query[kunci] = nilai

        penangan, params, path_dikenal = self.perute.cari(metode, path)
        if penangan is None:
            status = 405 if path_dikenal else 404
            pesan = "Metode tidak didukung" if path_dikenal else "Endpoint tidak ditemukan"
            self._kirim(Jawaban.json({"error": pesan, "path": path}, status=status))
            return

        try:
            panjang = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            panjang = 0
        if panjang > MAX_BODY_BYTES:
            self._kirim(Jawaban.json({"error": "Body terlalu besar"}, status=413))
            return
        body = self.rfile.read(panjang) if panjang > 0 else b""

        permintaan = Permintaan(metode, path, params, query, body)
        try:
            jawaban = penangan(permintaan)
        except GalatPermintaan as exc:
            jawaban = Jawaban.json({"error": exc.pesan}, status=exc.status)
        except Exception as exc:  # noqa: BLE001
            if self.pencatat is not None:
                self.pencatat.error("galat penangan", path=path, detail=str(exc))
            jawaban = Jawaban.json({"error": "Galat internal layanan"}, status=500)
        self._kirim(jawaban)

    def _kirim(self, jawaban: Jawaban) -> None:
        try:
            self.send_response(jawaban.status)
            self.send_header("Content-Type", jawaban.tipe)
            self.send_header("Content-Length", str(len(jawaban.body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            for kunci, nilai in jawaban.header.items():
                self.send_header(kunci, nilai)
            self.end_headers()
            if jawaban.body:
                self.wfile.write(jawaban.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._tangani("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._tangani("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._tangani("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._tangani("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._kirim(
            Jawaban(
                status=204,
                header={
                    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )
        )

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def jalankan(
    perute: Perute,
    host: str,
    port: int,
    pencatat=None,
    diam_log: bool = True,
) -> None:
    kelas = type(
        "PenangananRute",
        (_Penangan,),
        {"perute": perute, "pencatat": pencatat, "diam_log": diam_log},
    )
    server = Server((host, port), kelas)
    if pencatat is not None:
        pencatat.info("layanan siap", host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        if pencatat is not None:
            pencatat.info("layanan dihentikan")
        server.shutdown()
