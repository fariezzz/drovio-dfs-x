import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { getConversionResult } from '@/lib/converter/service';
import { ambilDariDfsx } from '@/lib/dfsx/client';
import { ambilCatatanDfsx } from '@/lib/dfsx/registry';

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: {
    id: string;
  };
}

export async function GET(_req: NextRequest, { params }: RouteContext) {
  const { id } = params;
  const result = getConversionResult(id);

  // Sumber utama DFS-X, berkas lokal hanya cadangan.
  const catatan = ambilCatatanDfsx(id);
  if (catatan) {
    try {
      const { isi, versi } = await ambilDariDfsx(catatan.fileId);
      const filename = catatan.nama;
      const safeAscii = filename.replace(/[^\x20-\x7E]/g, '_').replace(/"/g, '');
      return new Response(new Uint8Array(isi), {
        status: 200,
        headers: {
          'Content-Type': catatan.mimeType || 'application/octet-stream',
          'Content-Length': isi.length.toString(),
          'Content-Disposition': `attachment; filename="${safeAscii}"; filename*=UTF-8''${encodeURIComponent(filename)}`,
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'X-Sumber-Berkas': 'dfs-x',
          'X-DFSX-Versi': String(versi || catatan.versi),
        },
      });
    } catch (err) {
      const error = err as Error;
      if (!result?.filePath || !fs.existsSync(result.filePath)) {
        return NextResponse.json(
          { success: false, error: `Berkas tidak dapat diambil dari DFS-X: ${error.message}` },
          { status: 503 }
        );
      }
    }
  }

  if (!result || !result.filePath || !fs.existsSync(result.filePath)) {
    return NextResponse.json(
      { success: false, error: 'Berkas hasil konversi tidak ditemukan atau telah kedaluwarsa.' },
      { status: 404 }
    );
  }

  try {
    const stats = fs.statSync(result.filePath);
    const filename = result.convertedName || path.basename(result.filePath).replace(/\s*\[cnv_[^\]]+\]/g, '');
    const safeAscii = filename.replace(/[^\x20-\x7E]/g, '_').replace(/"/g, '');
    const encodedFilename = encodeURIComponent(filename);

    const nodeStream = fs.createReadStream(result.filePath);
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

    return new Response(webStream, {
      status: 200,
      headers: {
        'Content-Type': result.mimeType || 'application/octet-stream',
        'Content-Length': stats.size.toString(),
        'Content-Disposition': `attachment; filename="${safeAscii}"; filename*=UTF-8''${encodedFilename}`,
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    });
  } catch (err: unknown) {
    const error = err as Error;
    return NextResponse.json(
      { success: false, error: `Gagal membaca berkas: ${error.message}` },
      { status: 500 }
    );
  }
}
