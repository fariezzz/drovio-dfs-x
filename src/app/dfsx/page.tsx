'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Activity,
  AlertTriangle,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Server,
} from 'lucide-react';
import NodeStatusGrid from '@/components/dfsx/NodeStatusGrid';
import StorageStatsPanel from '@/components/dfsx/StorageStatsPanel';
import ReplicaMapPanel from '@/components/dfsx/ReplicaMapPanel';
import ActivityLogPanel from '@/components/dfsx/ActivityLogPanel';
import FileBrowserPanel from '@/components/dfsx/FileBrowserPanel';
import { DfsxStatus, formatWaktu } from '@/lib/dfsx/format';

// Cukup cepat untuk demo mematikan node, tanpa membanjiri master.
const JEDA_MUAT_ULANG_MS = 2000;

export default function DfsxDashboardPage() {
  const [status, setStatus] = useState<DfsxStatus | null>(null);
  const [galat, setGalat] = useState<string | null>(null);
  const [memuatAwal, setMemuatAwal] = useState(true);
  const [otomatis, setOtomatis] = useState(true);
  const [waktuAmbil, setWaktuAmbil] = useState<number | null>(null);
  const sedangAmbil = useRef(false);

  const ambilStatus = useCallback(async () => {
    if (sedangAmbil.current) return;
    sedangAmbil.current = true;
    try {
      const res = await fetch('/api/dfsx/status', { cache: 'no-store' });
      const data = await res.json();
      if (!data.success) {
        // Kegagalan ditampilkan apa adanya: dashboard tidak boleh
        // menyajikan angka lama seolah-olah sistem masih sehat.
        setGalat(data.error || 'Status DFS-X tidak dapat dibaca.');
        setStatus(null);
        return;
      }
      setStatus(data.data as DfsxStatus);
      setGalat(null);
      setWaktuAmbil(Date.now());
    } catch (err) {
      setGalat((err as Error).message || 'Master DFS-X tidak dapat dihubungi.');
      setStatus(null);
    } finally {
      sedangAmbil.current = false;
      setMemuatAwal(false);
    }
  }, []);

  useEffect(() => {
    void ambilStatus();
  }, [ambilStatus]);

  useEffect(() => {
    if (!otomatis) return;
    const timer = setInterval(() => void ambilStatus(), JEDA_MUAT_ULANG_MS);
    return () => clearInterval(timer);
  }, [otomatis, ambilStatus]);

  const nodeHidup = (status?.node || [])
    .filter((n) => n.status === 'hidup')
    .map((n) => n.node_id);

  return (
    <div className="min-h-screen bg-obsidian-canvas text-white">
      <header className="sticky top-0 z-40 w-full border-b border-obsidian-border bg-obsidian-canvas/95 backdrop-blur-md">
        <div className="mx-auto flex h-[54px] max-w-[1100px] items-center justify-between px-3.5 md:h-[64px] sm:px-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <Link
              href="/"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-obsidian-border bg-obsidian-surface text-obsidian-muted transition-colors hover:text-white"
              aria-label="Kembali ke Drovio"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-tight text-white">
                Monitor DFS-X
              </h1>
              <p className="truncate font-mono text-[10px] text-obsidian-faint">
                Penyimpanan Terdistribusi Drovio
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {status && (
              <span className="hidden items-center gap-1.5 rounded-md border border-obsidian-border bg-obsidian-surface px-2.5 py-1.5 font-mono text-[11px] text-obsidian-muted sm:flex">
                <Server className="h-3 w-3 text-emerald-accent" />
                {status.ringkasan_node.hidup}/{status.ringkasan_node.total} hidup
              </span>
            )}

            <button
              type="button"
              onClick={() => setOtomatis((v) => !v)}
              className="flex h-9 items-center gap-1.5 rounded-md border border-obsidian-border bg-obsidian-surface px-2.5 text-[11px] font-medium text-obsidian-muted transition-colors hover:border-obsidian-border-strong hover:text-white"
              title={otomatis ? 'Hentikan pembaruan otomatis' : 'Lanjutkan pembaruan otomatis'}
            >
              {otomatis ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              <span className="hidden sm:inline">{otomatis ? 'Live' : 'Jeda'}</span>
            </button>

            <button
              type="button"
              onClick={() => void ambilStatus()}
              className="flex h-9 w-9 items-center justify-center rounded-md border border-obsidian-border bg-obsidian-surface text-obsidian-muted transition-colors hover:border-obsidian-border-strong hover:text-white"
              aria-label="Muat ulang status"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1100px] space-y-2.5 px-3.5 py-4 sm:px-4">
        {/* Bilah keadaan sistem */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-obsidian-border bg-obsidian-surface px-3 py-2">
          <span className="flex items-center gap-1.5 text-[11px] font-medium text-obsidian-muted">
            <Activity
              className={`h-3 w-3 ${
                otomatis && !galat ? 'animate-pulse text-emerald-accent' : 'text-obsidian-faint'
              }`}
            />
            {galat ? 'Terputus' : otomatis ? 'Pembaruan otomatis aktif' : 'Pembaruan dijeda'}
          </span>
          {status && (
            <>
              <span className="font-mono text-[11px] text-obsidian-faint">
                Master: {formatWaktu(status.waktu)}
              </span>
              <span className="font-mono text-[11px] text-obsidian-faint">
                RF {status.konfigurasi.replication_factor} / min{' '}
                {status.konfigurasi.min_replicas}
              </span>
              <span className="font-mono text-[11px] text-obsidian-faint">
                Replikasi adaptif: {status.konfigurasi.replikasi_adaptif ? 'aktif' : 'nonaktif'}
              </span>
            </>
          )}
          {waktuAmbil && (
            <span className="ml-auto font-mono text-[10px] text-obsidian-faint">
              Diperbarui{' '}
              {new Date(waktuAmbil).toLocaleTimeString('id-ID', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </span>
          )}
        </div>

        {memuatAwal && (
          <div className="flex items-center justify-center gap-2 rounded-lg border border-obsidian-border bg-obsidian-surface py-10 text-xs text-obsidian-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            Memuat status DFS-X
          </div>
        )}

        {galat && !memuatAwal && (
          <div className="rounded-lg border border-crimson-accent/50 bg-crimson-muted p-4">
            <p className="flex items-center gap-2 text-xs font-semibold text-crimson-accent">
              <AlertTriangle className="h-4 w-4" />
              Master DFS-X tidak dapat dihubungi
            </p>
            <p className="mt-1.5 text-[11px] text-obsidian-muted">{galat}</p>
            <p className="mt-2 font-mono text-[10px] text-obsidian-faint">
              Jalankan: cd dfs-x &amp;&amp; docker compose --env-file config/.env up -d
            </p>
          </div>
        )}

        {status && (
          <>
            <NodeStatusGrid
              node={status.node}
              ambangMati={status.konfigurasi.node_dead_threshold_seconds}
            />
            <StorageStatsPanel status={status} />
            <FileBrowserPanel berkas={status.berkas} onPerubahan={() => void ambilStatus()} />
            <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
              <ReplicaMapPanel
                peta={status.peta_replika}
                faktorReplikasi={status.konfigurasi.replication_factor}
                nodeHidup={nodeHidup}
              />
              <ActivityLogPanel log={status.log} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
