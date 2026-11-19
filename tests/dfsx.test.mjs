import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {
  namaDfsxAman,
  formatUkuran,
  persenHematDedup,
  labelKejadian,
  kejadianBermasalah,
  nodeLayakMenerimaReplika,
} from '../src/lib/dfsx/dfsx-core.mjs';

test('Sanitasi Nama Berkas DFS-X (Pemisah Path & Karakter Terlarang)', () => {
  // Master menolak nama yang mengandung pemisah path, jadi hanya komponen
  // terakhir yang boleh lolos.
  assert.equal(namaDfsxAman('video hasil.mp4'), 'video hasil.mp4');
  assert.equal(namaDfsxAman('folder/rahasia/laporan.pdf'), 'laporan.pdf');
  assert.equal(namaDfsxAman('C:\\Users\\ASUS\\berkas.mp3'), 'berkas.mp3');
  assert.equal(namaDfsxAman('../../etc/passwd'), 'passwd');
  // Enam karakter terlarang setelah "ilegal": > : " | ? *
  assert.equal(namaDfsxAman('judul<ilegal>:"|?*.mp4'), 'judul_ilegal______.mp4');
  assert.equal(namaDfsxAman(''), 'berkas');
  assert.equal(namaDfsxAman('...'), 'berkas');
  assert.equal(namaDfsxAman(undefined), 'berkas');
  // Nama panjang dipotong agar tidak melampaui batas nama berkas.
  assert.equal(namaDfsxAman('a'.repeat(300)).length, 180);
});

test('Format Ukuran Berkas untuk Dashboard', () => {
  assert.equal(formatUkuran(0), '0 B');
  assert.equal(formatUkuran(null), '0 B');
  assert.equal(formatUkuran(900), '900 B');
  assert.equal(formatUkuran(4 * 1024 * 1024), '4.0 MB');
  assert.equal(formatUkuran(50 * 1024 * 1024), '50.0 MB');
  assert.equal(formatUkuran(1024 * 1024 * 1024), '1.0 GB');
});

test('Hitung Persentase Hemat Deduplikasi', () => {
  // Dua berkas identik 16 MB: 32 MB dirujuk, 16 MB dihemat.
  assert.equal(persenHematDedup(32 * 1024 * 1024, 16 * 1024 * 1024), 50);
  // Berkas seluruhnya unik tidak menghemat ruang sama sekali.
  assert.equal(persenHematDedup(32 * 1024 * 1024, 0), 0);
  // Pembagi nol tidak boleh menghasilkan NaN atau Infinity di dashboard.
  assert.equal(persenHematDedup(0, 0), 0);
});

test('Label dan Penandaan Kejadian Log Master', () => {
  assert.equal(labelKejadian('self_healing'), 'Pemulihan Otomatis');
  assert.equal(labelKejadian('node_mati'), 'Node Mati');
  // Jenis kejadian yang belum dikenal tetap ditampilkan apa adanya,
  // bukan disembunyikan dari pengguna.
  assert.equal(labelKejadian('kejadian_baru'), 'kejadian_baru');

  assert.equal(kejadianBermasalah('node_mati'), true);
  assert.equal(kejadianBermasalah('tulis_ditolak'), true);
  assert.equal(kejadianBermasalah('hash_tidak_cocok'), true);
  assert.equal(kejadianBermasalah('versi_disimpan'), false);
  assert.equal(kejadianBermasalah('self_healing'), false);
});

test('Kelayakan Node Menerima Replika Baru (Replikasi Adaptif)', () => {
  const total = 8192 * 1024 * 1024;
  const sehat = {
    status: 'hidup',
    kapasitas_total: total,
    kapasitas_terpakai: total * 0.4,
  };
  const hampirPenuh = {
    status: 'hidup',
    kapasitas_total: total,
    kapasitas_terpakai: total * 0.9,
  };
  const mati = {
    status: 'mati',
    kapasitas_total: total,
    kapasitas_terpakai: 0,
  };

  assert.equal(nodeLayakMenerimaReplika(sehat), true);
  assert.equal(nodeLayakMenerimaReplika(hampirPenuh), false);
  // Node mati tidak layak walau kapasitasnya kosong.
  assert.equal(nodeLayakMenerimaReplika(mati), false);
  assert.equal(nodeLayakMenerimaReplika(null), false);
  // Ambang dapat dikonfigurasi, sejalan dengan CAPACITY_WARN_RATIO.
  assert.equal(nodeLayakMenerimaReplika(hampirPenuh, 0.95), true);
});

test('Chunking 4 MB dan Verifikasi Hash SHA-256 Hasil Rakitan', () => {
  // Meniru alur inti DFS-X: potong berkas, hitung hash tiap chunk, lalu
  // rakit ulang dan bandingkan hash berkas utuh.
  const CHUNK = 4 * 1024 * 1024;
  const asal = crypto.randomBytes(10 * 1024 * 1024);
  const hashAsal = crypto.createHash('sha256').update(asal).digest('hex');

  const potongan = [];
  for (let mulai = 0; mulai < asal.length; mulai += CHUNK) {
    const bagian = asal.subarray(mulai, Math.min(mulai + CHUNK, asal.length));
    potongan.push({
      urutan: potongan.length,
      hash: crypto.createHash('sha256').update(bagian).digest('hex'),
      isi: bagian,
    });
  }

  // Berkas 10 MB dengan chunk 4 MB menghasilkan 3 chunk: 4, 4, dan 2 MB.
  assert.equal(potongan.length, 3);
  assert.equal(potongan[2].isi.length, 2 * 1024 * 1024);
  // Setiap hash chunk harus hex 64 karakter, karena dipakai sebagai nama
  // berkas di data node.
  for (const p of potongan) {
    assert.match(p.hash, /^[0-9a-f]{64}$/);
  }

  // Urutan sengaja diacak untuk memastikan perakitan bergantung pada
  // nomor urut yang dicatat master, bukan pada urutan kedatangan chunk.
  const teracak = [...potongan].reverse();
  const dirakit = Buffer.concat(
    teracak.sort((a, b) => a.urutan - b.urutan).map((p) => p.isi)
  );

  assert.equal(dirakit.length, asal.length);
  assert.equal(crypto.createHash('sha256').update(dirakit).digest('hex'), hashAsal);
});

test('Deduplikasi Chunk Berbasis Hash Identik', () => {
  const CHUNK = 4 * 1024 * 1024;
  const chunkA = crypto.randomBytes(CHUNK);
  const chunkB = crypto.randomBytes(CHUNK);
  const hash = (b) => crypto.createHash('sha256').update(b).digest('hex');

  // Isi yang sama selalu menghasilkan hash yang sama, dan itulah dasar
  // deduplikasi: chunk kedua tidak perlu ditulis fisik lagi.
  assert.equal(hash(chunkA), hash(Buffer.from(chunkA)));
  assert.notEqual(hash(chunkA), hash(chunkB));

  // Dua berkas yang separuh isinya sama hanya menyimpan chunk unik.
  const berkas1 = [chunkA, chunkB];
  const berkas2 = [chunkA, crypto.randomBytes(CHUNK)];
  const gudang = new Set();
  let ditulis = 0;
  let didedup = 0;
  for (const chunk of [...berkas1, ...berkas2]) {
    const h = hash(chunk);
    if (gudang.has(h)) {
      didedup += 1;
    } else {
      gudang.add(h);
      ditulis += 1;
    }
  }

  assert.equal(ditulis, 3);
  assert.equal(didedup, 1);
  assert.equal(persenHematDedup(4 * CHUNK, CHUNK), 25);
});
