// Satu pintu pengarsipan hasil unduhan, konversi, dan kompresi ke DFS-X.
// Kegagalan dikembalikan apa adanya, dan berkas lokal tidak dihapus.

import fs from 'fs';

import {
  DfsxError,
  getDfsxConfig,
  simpanKeDfsx,
} from './client';
import { catatBerkasDfsx, DfsxCatatan, DfsxSumber } from './registry';

export interface ArsipPermintaan {
  localId: string;
  sumber: DfsxSumber;
  filePath: string;
  namaBerkas: string;
  mimeType?: string;
}

export interface ArsipHasil {
  berhasil: boolean;
  catatan?: DfsxCatatan;
  galat?: string;
}

export async function arsipkanKeDfsx(permintaan: ArsipPermintaan): Promise<ArsipHasil> {
  const config = getDfsxConfig();
  if (!config.enabled) {
    return { berhasil: false, galat: 'DFS-X dinonaktifkan lewat konfigurasi.' };
  }

  try {
    const hasil = await simpanKeDfsx(permintaan.filePath, permintaan.namaBerkas);
    const catatan = catatBerkasDfsx({
      localId: permintaan.localId,
      sumber: permintaan.sumber,
      fileId: hasil.fileId,
      nama: hasil.nama,
      versi: hasil.versi,
      ukuran: hasil.ukuran,
      hashBerkas: hasil.hashBerkas,
      jumlahChunk: hasil.jumlahChunk,
      chunkDideduplikasi: hasil.chunkDideduplikasi,
      mimeType: permintaan.mimeType,
    });

    if (config.pruneLocal) {
      // Dihapus hanya setelah DFS-X membalas sukses.
      try {
        await fs.promises.unlink(permintaan.filePath);
      } catch {
        // Berkas sudah tidak ada atau terkunci: tidak mengubah hasil.
      }
    }

    return { berhasil: true, catatan };
  } catch (err) {
    const error = err as DfsxError;
    return {
      berhasil: false,
      galat: error.message || 'Berkas hasil gagal disimpan ke DFS-X.',
    };
  }
}
