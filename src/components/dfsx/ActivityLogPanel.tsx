'use client';

import React from 'react';
import { ScrollText } from 'lucide-react';
import {
  DfsxLogAktivitas,
  formatWaktu,
  kejadianBermasalah,
  labelKejadian,
} from '@/lib/dfsx/format';

interface ActivityLogPanelProps {
  log: DfsxLogAktivitas[];
}

export default function ActivityLogPanel({ log }: ActivityLogPanelProps) {
  return (
    <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5">
      <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
        <ScrollText className="h-3.5 w-3.5 text-violet-accent" />
        <h3 className="text-xs font-semibold text-white">Log Aktivitas Sistem</h3>
        <span className="ml-auto font-mono text-[10px] text-obsidian-faint">
          {log.length} kejadian
        </span>
      </div>

      {log.length === 0 ? (
        <p className="py-6 text-center text-xs text-obsidian-muted">
          Belum ada aktivitas tercatat.
        </p>
      ) : (
        <ul className="mt-2 max-h-[320px] space-y-1 overflow-y-auto">
          {log.map((l, i) => {
            const bermasalah = kejadianBermasalah(l.jenis_kejadian);
            const pemulihan = l.jenis_kejadian === 'self_healing';

            return (
              <li
                key={`${l.waktu}-${i}`}
                className="flex items-start gap-2 rounded-md bg-obsidian-lowest px-2 py-1.5"
              >
                <span className="shrink-0 font-mono text-[10px] text-obsidian-faint">
                  {formatWaktu(l.waktu)}
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                    bermasalah
                      ? 'bg-crimson-muted text-crimson-accent'
                      : pemulihan
                        ? 'bg-emerald-muted text-emerald-accent'
                        : 'bg-violet-muted text-violet-accent'
                  }`}
                >
                  {labelKejadian(l.jenis_kejadian)}
                </span>
                <span className="min-w-0 flex-1 break-words text-[11px] text-obsidian-muted">
                  {l.detail || '-'}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
