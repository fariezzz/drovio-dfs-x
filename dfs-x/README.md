# DFS-X Drovio

Sistem penyimpanan berkas terdistribusi dengan deduplikasi, consistency
control, versioning, replikasi adaptif, dan self-healing berbasis
monitoring real-time.

DFS-X adalah lapisan penyimpanan Drovio. Drovio tetap menjadi aplikasi
pengunduh, pengonversi, dan pemampat media di lapisan atas, sedangkan
seluruh berkas hasilnya disimpan dan diambil kembali dari DFS-X. Folder
unduhan lokal hanya dipakai sebagai area kerja sementara.

| Keterangan | Isi |
| --- | --- |
| Mata kuliah | Komputasi Paralel dan Terdistribusi, 3 SKS |
| Tugas | UAS ganjil 2026/2027, Tema 5: Cloud-based Distributed File Storage |
| Kelompok | Kelompok 2 |
| Penyusun | Muhammad Fariez Riziq Ilham, NIM 247006111146, Kelas E |
| Program studi | Informatika, Fakultas Teknik, Universitas Siliwangi |
| Dosen pengampu | Ir. Randi Rizal, Ph.D. |

---

## 1. Arsitektur

Sistem terdiri dari satu master node dan minimal tiga data node, masing
masing berjalan sebagai container terpisah dengan volume penyimpanan
sendiri.

```
                   Drovio (Next.js, port 48888)
                   src/lib/dfsx/  adapter penyimpanan
                              |
                              v
        +---------------- Master node (port 9100) ----------------+
        |  Metadata SQLite: berkas, versi, chunk, hash, replika   |
        |  Penempatan chunk, consistency control, self-healing    |
        +---------------------------------------------------------+
            |                    |                     |
            v                    v                     v
      datanode-1           datanode-2            datanode-3
      isi chunk            isi chunk             isi chunk
      heartbeat 5 detik    heartbeat 5 detik     heartbeat 5 detik
```

Pembagian peran:

- **Master node menyimpan metadata, bukan isi berkas.** Master mencatat
  daftar berkas, nomor versi, urutan chunk, hash SHA-256, lokasi replika,
  status node, dan log aktivitas. Isi chunk tidak pernah masuk ke basis
  data master.
- **Data node menyimpan isi chunk saja.** Data node tidak tahu apa pun
  tentang berkas, versi, atau urutan chunk. Pengetahuan itu milik master.
- **Pemulihan berjalan antar data node.** Saat self-healing, master hanya
  memerintahkan node tujuan menarik chunk dari node sumber, sehingga isi
  chunk tidak melewati master.

### Pilihan teknologi dan alasannya

| Aspek | Pilihan | Alasan |
| --- | --- | --- |
| Protokol antar-node | REST di atas HTTP | Lebih mudah diperiksa saat demo dengan curl dan dashboard, dan tidak memerlukan kompilasi stub seperti gRPC |
| Bahasa layanan | Python, hanya pustaka standar | Image tetap kecil dan dapat dibangun tanpa akses PyPI, penting saat 16 node berjalan di satu laptop |
| Metadata | SQLite dengan mode WAL | Cukup untuk satu master, tanpa layanan basis data tambahan |
| Hash | SHA-256 | Dipakai sebagai identitas chunk sekaligus alat verifikasi keutuhan |
| Orkestrasi | Docker Compose dengan profil | Jumlah node diubah lewat profil, tanpa berkas compose terpisah |

Keterbatasan desain yang disadari: master node adalah titik gagal tunggal.
Bila master mati, metadata tidak dapat diakses walaupun isi chunk masih
ada di data node. Replikasi master berada di luar ruang lingkup pekerjaan
ini.

---

## 2. Menjalankan sistem dari nol

### Prasyarat

- Docker Desktop aktif. Di WSL, perintah yang dipakai adalah `docker.exe`
  bila integrasi WSL pada Docker Desktop tidak dinyalakan.
- Python 3.10 atau lebih baru untuk menjalankan skrip pengujian dari host.
- Ruang disk kosong. Pengujian 100 berkas berukuran 50 MB dengan faktor
  replikasi 2 membutuhkan sekitar 15 GB termasuk replika.

### Langkah menjalankan

```bash
cd dfs-x
cp config/.env.example config/.env
docker compose --env-file config/.env up -d --build
```

Periksa bahwa master hidup dan ketiga data node terdaftar:

```bash
curl http://127.0.0.1:9100/health
```

