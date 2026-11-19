// Pemetaan hasil Drovio ke berkas DFS-X, disimpan di disk karena route
// Next.js berbeda berjalan di bundle terpisah saat produksi.

import fs from 'fs';
import path from 'path';

export type DfsxSumber = 'download' | 'convert' | 'compress';

export interface DfsxCatatan {
  // Id pekerjaan di sisi Drovio (job_..., cnv_..., cmp_...).
  localId: string;
  sumber: DfsxSumber;
  fileId: string;
  nama: string;
  versi: number;
  ukuran: number;
  hashBerkas: string;
  jumlahChunk: number;
  chunkDideduplikasi: number;
  mimeType?: string;
  disimpanPada: number;
}

interface Simpanan {
  versiSkema: 1;
  catatan: Record<string, DfsxCatatan>;
}

const MAKS_CATATAN = 500;

function pathSimpanan(): string {
  const dasar = process.env.DFSX_STATE_DIR || path.join(process.cwd(), 'state');
  return path.join(dasar, 'dfsx-registry.json');
}

function muat(): Simpanan {
  const berkas = pathSimpanan();
  try {
    if (fs.existsSync(berkas)) {
      const data = JSON.parse(fs.readFileSync(berkas, 'utf-8')) as Partial<Simpanan>;
      if (data && typeof data === 'object' && data.catatan) {
        return { versiSkema: 1, catatan: data.catatan };
      }
    }
  } catch {
    // Berkas rusak atau belum ada: mulai dari catatan kosong.
  }
  return { versiSkema: 1, catatan: {} };
}

function tulis(simpanan: Simpanan): void {
  const berkas = pathSimpanan();
  try {
    fs.mkdirSync(path.dirname(berkas), { recursive: true });
    const sementara = `${berkas}.tmp`;
    fs.writeFileSync(sementara, JSON.stringify(simpanan, null, 2), 'utf-8');
    fs.renameSync(sementara, berkas);
  } catch {
    // Gagal menulis catatan tidak menggagalkan pekerjaan yang sudah tersimpan.
  }
}

export function catatBerkasDfsx(catatan: Omit<DfsxCatatan, 'disimpanPada'>): DfsxCatatan {
  const simpanan = muat();
  const lengkap: DfsxCatatan = { ...catatan, disimpanPada: Date.now() };
  simpanan.catatan[catatan.localId] = lengkap;

  const kunci = Object.keys(simpanan.catatan);
  if (kunci.length > MAKS_CATATAN) {
    kunci
      .sort((a, b) => simpanan.catatan[a].disimpanPada - simpanan.catatan[b].disimpanPada)
      .slice(0, kunci.length - MAKS_CATATAN)
      .forEach((k) => delete simpanan.catatan[k]);
  }

  tulis(simpanan);
  return lengkap;
}

export function ambilCatatanDfsx(localId: string): DfsxCatatan | undefined {
  return muat().catatan[localId];
}

export function daftarCatatanDfsx(sumber?: DfsxSumber): DfsxCatatan[] {
  const semua = Object.values(muat().catatan);
  const hasil = sumber ? semua.filter((c) => c.sumber === sumber) : semua;
  return hasil.sort((a, b) => b.disimpanPada - a.disimpanPada);
}

export function hapusCatatanDfsx(localId: string): void {
  const simpanan = muat();
  if (simpanan.catatan[localId]) {
    delete simpanan.catatan[localId];
    tulis(simpanan);
  }
}
