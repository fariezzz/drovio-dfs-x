import { NextRequest, NextResponse } from 'next/server';
import { DfsxError, ambilDariDfsx, metadataDfsx } from '@/lib/dfsx/client';

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: {
    fileId: string;
  };
}

export async function GET(req: NextRequest, { params }: RouteContext) {
  const versiParam = req.nextUrl.searchParams.get('versi');
  const versi = versiParam ? Number(versiParam) : undefined;
  if (versiParam && (!Number.isInteger(versi) || (versi as number) <= 0)) {
    return NextResponse.json(
      { success: false, error: 'Parameter versi harus angka bulat positif.' },
      { status: 400 }
    );
  }

  try {
    const meta = (await metadataDfsx(params.fileId, versi)) as { nama?: string };
    const { isi, versi: versiHasil } = await ambilDariDfsx(params.fileId, versi);
    const filename = meta.nama || 'berkas';
    const safeAscii = filename.replace(/[^\x20-\x7E]/g, '_').replace(/"/g, '');

    return new Response(new Uint8Array(isi), {
      status: 200,
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Length': isi.length.toString(),
        'Content-Disposition': `attachment; filename="${safeAscii}"; filename*=UTF-8''${encodeURIComponent(filename)}`,
        'Cache-Control': 'no-store',
        'X-Sumber-Berkas': 'dfs-x',
        'X-DFSX-Versi': String(versiHasil),
      },
    });
  } catch (err) {
    const error = err as DfsxError;
    return NextResponse.json(
      { success: false, error: error.message },
      { status: error.status || 503 }
    );
  }
}