Keluaran yang diharapkan menunjukkan `node_hidup` bernilai 3:

```json
{"status": "hidup", "peran": "master", "node_hidup": 3, "node_total": 3,
 "chunk_size": 4194304, "replication_factor": 2, "min_replicas": 2,
 "replikasi_adaptif": true}
```

Menghentikan sistem:

```bash
docker compose --env-file config/.env down          # hentikan container
docker compose --env-file config/.env down -v       # hapus juga volume
```

### Mengubah jumlah data node

Profil compose menyediakan konfigurasi 4, 8, dan 16 node:

```bash
docker compose --env-file config/.env --profile n4 up -d     # 4 node
docker compose --env-file config/.env --profile n8 up -d     # 8 node
docker compose --env-file config/.env --profile n16 up -d    # 16 node
docker compose --env-file config/.env stop datanode-3        # turun ke 2 node
```

### Menjalankan Drovio di atas DFS-X

Dari akar proyek:

```bash
npm install
npm run build
npm run start
```

Drovio berjalan di `http://127.0.0.1:48888`, dan dashboard DFS-X ada di
`http://127.0.0.1:48888/dfsx`. Konfigurasi integrasi berada di `.env.local`
pada akar proyek, dengan nilai bawaan `DFSX_MASTER_URL=http://127.0.0.1:9100`.

---

## 3. Konfigurasi

Seluruh nilai yang dapat berubah diatur lewat `config/.env`, tanpa
menyentuh kode layanan. Berkas `config/.env.example` memuat nilai awal
beserta penjelasannya.

| Variabel | Nilai awal | Keterangan |
| --- | --- | --- |
| `CHUNK_SIZE_MB` | 4 | Ukuran potongan berkas. Cukup besar untuk menekan jumlah permintaan HTTP per berkas 50 MB, cukup kecil agar sebaran chunk tetap merata |
| `REPLICATION_FACTOR` | 2 | Jumlah salinan setiap chunk. Nilai 2 memenuhi syarat toleransi 1 node mati |
| `MIN_REPLICAS` | 2 | Replika minimum yang harus tertulis sebelum penulisan diakui |
| `HEARTBEAT_INTERVAL_SECONDS` | 5 | Jeda heartbeat data node ke master |
| `NODE_DEAD_THRESHOLD_SECONDS` | 15 | Ambang node dinyatakan mati, yaitu tiga kali jeda heartbeat |
| `HEAL_INTERVAL_SECONDS` | 5 | Jeda antar siklus self-healing |
| `ADAPTIVE_REPLICATION` | 1 | Penempatan replika mempertimbangkan kapasitas dan kesehatan node |
| `CAPACITY_WARN_RATIO` | 0.85 | Rasio pemakaian yang membuat node dianggap hampir penuh |
| `NODE_CAPACITY_MB` | 8192 | Kapasitas logis per data node |
| `MASTER_IO_WORKERS` | 8 | Pekerja paralel master saat menyebar dan merakit chunk |
| `CHUNK_READ_TIMEOUT_SECONDS` | 10 | Batas waktu membaca satu chunk dari satu replika |

Konfigurasi aktif dapat diperiksa lewat `GET /config` pada master.

---

## 4. Cara enam kemampuan inti bekerja

### 4.1 Pemotongan berkas dan distribusi chunk

Berkas dipecah menjadi chunk berukuran tetap 4 MB. Master mencatat urutan
chunk beserta node penyimpannya, lalu saat dibaca chunk diambil dari data
node dan dirakit sesuai urutan. Hash SHA-256 berkas hasil rakitan
dibandingkan dengan hash berkas asal, dan ketidakcocokan diperlakukan
sebagai kegagalan, bukan peringatan.

### 4.2 Replikasi dan fault tolerance

Setiap chunk disimpan di dua data node. Saat satu node mati, pembacaan
beralih ke replika di node lain. Daftar replika diurutkan dari heartbeat
terbaru, sehingga node yang baru berhenti tetapi belum ditandai mati tidak
dicoba lebih dulu. Batas waktu baca per replika dibuat pendek agar
pembacaan cepat berpindah ke replika berikutnya.

### 4.3 Deduplikasi konten

Sebelum chunk disimpan, hash SHA-256-nya dihitung. Bila hash itu sudah ada
dan masih memiliki replika aktif di node yang hidup, chunk fisik tidak
ditulis lagi dan sistem hanya mencatat referensi baru. Syarat "masih
memiliki replika aktif" penting: tanpa itu, deduplikasi bisa menunjuk ke
chunk yang isinya sudah tidak ada di mana pun.

