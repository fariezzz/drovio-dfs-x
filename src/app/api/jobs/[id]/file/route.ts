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

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: {
    id: string;
  };
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
    const ext = path.extname(filename).toLowerCase();

    let contentType = 'application/octet-stream';
    if (ext === '.mp4') contentType = 'video/mp4';
    else if (ext === '.mp3') contentType = 'audio/mpeg';
    else if (ext === '.webm') contentType = 'video/webm';
    else if (ext === '.m4a') contentType = 'audio/mp4';
    else if (ext === '.srt') contentType = 'application/x-subrip';
    else if (ext === '.vtt') contentType = 'text/vtt';
    else if (ext === '.ass' || ext === '.ssa' || ext === '.sbv' || ext === '.lrc' || ext === '.sub') contentType = 'text/plain; charset=utf-8';

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
