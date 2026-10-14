import csv
import json
import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

KATEGORI = "Mobil"
ENDPOINT = "https://api.lelang.go.id/api/v1/landing-page/katalog-lot-lelang"
DATA_JSON_PATH = "data.json"
DATA_CSV_PATH = "hasil_lelang_mobil.csv"

def load_existing_database():
    """Memuat database lama agar tidak terjadi duplikasi dan menghemat waktu scraping."""
    if os.path.exists(DATA_JSON_PATH):
        try:
            with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
                items = json.load(f)
                # Petakan berdasarkan ID lelang unik
                return {str(item.get("ID_Lot")): item for item in items if item.get("ID_Lot")}
        except Exception:
            return {}
    return {}

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

def extract_deadline(item, body_text=""):
    """Mengekstrak tanggal batas penawaran ISO format YYYY-MM-DD HH:MM."""
    date_keys = ["bataspenawaran", "tglbataspenawaran", "tglakhirpenawaran", "tglselesai", "tglakhir", "tgllelang"]
    for k, v in item.items():
        k_clean = k.lower().replace("_", "").replace("-", "")
        if any(dk == k_clean for dk in date_keys) and isinstance(v, str):
            m = re.search(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?", v)
            if m:
                return m.group(0).replace("T", " ")

    # Fallback pencarian di teks body
    m_body = re.search(r'(?:batas\s*akhir\s*penawaran|batas\s*penawaran)\s*[:\s\-]*([0-9]{1,2}\s+[a-zA-Z]+\s+[0-9]{4}(?:\s+[0-9]{2}:[0-9]{2})?)', body_text, re.I)
    if m_body:
        return m_body.group(1).strip()

    return "-"

def parse_specs_from_text(text):
    if not text:
        return "-", "-", "-", "-"
    text_clean = str(text)

    # Nopol
    nopol = "-"
    m_pol = re.search(r'(?:nomor\s*polisi|no\.?\s*polisi|nopol|plat(?:\s*nomor)?)\s*[:\s\-]*([a-zA-Z]{1,2}\s*\d{1,4}\s*[a-zA-Z]{1,3})', text_clean, re.I)
    if m_pol:
        nopol = re.sub(r'\s+', ' ', m_pol.group(1)).strip().upper()
    else:
        plate_codes = r'KT|B|D|F|BK|L|AB|AD|BG|DA|BM|DK|DH|DE|PA|A|E|G|H|K|M|N|P|R|S|T|W|Z|AA|BA|BB|BD|BE|BH|BL|BN|BP|DB|DC|DD|DG|DM|DN|DP|DR|DT|EA|EB|ED|KB|KH|KU|PB'
        m_pol2 = re.search(rf'(?<![a-zA-Z0-9])({plate_codes})\s*(\d{{1,4}})\s*([A-Z]{{1,3}})(?![a-zA-Z0-9])', text_clean.upper())
        if m_pol2:
            nopol = f"{m_pol2.group(1)} {m_pol2.group(2)} {m_pol2.group(3)}"

    # Tahun
    tahun = "-"
    m_thn = re.search(r'(?:tahun(?:\s*pembuatan|\s*rakit)?|thn\.?|th\.)\s*[:\s\-]*\b(19[89]\d|20[0-2]\d)\b', text_clean, re.I)
    if m_thn:
        tahun = m_thn.group(1)
    else:
        filtered = re.sub(r'\b\d{3,4}\s*(?:cc|cm3|km|kg|m2|m²)\b', '', text_clean, flags=re.I)
        m_thn2 = re.findall(r'\b(19[89]\d|20[0-1]\d|202[0-5])\b', filtered)
        if m_thn2:
            tahun = m_thn2[0]

    # Warna
    warna = "-"
    m_warna = re.search(r'(?:warna)\s*[:\s\-]*([a-zA-Z\s]{3,25})', text_clean, re.I)
    if m_warna:
        warna = re.sub(r'\s+', ' ', m_warna.group(1).split("\n")[0].strip().upper())

    # Nomor Rangka
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
    print("[*] Memuat database lelang lokal...")
    existing_db = load_existing_database()
    print(f"[*] Ditemukan {len(existing_db)} riwayat data lama tersimpan.")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://lelang.go.id/",
    })

    kpknl_map = load_kpknl_map(session)

    # 1. Tarik seluruh katalog aktif secara dinamis
    active_catalog_items = []
    current_page = 1
    total_pages = 1

    print("[*] Mengambil data katalog aktif dari DJKN...")
    while current_page <= total_pages:
        params = {
            "limit": 16,
            "dcp": "true",
            "namakategori[]": KATEGORI,
            "page": current_page
        }
        try:
            r = session.get(ENDPOINT, params=params, timeout=20)
            if r.status_code == 200:
                res_json = r.json()
                items = res_json.get("data", [])
                if current_page == 1:
                    total_pages = res_json.get("totalPage", 1)
                    print(f"[*] Total {res_json.get('totalItem', len(items))} lot aktif ({total_pages} halaman).")
                if not items:
                    break
                active_catalog_items.extend(items)
            else:
                break
        except Exception as e:
            print(f"[!] Error: {e}")
            break
        current_page += 1
        time.sleep(0.5)

    # Catat ID yang masih aktif di website hari ini
    active_lot_ids = set()
    items_to_scrape = []
    uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)

    for item in active_catalog_items:
        cat_id = str(item.get("id") or "-").strip()
        auc_id = str(item.get("lotLelangId") or cat_id).strip()
        active_lot_ids.add(auc_id)

        # Cek apakah unit ini sudah ada di database lokal dan lengkap rinciannya
        if auc_id in existing_db and existing_db[auc_id].get("Nomor Rangka") not in ("-", "", None):
            # Perbarui statusnya menjadi aktif
            existing_db[auc_id]["Status"] = "aktif"
        else:
            # Masukkan ke antrean scraping baru
            items_to_scrape.append((auc_id, item))

    print(f"[*] Lot baru / butuh scraping detail: {len(items_to_scrape)} unit.")
    print(f"[*] Lot lama dilewati (menghemat waktu): {len(active_catalog_items) - len(items_to_scrape)} unit.")

    # 2. Hanya buka Playwright untuk unit BARU
    if items_to_scrape:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

            for idx, (auc_id, item) in enumerate(items_to_scrape, 1):
                kpknl_uuid = "-"
                for k, v in item.items():
                    if isinstance(v, str) and uuid_pattern.match(v.strip().lower()):
                        val = v.strip().lower()
                        if val.startswith("670") and val != auc_id.lower():
                            kpknl_uuid = val
                            break

                kpknl_name = kpknl_map.get(kpknl_uuid, kpknl_uuid)
                judul = extract_title(item)
                link_url = f"https://lelang.go.id/kpknl/{kpknl_uuid}/detail-auction/{auc_id}" if kpknl_uuid != "-" else f"https://lelang.go.id/lot-lelang/detail/{auc_id}"

                print(f"[{idx}/{len(items_to_scrape)}] Membaca lot baru: {judul[:35]}...")

                nopol, tahun, warna, norangka = "-", "-", "-", "-"
                foto_url = "-"
                deadline_text = extract_deadline(item)

                try:
                    page.goto(link_url, timeout=25000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    body_text = page.inner_text("body")
                    nopol, tahun, warna, norangka = parse_specs_from_text(body_text)
                    if deadline_text == "-":
                        deadline_text = extract_deadline(item, body_text)

                    images = page.query_selector_all("img")
                    for img in images:
                        src = img.get_attribute("src") or ""
                        if src and not any(ign in src.lower() for ign in ["logo", "icon", "banner", "svg", "avatar", "profil"]):
                            foto_url = src if src.startswith("http") else f"https://lelang.go.id{src}"
                            break
                except Exception as err:
                    print(f"    [!] Error halaman: {err}")

                def format_rupiah(k):
                    val = item.get(k, 0)
                    try:
                        return f"{int(float(str(val))):,}"
                    except Exception:
                        return str(val)

                # Simpan atau update ke database lokal
                existing_db[auc_id] = {
                    "ID_Lot": auc_id,
                    "Nama / Unit Kendaraan": judul,
                    "Tahun Pembuatan": tahun,
                    "Nomor Polisi": nopol,
                    "Warna": warna,
                    "Nomor Rangka": norangka,
                    "Nilai Limit (Rp)": format_rupiah("nilaiLimit"),
                    "Uang Jaminan (Rp)": format_rupiah("uangJaminan"),
                    "Batas Penawaran": deadline_text,
                    "KPKNL Penyelenggara": kpknl_name,
                    "Link Foto": foto_url,
                    "Link Katalog": link_url,
                    "Status": "aktif"
                }

            browser.close()

    # 3. Tandai unit yang hilang dari web DJKN sebagai "selesai"
    for stored_id, data in existing_db.items():
        if stored_id not in active_lot_ids:
            data["Status"] = "selesai"

    # Susun kembali list hasil
    final_results = []
    for idx, (auc_id, data) in enumerate(existing_db.items(), 1):
        data["No"] = idx
        final_results.append(data)

    # 4. Simpan ke JSON & CSV
    with open(DATA_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)

    with open(DATA_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(final_results[0].keys()))
        writer.writeheader()
        writer.writerows(final_results)

    aktif_count = sum(1 for d in final_results if d.get("Status") == "aktif")
    selesai_count = sum(1 for d in final_results if d.get("Status") == "selesai")
    print(f"\n[OK] Database diperbarui! Total: {len(final_results)} unit ({aktif_count} Aktif, {selesai_count} Selesai/Kedaluwarsa).")

if __name__ == "__main__":
    main()