### 4.4 Consistency control dan versioning

Penulisan hanya diakui setelah replika minimum setiap chunk terpenuhi.
Pada jalur dua tahap, master memverifikasi ulang keadaan replika saat
commit, bukan mempercayai laporan klien, dan menolak dengan HTTP 409 bila
masih ada chunk di bawah replika minimum. Nomor versi diberikan master
dalam satu transaksi terkunci, sehingga urutan versi tetap teratur.

Versioning bekerja di tingkat berkas. Berkas bernama sama yang disimpan
ulang menjadi versi baru dengan penomoran v1, v2, v3, bukan menimpa versi
lama. Rollback hanya mengganti penunjuk versi aktif, jadi biayanya tetap
dan tindakannya dapat dibalik.

### 4.5 Replikasi adaptif

Node tujuan replika diurutkan dari yang paling lega dan paling sehat,
memakai rasio pemakaian kapasitas agar node berkapasitas berbeda tetap
dibandingkan secara adil. Pilihan penempatan dicatat sebagai beban
sementara, sehingga chunk berikutnya dalam unggahan yang sama diarahkan ke
node lain. Tanpa catatan beban ini, seluruh chunk satu berkas akan
menumpuk di node yang sama karena skor kapasitas baru berubah setelah
heartbeat berikutnya masuk.

Saat memulihkan replika, chunk dengan salinan paling sedikit dikerjakan
lebih dulu.

### 4.6 Self-healing dan monitoring

Master menilai node mati dari jeda heartbeat terakhir, bukan dari
percobaan koneksi, agar waktu deteksi dapat dijelaskan langsung dengan
ambang yang dikonfigurasi. Setelah node ditandai mati, siklus self-healing
membuat replika pengganti di node yang masih hidup sampai faktor replikasi
pulih. Seluruh prosesnya tercatat di log aktivitas dan tampil di dashboard
tanpa perlu dimuat ulang manual.

---

## 5. Kontrak API

### Master node (port 9100)

| Fungsi | Method dan path | Keterangan |
| --- | --- | --- |
| Rencana penempatan chunk | `POST /files` | Daftarkan berkas, balas node tujuan per chunk dan tandai chunk hasil deduplikasi |
| Sahkan versi baru | `POST /files/{file_id}/commit` | Verifikasi replika minimum, lalu catat metadata versi |
| Simpan berkas utuh | `PUT /files/content?nama=<nama>` | Jalur ringkas: master memotong dan menyebarkan chunk sendiri |
| Metadata berkas | `GET /files/{file_id}` | Versi aktif, daftar versi, daftar chunk, lokasi replika |
| Ambil isi berkas | `GET /files/{file_id}/content` | Rakit ulang chunk dan verifikasi hash hasil rakitan |
| Ambil versi tertentu | `GET /files/{file_id}/content?version={n}` | Unduh versi lama tanpa mengubah versi aktif |
| Daftar berkas | `GET /files` | Seluruh berkas beserta versi aktifnya |
| Daftar versi | `GET /files/{file_id}/versions` | Riwayat versi satu berkas |
| Rollback versi aktif | `POST /files/{file_id}/rollback` | Body `{"versi": n}` |
| Hapus berkas | `DELETE /files/{file_id}` | Hapus seluruh versi dan chunk yang tidak lagi dirujuk |
| Lokasi replika chunk | `GET /chunks/{chunk_hash}/locations` | Daftar node pemilik satu chunk |
| Terima heartbeat | `POST /nodes/heartbeat` | Dipanggil data node secara berkala |
| Status sistem | `GET /status` | Status node, statistik, peta replika, log aktivitas, keadaan self-healing |
| Konfigurasi aktif | `GET /config` | Nilai konfigurasi yang sedang dipakai |
| Kesehatan layanan | `GET /health` | Ringkasan singkat untuk pemeriksaan cepat |
| Pemulihan manual | `POST /maintenance/heal` | Jalankan satu siklus self-healing segera |
| Bersihkan metadata | `POST /maintenance/reset` | Hapus seluruh berkas agar pengujian mulai dari nol |

### Data node (port 9101, dipetakan ke 9101 sampai 9103 di host)

