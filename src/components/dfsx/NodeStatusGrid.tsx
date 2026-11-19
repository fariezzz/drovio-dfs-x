'use client';

import React from 'react';
import { HardDrive, Server, AlertTriangle } from 'lucide-react';
import {
  DfsxNodeStatus,
  formatDetik,
  formatPersen,
  formatUkuran,
  formatWaktu,
} from '@/lib/dfsx/format';

interface NodeStatusGridProps {
  node: DfsxNodeStatus[];
  ambangMati: number;
}

export default function NodeStatusGrid({ node, ambangMati }: NodeStatusGridProps) {
  if (node.length === 0) {
    return (
      <div className="rounded-lg border border-obsidian-border bg-obsidian-lowest p-6 text-center">
        <Server className="mx-auto h-5 w-5 text-obsidian-faint" />
        <p className="mt-2 text-xs text-obsidian-muted">
          Belum ada data node yang terdaftar di master.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
      {node.map((n) => {
        const hidup = n.status === 'hidup';
        const telat = hidup && n.jeda_heartbeat > ambangMati * 0.6;

        return (
          <div
            key={n.node_id}
            className={`rounded-lg border bg-obsidian-surface p-3 transition-colors ${
              hidup
                ? telat
                  ? 'border-amber-500/40'
                  : 'border-obsidian-border'
                : 'border-crimson-accent/50 bg-crimson-muted'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <div
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
                    hidup ? 'bg-emerald-muted' : 'bg-crimson-muted'
                  }`}
                >
                  <HardDrive
                    className={`h-3.5 w-3.5 ${
                      hidup ? 'text-emerald-accent' : 'text-crimson-accent'
                    }`}
                  />
                </div>
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs font-semibold text-white">
                    {n.node_id}
                  </p>
                  <p className="truncate font-mono text-[10px] text-obsidian-faint">
                    {n.alamat.replace(/^https?:\/\//, '')}
                  </p>
                </div>
              </div>

              <span
                className={`flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  hidup
                    ? 'bg-emerald-muted text-emerald-accent'
                    : 'bg-crimson-muted text-crimson-accent'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    hidup ? 'animate-pulse bg-emerald-accent' : 'bg-crimson-accent'
                  }`}
                />
                {hidup ? 'Hidup' : 'Mati'}
              </span>
            </div>

            {/* Bilah kapasitas */}
            <div className="mt-3">
              <div className="flex items-center justify-between font-mono text-[10px] text-obsidian-muted">
                <span>{formatUkuran(n.kapasitas_terpakai)}</span>
                <span>{formatPersen(n.rasio_terpakai)}</span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-obsidian-lowest">
                <div
                  className={`h-full rounded-full transition-all ${
                    n.hampir_penuh
                      ? 'bg-crimson-accent'
                      : hidup
                        ? 'bg-violet-accent'
                        : 'bg-obsidian-border-strong'
                  }`}
                  style={{ width: `${Math.min(n.rasio_terpakai * 100, 100)}%` }}
                />
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-obsidian-border pt-2.5">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-obsidian-faint">Chunk</p>
                <p className="font-mono text-xs font-semibold text-white">{n.jumlah_chunk}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-obsidian-faint">Kapasitas</p>
                <p className="font-mono text-xs text-obsidian-muted">
                  {formatUkuran(n.kapasitas_total)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-obsidian-faint">Heartbeat</p>
                <p
                  className={`font-mono text-xs ${
                    telat ? 'text-amber-400' : 'text-obsidian-muted'
                  }`}
                >
                  {hidup ? formatDetik(n.jeda_heartbeat) : formatWaktu(n.heartbeat_terakhir)}
                </p>
              </div>
            </div>

            {n.hampir_penuh && hidup && (
              <p className="mt-2 flex items-center gap-1 text-[10px] text-crimson-accent">
                <AlertTriangle className="h-3 w-3" />
                Hampir penuh, replika baru diarahkan ke node lain
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
