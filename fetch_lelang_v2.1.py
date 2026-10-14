import csv
import io
import json
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
import requests

# Cek modul GUI gambar
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Cek modul Browser Otomatis Playwright
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class LelangApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pengambil Data lelang.go.id - Otomasi Scraping Uraian & Nomor Rangka")
        self.root.geometry("1300x720")
        self.root.minsize(1050, 550)

        self.data_results = []
        self.kpknl_map = {}
        self.is_fetching = False
        self.current_photo = None

        self._build_ui()

    def _build_ui(self):
        # 1. Parameter Input
        control_frame = ttk.LabelFrame(self.root, text=" Parameter Pengambilan Data ", padding=10)
        control_frame.pack(fill=tk.X, padx=12, pady=8)

        ttk.Label(control_frame, text="Kategori:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=4)
        self.entry_category = ttk.Combobox(control_frame, values=["Mobil", "Sepeda Motor", "Tanah dan Bangunan"], width=18)
        self.entry_category.set("Mobil")
        self.entry_category.grid(row=0, column=1, padx=5, pady=4)

        ttk.Label(control_frame, text="Jumlah Halaman:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=4)
        self.spin_pages = ttk.Spinbox(control_frame, from_=1, to=50, width=5)
        self.spin_pages.set(1)
        self.spin_pages.grid(row=0, column=3, padx=5, pady=4)

        self.var_headless = tk.BooleanVar(value=True)
        self.chk_headless = ttk.Checkbutton(control_frame, text="Browser Senyap (Headless di latar belakang)", variable=self.var_headless)
        self.chk_headless.grid(row=0, column=4, padx=10, pady=4, sticky=tk.W)

        ttk.Label(control_frame, text="Endpoint API:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=4)
        self.entry_endpoint = ttk.Entry(control_frame, width=70)
        self.entry_endpoint.insert(0, "https://api.lelang.go.id/api/v1/landing-page/katalog-lot-lelang")
        self.entry_endpoint.grid(row=1, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5, pady=4)

        self.btn_fetch = ttk.Button(control_frame, text="Mulai Ambil Data", command=self.start_fetching)
        self.btn_fetch.grid(row=0, column=5, rowspan=2, padx=15, pady=4, sticky=tk.N + tk.S + tk.E + tk.W)

        # 2. Main Frame: Tabel (Kiri) + Preview Foto (Kanan)
        main_frame = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        main_frame.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(main_frame)
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Kolom sesuai permintaan: No, Judul, Tahun, No. Polisi, Warna, Nomor Rangka, Limit, Jaminan, KPKNL, Gambar, Link
        columns = ("no", "judul", "tahun", "nopol", "warna", "norangka", "nilai_limit", "uang_jaminan", "kpknl", "foto", "link")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("no", text="No.")
        self.tree.heading("judul", text="Nama / Unit Kendaraan")
        self.tree.heading("tahun", text="Tahun")
        self.tree.heading("nopol", text="No. Polisi")
        self.tree.heading("warna", text="Warna")
        self.tree.heading("norangka", text="Nomor Rangka")
        self.tree.heading("nilai_limit", text="Nilai Limit (Rp)")
        self.tree.heading("uang_jaminan", text="Uang Jaminan (Rp)")
        self.tree.heading("kpknl", text="KPKNL Penyelenggara")
        self.tree.heading("foto", text="Link Gambar")
        self.tree.heading("link", text="Link Katalog")

        self.tree.column("no", width=38, anchor=tk.CENTER)
        self.tree.column("judul", width=270)
        self.tree.column("tahun", width=60, anchor=tk.CENTER)
        self.tree.column("nopol", width=95, anchor=tk.CENTER)
        self.tree.column("warna", width=100, anchor=tk.CENTER)
        self.tree.column("norangka", width=165, anchor=tk.CENTER)
        self.tree.column("nilai_limit", width=105, anchor=tk.E)
        self.tree.column("uang_jaminan", width=105, anchor=tk.E)
        self.tree.column("kpknl", width=140)
        self.tree.column("foto", width=110)
        self.tree.column("link", width=130)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_double_click_row)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # 3. Panel Preview Foto & Detail Cepat
        self.preview_frame = ttk.LabelFrame(main_frame, text=" Foto & Info Unit ", width=300, padding=10)
        self.preview_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.preview_frame.pack_propagate(False)

        self.lbl_image = tk.Label(self.preview_frame, text="Klik baris pada tabel\nuntuk melihat foto mobil", bg="#f0f0f0", fg="#666666", width=36, height=13)
        self.lbl_image.pack(fill=tk.X, pady=5)

        self.lbl_info_title = ttk.Label(self.preview_frame, text="-", wraplength=270, font=("Helvetica", 9, "bold"))
        self.lbl_info_title.pack(anchor=tk.W, pady=(8, 2))

        self.lbl_info_meta = ttk.Label(self.preview_frame, text="Tahun: -\nNo. Polisi: -\nWarna: -\nNo. Rangka: -", font=("Helvetica", 9))
        self.lbl_info_meta.pack(anchor=tk.W, pady=2)

        self.btn_open_link = ttk.Button(self.preview_frame, text="Buka Web Lelang", state=tk.DISABLED, command=self._open_web)
        self.btn_open_link.pack(fill=tk.X, pady=(12, 3))

        self.btn_open_img = ttk.Button(self.preview_frame, text="Lihat Foto Ukuran Asli", state=tk.DISABLED, command=self._open_image)
        self.btn_open_img.pack(fill=tk.X, pady=2)

        # 4. Status Bar & Ekspor
        bottom_frame = ttk.Frame(self.root, padding=12)
        bottom_frame.pack(fill=tk.X)

        self.lbl_status = ttk.Label(bottom_frame, text="Status: Siap.")
        self.lbl_status.pack(side=tk.LEFT)

        self.btn_export_json = ttk.Button(bottom_frame, text="Ekspor JSON", command=self.export_json, state=tk.DISABLED)
        self.btn_export_json.pack(side=tk.RIGHT, padx=4)

        self.btn_export_csv = ttk.Button(bottom_frame, text="Ekspor CSV", command=self.export_csv, state=tk.DISABLED)
        self.btn_export_csv.pack(side=tk.RIGHT, padx=4)

    def _on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return

        values = self.tree.item(selected[0], "values")
        if not values or len(values) < 11:
            return

        no, judul, tahun, nopol, warna, norangka, limit, jaminan, kpknl, foto_url, link_url = values[:11]

        self.lbl_info_title.config(text=f"No. {no}: {judul[:70]}...")
        self.lbl_info_meta.config(text=f"Tahun: {tahun}\nNo. Polisi: {nopol}\nWarna: {warna}\nNo. Rangka: {norangka}\nNilai Limit: Rp {limit}\nKPKNL: {kpknl}")

        self.selected_link_url = link_url
        self.selected_foto_url = foto_url

        self.btn_open_link.config(state=tk.NORMAL if link_url.startswith("http") else tk.DISABLED)
        self.btn_open_img.config(state=tk.NORMAL if foto_url.startswith("http") else tk.DISABLED)

        if foto_url.startswith("http"):
            self.lbl_image.config(text="Memuat foto...", image="")
            threading.Thread(target=self._load_photo_async, args=(foto_url,), daemon=True).start()
        else:
            self.lbl_image.config(text="Foto tidak ditemukan", image="")

    def _load_photo_async(self, url):
        if not HAS_PIL:
            self.root.after(0, lambda: self.lbl_image.config(text="Pasang Pillow:\npip install pillow", image=""))
            return

        try:
            r = requests.get(url, timeout=7)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                img.thumbnail((270, 200))
                photo = ImageTk.PhotoImage(img)

                def show():
                    self.current_photo = photo
                    self.lbl_image.config(image=photo, text="")

                self.root.after(0, show)
            else:
                self.root.after(0, lambda: self.lbl_image.config(text="Gagal memuat foto", image=""))
        except Exception:
            self.root.after(0, lambda: self.lbl_image.config(text="Gagal memuat foto", image=""))

    def _open_web(self):
        if hasattr(self, "selected_link_url") and self.selected_link_url.startswith("http"):
            webbrowser.open(self.selected_link_url)

    def _open_image(self):
        if hasattr(self, "selected_foto_url") and self.selected_foto_url.startswith("http"):
            webbrowser.open(self.selected_foto_url)

    def _on_double_click_row(self, event):
        self._open_web()

    def start_fetching(self):
        if not HAS_PLAYWRIGHT:
            messagebox.showerror(
                "Playwright Belum Terpasang",
                "Fitur buka halaman detail otomatis membutuhkan Playwright.\n\n"
                "Jalankan di Command Prompt (CMD):\n"
                "pip install playwright\n"
                "playwright install chromium"
            )
            return

        if self.is_fetching:
            return

        category = self.entry_category.get().strip()
        try:
            pages = int(self.spin_pages.get().strip())
        except ValueError:
            messagebox.showerror("Input Salah", "Jumlah halaman harus berupa angka bulat.")
            return

        endpoint = self.entry_endpoint.get().strip()
        if not endpoint:
            messagebox.showerror("Input Kosong", "Endpoint API tidak boleh kosong.")
            return

        self.is_fetching = True
        self.btn_fetch.config(state=tk.DISABLED)
        self.btn_export_csv.config(state=tk.DISABLED)
        self.btn_export_json.config(state=tk.DISABLED)

        for row in self.tree.get_children():
            self.tree.delete(row)
        self.data_results.clear()

        headless_mode = self.var_headless.get()
        threading.Thread(target=self._worker_fetch, args=(category, pages, endpoint, headless_mode), daemon=True).start()

    def _load_kpknl_reference(self, session):
        urls = [
            "https://api.lelang.go.id/api/v1/landing-page/kpknl?sortby=nama&sortdir=asc",
            "https://api.lelang.go.id/api/v1/kpknl?sortby=nama&sortdir=asc",
        ]
        for url in urls:
            try:
                res = session.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    for it in data:
                        if isinstance(it, dict):
                            kid = str(it.get("id") or "").strip().lower()
                            nama = it.get("nama") or it.get("namaKpknl") or it.get("uraian")
                            if kid and nama:
                                self.kpknl_map[kid] = str(nama).strip()
                    if self.kpknl_map:
                        break
            except Exception:
                continue

    def _extract_title(self, item):
        candidates = ["deskripsi", "uraian", "deskripsibarang", "uraianbarang", "objeklelang", "namabarang", "judul", "nama", "title"]
        for cand in candidates:
            for k, v in item.items():
                if cand in k.lower() and isinstance(v, str) and len(v.strip()) > 5:
                    clean = re.sub(r"<[^>]+>", "", v).strip()
                    lines = [ln.strip() for ln in clean.split("\n") if ln.strip()]
                    if lines:
                        return lines[0]

        for v in item.values():
            if isinstance(v, dict):
                res = self._extract_title(v)
                if res != "-":
                    return res

        uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)
        for k, v in item.items():
            if isinstance(v, str) and " " in v and not v.startswith("http") and not uuid_pattern.match(v.strip()):
                clean = re.sub(r"<[^>]+>", "", v).strip()
                if not re.search(r"^\d{4}-\d{2}-\d{2}", clean) and len(clean) > 8:
                    lines = [ln.strip() for ln in clean.split("\n") if ln.strip()]
                    return lines[0] if lines else "-"

        return "-"

    def _parse_specs_from_uraian(self, text):
        """Mengekstrak No Polisi, Tahun, Warna, dan Nomor Rangka langsung dari teks Uraian."""
        if not text:
            return "-", "-", "-", "-"

        text_clean = str(text)

        # 1. NOMOR POLISI
        nopol = "-"
        m_pol = re.search(r'(?:nomor\s*polisi|no\.?\s*polisi|nopol|plat(?:\s*nomor)?)\s*[:\s\-]*([a-zA-Z]{1,2}\s*\d{1,4}\s*[a-zA-Z]{1,3})', text_clean, re.I)
        if m_pol:
            nopol = re.sub(r'\s+', ' ', m_pol.group(1)).strip().upper()
        else:
            plate_codes = r'KT|B|D|F|BK|L|AB|AD|BG|DA|BM|DK|DH|DE|PA|A|E|G|H|K|M|N|P|R|S|T|W|Z|AA|BA|BB|BD|BE|BH|BL|BN|BP|DB|DC|DD|DG|DM|DN|DP|DR|DT|EA|EB|ED|KB|KH|KU|PB'
            m_pol2 = re.search(rf'(?<![a-zA-Z0-9])({plate_codes})\s*(\d{{1,4}})\s*([A-Z]{{1,3}})(?![a-zA-Z0-9])', text_clean.upper())
            if m_pol2:
                nopol = f"{m_pol2.group(1)} {m_pol2.group(2)} {m_pol2.group(3)}"

        # 2. TAHUN PEMBUATAN
        tahun = "-"
        m_thn = re.search(r'(?:tahun(?:\s*pembuatan|\s*rakit)?|thn\.?|th\.)\s*[:\s\-]*\b(19[89]\d|20[0-2]\d)\b', text_clean, re.I)
        if m_thn:
            tahun = m_thn.group(1)
        else:
            filtered = re.sub(r'\b\d{3,4}\s*(?:cc|cm3|km|kg|m2|m²)\b', '', text_clean, flags=re.I)
            m_thn2 = re.findall(r'\b(19[89]\d|20[0-1]\d|202[0-5])\b', filtered)
            if m_thn2:
                tahun = m_thn2[0]

        # 3. WARNA
        warna = "-"
        m_warna = re.search(r'(?:warna)\s*[:\s\-]*([a-zA-Z\s]{3,25})', text_clean, re.I)
        if m_warna:
            first_w = m_warna.group(1).split("\n")[0].strip().upper()
            warna = re.sub(r'\s+', ' ', first_w)

        # 4. NOMOR RANGKA
        norangka = "-"
        m_rangka = re.search(r'(?:nomor\s*rangka|no\.?\s*rangka|norangka|noka|no\.?\s*chasis|vin)\s*[:\s\-]*([a-zA-Z0-9]{8,25})', text_clean, re.I)
        if m_rangka:
            norangka = m_rangka.group(1).strip().upper()
        else:
            m_rangka2 = re.search(r'\b([A-HJ-NPR-Z0-9]{17})\b', text_clean.upper())
            if m_rangka2:
                norangka = m_rangka2.group(1).strip()

        return nopol, tahun, warna, norangka

    def _worker_fetch(self, category, max_pages, endpoint, headless_mode):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://lelang.go.id/",
            "Origin": "https://lelang.go.id",
        })

        self._update_status("Memuat master data KPKNL...")
        self._load_kpknl_reference(session)

        # 1. Kumpulkan daftar katalog lelang
        catalog_items = []
        for current_page in range(1, max_pages + 1):
            self._update_status(f"Mengambil katalog halaman {current_page} dari {max_pages}...")
            params = {
                "limit": 16,
                "dcp": "true",
                "namakategori[]": category,
                "page": current_page
            }
            try:
                res = session.get(endpoint, params=params, timeout=15)
                if res.status_code == 200:
                    items = res.json().get("data") or []
                    if not items:
                        break
                    catalog_items.extend(items)
                else:
                    break
            except Exception as e:
                self._update_status(f"Error katalog: {e}")
                break

        if not catalog_items:
            self._update_status("Katalog kosong atau gagal dimuat.")
            self.root.after(0, self._finish_fetching)
            return

        total_lots = len(catalog_items)
        self._update_status(f"Ditemukan {total_lots} unit. Memulai peramban otomatis untuk membuka halaman detail...")

        # 2. Otomatis buka setiap halaman lelang menggunakan Playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless_mode)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = context.new_page()

                for idx, item in enumerate(catalog_items, 1):
                    catalog_id = str(item.get("id") or "-").strip()
                    auction_id = str(item.get("lotLelangId") or catalog_id).strip()

                    # Resolusi UUID KPKNL
                    uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)
                    kpknl_uuid = "-"
                    for k, v in item.items():
                        if isinstance(v, str) and uuid_pattern.match(v.strip().lower()):
                            val = v.strip().lower()
                            if val.startswith("670") and val != auction_id.lower():
                                kpknl_uuid = val
                                break

                    kpknl_name = self.kpknl_map.get(kpknl_uuid, kpknl_uuid)
                    judul = self._extract_title(item)

                    if kpknl_uuid != "-" and auction_id != "-":
                        link_url = f"https://lelang.go.id/kpknl/{kpknl_uuid}/detail-auction/{auction_id}"
                    else:
                        link_url = f"https://lelang.go.id/lot-lelang/detail/{auction_id}"

                    self._update_status(f"[{idx}/{total_lots}] Membuka web lelang: {judul[:35]}...")

                    nopol, tahun, warna, norangka = "-", "-", "-", "-"
                    foto_url = "-"

                    # Buka halaman lelang asli secara otomatis
                    try:
                        page.goto(link_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)  # Beri jeda agar data SPA/JavaScript selesai dimuat

                        # Ambil seluruh teks halaman yang ter-render
                        body_text = page.inner_text("body")
                        nopol, tahun, warna, norangka = self._parse_specs_from_uraian(body_text)

                        # Ambil foto mobil dari elemen gambar utama
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
                        print(f"Gagal memuat lot {idx}: {err}")

                    # Nominal Limit & Jaminan
                    def get_num(key_list):
                        for k in key_list:
                            for ik, iv in item.items():
                                if k.lower() == ik.lower() and iv not in (None, ""):
                                    try:
                                        val_int = int(float(str(iv).replace(".", "").replace(",", "")))
                                        return f"{val_int:,}"
                                    except Exception:
                                        return str(iv)
                        return "0"

                    nilai_limit = get_num(["nilaiLimit", "hargaLimit", "limit", "nominalLimit"])
                    uang_jaminan = get_num(["uangJaminan", "nominalJaminan", "jaminan"])

                    row_data = {
                        "no": str(idx),
                        "judul": judul,
                        "tahun": tahun,
                        "nopol": nopol,
                        "warna": warna,
                        "norangka": norangka,
                        "nilai_limit": nilai_limit,
                        "uang_jaminan": uang_jaminan,
                        "kpknl": kpknl_name,
                        "foto": foto_url,
                        "link": link_url,
                        "raw": item
                    }

                    self.data_results.append(row_data)
                    self.root.after(0, self._insert_table_row, row_data)

                browser.close()

        except Exception as e:
            self._update_status(f"Error otomasi Playwright: {e}")

        self.root.after(0, self._finish_fetching)

    def _insert_table_row(self, row):
        self.tree.insert(
            "",
            tk.END,
            values=(
                row["no"],
                row["judul"],
                row["tahun"],
                row["nopol"],
                row["warna"],
                row["norangka"],
                row["nilai_limit"],
                row["uang_jaminan"],
                row["kpknl"],
                row["foto"],
                row["link"]
            )
        )

    def _update_status(self, text):
        self.root.after(0, lambda: self.lbl_status.config(text=f"Status: {text}"))

    def _finish_fetching(self):
        self.is_fetching = False
        self.btn_fetch.config(state=tk.NORMAL)
        total = len(self.data_results)
        self.lbl_status.config(text=f"Status: Selesai. Diperoleh {total} unit kendaraan dengan detail lengkap.")

        if total > 0:
            self.btn_export_csv.config(state=tk.NORMAL)
            self.btn_export_json.config(state=tk.NORMAL)

    def export_csv(self):
        if not self.data_results:
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Simpan Hasil ke CSV"
        )
        if not file_path:
            return

        try:
            export_rows = [
                {
                    "No": row["no"],
                    "Nama / Unit Kendaraan": row["judul"],
                    "Tahun Pembuatan": row["tahun"],
                    "Nomor Polisi": row["nopol"],
                    "Warna": row["warna"],
                    "Nomor Rangka": row["norangka"],
                    "Nilai Limit (Rp)": row["nilai_limit"],
                    "Uang Jaminan (Rp)": row["uang_jaminan"],
                    "KPKNL Penyelenggara": row["kpknl"],
                    "Link Foto": row["foto"],
                    "Link Katalog": row["link"]
                }
                for row in self.data_results
            ]
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(export_rows[0].keys()))
                writer.writeheader()
                writer.writerows(export_rows)
            messagebox.showinfo("Berhasil", f"Data berhasil disimpan ke:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Gagal Simpan", f"Terjadi kesalahan: {e}")

    def export_json(self):
        if not self.data_results:
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Simpan Hasil ke JSON"
        )
        if not file_path:
            return

        try:
            raw_data = [row["raw"] for row in self.data_results]
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Berhasil", f"Data lengkap berhasil disimpan ke:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Gagal Simpan", f"Terjadi kesalahan: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = LelangApp(root)
    root.mainloop()