| Fungsi | Method dan path | Keterangan |
| --- | --- | --- |
| Simpan chunk | `PUT /chunks/{chunk_hash}` | Isi chunk biner, diverifikasi hash sebelum ditulis |
| Ambil chunk | `GET /chunks/{chunk_hash}` | Isi chunk biner |
| Hapus chunk | `DELETE /chunks/{chunk_hash}` | Dipakai saat berkas dihapus |
| Tarik chunk dari node lain | `POST /chunks/{chunk_hash}/tarik` | Dipakai master saat self-healing |
| Daftar chunk | `GET /chunks` | Seluruh hash chunk yang tersimpan di node ini |
| Kesehatan node | `GET /health` | Status, jumlah chunk, kapasitas total dan terpakai |

### API DFS-X di sisi Drovio

| Fungsi | Method dan path |
| --- | --- |
| Status untuk dashboard | `GET /api/dfsx/status` |
| Daftar berkas | `GET /api/dfsx/files` |
| Daftar versi | `GET /api/dfsx/files/{fileId}/versions` |
| Rollback versi | `POST /api/dfsx/files/{fileId}/versions` |
| Unduh berkas | `GET /api/dfsx/files/{fileId}/content?versi={n}` |

Ketiga endpoint unduh Drovio yang sudah ada, yaitu `/api/jobs/{id}/file`,
`/api/convert/{id}/file`, dan `/api/compress/{id}/file`, mengambil berkas
dari DFS-X lebih dulu dan menyertakan header `X-Sumber-Berkas: dfs-x`.
Berkas di area kerja lokal hanya dipakai sebagai cadangan bila DFS-X belum
menyimpan berkas itu atau sedang tidak dapat dihubungi.

---

## 6. Menjalankan pengujian

Seluruh pengujian memakai berkas dummy lokal berukuran terkontrol. Berkas
video hasil Drovio hanya dipakai untuk demo aplikasi, bukan untuk angka
pengujian.

Siapkan variabel lingkungan lebih dulu. Di WSL dengan Docker Desktop,
`DOCKER_BIN` perlu diarahkan ke `docker.exe`:

```bash
cd dfs-x/tests
export MASTER_URL=http://127.0.0.1:9100
export DUMMY_DIR=$HOME/dfsx-dummy
export DOCKER_BIN=docker.exe        # hanya di WSL
```

### Membuat berkas dummy

```bash
python3 make_dummy_files.py --jumlah 100 --ukuran-mb 50 --bersihkan
```

Isi berkas dibuat acak dan unik per berkas, sehingga tidak terdeduplikasi
dan angka throughput mencerminkan pemindahan data yang sebenarnya.

### Upload dan download massal, speedup, efisiensi, latency

```bash
python3 test_upload_download.py --jumlah 100 --paralel 4
python3 test_upload_download.py --jumlah 100 --paralel 4 --lewati-speedup
```

### Fault tolerance dan self-healing

```bash
python3 test_fault_tolerance.py --jumlah 10 --node dfsx-datanode-2
```

Skrip mematikan satu data node di tengah pengujian, melanjutkan download,
lalu mencatat waktu deteksi dan waktu pemulihan replikasi.

### Deduplikasi dan versioning

```bash
python3 test_dedup_versioning.py --ukuran-mb 16 --ulangi 3
```

### Skalabilitas 2, 4, 8, dan 16 node

```bash
python3 test_scalability.py --jumlah 10 --paralel 4 --node-list 2,4,8,16
```

### Grafik hasil pengujian

```bash
python3 make_charts.py
```

Grafik ditulis sebagai SVG memakai pustaka standar Python, tanpa
matplotlib, sehingga pengujian tidak memerlukan pemasangan paket tambahan.

Berkas hasil tersimpan di `tests/results/`: data mentah JSON dan CSV di
`raw/`, grafik di `charts/`, dan tangkapan layar dashboard di
`screenshots/`.

### Dua mode klien pengujian

Mode yang dipakai selalu dicatat di berkas hasil agar angka tidak salah
ditafsirkan.

| Mode | Cara kerja | Kapan dipakai |
| --- | --- | --- |
| `ringkas` | Klien mengirim berkas utuh ke master, master memotong dan menyebarkan chunk | Dapat dijalankan dari host. Jalur ini yang dipakai integrasi Drovio |
| `dua_tahap` | Klien memotong berkas dan mengunggah chunk langsung ke data node secara paralel | Mengukur paralelisme penyimpanan yang sebenarnya, hanya bisa dari dalam jaringan Docker karena alamat data node adalah nama container |

