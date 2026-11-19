'use client';

import React from 'react';
import { Database, Layers, ShieldCheck, Activity } from 'lucide-react';
import {
  DfsxStatus,
  formatDetik,
  formatUkuran,
  formatWaktu,
} from '@/lib/dfsx/format';

interface StorageStatsPanelProps {
  status: DfsxStatus;
}

function Metrik({
  label,
  nilai,
  satuan,
  tekan,
}: {
  label: string;
  nilai: string;
  satuan?: string;
  tekan?: 'violet' | 'emerald' | 'crimson';
}) {
  const warna =
    tekan === 'emerald'
      ? 'text-emerald-accent'
      : tekan === 'crimson'
        ? 'text-crimson-accent'
        : tekan === 'violet'
          ? 'text-violet-accent'
          : 'text-white';

  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-obsidian-faint">{label}</p>
      <p className={`mt-0.5 font-mono text-sm font-semibold ${warna}`}>
        {nilai}
        {satuan && <span className="ml-1 text-[10px] font-normal text-obsidian-muted">{satuan}</span>}
      </p>
    </div>
  );
}

export default function StorageStatsPanel({ status }: StorageStatsPanelProps) {
  const { statistik: s, kesehatan_replikasi: kr, self_healing: sh, konfigurasi: cfg } = status;
  const hematPersen =
    s.ukuran_chunk_direferensikan > 0
      ? (s.hemat_deduplikasi / s.ukuran_chunk_direferensikan) * 100
      : 0;

  return (
    <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
      {/* Deduplikasi */}
      <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5">
        <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
          <Layers className="h-3.5 w-3.5 text-violet-accent" />
          <h3 className="text-xs font-semibold text-white">Deduplikasi Konten</h3>
          <span className="ml-auto rounded bg-violet-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-violet-accent">
            {s.rasio_deduplikasi.toFixed(2)}x
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metrik label="Ukuran Logis" nilai={formatUkuran(s.ukuran_logis)} />
          <Metrik label="Fisik Unik" nilai={formatUkuran(s.ukuran_fisik_unik)} />
          <Metrik
            label="Ruang Dihemat"
            nilai={formatUkuran(s.hemat_deduplikasi)}
            tekan="emerald"
          />
          <Metrik label="Chunk Unik" nilai={String(s.jumlah_chunk_unik)} />
        </div>

        <div className="mt-3">
          <div className="flex items-center justify-between font-mono text-[10px] text-obsidian-muted">
            <span>Hemat {hematPersen.toFixed(1)}% dari total chunk direferensikan</span>
            <span>{formatUkuran(s.ukuran_chunk_direferensikan)}</span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-obsidian-lowest">
            <div
              className="h-full rounded-full bg-emerald-accent transition-all"
              style={{ width: `${Math.min(hematPersen, 100)}%` }}
            />
          </div>
        </div>

        <p className="mt-2.5 border-t border-obsidian-border pt-2 font-mono text-[10px] text-obsidian-faint">
          Fisik termasuk replika: {formatUkuran(s.ukuran_fisik_dengan_replika)}
        </p>
      </div>

      {/* Kesehatan replikasi dan self-healing */}
      <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5">
        <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
          <ShieldCheck className="h-3.5 w-3.5 text-violet-accent" />
          <h3 className="text-xs font-semibold text-white">Kesehatan Replikasi</h3>
          {sh.sedang_memulihkan ? (
            <span className="ml-auto flex items-center gap-1 rounded bg-violet-muted px-1.5 py-0.5 text-[10px] font-semibold text-violet-accent">
              <Activity className="h-2.5 w-2.5 animate-pulse" />
              Memulihkan
            </span>
          ) : (
            <span
              className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                kr.chunk_di_bawah_faktor === 0
                  ? 'bg-emerald-muted text-emerald-accent'
                  : 'bg-amber-500/15 text-amber-400'
              }`}
            >
              {kr.chunk_di_bawah_faktor === 0 ? 'Lengkap' : 'Belum Lengkap'}
            </span>
          )}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metrik
            label="Di Bawah RF"
            nilai={String(kr.chunk_di_bawah_faktor)}
            satuan="chunk"
            tekan={kr.chunk_di_bawah_faktor > 0 ? 'crimson' : 'emerald'}
          />
          <Metrik
            label="Tanpa Replika"
            nilai={String(kr.chunk_tanpa_replika)}
            satuan="chunk"
            tekan={kr.chunk_tanpa_replika > 0 ? 'crimson' : undefined}
          />
          <Metrik
            label="Dipulihkan"
            nilai={String(sh.chunk_dipulihkan)}
            satuan="chunk"
            tekan="emerald"
          />
          <Metrik label="Siklus" nilai={String(sh.siklus)} />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 border-t border-obsidian-border pt-2.5 sm:grid-cols-4">
          <Metrik label="Faktor Replikasi" nilai={String(cfg.replication_factor)} />
          <Metrik label="Replika Minimum" nilai={String(cfg.min_replicas)} />
          <Metrik
            label="Pemulihan Terakhir"
            nilai={formatWaktu(sh.pemulihan_terakhir)}
          />
          <Metrik label="Durasi Terakhir" nilai={formatDetik(sh.durasi_terakhir)} />
        </div>

        {kr.chunk_di_bawah_faktor > 0 && (
          <p className="mt-2.5 border-t border-obsidian-border pt-2 text-[10px] text-obsidian-muted">
            Chunk dengan salinan paling sedikit dipulihkan lebih dulu. Contoh chunk berisiko:{' '}
            <span className="font-mono text-obsidian-faint">
              {kr.contoh
                .slice(0, 3)
                .map((c) => `${c.chunk_hash.slice(0, 8)} (${c.jumlah_replika})`)
                .join(', ')}
            </span>
          </p>
        )}
      </div>

      {/* Ringkasan berkas */}
      <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5 lg:col-span-2">
        <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
          <Database className="h-3.5 w-3.5 text-violet-accent" />
          <h3 className="text-xs font-semibold text-white">Ringkasan Penyimpanan</h3>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Metrik label="Berkas" nilai={String(s.jumlah_berkas)} />
          <Metrik label="Total Versi" nilai={String(s.jumlah_versi)} />
          <Metrik label="Chunk Unik" nilai={String(s.jumlah_chunk_unik)} />
          <Metrik
            label="Ukuran Chunk"
            nilai={formatUkuran(cfg.chunk_size_bytes)}
          />
          <Metrik
            label="Heartbeat"
            nilai={`${cfg.heartbeat_interval_seconds}`}
            satuan="detik"
          />
          <Metrik
            label="Ambang Mati"
            nilai={`${cfg.node_dead_threshold_seconds}`}
            satuan="detik"
          />
        </div>
      </div>
    </div>
  );
}
