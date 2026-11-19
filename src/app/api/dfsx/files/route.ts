import { NextResponse } from 'next/server';
import { DfsxError, daftarBerkasDfsx } from '@/lib/dfsx/client';
import { daftarCatatanDfsx } from '@/lib/dfsx/registry';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const berkas = await daftarBerkasDfsx();
    const catatan = daftarCatatanDfsx();
    // Tandai asal berkas: unduhan, konversi, atau kompresi.
    const sumberPerFileId = new Map(catatan.map((c) => [c.fileId, c.sumber]));

    return NextResponse.json(
      {
        success: true,
        data: berkas.map((b) => ({
          ...b,
          sumber_drovio: sumberPerFileId.get(b.file_id) || null,
        })),
      },
      { headers: { 'Cache-Control': 'no-store, no-cache, must-revalidate' } }
    );
  } catch (err) {
    const error = err as DfsxError;
    return NextResponse.json(
      { success: false, error: error.message },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}
