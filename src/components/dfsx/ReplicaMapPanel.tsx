'use client';

import React from 'react';
import { Boxes } from 'lucide-react';
import { DfsxPetaReplika, formatUkuran } from '@/lib/dfsx/format';

interface ReplicaMapPanelProps {
  peta: DfsxPetaReplika[];
  faktorReplikasi: number;
  nodeHidup: string[];
}

export default function ReplicaMapPanel({
  peta,
  faktorReplikasi,
  nodeHidup,
}: ReplicaMapPanelProps) {
  return (
    <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5">
      <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
        <Boxes className="h-3.5 w-3.5 text-violet-accent" />
        <h3 className="text-xs font-semibold text-white">Peta Replika Chunk</h3>
        <span className="ml-auto font-mono text-[10px] text-obsidian-faint">
          {peta.length} chunk terbaru
        </span>
      </div>

      {peta.length === 0 ? (
        <p className="py-6 text-center text-xs text-obsidian-muted">
          Belum ada chunk tersimpan. Simpan berkas lewat Drovio atau skrip pengujian.
        </p>
      ) : (
        <div className="mt-2 max-h-[320px] overflow-y-auto">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-obsidian-surface">
              <tr className="border-b border-obsidian-border text-[10px] uppercase tracking-wide text-obsidian-faint">
                <th className="py-1.5 pr-2 font-medium">Hash Chunk</th>
                <th className="py-1.5 pr-2 font-medium">Ukuran</th>
                <th className="py-1.5 pr-2 font-medium">Ref</th>
                <th className="py-1.5 font-medium">Lokasi Replika</th>
              </tr>
            </thead>
            <tbody>
              {peta.map((c) => {
                const daftarNode = (c.node_list || '')
                  .split(',')
                  .map((n) => n.trim())
                  .filter(Boolean);
                const kurang = c.jumlah_replika < faktorReplikasi;

                return (
                  <tr
                    key={c.chunk_hash}
                    className="border-b border-obsidian-border/50 last:border-0"
                  >
                    <td className="py-1.5 pr-2 font-mono text-[11px] text-obsidian-muted">
                      {c.chunk_hash.slice(0, 12)}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-[11px] text-obsidian-muted">
                      {formatUkuran(c.ukuran)}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-[11px] text-obsidian-muted">
                      {c.jumlah_referensi}
                    </td>
                    <td className="py-1.5">
                      <div className="flex flex-wrap items-center gap-1">
                        {daftarNode.length === 0 ? (
                          <span className="rounded bg-crimson-muted px-1.5 py-0.5 font-mono text-[10px] text-crimson-accent">
                            tidak ada replika
                          </span>
                        ) : (
                          daftarNode.map((n) => (
                            <span
                              key={n}
                              className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                                nodeHidup.includes(n)
                                  ? 'bg-emerald-muted text-emerald-accent'
                                  : 'bg-crimson-muted text-crimson-accent line-through'
                              }`}
                            >
                              {n.replace('datanode-', 'dn')}
                            </span>
                          ))
                        )}
                        {kurang && daftarNode.length > 0 && (
                          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] text-amber-400">
                            {c.jumlah_replika}/{faktorReplikasi}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
