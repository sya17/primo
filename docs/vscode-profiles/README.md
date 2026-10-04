# Profiles VS Code untuk Primo

Delapan profil lokal: General, Spring Boot, Flutter, Nuxt, Next.js, Python, Rust,
dan Go. Tema/font diambil dari pengaturan tampilan saat profil dibuat. Profil
memisahkan ekstensi bahasa; tidak memasukkan akun maupun kredensial.

## Pasang

1. Tutup semua jendela VS Code, lalu jalankan di terminal desktop:

   ```bash
   python3 ~/workspace/hyperland/scripts/setup-vscode-profile-privacy.py
   ```

   Pengaturan lama dibackup sebelum diubah. Script membaca JSON biasa; bila
   settings.json memakai komentar/trailing commas, script berhenti tanpa mengubah
   file. Atur enam preferensi di dalam script melalui Settings VS Code sebagai gantinya.

2. Buka VS Code. Pilih **File > Preferences > Profiles > Import Profile**,
   lalu pilih berkas `.code-profile` di folder ini dan klik **Create/Import**.
   Impor profil yang dibutuhkan; ulangi untuk profil lain.
3. Tema Primo dibuat lokal dan tidak ada di Marketplace. Untuk setiap profil
   yang sudah diimpor, pasang tema lokal, misalnya:

   ```bash
   code --profile "Spring Boot" --install-extension ~/workspace/hyperland/vscode/primo-themes-0.1.0.vsix
   ```

   Ganti nama dengan Flutter, Nuxt, Next.js, Python, Rust, Go atau General.
   Tokyo Night dan Material Icon Theme tersedia melalui Marketplace.
4. Buka folder proyek, lalu pilih **Profiles: Switch Profile** melalui
   `Ctrl+Shift+P`. VS Code mengingat asosiasi profil untuk folder tersebut.

   ```bash
   code --profile "Spring Boot" /path/ke/backend
   code --profile "Nuxt" /path/ke/frontend
   ```

## Isi profil

| Profil | Tooling |
|---|---|
| General | Tema dan ikon, editing biasa |
| Spring Boot | Java, debugger, test runner, Maven, Gradle, Spring Boot/dashboard/Initializr |
| Flutter | Dart, Flutter, debugger dan tooling test dari Dart Code |
| Nuxt | Vue Official, Nuxtr, MDC, ESLint, Prettier |
| Next.js | JS/TS dan debugger bawaan VS Code, ESLint, Prettier |
| Python | Python, Pylance, debugpy, Ruff; interpreter `.venv` lokal |
| Rust | rust-analyzer, CodeLLDB |
| Go | Ekstensi resmi Go |

Prettier hanya berjalan jika proyek memiliki konfigurasi Prettier. Tidak ada
konfigurasi format proyek yang diubah. Next memakai tooling React/TypeScript
bawaan; plugin Next.js milik framework mengikuti konfigurasi proyek.

## Privasi dan runtime

Telemetry VS Code/Red Hat dan eksperimen dimatikan; fitur AI bawaan serta Git
autofetch dimatikan. Script diperlukan karena beberapa pengaturan berlaku untuk
seluruh aplikasi dan tidak selalu diterapkan oleh impor profil. Biarkan Settings
Sync nonaktif. Profil tidak memindahkan atau menghapus ekstensi Default.

Impor ekstensi mengakses Marketplace; runtime, dependency dan language server
bisa memerlukan unduhan. Pengaturan ini bukan blokir seluruh koneksi internet,
dan telemetry ekstensi pihak ketiga perlu diperiksa terpisah.

SDK/runtime tidak dipasang oleh profil: gunakan mise untuk Java/Node/Go, Flutter
SDK untuk Flutter, uv untuk Python, dan rustup untuk Rust. Untuk Python jalankan
`uv sync` pada proyek yang sudah memakai uv, atau `uv venv` untuk membuat `.venv`.
Runtime Java proyek mengikuti Maven/Gradle; jangan hardcode lokasi JDK global.

Regenerasi berkas profil jika tampilan Default berubah:

```bash
python3 ~/workspace/hyperland/scripts/gen-vscode-profiles.py
```

Perubahan tema melalui script Hyprland yang hanya menyentuh profil Default belum
tentu otomatis diterapkan pada profil bahasa yang memiliki pengaturan sendiri.
