// Adapter penyimpanan Drovio ke DFS-X. Hanya berbicara HTTP ke master node.

import fs from 'fs';
import path from 'path';

import { namaDfsxAman } from './dfsx-core.mjs';

export interface DfsxConfig {
  enabled: boolean;
  masterUrl: string;
  // Hapus berkas lokal setelah berhasil disimpan ke DFS-X.
  pruneLocal: boolean;
  timeoutMs: number;
}

export interface DfsxSimpanHasil {
  fileId: string;
  nama: string;
  versi: number;
  ukuran: number;
  hashBerkas: string;
  jumlahChunk: number;
  chunkDideduplikasi: number;
  byteDideduplikasi: number;
}

export interface DfsxVersi {
  versi: number;
  hash_berkas: string;
  ukuran: number;
  jumlah_chunk: number;
  dibuat_pada: number;
}

export interface DfsxBerkas {
  file_id: string;
  nama: string;
  versi_aktif: number;
  ukuran: number | null;
  hash_berkas: string | null;
  jumlah_chunk: number | null;
  jumlah_versi: number;
  dibuat_pada: number;
  diperbarui_pada: number;
}

let cachedConfig: DfsxConfig | null = null;

export function getDfsxConfig(): DfsxConfig {
  if (cachedConfig) return cachedConfig;
  const masterUrl = (process.env.DFSX_MASTER_URL || 'http://127.0.0.1:9100').replace(/\/+$/, '');
  cachedConfig = {
    // Dapat dinonaktifkan agar Drovio tetap jalan tanpa DFS-X.
    enabled: process.env.DFSX_ENABLED !== 'false' && process.env.DFSX_ENABLED !== '0',
    masterUrl,
    pruneLocal: process.env.DFSX_PRUNE_LOCAL === 'true' || process.env.DFSX_PRUNE_LOCAL === '1',
    timeoutMs: Math.max(5000, parseInt(process.env.DFSX_TIMEOUT_MS || '600000', 10) || 600000),
  };
  return cachedConfig;
}

export class DfsxError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = 'DfsxError';
    this.status = status;
  }
}

async function fetchDfsx(
  jalur: string,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const config = getDfsxConfig();
  const { timeoutMs, ...rest } = init;
  const kendali = new AbortController();
  const batas = setTimeout(() => kendali.abort(), timeoutMs || config.timeoutMs);
  try {
    return await fetch(`${config.masterUrl}${jalur}`, {
      ...rest,
      signal: kendali.signal,
      cache: 'no-store',
    });
  } catch (err) {
    const error = err as Error;
    if (error.name === 'AbortError') {
      throw new DfsxError('Permintaan ke DFS-X melebihi batas waktu.');
    }
    throw new DfsxError(`DFS-X tidak dapat dihubungi: ${error.message}`);
  } finally {
    clearTimeout(batas);
  }
}

async function bacaGalat(resp: Response, bawaan: string): Promise<string> {
  try {
    const data = (await resp.json()) as { error?: string };
    return data.error || bawaan;
  } catch {
    return bawaan;
  }
}

// Nama berkas DFS-X harus datar, tanpa pemisah path.
export { namaDfsxAman } from './dfsx-core.mjs';

