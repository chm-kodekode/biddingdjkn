@echo off
echo [*] Menjalankan Scraper Lelang di Laptop...
python scrapper_lelang.py

echo [*] Mengatur identitas Git...
git config user.email "aryo.w13@gmail.com"
git config user.name "chm-kodekode"

echo [*] Mengunggah data terbaru ke GitHub Pages...
git add data.json hasil_lelang_mobil.csv
git commit -m "update data lelang mobil"
git push origin main

echo.
echo [OK] Selesai! Data berhasil diunggah. Web akan terupdate dalam 1 menit.
pause