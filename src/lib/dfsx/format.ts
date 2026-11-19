// Tipe dan pembantu tampilan dashboard DFS-X. Aman dipakai di komponen
// klien: tidak menyentuh modul Node khusus server.
export {
  formatUkuran,
  formatPersen,
  persenHematDedup,
  labelKejadian,
  kejadianBermasalah,
  nodeLayakMenerimaReplika,
  namaDfsxAman,
  LABEL_KEJADIAN,
} from './dfsx-core.mjs';

// Waktu dari master dikirim sebagai detik epoch, bukan milidetik.
export function formatWaktu(detikEpoch: number | null | undefined): string {
  const nilai = Number(detikEpoch || 0);
  if (nilai <= 0) return '-';
  return new Date(nilai * 1000).toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatTanggalWaktu(detikEpoch: number | null | undefined): string {
  const nilai = Number(detikEpoch || 0);
  if (nilai <= 0) return '-';
  return new Date(nilai * 1000).toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatDetik(detik: number | null | undefined): string {
  const nilai = Number(detik || 0);
  if (nilai <= 0) return '-';
  if (nilai < 1) return `${(nilai * 1000).toFixed(0)} ms`;
  if (nilai < 60) return `${nilai.toFixed(1)} s`;
  return `${Math.floor(nilai / 60)} m ${Math.round(nilai % 60)} s`;
}

export interface DfsxNodeStatus {
  node_id: string;
  alamat: string;
  status: string;
  status_kesehatan: string;
  kapasitas_total: number;
  kapasitas_terpakai: number;
  rasio_terpakai: number;
  jumlah_chunk: number;
  heartbeat_terakhir: number;
  jeda_heartbeat: number;
  hampir_penuh: boolean;
}

export interface DfsxStatistik {
  jumlah_berkas: number;
  jumlah_versi: number;
  jumlah_chunk_unik: number;
  ukuran_logis: number;
  ukuran_chunk_direferensikan: number;
  ukuran_fisik_unik: number;
  ukuran_fisik_dengan_replika: number;
  hemat_deduplikasi: number;
  rasio_deduplikasi: number;
}

export interface DfsxPetaReplika {
  chunk_hash: string;
  ukuran: number;
  jumlah_referensi: number;
  node_list: string | null;
  jumlah_replika: number;
}

export interface DfsxLogAktivitas {
  waktu: number;
  jenis_kejadian: string;
  detail: string;
}

export interface DfsxVersiRingkas {
  versi: number;
  hash_berkas: string;
  ukuran: number;
  jumlah_chunk: number;
  dibuat_pada: number;
}

export interface DfsxBerkasRingkas {
  file_id: string;
  nama: string;
  versi_aktif: number;
  ukuran: number | null;
  hash_berkas: string | null;
  jumlah_chunk: number | null;
  jumlah_versi: number;
  diperbarui_pada: number;
}

export interface DfsxStatus {
  waktu: number;
  konfigurasi: {
    chunk_size_bytes: number;
    replication_factor: number;
    min_replicas: number;
    heartbeat_interval_seconds: number;
    node_dead_threshold_seconds: number;
    replikasi_adaptif: boolean;
    ambang_hampir_penuh: number;
  };
  ringkasan_node: { total: number; hidup: number; mati: number };
  node: DfsxNodeStatus[];
  statistik: DfsxStatistik;
  kesehatan_replikasi: {
    chunk_di_bawah_faktor: number;
    chunk_tanpa_replika: number;
    contoh: { chunk_hash: string; ukuran: number; jumlah_replika: number }[];
  };
  self_healing: {
    siklus: number;
    chunk_dipulihkan: number;
    chunk_gagal: number;
    pemulihan_terakhir: number | null;
    durasi_terakhir: number | null;
    sedang_memulihkan: boolean;
  };
  peta_replika: DfsxPetaReplika[];
  berkas: DfsxBerkasRingkas[];
  log: DfsxLogAktivitas[];
}