// Nama yang sudah ada menjadi versi berikutnya, bukan menimpa versi lama.
export async function simpanKeDfsx(
  filePath: string,
  namaBerkas?: string
): Promise<DfsxSimpanHasil> {
  if (!fs.existsSync(filePath)) {
    throw new DfsxError('Berkas lokal tidak ditemukan untuk disimpan ke DFS-X.', 404);
  }
  const nama = namaDfsxAman(namaBerkas || path.basename(filePath));
  const isi = await fs.promises.readFile(filePath);

  const resp = await fetchDfsx(`/files/content?nama=${encodeURIComponent(nama)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: new Uint8Array(isi),
  });

  if (!resp.ok) {
    throw new DfsxError(
      await bacaGalat(resp, 'DFS-X menolak menyimpan berkas hasil.'),
      resp.status
    );
  }

  const data = (await resp.json()) as Record<string, unknown>;
  return {
    fileId: String(data.file_id),
    nama: String(data.nama),
    versi: Number(data.versi),
    ukuran: Number(data.ukuran),
    hashBerkas: String(data.hash_berkas),
    jumlahChunk: Number(data.jumlah_chunk),
    chunkDideduplikasi: Number(data.chunk_dideduplikasi || 0),
    byteDideduplikasi: Number(data.byte_dideduplikasi || 0),
  };
}

// Tanpa nomor versi, yang diambil adalah versi aktif.
export async function ambilDariDfsx(
  fileId: string,
  versi?: number
): Promise<{ isi: Buffer; versi: number; hash: string }> {
  const kueri = versi ? `?version=${encodeURIComponent(String(versi))}` : '';
  const resp = await fetchDfsx(`/files/${encodeURIComponent(fileId)}/content${kueri}`);
  if (!resp.ok) {
    throw new DfsxError(
      await bacaGalat(resp, 'Berkas tidak dapat diambil dari DFS-X.'),
      resp.status
    );
  }
  const buffer = Buffer.from(await resp.arrayBuffer());
  return {
    isi: buffer,
    versi: Number(resp.headers.get('X-DFSX-Versi') || versi || 0),
    hash: resp.headers.get('X-DFSX-Hash') || '',
  };
}

export async function metadataDfsx(fileId: string, versi?: number): Promise<Record<string, unknown>> {
  const kueri = versi ? `?version=${encodeURIComponent(String(versi))}` : '';
  const resp = await fetchDfsx(`/files/${encodeURIComponent(fileId)}${kueri}`);
  if (!resp.ok) {
    throw new DfsxError(await bacaGalat(resp, 'Metadata berkas tidak ditemukan.'), resp.status);
  }
  return (await resp.json()) as Record<string, unknown>;
}

export async function daftarVersiDfsx(fileId: string): Promise<{
  file_id: string;
  nama: string;
  versi_aktif: number;
  versi: DfsxVersi[];
}> {
  const resp = await fetchDfsx(`/files/${encodeURIComponent(fileId)}/versions`);
  if (!resp.ok) {
    throw new DfsxError(await bacaGalat(resp, 'Daftar versi tidak tersedia.'), resp.status);
  }
  return (await resp.json()) as {
    file_id: string;
    nama: string;
    versi_aktif: number;
    versi: DfsxVersi[];
  };
}

export async function rollbackDfsx(fileId: string, versi: number): Promise<Record<string, unknown>> {
  const resp = await fetchDfsx(`/files/${encodeURIComponent(fileId)}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ versi }),
  });
  if (!resp.ok) {
    throw new DfsxError(await bacaGalat(resp, 'Rollback versi gagal.'), resp.status);
  }
  return (await resp.json()) as Record<string, unknown>;
}

export async function daftarBerkasDfsx(): Promise<DfsxBerkas[]> {
  const resp = await fetchDfsx('/files', { timeoutMs: 15000 });
  if (!resp.ok) {
    throw new DfsxError(await bacaGalat(resp, 'Daftar berkas DFS-X tidak tersedia.'), resp.status);
  }
  const data = (await resp.json()) as { berkas?: DfsxBerkas[] };
  return data.berkas || [];
}

export async function statusDfsx(): Promise<Record<string, unknown>> {
  const resp = await fetchDfsx('/status', { timeoutMs: 15000 });
  if (!resp.ok) {
    throw new DfsxError(await bacaGalat(resp, 'Status DFS-X tidak tersedia.'), resp.status);
  }
  return (await resp.json()) as Record<string, unknown>;
}

export async function hapusDariDfsx(fileId: string): Promise<void> {
  const resp = await fetchDfsx(`/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
  if (!resp.ok && resp.status !== 404) {
    throw new DfsxError(await bacaGalat(resp, 'Berkas gagal dihapus dari DFS-X.'), resp.status);
  }
}

export async function dfsxSiap(): Promise<boolean> {
  const config = getDfsxConfig();
  if (!config.enabled) return false;
  try {
    const resp = await fetchDfsx('/health', { timeoutMs: 4000 });
    if (!resp.ok) return false;
    const data = (await resp.json()) as { node_hidup?: number; min_replicas?: number };
    return (data.node_hidup || 0) >= (data.min_replicas || 1);
  } catch {
    return false;
  }
}
