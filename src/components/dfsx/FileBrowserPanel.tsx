'use client';

import React, { useCallback, useState } from 'react';
import { FileStack, Download, History, Undo2, Loader2 } from 'lucide-react';
import {
  DfsxBerkasRingkas,
  DfsxVersiRingkas,
  formatTanggalWaktu,
  formatUkuran,
} from '@/lib/dfsx/format';

interface FileBrowserPanelProps {
  berkas: DfsxBerkasRingkas[];
  onPerubahan: () => void;
}

export default function FileBrowserPanel({ berkas, onPerubahan }: FileBrowserPanelProps) {
  const [terbuka, setTerbuka] = useState<string | null>(null);
  const [versi, setVersi] = useState<Record<string, DfsxVersiRingkas[]>>({});
  const [versiAktif, setVersiAktif] = useState<Record<string, number>>({});
  const [memuat, setMemuat] = useState<string | null>(null);
  const [memproses, setMemproses] = useState<string | null>(null);
  const [galat, setGalat] = useState<string | null>(null);

  const muatVersi = useCallback(async (fileId: string) => {
    setMemuat(fileId);
    setGalat(null);
    try {
      const res = await fetch(`/api/dfsx/files/${fileId}/versions`, { cache: 'no-store' });
      const data = await res.json();
      if (!data.success) {
        setGalat(data.error || 'Daftar versi tidak dapat dimuat.');
        return;
      }
      setVersi((prev) => ({ ...prev, [fileId]: data.data.versi }));
      setVersiAktif((prev) => ({ ...prev, [fileId]: data.data.versi_aktif }));
    } catch (err) {
      setGalat((err as Error).message);
    } finally {
      setMemuat(null);
    }
  }, []);

  const bukaTutup = useCallback(
    (fileId: string) => {
      if (terbuka === fileId) {
        setTerbuka(null);
        return;
      }
      setTerbuka(fileId);
      if (!versi[fileId]) void muatVersi(fileId);
    },
    [terbuka, versi, muatVersi]
  );

  const lakukanRollback = useCallback(
    async (fileId: string, tujuan: number) => {
      setMemproses(`${fileId}-${tujuan}`);
      setGalat(null);
      try {
        const res = await fetch(`/api/dfsx/files/${fileId}/versions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ versi: tujuan }),
        });
        const data = await res.json();
        if (!data.success) {
          setGalat(data.error || 'Rollback versi gagal.');
          return;
        }
        setVersiAktif((prev) => ({ ...prev, [fileId]: tujuan }));
        onPerubahan();
      } catch (err) {
        setGalat((err as Error).message);
      } finally {
        setMemproses(null);
      }
    },
    [onPerubahan]
  );

  return (
    <div className="rounded-lg border border-obsidian-border bg-obsidian-surface p-3.5">
      <div className="flex items-center gap-2 border-b border-obsidian-border pb-2.5">
        <FileStack className="h-3.5 w-3.5 text-violet-accent" />
        <h3 className="text-xs font-semibold text-white">Berkas Tersimpan di DFS-X</h3>
        <span className="ml-auto font-mono text-[10px] text-obsidian-faint">
          {berkas.length} berkas
        </span>
      </div>

      {galat && (
        <p className="mt-2 rounded-md bg-crimson-muted px-2 py-1.5 text-[11px] text-crimson-accent">
          {galat}
        </p>
      )}

      {berkas.length === 0 ? (
        <p className="py-6 text-center text-xs text-obsidian-muted">
          Belum ada berkas di DFS-X. Hasil unduhan, konversi, dan kompresi Drovio akan
          otomatis muncul di sini.
        </p>
      ) : (
        <ul className="mt-2 max-h-[360px] space-y-1.5 overflow-y-auto">
          {berkas.map((b) => {
            const aktif = versiAktif[b.file_id] ?? b.versi_aktif;
            const sedangTerbuka = terbuka === b.file_id;

            return (
              <li
                key={b.file_id}
                className="rounded-md border border-obsidian-border bg-obsidian-lowest"
              >
                <div className="flex items-center gap-2 px-2.5 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-white">{b.nama}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[10px] text-obsidian-faint">
                      <span>{formatUkuran(b.ukuran)}</span>
                      <span>v{aktif}</span>
                      <span>{b.jumlah_chunk ?? 0} chunk</span>
                      <span>{formatTanggalWaktu(b.diperbarui_pada)}</span>
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={() => bukaTutup(b.file_id)}
                    className="flex h-7 shrink-0 items-center gap-1 rounded-md border border-obsidian-border bg-obsidian-surface px-2 text-[11px] font-medium text-obsidian-muted transition-colors hover:border-obsidian-border-strong hover:text-white"
                  >
                    <History className="h-3 w-3" />
                    <span>{b.jumlah_versi} Versi</span>
                  </button>

                  <a
                    href={`/api/dfsx/files/${b.file_id}/content`}
                    className="flex h-7 shrink-0 items-center gap-1 rounded-md bg-violet-accent px-2.5 text-[11px] font-semibold text-obsidian-canvas transition-colors hover:bg-violet-hover"
                  >
                    <Download className="h-3 w-3" />
                    <span>Unduh</span>
                  </a>
                </div>

                {sedangTerbuka && (
                  <div className="border-t border-obsidian-border px-2.5 py-2">
                    {memuat === b.file_id ? (
                      <p className="flex items-center gap-1.5 text-[11px] text-obsidian-muted">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Memuat daftar versi
                      </p>
                    ) : (
                      <ul className="space-y-1">
                        {(versi[b.file_id] || []).map((v) => {
                          const iniAktif = v.versi === aktif;
                          const kunciProses = `${b.file_id}-${v.versi}`;

                          return (
                            <li
                              key={v.versi}
                              className="flex items-center gap-2 rounded bg-obsidian-surface px-2 py-1.5"
                            >
                              <span
                                className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${
                                  iniAktif
                                    ? 'bg-emerald-muted text-emerald-accent'
                                    : 'bg-obsidian-lowest text-obsidian-muted'
                                }`}
                              >
                                v{v.versi}
                              </span>
                              <span className="font-mono text-[10px] text-obsidian-muted">
                                {formatUkuran(v.ukuran)}
                              </span>
                              <span className="font-mono text-[10px] text-obsidian-faint">
                                {v.jumlah_chunk} chunk
                              </span>
                              <span className="hidden font-mono text-[10px] text-obsidian-faint sm:inline">
                                {formatTanggalWaktu(v.dibuat_pada)}
                              </span>

                              <div className="ml-auto flex shrink-0 items-center gap-1.5">
                                <a
                                  href={`/api/dfsx/files/${b.file_id}/content?versi=${v.versi}`}
                                  className="rounded border border-obsidian-border px-1.5 py-0.5 text-[10px] font-medium text-obsidian-muted transition-colors hover:text-white"
                                >
                                  Unduh
                                </a>
                                {!iniAktif && (
                                  <button
                                    type="button"
                                    onClick={() => void lakukanRollback(b.file_id, v.versi)}
                                    disabled={memproses === kunciProses}
                                    className="flex items-center gap-1 rounded bg-violet-muted px-1.5 py-0.5 text-[10px] font-semibold text-violet-accent transition-colors hover:bg-violet-accent hover:text-obsidian-canvas disabled:opacity-50"
                                  >
                                    {memproses === kunciProses ? (
                                      <Loader2 className="h-2.5 w-2.5 animate-spin" />
                                    ) : (
                                      <Undo2 className="h-2.5 w-2.5" />
                                    )}
                                    Rollback
                                  </button>
                                )}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