Mode dipilih otomatis berdasarkan keterjangkauan alamat data node, dan
dapat dipaksa dengan `--mode ringkas` atau `--mode dua_tahap`.

---

## 7. Hasil yang sudah diverifikasi

Angka berikut berasal dari pengujian nyata di laptop penyusun pada
19 November 2026, dengan konfigurasi 1 master dan 3 data node, chunk 4 MB,
faktor replikasi 2, dan mode klien `ringkas`.

Pengujian ini memakai berkas dummy berukuran 8 MB sebagai uji fungsi,
bukan angka final untuk laporan. Pengujian resmi Bab 11 PRD, yaitu
100 berkas berukuran 50 MB dan skalabilitas sampai 16 node, dijalankan
pada tahap pengujian penuh.

### Inti DFS-X

| Pengujian | Hasil |
| --- | --- |
| Chunking dan rakit ulang | Berkas 20 MB menjadi 5 chunk, hash SHA-256 hasil rakitan cocok |
| Sebaran replika | datanode-1 3 chunk, datanode-2 2 chunk, datanode-3 5 chunk |
| Upload massal, 6 berkas | 6 dari 6 berhasil, 0,98 detik, 49,09 MB/s |
| Download massal, 6 berkas | 6 dari 6 lolos verifikasi hash, 0,39 detik, 122,92 MB/s |
| Speedup upload, paralel 3 | S 1,752, E 0,584 |
| Speedup download, paralel 3 | S 1,658, E 0,553 |

### Fault tolerance dan self-healing

| Pengukuran | Hasil |
| --- | --- |
| Download saat 1 data node mati | 6 dari 6 lolos verifikasi hash, 103,58 MB/s |
| Waktu deteksi node mati | 14,47 detik sejak perintah mematikan container, dengan ambang 15 detik |
| Chunk kehilangan salinan | 9 chunk |
| Chunk dipulihkan otomatis | 9 chunk, 0 gagal |
| Waktu replikasi pulih penuh | 20,51 detik sejak perintah mematikan container |
| Download setelah pemulihan | 6 dari 6 lolos verifikasi hash |

Catatan perbaikan yang dilakukan setelah pengujian pertama: pada
percobaan awal, pembacaan saat satu node mati melambat ke 2,90 MB/s karena
master masih mencoba node yang belum ditandai mati dan menunggu batas
waktu 120 detik. Setelah daftar replika diurutkan dari heartbeat terbaru
dan batas waktu baca per replika diturunkan ke 10 detik, pembacaan dalam
keadaan yang sama mencapai 103,58 MB/s.

### Deduplikasi

| Pengukuran | Hasil |
| --- | --- |
| Berkas sama diunggah 3 kali, @16 MB | Unggahan 2 dan 3 mendeduplikasi seluruh 4 chunk |
| Ruang fisik unik | 16 MB, tetap, walau ukuran logis 48 MB |
| Ruang dihemat | 32 MB setelah unggahan ketiga |
| Berkas berbeda, separuh isi sama | 2 dari 4 chunk terdeduplikasi |
| Berkas yang isinya seluruhnya unik | 0 chunk terdeduplikasi, sesuai harapan |
| Keutuhan berkas terdeduplikasi | Hash hasil rakitan cocok dengan berkas asal |

### Versioning

| Pengukuran | Hasil |
| --- | --- |
| Simpan ulang nama sama | Menjadi v1, v2, v3, tanpa menimpa versi lama |
| Unduh tiap versi | v1, v2, v3 semuanya lolos verifikasi hash |
| Rollback ke v1 | Berhasil, unduhan tanpa nomor versi mengembalikan isi v1 |

### Skalabilitas

| Node | Upload detik | Download detik | Upload MB/s | Download MB/s | S upload | E upload | S download | E download |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 0,47 | 0,22 | 103,16 | 214,67 | 1,788 | 0,894 | 2,080 | 1,040 |
| 4 | 0,43 | 0,24 | 112,05 | 202,79 | 1,942 | 0,485 | 1,964 | 0,491 |

Efisiensi turun dari 0,894 ke 0,485 saat node bertambah dari 2 ke 4.
Penyebabnya adalah ukuran data uji yang kecil, 48 MB total, sehingga
waktu koordinasi master lebih besar porsinya dibanding waktu pemindahan
data. Nilai E download 1,040 pada 2 node melebihi 1 karena pembacaan
sebagian terlayani dari cache sistem berkas. Keduanya dilaporkan apa
adanya, dan pengujian dengan 100 berkas berukuran 50 MB diperlukan untuk
menilai skalabilitas secara layak.

