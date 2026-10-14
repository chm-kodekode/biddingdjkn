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

# Cek apakah modul Pillow terpasang untuk merender foto di GUI
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class LelangApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pengambil Data lelang.go.id - Katalog Kendaraan Lengkap")
        self.root.geometry("1240x700")
        self.root.minsize(1000, 550)

        self.data_results = []
        self.kpknl_map = {}
        self.is_fetching = False
        self.current_image = None

        self._build_ui()

    def _build_ui(self):
        # 1. Frame Parameter / Input Atas
        control_frame = ttk.LabelFrame(self.root, text=" Parameter Pengambilan Data ", padding=10)
        control_frame.pack(fill=tk.X, padx=12, pady=8)

        ttk.Label(control_frame, text="Kategori:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_category = ttk.Combobox(control_frame, values=["Mobil", "Sepeda Motor", "Tanah dan Bangunan"], width=16)
        self.entry_category.set("Mobil")
        self.entry_category.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(control_frame, text="Jumlah Halaman:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.spin_pages = ttk.Spinbox(control_frame, from_=1, to=50, width=5)
        self.spin_pages.set(2)
        self.spin_pages.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(control_frame, text="Endpoint API:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_endpoint = ttk.Entry(control_frame, width=65)
        self.entry_endpoint.insert(0, "https://api.lelang.go.id/api/v1/landing-page/katalog-lot-lelang")
        self.entry_endpoint.grid(row=1, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5, pady=5)

        self.btn_fetch = ttk.Button(control_frame, text="Mulai Ambil Data", command=self.start_fetching)
        self.btn_fetch.grid(row=0, column=4, rowspan=2, padx=15, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

        # 2. Main Frame (Dibagi 2: Tabel Kiri, Panel Preview Foto Kanan)
        main_content_frame = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        main_content_frame.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(main_content_frame)
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Kolom tabel baru: No, Tahun, No. Polisi, Judul, Nilai Limit, Jaminan, KPKNL, Tenggat, Link Foto, Link Katalog
        columns = ("no", "tahun", "nopol", "judul", "nilai_limit", "uang_jaminan", "kpknl", "tenggat", "foto", "link")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("no", text="No.")
        self.tree.heading("tahun", text="Tahun")
        self.tree.heading("nopol", text="No. Polisi")
        self.tree.heading("judul", text="Nama / Unit Kendaraan")
        self.tree.heading("nilai_limit", text="Nilai Limit (Rp)")
        self.tree.heading("uang_jaminan", text="Uang Jaminan (Rp)")
        self.tree.heading("kpknl", text="KPKNL Penyelenggara")
        self.tree.heading("tenggat", text="Batas Penawaran")
        self.tree.heading("foto", text="Link Gambar")
        self.tree.heading("link", text="Link Katalog")

        self.tree.column("no", width=42, anchor=tk.CENTER)
        self.tree.column("tahun", width=65, anchor=tk.CENTER)
        self.tree.column("nopol", width=95, anchor=tk.CENTER)
        self.tree.column("judul", width=310)
        self.tree.column("nilai_limit", width=110, anchor=tk.E)
        self.tree.column("uang_jaminan", width=110, anchor=tk.E)
        self.tree.column("kpknl", width=150)
        self.tree.column("tenggat", width=125, anchor=tk.CENTER)
        self.tree.column("foto", width=120)
        self.tree.column("link", width=150)

        # Event: Klik baris untuk preview foto & Klik ganda untuk buka tautan
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

        # 3. Panel Preview Foto & Info Cepat di Kanan
        self.preview_frame = ttk.LabelFrame(main_content_frame, text=" Preview Foto & Info ", width=280, padding=10)
        self.preview_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.preview_frame.pack_propagate(False)

        # Box Gambar
        self.lbl_image = tk.Label(self.preview_frame, text="Pilih baris kendaraan\nuntuk melihat foto", bg="#eaeaea", fg="#555555", width=34, height=12)
        self.lbl_image.pack(fill=tk.X, pady=5)

        # Info Ringkas
        self.lbl_info_title = ttk.Label(self.preview_frame, text="Pilih baris pada tabel.", wraplength=250, font=("Helvetica", 9, "bold"))
        self.lbl_info_title.pack(anchor=tk.W, pady=(8, 2))

        self.lbl_info_meta = ttk.Label(self.preview_frame, text="Tahun: -\nNo. Polisi: -\nLimit: -", font=("Helvetica", 9))
        self.lbl_info_meta.pack(anchor=tk.W, pady=2)

        self.btn_open_link = ttk.Button(self.preview_frame, text="Buka Web Lelang", state=tk.DISABLED, command=self._action_open_web)
        self.btn_open_link.pack(fill=tk.X, pady=(10, 3))

        self.btn_open_img = ttk.Button(self.preview_frame, text="Lihat Foto Ukuran Penuh", state=tk.DISABLED, command=self._action_open_image)
        self.btn_open_img.pack(fill=tk.X, pady=2)

        # 4. Status Bar & Tombol Ekspor Bawah
        bottom_frame = ttk.Frame(self.root, padding=12)
        bottom_frame.pack(fill=tk.X)

        self.lbl_status = ttk.Label(bottom_frame, text="Status: Siap.")
        self.lbl_status.pack(side=tk.LEFT)

        self.btn_export_json = ttk.Button(bottom_frame, text="Ekspor JSON", command=self.export_json, state=tk.DISABLED)
        self.btn_export_json.pack(side=tk.RIGHT, padx=4)

        self.btn_export_csv = ttk.Button(bottom_frame, text="Ekspor CSV", command=self.export_csv, state=tk.DISABLED)
        self.btn_export_csv.pack(side=tk.RIGHT, padx=4)

    def _on_tree_select(self, event):
        """Memperbarui preview foto saat baris dipilih."""
        selected = self.tree.selection()
        if not selected:
            return

        values = self.tree.item(selected[0], "values")
        if not values or len(values) < 10:
            return

        no, tahun, nopol, judul, limit, jaminan, kpknl, tenggat, foto_url, link_url = values[:10]

        self.lbl_info_title.config(text=f"No. {no} - {judul[:60]}...")
        self.lbl_info_meta.config(text=f"Tahun: {tahun}\nNo. Polisi: {nopol}\nLimit: Rp {limit}\nKPKNL: {kpknl}")

        # Aktifkan tombol aksi
        self.selected_link_url = link_url
        self.selected_foto_url = foto_url

        self.btn_open_link.config(state=tk.NORMAL if link_url.startswith("http") else tk.DISABLED)
        self.btn_open_img.config(state=tk.NORMAL if foto_url.startswith("http") else tk.DISABLED)

        # Muat gambar secara asinkron agar UI tidak membeku
        if foto_url.startswith("http"):
            self.lbl_image.config(text="Memuat foto...", image="")
            threading.Thread(target=self._load_image_async, args=(foto_url,), daemon=True).start()
        else:
            self.lbl_image.config(text="Foto tidak tersedia", image="")

    def _load_image_async(self, img_url):
        if not HAS_PIL:
            self.root.after(0, lambda: self.lbl_image.config(text="[Foto Tersedia]\nInstall Pillow untuk preview:\npip install pillow", image=""))
            return

        try:
            res = requests.get(img_url, timeout=6)
            if res.status_code == 200:
                raw_data = res.content
                image_pil = Image.open(io.BytesIO(raw_data))
                image_pil.thumbnail((250, 180))
                photo = ImageTk.PhotoImage(image_pil)

                def update_img():
                    self.current_image = photo
                    self.lbl_image.config(image=photo, text="")

                self.root.after(0, update_img)
            else:
                self.root.after(0, lambda: self.lbl_image.config(text="Gagal memuat foto", image=""))
        except Exception:
            self.root.after(0, lambda: self.lbl_image.config(text="Gagal memuat foto", image=""))

    def _action_open_web(self):
        if hasattr(self, "selected_link_url") and self.selected_link_url.startswith("http"):
            webbrowser.open(self.selected_link_url)

    def _action_open_image(self):
        if hasattr(self, "selected_foto_url") and self.selected_foto_url.startswith("http"):
            webbrowser.open(self.selected_foto_url)

    def _on_double_click_row(self, event):
        selected_item = self.tree.selection()
        if not selected_item:
            return
        values = self.tree.item(selected_item[0], "values")
        if values and len(values) >= 10:
            target_url = values[9]
            if target_url.startswith("http"):
                webbrowser.open(target_url)

    def start_fetching(self):
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

        threading.Thread(target=self._worker_fetch, args=(category, pages, endpoint), daemon=True).start()

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

    def _worker_fetch(self, category, max_pages, endpoint):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
            "Referer": "https://lelang.go.id/",
            "Origin": "https://lelang.go.id",
        }

        session = requests.Session()
        session.headers.update(headers)

        self._update_status("Memuat master data KPKNL...")
        self._load_kpknl_reference(session)

        item_counter = 0

        for current_page in range(1, max_pages + 1):
            self._update_status(f"Mengambil halaman {current_page} dari {max_pages}...")

            params = {
                "limit": 16,
                "dcp": "true",
                "namakategori[]": category,
                "page": current_page
            }

            try:
                response = session.get(endpoint, params=params, timeout=15)
                if response.status_code != 200:
                    self._update_status(f"Gagal memuat halaman {current_page} (HTTP {response.status_code})")
                    break

                res_json = response.json()
                items = res_json.get("data") or []

                if not items:
                    self._update_status(f"Tidak ada data di halaman {current_page}.")
                    break

                for raw in items:
                    item_counter += 1
                    row_data = self._clean_data(raw, item_counter)
                    self.data_results.append(row_data)
                    self.root.after(0, self._insert_table_row, row_data)

            except Exception as e:
                self._update_status(f"Error: {e}")
                break

            time.sleep(1.2)

        self.root.after(0, self._finish_fetching)

    def _extract_title(self, item):
        title_candidates = [
            "deskripsi", "uraian", "deskripsibarang", "uraianbarang", "objeklelang",
            "namabarang", "judul", "nama", "title", "namalot", "uraianlot", "keterangan"
        ]
        for cand in title_candidates:
            for k, v in item.items():
                if k.lower() == cand and isinstance(v, str) and len(v.strip()) > 3:
                    return re.sub(r"<[^>]+>", "", v).strip()

        for v in item.values():
            if isinstance(v, dict):
                for cand in title_candidates:
                    sub_val = v.get(cand)
                    if isinstance(sub_val, str) and len(sub_val.strip()) > 3:
                        return re.sub(r"<[^>]+>", "", sub_val).strip()

        longest_str = ""
        for k, v in item.items():
            if isinstance(v, str) and " " in v and not v.startswith("http"):
                clean = re.sub(r"<[^>]+>", "", v).strip()
                if len(clean) > len(longest_str) and not re.search(r"^\d{4}-\d{2}-\d{2}", clean):
                    longest_str = clean

        return longest_str if longest_str else "-"

    def _extract_nopol(self, text, item):
        """Mengekstrak nomor polisi kendaraan dari JSON atau regex judul."""
        # 1. Cek langsung dari kunci dictionary JSON jika ada
        for k in ["nopol", "nomorpolisi", "nopolisi", "platnomor", "plat", "policenumber"]:
            for ik, iv in item.items():
                if k == ik.lower().replace("_", "") and iv and isinstance(iv, str):
                    return iv.strip().upper()

        # 2. Cari dari teks menggunakan pola regex
        text_clean = str(text).upper()
        # Pola dengan keyword "No Polisi", "Nopol", atau "Plat"
        m = re.search(r'(?:NO(?:MOR|\.)?\s*POL(?:ISI)?|NOPOL|PLAT)\s*[:\s\-]*([A-Z]{1,2}\s*\d{1,4}\s*[A-Z]{1,3})', text_clean)
        if m:
            return re.sub(r'\s+', ' ', m.group(1)).strip()

        # Pola plat nomor standar Indonesia (1-2 huruf awal, 1-4 angka, 1-3 huruf akhir)
        plate_codes = r'KT|B|D|F|BK|L|AB|AD|BG|DA|BM|DK|DH|DE|PA|A|E|G|H|K|M|N|P|R|S|T|W|Z|AA|BA|BB|BD|BE|BH|BL|BN|BP|DB|DC|DD|DG|DM|DN|DP|DR|DT|EA|EB|ED|KB|KH|KU|PB'
        m2 = re.search(rf'\b({plate_codes})\s*(\d{{1,4}})\s*([A-Z]{{1,3}})\b', text_clean)
        if m2:
            return f"{m2.group(1)} {m2.group(2)} {m2.group(3)}"

        return "-"

    def _extract_year(self, text, item):
        """Mengekstrak tahun pembuatan kendaraan dari JSON atau regex judul."""
        # 1. Cek langsung kunci dictionary JSON
        for k in ["tahun", "tahunpembuatan", "tahunkendaraan", "tahunrakit", "year"]:
            for ik, iv in item.items():
                if k == ik.lower().replace("_", "") and iv:
                    val_str = str(iv).strip()
                    if re.match(r'^(?:19|20)\d{2}$', val_str):
                        return val_str

        # 2. Cari dari teks judul / uraian
        text_clean = str(text).lower()
        # Pola "Tahun : 2018" atau "Th. 2015"
        m = re.search(r'(?:tahun|thn|th\.?)\s*(?:pembuatan|rakit)?\s*[:\s\-]*\b(19[89]\d|20[0-2]\d)\b', text_clean)
        if m:
            return m.group(1)

        # Pola angka 4 digit tanpa satuan cc, km, kg, m2
        filtered = re.sub(r'\b\d{3,4}\s*(?:cc|cm3|km|kg|m2|m²|ha)\b', '', text_clean)
        m2 = re.search(r'\b(19[89]\d|20[0-2]\d)\b', filtered)
        if m2:
            return m2.group(1)

        return "-"

    def _extract_image_url(self, item):
        """Mengekstrak URL foto kendaraan utama."""
        # 1. Cek field langsung yang memuat URL
        for k in ["objecturl", "photourl", "imageurl", "urlfoto", "fotourl", "urlgambar", "gambarurl", "url"]:
            for ik, iv in item.items():
                if k == ik.lower().replace("_", "") and isinstance(iv, str) and iv.startswith("http"):
                    return iv.strip()

        # 2. Cek apakah ada file/objectName untuk endpoint object-url
        for k in ["objectname", "filename", "fileid"]:
            for ik, iv in item.items():
                if k == ik.lower().replace("_", "") and isinstance(iv, str) and len(iv.strip()) > 4:
                    return f"https://api.lelang.go.id/api/v1/landing-page/object-url?objectName={iv.strip()}"

        # 3. Cek struktur list lampiran / foto / images
        for k in ["foto", "images", "photos", "lampiran", "dokumen", "files", "fotolot"]:
            for ik, iv in item.items():
                if k == ik.lower().replace("_", "") and isinstance(iv, list) and len(iv) > 0:
                    first = iv[0]
                    if isinstance(first, str):
                        if first.startswith("http"):
                            return first
                        return f"https://api.lelang.go.id/api/v1/landing-page/object-url?objectName={first}"
                    elif isinstance(first, dict):
                        for sub_k in ["url", "path", "objectUrl", "objectName", "fileUrl"]:
                            if first.get(sub_k):
                                sub_v = str(first[sub_k])
                                if sub_v.startswith("http"):
                                    return sub_v
                                return f"https://api.lelang.go.id/api/v1/landing-page/object-url?objectName={sub_v}"

        return "-"

    def _clean_data(self, item, item_no):
        auction_id = str(item.get("lotLelangId") or item.get("id") or "-").strip()
        judul = self._extract_title(item)

        # Ekstraksi Tahun & Nopol
        tahun = self._extract_year(judul, item)
        nopol = self._extract_nopol(judul, item)

        # Nominal Limit & Jaminan
        def get_num(key_list):
            for k in key_list:
                for ik, iv in item.items():
                    if k.lower() == ik.lower() and iv not in (None, ""):
                        try:
                            val_int = int(float(str(iv).replace(".", "").replace(",", "")))
                            return f"{val_int:,}"
                        except (ValueError, TypeError):
                            return str(iv)
            return "0"

        nilai_limit = get_num(["nilaiLimit", "hargaLimit", "limit", "nominalLimit"])
        uang_jaminan = get_num(["uangJaminan", "nominalJaminan", "jaminan"])

        # Resolusi UUID KPKNL
        uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)
        kpknl_uuid = "-"
        for k, v in item.items():
            if isinstance(v, str) and uuid_pattern.match(v.strip().lower()):
                val_clean = v.strip().lower()
                if val_clean.startswith("670") and val_clean != auction_id.lower():
                    kpknl_uuid = val_clean
                    break

        kpknl_name = self.kpknl_map.get(kpknl_uuid, kpknl_uuid)

        # URL Katalog & Foto
        if kpknl_uuid != "-" and auction_id != "-":
            link_url = f"https://lelang.go.id/kpknl/{kpknl_uuid}/detail-auction/{auction_id}"
        elif auction_id != "-":
            link_url = f"https://lelang.go.id/lot-lelang/detail/{auction_id}"
        else:
            link_url = "-"

        foto_url = self._extract_image_url(item)

        # Tanggal Batas Penawaran
        tenggat = "-"
        date_keys = ["bataspenawaran", "tglbataspenawaran", "tglakhirpenawaran", "tglselesai", "tglakhir", "tgllelang"]
        for k, v in item.items():
            k_clean = k.lower().replace("_", "").replace("-", "")
            if any(dk == k_clean for dk in date_keys) and isinstance(v, str):
                m = re.search(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?", v.replace("T", " "))
                if m:
                    tenggat = m.group(0)
                    break

        return {
            "no": str(item_no),
            "tahun": tahun,
            "nopol": nopol,
            "judul": judul,
            "nilai_limit": nilai_limit,
            "uang_jaminan": uang_jaminan,
            "kpknl": kpknl_name,
            "tenggat": tenggat,
            "foto": foto_url,
            "link": link_url,
            "raw": item
        }

    def _insert_table_row(self, row):
        self.tree.insert(
            "",
            tk.END,
            values=(
                row["no"],
                row["tahun"],
                row["nopol"],
                row["judul"],
                row["nilai_limit"],
                row["uang_jaminan"],
                row["kpknl"],
                row["tenggat"],
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
        self.lbl_status.config(text=f"Status: Selesai. Diperoleh {total} unit kendaraan.")

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
                {k: v for k, v in row.items() if k != "raw"}
                for row in self.data_results
            ]
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=export_rows[0].keys())
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