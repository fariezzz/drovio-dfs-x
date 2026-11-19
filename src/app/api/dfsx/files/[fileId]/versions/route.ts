import { NextRequest, NextResponse } from 'next/server';
import { DfsxError, daftarVersiDfsx, rollbackDfsx } from '@/lib/dfsx/client';

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: {
    fileId: string;
  };
}

export async function GET(_req: NextRequest, { params }: RouteContext) {
  try {
    const data = await daftarVersiDfsx(params.fileId);
    return NextResponse.json(
      { success: true, data },
      { headers: { 'Cache-Control': 'no-store' } }
    );
  } catch (err) {
    const error = err as DfsxError;
    return NextResponse.json(
      { success: false, error: error.message },
      { status: error.status || 503 }
    );
  }
}

export async function POST(req: NextRequest, { params }: RouteContext) {
  // Hanya mengganti penunjuk versi aktif, jadi dapat dibalik.
  const body = await req.json().catch(() => ({}));
  const versi = Number(body?.versi);
  if (!Number.isInteger(versi) || versi <= 0) {
    return NextResponse.json(
      { success: false, error: 'Nomor versi tujuan wajib berupa angka bulat positif.' },
      { status: 400 }
    );
  }

  try {
    const data = await rollbackDfsx(params.fileId, versi);
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const error = err as DfsxError;
    return NextResponse.json(
      { success: false, error: error.message },
      { status: error.status || 503 }
    );
  }
}
