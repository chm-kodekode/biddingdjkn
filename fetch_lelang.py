import csv
import json
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
import requests


class LelangApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pengambil Data lelang.go.id - Kategori Kendaraan")
        self.root.geometry("1180x680")
        self.root.minsize(950, 500)

        self.data_results = []
        self.kpknl_map = {}
        self.is_fetching = False

        self._build_ui()

    def _build_ui(self):
        # Frame Parameter
        control_frame = ttk.LabelFrame(self.root, text=" Parameter Pengambilan Data ", padding=10)
        control_frame.pack(fill=tk.X, padx=12, pady=8)

        ttk.Label(control_frame, text="Kategori:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_category = ttk.Combobox(control_frame, values=["Mobil", "Motor"], width=18)
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

        # Frame Tabel
        table_frame = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "judul", "nilai_limit", "uang_jaminan", "kpknl", "tenggat", "link")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID")
        self.tree.heading("judul", text="Nama / Unit Kendaraan")
        self.tree.heading("nilai_limit", text="Nilai Limit (Rp)")
        self.tree.heading("uang_jaminan", text="Uang Jaminan (Rp)")
        self.tree.heading("kpknl", text="KPKNL Penyelenggara")
        self.tree.heading("tenggat", text="Batas Penawaran")
        self.tree.heading("link", text="Link Tautan Katalog (Klik Ganda untuk Buka)")

        self.tree.column("id", width=80, anchor=tk.CENTER)
        self.tree.column("judul", width=360)
        self.tree.column("nilai_limit", width=115, anchor=tk.E)
        self.tree.column("uang_jaminan", width=115, anchor=tk.E)
        self.tree.column("kpknl", width=170)
        self.tree.column("tenggat", width=130, anchor=tk.CENTER)
        self.tree.column("link", width=250)

        # Klik ganda pada baris untuk membuka link di browser
        self.tree.bind("<Double-1>", self._on_double_click_row)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # Status & Tombol Ekspor
        bottom_frame = ttk.Frame(self.root, padding=12)
        bottom_frame.pack(fill=tk.X)

        self.lbl_status = ttk.Label(bottom_frame, text="Status: Siap. (Klik ganda baris tabel untuk langsung membuka web lelang)")
        self.lbl_status.pack(side=tk.LEFT)

        self.btn_export_json = ttk.Button(bottom_frame, text="Ekspor JSON", command=self.export_json, state=tk.DISABLED)
        self.btn_export_json.pack(side=tk.RIGHT, padx=4)

        self.btn_export_csv = ttk.Button(bottom_frame, text="Ekspor CSV", command=self.export_csv, state=tk.DISABLED)
        self.btn_export_csv.pack(side=tk.RIGHT, padx=4)

    def _on_double_click_row(self, event):
        selected_item = self.tree.selection()
        if not selected_item:
            return

        values = self.tree.item(selected_item[0], "values")
        if values and len(values) >= 7:
            target_url = values[6]
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

        self._update_status("Memuat data referensi kantor KPKNL...")
        self._load_kpknl_reference(session)

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
                    row_data = self._clean_data(raw)
                    self.data_results.append(row_data)
                    self.root.after(0, self._insert_table_row, row_data)

            except Exception as e:
                self._update_status(f"Error: {e}")
                break

            time.sleep(1.2)

        self.root.after(0, self._finish_fetching)

    def _extract_title(self, item):
        """Mengekstrak judul/deskripsi unit lelang secara cerdas."""
        title_candidates = [
            "deskripsi", "uraian", "deskripsibarang", "uraianbarang", "objeklelang",
            "namabarang", "judul", "nama", "title", "namalot", "uraianlot", "keterangan"
        ]

        # 1. Cek langsung nama kunci
        for cand in title_candidates:
            for k, v in item.items():
                if k.lower() == cand and isinstance(v, str) and len(v.strip()) > 3:
                    return re.sub(r"<[^>]+>", "", v).strip()

        # 2. Cek apakah ada anak dictionary yang memuat nama
        for v in item.values():
            if isinstance(v, dict):
                for cand in title_candidates:
                    sub_val = v.get(cand)
                    if isinstance(sub_val, str) and len(sub_val.strip()) > 3:
                        return re.sub(r"<[^>]+>", "", sub_val).strip()

        # 3. Fallback: Cari string terpanjang yang memuat spasi (teks uraian)
        longest_str = ""
        for k, v in item.items():
            if isinstance(v, str) and " " in v and not v.startswith("http"):
                clean = re.sub(r"<[^>]+>", "", v).strip()
                if len(clean) > len(longest_str) and not re.search(r"^\d{4}-\d{2}-\d{2}", clean):
                    longest_str = clean

        return longest_str if longest_str else "-"

    def _extract_kpknl_uuid(self, item, auction_id):
        """Mencari UUID milik KPKNL di dalam objek lelang."""
        uuid_pattern = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)

        # 1. Prioritas KPKNL yang memiliki pola format lelang.go.id (diawali 670... atau ada kata kpknl)
        for k, v in item.items():
            if "kpknl" in k.lower() and isinstance(v, str) and uuid_pattern.match(v.strip()):
                return v.strip().lower()

        # 2. Cari string yang cocok dengan format UUID dan bukan ID lot lelang
        for k, v in item.items():
            if isinstance(v, str):
                val_clean = v.strip().lower()
                if uuid_pattern.match(val_clean):
                    if val_clean.startswith("670") and val_clean != auction_id.lower():
                        return val_clean

        # 3. Rekursif ke dalam dictionary anak jika ada
        for v in item.values():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, str) and uuid_pattern.match(sv.strip()):
                        val_clean = sv.strip().lower()
                        if val_clean != auction_id.lower():
                            return val_clean

        return "-"

    def _extract_deadline(self, item):
        date_keys = [
            "bataspenawaran", "tglbataspenawaran", "tglakhirpenawaran", "tglselesai",
            "tglakhir", "tanggalselesai", "tanggalakhir", "waktuselesai", "waktuakhir",
            "batasakhir", "tglpelaksanaan", "tanggalpelaksanaan", "tgllelang", "tanggallelang"
        ]

        # 1. Cek kunci yang tepat untuk batas waktu
        for k, v in item.items():
            k_clean = k.lower().replace("_", "").replace("-", "")
            if any(dk == k_clean for dk in date_keys) and isinstance(v, str):
                clean_date = v.replace("T", " ").replace(".000Z", "").replace("Z", "")
                m = re.search(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?", clean_date)
                if m:
                    return m.group(0)

        # 2. Cek tanggal di dalam string mana pun yang bukan tanggal pembuatan/update data
        for k, v in item.items():
            k_lower = k.lower()
            if isinstance(v, str) and not any(ign in k_lower for ign in ["create", "update", "delete", "server"]):
                m = re.search(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?", v.replace("T", " "))
                if m:
                    return m.group(0)

        return "-"

    def _clean_data(self, item):
        # 1. ID Lelang
        auction_id = str(item.get("lotLelangId") or item.get("id") or "-").strip()

        # 2. Nama Barang / Mobil
        judul = self._extract_title(item)

        # 3. Nilai Limit & Jaminan
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

        # 4. KPKNL & Link URL
        kpknl_uuid = self._extract_kpknl_uuid(item, auction_id)
        kpknl_name = self.kpknl_map.get(kpknl_uuid.lower(), kpknl_uuid)

        if kpknl_uuid != "-" and auction_id != "-":
            link_url = f"https://lelang.go.id/kpknl/{kpknl_uuid}/detail-auction/{auction_id}"
        elif auction_id != "-":
            link_url = f"https://lelang.go.id/lot-lelang/detail/{auction_id}"
        else:
            link_url = "-"

        # 5. Batas Waktu
        tenggat = self._extract_deadline(item)

        return {
            "id": auction_id[:10] + "..." if len(auction_id) > 10 else auction_id,
            "judul": judul,
            "nilai_limit": nilai_limit,
            "uang_jaminan": uang_jaminan,
            "kpknl": kpknl_name,
            "tenggat": tenggat,
            "link": link_url,
            "raw": item
        }

    def _insert_table_row(self, row):
        self.tree.insert(
            "",
            tk.END,
            values=(
                row["id"],
                row["judul"],
                row["nilai_limit"],
                row["uang_jaminan"],
                row["kpknl"],
                row["tenggat"],
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