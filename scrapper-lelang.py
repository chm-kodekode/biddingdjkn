import csv
import json
import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

KATEGORI = "Mobil"
MAX_PAGES = 2  # Ubah sesuai kebutuhan (1 halaman = 16 unit)
ENDPOINT = "https://api.lelang.go.id/api/v1/landing-page/katalog-lot-lelang"

def load_kpknl_map(session):
    kpknl_map = {}
    urls = [
        "https://api.lelang.go.id/api/v1/landing-page/kpknl?sortby=nama&sortdir=asc",
        "https://api.lelang.go.id/api/v1/kpknl?sortby=nama&sortdir=asc",
    ]
    for url in urls:
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    if isinstance(item, dict):
                        kid = str(item.get("id") or "").strip().lower()
                        nama = item.get("nama") or item.get("namaKpknl") or item.get("uraian")
                        if kid and nama:
                            kpknl_map[kid] = str(nama).strip()
                if kpknl_map:
                    break
        except Exception:
            continue
    return kpknl_map

def extract_title(item):
    candidates = ["deskripsi", "uraian", "deskripsibarang", "uraianbarang", "objeklelang", "namabarang", "judul", "nama"]
    for c in candidates:
        for k, v in item.items():
            if c in k.lower() and isinstance(v, str) and len(v.strip()) > 5:
                clean = re.sub(r"<[^>]+>", "", v).strip()
                lines = [ln.strip() for ln in clean.split("\n") if ln.strip()]
                if lines:
                    return lines[0]
    return "-"

def parse_specs_from_text(text):
    if not text:
        return "-", "-", "-", "-"
    text_clean = str(text)

    # 1. Nomor Polisi
    nopol = "-"
    m_pol = re.search(r'(?:nomor\s*polisi|no\.?\s*polisi|nopol|plat(?:\s*nomor)?)\s*[:\s\-]*([a-zA-Z]{1,2}\s*\d{1,4}\s*[a-zA-Z]{1,3})', text_clean, re.I)
    if m_pol:
        nopol = re.sub(r'\s+', ' ', m_pol.group(1)).strip().upper()
    else:
        plate_codes = r'KT|B|D|F|BK|L|AB|AD|BG|DA|BM|DK|DH|DE|PA|A|E|G|H|K|M|N|P|R|S|T|W|Z|AA|BA|BB|BD|BE|BH|BL|BN|BP|DB|DC|DD|DG|DM|DN|DP|DR|DT|EA|EB|ED|KB|KH|KU|PB'
        m_pol2 = re.search(rf'(?<![a-zA-Z0-9])({plate_codes})\s*(\d{{1,4}})\s*([A-Z]{{1,3}})(?![a-zA-Z0-9])', text_clean.upper())
        if m_pol2:
            nopol = f"{m_pol2.group(1)} {m_pol2.group(2)} {m_pol2.group(3)}"

    # 2. Tahun Pembuatan
    tahun = "-"
    m_thn = re.search(r'(?:tahun(?:\s*pembuatan|\s*rakit)?|thn\.?|th\.)\s*[:\s\-]*\b(19[89]\d|20[0-2]\d)\b', text_clean, re.I)
    if m_thn:
        tahun = m_thn.group(1)
    else:
        filtered = re.sub(r'\b\d{3,4}\s*(?:cc|cm3|km|kg|m2|m²)\b', '', text_clean, flags=re.I)
        m_thn2 = re.findall(r'\b(19[89]\d|20[0-1]\d|202[0-5])\b', filtered)
        if m_thn2:
            tahun = m_thn2[0]

    # 3. Warna
    warna = "-"
    m_warna = re.search(r'(?:warna)\s*[:\s\-]*([a-zA-Z\s]{3,25})', text_clean, re.I)
    if m_warna:
        first_w = m_warna.group(1).split("\n")[0].strip().upper()
        warna = re.sub(r'\s+', ' ', first_w)

    # 4. Nomor Rangka
    norangka = "-"
    m_rangka = re.search(r'(?:nomor\s*rangka|no\.?\s*rangka|norangka|noka|no\.?\s*chasis|vin)\s*[:\s\-]*([a-zA-Z0-9]{8,25})', text_clean, re.I)
    if m_rangka:
        norangka = m_rangka.group(1).strip().upper()
    else:
        m_rangka2 = re.search(r'\b([A-HJ-NPR-Z0-9]{17})\b', text_clean.upper())
        if m_rangka2:
            norangka = m_rangka2.group(1).strip()

    return nopol, tahun, warna, norangka