### Integrasi Drovio

| Pengujian | Hasil |
| --- | --- |
| Kompresi gambar lewat Drovio | 56,54 KB menjadi 25,60 KB, hemat 54,7 persen |
| Berkas hasil masuk DFS-X | file_id tercatat, 1 chunk, versi 1 |
| Unduh hasil dari Drovio | HTTP 200 dengan header `X-Sumber-Berkas: dfs-x` dan `X-DFSX-Versi: 1` |

Yang belum diuji ujung ke ujung: unduhan media dari tautan publik melalui
yt-dlp dan konversi berkas, karena keduanya memerlukan jaringan ke
platform sumber. Jalur kodenya sama dengan kompresi, yaitu memakai
`arsipkanKeDfsx` pada titik pekerjaan selesai, tetapi belum dijalankan
dengan tautan nyata.

---

## 8. Pemecahan masalah

| Gejala | Penyebab dan penanganan |
| --- | --- |
| `docker: command not found` di WSL | Integrasi WSL pada Docker Desktop tidak aktif. Pakai `docker.exe`, dan set `DOCKER_BIN=docker.exe` untuk skrip pengujian |
| Container keluar dengan kode 137 | Kehabisan memori. Perintah seperti `npm run build` dapat memicunya di WSL berkapasitas kecil. Jalankan ulang dengan `docker compose up -d` dan hindari build berat saat 16 node berjalan |
| `couldn't find env file: C:\mnt\c\...` | `docker.exe` tidak mengerti path WSL. Pakai path relatif untuk `--env-file`, misalnya `config/.env` |
| Dashboard menampilkan "Master DFS-X tidak dapat dihubungi" | Container master belum berjalan. Periksa dengan `docker compose ps`, lalu `docker compose --env-file config/.env up -d` |
| `POST /files` menjawab 503 | Jumlah data node hidup lebih sedikit dari `MIN_REPLICAS`. Hidupkan data node, atau turunkan `MIN_REPLICAS` secara sadar |
| `commit` menjawab 409 | Consistency control menolak penulisan karena ada chunk di bawah replika minimum. Periksa kesehatan data node, lalu ulangi penulisan |
| Seluruh chunk menumpuk di satu node | Pastikan `ADAPTIVE_REPLICATION=1`. Catatan beban sementara di master memerlukan heartbeat yang berjalan normal |
| Uji skalabilitas melaporkan jumlah node lebih sedikit dari yang diminta | Container profil belum selesai naik atau node belum melewati ambang heartbeat. Hasil tetap dicatat sesuai jumlah node yang benar-benar hidup |

---

## 9. Struktur berkas

```text
dfs-x/
  docker-compose.yml        1 master, 16 data node lewat profil n4, n8, n16
  README.md                 dokumen ini
  common/
    dfsx_core.py            konfigurasi, hash, HTTP, pencatat log
    http_mini.py            server dan perute HTTP berbasis pustaka standar
  master/
    Dockerfile
    app.py                  penempatan chunk, consistency control, self-healing
    metadata.py             skema dan kueri metadata SQLite
  datanode/
    Dockerfile
    app.py                  simpan, baca, hapus, tarik chunk, dan heartbeat
  config/
    .env.example            konfigurasi awal beserta penjelasannya
  tests/
    lib_uji.py              klien pengujian dan penulis hasil
    make_dummy_files.py     pembuat berkas dummy
    test_upload_download.py upload, download, speedup, efisiensi, latency
    test_fault_tolerance.py fault tolerance dan self-healing
    test_dedup_versioning.py deduplikasi dan versioning
    test_scalability.py     skalabilitas 2, 4, 8, 16 node
    make_charts.py          pembuat grafik SVG
    results/raw             data mentah JSON dan CSV
    results/charts          grafik hasil pengujian
    results/screenshots     tangkapan layar dashboard
```

Berkas di sisi Drovio:

```text
src/lib/dfsx/
  client.ts                 adapter HTTP ke master DFS-X
  registry.ts               pemetaan hasil Drovio ke berkas DFS-X
  archive.ts                pengarsipan berkas hasil ke DFS-X
  format.ts                 tipe dan pembantu tampilan dashboard
src/app/dfsx/page.tsx       halaman dashboard monitoring
src/app/api/dfsx/           API status, daftar berkas, versi, dan unduhan
src/components/dfsx/        panel node, statistik, peta replika, log, berkas
```
