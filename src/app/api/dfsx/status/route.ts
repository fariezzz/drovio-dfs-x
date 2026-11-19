import { NextResponse } from 'next/server';
import { DfsxError, getDfsxConfig, statusDfsx } from '@/lib/dfsx/client';

export const dynamic = 'force-dynamic';

export async function GET() {
  const config = getDfsxConfig();
  if (!config.enabled) {
    return NextResponse.json(
      { success: false, error: 'DFS-X dinonaktifkan lewat konfigurasi.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    );
  }

  try {
    const data = await statusDfsx();
    return NextResponse.json(
      { success: true, data },
      { headers: { 'Cache-Control': 'no-store, no-cache, must-revalidate' } }
    );
  } catch (err) {
    const error = err as DfsxError;
    // Galat ditampilkan apa adanya, bukan status lama.
    return NextResponse.json(
      { success: false, error: error.message },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}
