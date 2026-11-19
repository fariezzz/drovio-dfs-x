// Logika murni DFS-X, dipakai bersama modul TypeScript dan berkas uji.

// Master menolak nama bertingkat, jadi hanya komponen terakhir yang dipakai.
export function namaDfsxAman(nama) {
  const teks = typeof nama === 'string' ? nama : '';
  // Ambil komponen terakhir, menangani pemisah gaya Unix dan Windows.
  const dasar = teks.split(/[\\/]/).pop() || '';
  const bersih = dasar
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001F<>:"|?*]/g, '_')
    .replace(/^\.+$/, '')
    .trim()
    .slice(0, 180);
  return bersih || 'berkas';
}

export function formatUkuran(byte) {
  const nilai = Number(byte || 0);
  if (!Number.isFinite(nilai) || nilai <= 0) return '0 B';
  const satuan = ['B', 'KB', 'MB', 'GB', 'TB'];
  const pangkat = Math.min(
    Math.floor(Math.log(nilai) / Math.log(1024)),
    satuan.length - 1
  );
  const hasil = nilai / Math.pow(1024, pangkat);
  return `${hasil.toFixed(hasil >= 100 || pangkat === 0 ? 0 : 1)} ${satuan[pangkat]}`;
}

export function formatPersen(rasio) {
  return `${(Number(rasio || 0) * 100).toFixed(1)}%`;
}

// Pembaginya total chunk yang dirujuk, sejalan dengan statistik master.
export function persenHematDedup(byteDirujuk, byteDihemat) {
  const dirujuk = Number(byteDirujuk || 0);
  const dihemat = Number(byteDihemat || 0);
  if (dirujuk <= 0) return 0;
  return Math.round((dihemat / dirujuk) * 1000) / 10;
}

// Label untuk jenis kejadian di log aktivitas master.
export const LABEL_KEJADIAN = {
  master_mulai: 'Master Mulai',
  node_hidup: 'Node Hidup',
  node_mati: 'Node Mati',
  versi_disimpan: 'Versi Disimpan',
  tulis_ditolak: 'Tulis Ditolak',
  self_healing: 'Pemulihan Otomatis',
  chunk_rusak: 'Chunk Rusak',
  baca_gagal: 'Baca Gagal',
  hash_tidak_cocok: 'Hash Tidak Cocok',
  berkas_dihapus: 'Berkas Dihapus',
  reset_metadata: 'Reset Metadata',
  rollback: 'Rollback Versi',
};

export function labelKejadian(jenis) {
  return LABEL_KEJADIAN[jenis] || jenis;
}

// Kejadian yang ditandai merah di log aktivitas.
export function kejadianBermasalah(jenis) {
  return [
    'node_mati',
    'tulis_ditolak',
    'chunk_rusak',
    'baca_gagal',
    'hash_tidak_cocok',
  ].includes(jenis);
}

// Node mati atau hampir penuh hanya dipakai bila tidak ada pilihan lain.
export function nodeLayakMenerimaReplika(node, ambangPenuh = 0.85) {
  if (!node || node.status !== 'hidup') return false;
  const total = Math.max(Number(node.kapasitas_total || 0), 1);
  const terpakai = Number(node.kapasitas_terpakai || 0);
  return terpakai / total < ambangPenuh;
}