def main():
    print("[*] Memulai scraper lelang.go.id...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://lelang.go.id/",
    })

    kpknl_map = load_kpknl_map(session)
    print(f"[*] Berhasil memuat {len(kpknl_map)} kantor KPKNL.")

    # 1. Tarik daftar lot katalog
    catalog_items = []
    for page in range(1, MAX_PAGES + 1):
        print(f"[*] Mengambil katalog halaman {page}...")
        params = {
            "limit": 16,
            "dcp": "true",
            "namakategori[]": KATEGORI,
            "page": page
        }
        try:
            r = session.get(ENDPOINT, params=params, timeout=15)
            if r.status_code == 200:
                items = r.json().get("data", [])
                if not items:
                    break
                catalog_items.extend(items)
        except Exception as e:
            print(f"[!] Error katalog halaman {page}: {e}")
            break
        time.sleep(1)

    print(f"[*] Ditemukan {len(catalog_items)} unit kendaraan.")
    if not catalog_items:
        return

    results = []
    uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)

    # 2. Buka setiap halaman lelang menggunakan Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for idx, item in enumerate(catalog_items, 1):
            cat_id = str(item.get("id") or "-").strip()
            auc_id = str(item.get("lotLelangId") or cat_id).strip()

            kpknl_uuid = "-"
            for k, v in item.items():
                if isinstance(v, str) and uuid_pattern.match(v.strip().lower()):
                    val = v.strip().lower()
                    if val.startswith("670") and val != auc_id.lower():
                        kpknl_uuid = val
                        break

            kpknl_name = kpknl_map.get(kpknl_uuid, kpknl_uuid)
            judul = extract_title(item)

            if kpknl_uuid != "-" and auc_id != "-":
                link_url = f"https://lelang.go.id/kpknl/{kpknl_uuid}/detail-auction/{auc_id}"
            else:
                link_url = f"https://lelang.go.id/lot-lelang/detail/{auc_id}"

            print(f"[{idx}/{len(catalog_items)}] Mengambil data: {judul[:40]}...")

            nopol, tahun, warna, norangka, foto_url = "-", "-", "-", "-", "-"
            try:
                page.goto(link_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                body_text = page.inner_text("body")
                nopol, tahun, warna, norangka = parse_specs_from_text(body_text)

                images = page.query_selector_all("img")
                for img in images:
                    src = img.get_attribute("src") or ""
                    if src and not any(ign in src.lower() for ign in ["logo", "icon", "banner", "svg", "avatar", "profil"]):
                        if src.startswith("//"):
                            foto_url = "https:" + src
                            break
                        elif src.startswith("/"):
                            foto_url = "https://lelang.go.id" + src
                            break
                        elif src.startswith("http"):
                            foto_url = src
                            break
            except Exception as err:
                print(f"    [!] Gagal memuat halaman: {err}")

            # Format Harga
            def format_rupiah(k):
                val = item.get(k, 0)
                try:
                    return f"{int(float(str(val))):,}"
                except Exception:
                    return str(val)

            results.append({
                "No": idx,
                "Nama / Unit Kendaraan": judul,
                "Tahun Pembuatan": tahun,
                "Nomor Polisi": nopol,
                "Warna": warna,
                "Nomor Rangka": norangka,
                "Nilai Limit (Rp)": format_rupiah("nilaiLimit"),
                "Uang Jaminan (Rp)": format_rupiah("uangJaminan"),
                "KPKNL Penyelenggara": kpknl_name,
                "Link Foto": foto_url,
                "Link Katalog": link_url
            })

        browser.close()

    # 3. Simpan ke CSV
    output_filename = "hasil_lelang_mobil.csv"
    if results:
        fieldnames = list(results[0].keys())
        with open(output_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"\n[OK] Berhasil mengekspor {len(results)} data ke '{output_filename}'")

if __name__ == "__main__":
    main()

    # Tambahkan di bagian akhir scraper.py (setelah menyimpan CSV):
    output_json = "data.json"
    if results:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[OK] Berhasil mengekspor {len(results)} data ke '{output_json}'")