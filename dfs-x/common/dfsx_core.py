from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

CHUNK_READ_SIZE = 1024 * 1024

def env_str(nama: str, bawaan: str) -> str:
    nilai = os.environ.get(nama)
    if nilai is None or nilai.strip() == "":
        return bawaan
    return nilai.strip()

def env_int(nama: str, bawaan: int) -> int:
    try:
        return int(float(env_str(nama, str(bawaan))))
    except (TypeError, ValueError):
        return bawaan

def env_float(nama: str, bawaan: float) -> float:
    try:
        return float(env_str(nama, str(bawaan)))
    except (TypeError, ValueError):
        return bawaan

def env_bool(nama: str, bawaan: bool = False) -> bool:
    nilai = env_str(nama, "1" if bawaan else "0").lower()
    return nilai in ("1", "true", "yes", "on")

def sekarang() -> float:
    return time.time()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            blok = f.read(CHUNK_READ_SIZE)
            if not blok:
                break
            h.update(blok)
    return h.hexdigest()

def hash_valid(nilai: object) -> bool:
    if not isinstance(nilai, str) or len(nilai) != 64:
        return False
    return all(c in "0123456789abcdef" for c in nilai.lower())

def json_request(
    url: str,
    metode: str = "GET",
    payload: object = None,
    timeout: float = 15.0,
) -> tuple[int, object]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=metode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            mentah = resp.read()
            try:
                return resp.status, json.loads(mentah.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return resp.status, {"raw": mentah[:200].decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        mentah = exc.read()
        try:
            return exc.code, json.loads(mentah.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, {"error": mentah[:200].decode("utf-8", "replace")}
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return 0, {"error": str(exc)}

def binary_request(
    url: str,
    metode: str = "GET",
    body: bytes | None = None,
    timeout: float = 60.0,
) -> tuple[int, bytes]:
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
        headers["Content-Length"] = str(len(body))
    req = urllib.request.Request(url, data=body, headers=headers, method=metode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:500]
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return 0, str(exc).encode("utf-8")

class Pencatat:
    def __init__(self, nama: str) -> None:
        self.nama = nama
        self._kunci = threading.Lock()

    def info(self, pesan: str, **detail: object) -> None:
        self._tulis("INFO", pesan, detail)

    def warn(self, pesan: str, **detail: object) -> None:
        self._tulis("WARN", pesan, detail)

    def error(self, pesan: str, **detail: object) -> None:
        self._tulis("ERROR", pesan, detail)

    def _tulis(self, taraf: str, pesan: str, detail: dict) -> None:
        waktu = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        tambahan = ""
        if detail:
            tambahan = " " + json.dumps(detail, ensure_ascii=False, default=str)
        with self._kunci:
            print(f"{waktu} [{taraf}] [{self.nama}] {pesan}{tambahan}", flush=True)
