import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { getJobManager } from '@/lib/job-queue';
import { getConfig } from '@/lib/config';
import { isPathInside } from '@/lib/security';
import {
  getOrCreateSessionId,
  setPrivateSessionCookie,
} from '@/lib/private-history';
import { canAccessPrivateJob } from '@/lib/job-access';
import { ambilDariDfsx } from '@/lib/dfsx/client';
import { ambilCatatanDfsx } from '@/lib/dfsx/registry';

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: {
    id: string;
  };
}

function tentukanTipeKonten(filename: string): string {
  const ext = path.extname(filename).toLowerCase();
  if (ext === '.mp4') return 'video/mp4';
  if (ext === '.mp3') return 'audio/mpeg';
  if (ext === '.webm') return 'video/webm';
  if (ext === '.m4a') return 'audio/mp4';
  if (ext === '.srt') return 'application/x-subrip';
  if (ext === '.vtt') return 'text/vtt';
  if (['.ass', '.ssa', '.sbv', '.lrc', '.sub'].includes(ext)) {
    return 'text/plain; charset=utf-8';
  }
  return 'application/octet-stream';
}

export async function GET(req: NextRequest, { params }: RouteContext) {
  const { sessionId, isNew } = getOrCreateSessionId(req);
  const manager = getJobManager();
  const job = manager.getJob(params.id);
  const config = getConfig();

  if (!job || !canAccessPrivateJob(job.ownerSessionId, sessionId)) {
    return NextResponse.json(
      { success: false, error: 'File unduhan tidak ditemukan.' },
      { status: 404 }
    );
  }

  // ?kind=subtitle melayani berkas subtitle terpisah milik job ini
  // (perbaikan 2026-11-16). Tanpa parameter, perilaku lama dipertahankan:
  // berkas media utama. Pemeriksaan sesi, direktori, dan keberadaan file
  // sama untuk keduanya.
  const isSubtitle = req.nextUrl.searchParams.get('kind') === 'subtitle';
  const filepath = isSubtitle ? job.subtitleFilepath : job.outputFilepath;
  const storedFilename = isSubtitle ? job.subtitleFilename : job.outputFilename;

  // Sumber utama berkas media adalah DFS-X, berkas lokal hanya cadangan.
  // Subtitle tetap dari disk lokal karena belum diarsipkan ke DFS-X.
  if (!isSubtitle && job.status === 'completed') {
    const catatan = ambilCatatanDfsx(job.id);
    if (catatan) {
      const versiDiminta = req.nextUrl.searchParams.get('versi');
      try {
        const { isi, versi } = await ambilDariDfsx(
          catatan.fileId,
          versiDiminta ? Number(versiDiminta) : undefined
        );
        const filename = catatan.nama || storedFilename || 'berkas';
        const safeAscii = filename.replace(/[^\x20-\x7E]/g, '_').replace(/"/g, '');
        const response = new NextResponse(new Uint8Array(isi), {
          status: 200,
          headers: {
            'Content-Type': tentukanTipeKonten(filename),
            'Content-Length': isi.length.toString(),
            'Content-Disposition': `attachment; filename="${safeAscii}"; filename*=UTF-8''${encodeURIComponent(filename)}`,
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'X-Sumber-Berkas': 'dfs-x',
            'X-DFSX-Versi': String(versi || catatan.versi),
          },
        });
        if (isNew) setPrivateSessionCookie(response, sessionId, req.nextUrl.protocol === 'https:');
        return response;
      } catch (err) {
        const error = err as Error;
        // Bila berkas lokal sudah dibersihkan, tidak ada cadangan lagi:
        // galat DFS-X yang sebenarnya ditampilkan apa adanya.
        if (!filepath || !fs.existsSync(filepath)) {
          return NextResponse.json(
            { success: false, error: `Berkas tidak dapat diambil dari DFS-X: ${error.message}` },
            { status: 503 }
          );
        }
      }
    }
  }

  if (job.status !== 'completed' || !filepath) {
    return NextResponse.json(
      { success: false, error: isSubtitle ? 'File subtitle tidak tersedia untuk unduhan ini.' : 'File unduhan belum selesai diproses atau gagal.' },
      { status: 400 }
    );
  }

  if (!isPathInside(config.downloadDir, filepath)) {
    return NextResponse.json(
      { success: false, error: 'Akses ke file ditolak (keamanan direktori).' },
      { status: 403 }
    );
  }

  if (!fs.existsSync(filepath)) {
    return NextResponse.json(
      { success: false, error: 'File fisik telah dihapus atau dipindahkan dari disk lokal.' },
      { status: 404 }
    );
  }

  try {
    const stats = fs.statSync(filepath);
    const filename = storedFilename || path.basename(filepath);
    const contentType = tentukanTipeKonten(filename);

    const nodeStream = fs.createReadStream(filepath);
    const webStream = new ReadableStream({
      start(controller) {
        nodeStream.on('data', (chunk) => controller.enqueue(chunk));
        nodeStream.on('end', () => controller.close());
        nodeStream.on('error', (err) => controller.error(err));
      },
      cancel() {
        nodeStream.destroy();
      },
    });

    const safeAscii = filename.replace(/[^\x20-\x7E]/g, '_').replace(/"/g, '');
    const encodedFilename = encodeURIComponent(filename);
    const response = new NextResponse(webStream, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': stats.size.toString(),
        'Content-Disposition': `attachment; filename="${safeAscii}"; filename*=UTF-8''${encodedFilename}`,
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    });

    if (isNew) setPrivateSessionCookie(response, sessionId, req.nextUrl.protocol === 'https:');
    return response;
  } catch (err: unknown) {
    const error = err as Error;
    return NextResponse.json(
      { success: false, error: `Gagal membaca file dari disk: ${error.message}` },
      { status: 500 }
    );
  }
}
