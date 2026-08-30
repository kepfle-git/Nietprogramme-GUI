#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keller Nietprogramm-Tool - GUI
================================
Grafische Oberflaeche zum Lesen und Schreiben von KELLER-Nietprogrammen
auf Disketten-Images (.img) oder direkt auf HFE-Dateien (.hfe).

Start:  python keller_gui.py
Exe bauen (auf Windows, siehe README.txt fuer Details):
    pip install -r requirements.txt pyinstaller
    pyinstaller --onefile --add-data "greaseweazle;greaseweazle" ^
        --add-data "keller_diskdef.cfg;." keller_gui.py
"""

import os
import sys
import tempfile
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import keller_core as kc
import hfe_convert as hc

FIELD_ORDER = ["X", "Y", "Z1", "Z1-Tol", "Abh.", "Druck", "Z2", "Z2-Tol", "Zeit", "Ng"]
FIELD_TO_KEY = {
    "X": "x", "Y": "y", "Z1": "z1", "Z1-Tol": "z1tol", "Abh.": "abh",
    "Druck": "druck", "Z2": "z2", "Z2-Tol": "z2tol", "Zeit": "zeit", "Ng": "ng",
}


class KellerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Keller Nietprogramm-Tool")
        self.geometry("980x620")

        self.img_data = None          # aktuell geladene Sektor-Rohdaten (bytes)
        self.current_file = None      # Pfad der zuletzt geladenen Datei
        self.current_is_hfe = False
        self.entries = []             # Verzeichniseintraege
        self.target_program = None    # aktuell in der Tabelle gezeigtes Programm
        self.creating_new = False

        self._build_widgets()

    def new_program_mode(self):
        if self.img_data is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst eine Datei laden (als Basis fuer das neue Programm).")
            return
        self.tree.delete(*self.tree.get_children())
        self.creating_new = True
        self.target_program = None
        self.target_entry.delete(0, tk.END)
        self.status.set("Neues Programm: Name eingeben, Punkte hinzufuegen, dann 'Programm patchen & speichern' klicken.")

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_widgets(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Button(top, text="Datei oeffnen (.hfe/.img)...",
                   command=self.open_file).pack(side="left")
        ttk.Button(top, text="Neues Programm anlegen",
                   command=self.new_program_mode).pack(side="left", padx=6)
        self.file_label = ttk.Label(top, text="Keine Datei geladen")
        self.file_label.pack(side="left", padx=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # Linke Spalte: Programmliste
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Programme:").pack(anchor="w")
        self.prog_list = tk.Listbox(left, width=22, height=30)
        self.prog_list.pack(fill="y", expand=True)
        self.prog_list.bind("<<ListboxSelect>>", self.on_select_program)

        # Rechte Spalte: Punkte-Tabelle + Bearbeitung
        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        ttk.Label(right, text="Nietpunkte:").pack(anchor="w")

        cols = FIELD_ORDER
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=12)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=70, anchor="center")
        self.tree.pack(fill="both", expand=True)

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Zeile hinzufuegen", command=self.add_row).pack(side="left")
        ttk.Button(btns, text="Ausgewaehlte Zeile bearbeiten", command=self.edit_row).pack(side="left", padx=6)
        ttk.Button(btns, text="Ausgewaehlte Zeile loeschen", command=self.delete_row).pack(side="left")

        ttk.Separator(right).pack(fill="x", pady=8)

        save_frame = ttk.Frame(right)
        save_frame.pack(fill="x")
        ttk.Label(save_frame, text="Ziel-Programmnummer:").pack(side="left")
        self.target_entry = ttk.Entry(save_frame, width=14)
        self.target_entry.pack(side="left", padx=6)
        ttk.Button(save_frame, text="Speichern (patchen / neu anlegen)...",
                   command=self.patch_and_save).pack(side="left", padx=6)

        warn = ("WARNUNG: Nur mit Testprogrammen ueben (z.B. 0000000005-0000000018)!\n"
                "Ergebnis immer erst am Bildschirm der Maschine pruefen, bevor produktiv genutzt wird.\n"
                "Original-Datei bleibt unveraendert - es wird immer eine neue Datei gespeichert.")
        ttk.Label(right, text=warn, foreground="#a00000", justify="left").pack(anchor="w", pady=(10, 0))

        # Statuszeile / Log
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    # ------------------------------------------------------------------
    # Datei laden
    # ------------------------------------------------------------------
    def open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Disk-Images", "*.hfe *.img"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            self._load_path(path)
        except Exception as e:
            messagebox.showerror("Fehler beim Laden", f"{e}\n\n{traceback.format_exc()}")

    def _load_path(self, path):
        self.status.set("Lade Datei...")
        self.update_idletasks()
        ext = os.path.splitext(path)[1].lower()
        if ext == ".hfe":
            tmp_img = tempfile.mktemp(suffix=".img")
            hc.hfe_to_img(path, tmp_img)
            self.img_data = kc.load_image(tmp_img)
            self.current_is_hfe = True
        else:
            self.img_data = kc.load_image(path)
            self.current_is_hfe = False

        self.current_file = path
        self.entries = kc.find_programs(self.img_data)
        self.file_label.config(text=os.path.basename(path))
        self.prog_list.delete(0, tk.END)
        for e in self.entries:
            self.prog_list.insert(tk.END, e["name"])
        self.status.set(f"{len(self.entries)} Programme gefunden.")

    # ------------------------------------------------------------------
    # Programm auswaehlen / Tabelle fuellen
    # ------------------------------------------------------------------
    def on_select_program(self, event):
        sel = self.prog_list.curselection()
        if not sel:
            return
        name = self.prog_list.get(sel[0])
        self.target_program = name
        self.creating_new = False
        self.target_entry.delete(0, tk.END)
        self.target_entry.insert(0, name)

        entry = next(e for e in self.entries if e["name"] == name)
        end_sector = kc.guess_end_sector(self.entries, entry)
        payload = kc.strip_sector_headers(self.img_data, entry["start_sector"], end_sector)
        points = kc.extract_points(payload)

        self.tree.delete(*self.tree.get_children())
        for p in points:
            self._insert_point_row(p_dict={
                "x": p["X"], "y": p["Y"], "z1": p["Z1"], "z1tol": p["Z1-Tol"],
                "abh": p["Abh."], "druck": p["Druck"], "z2": p["Z2"], "z2tol": p["Z2-Tol"],
                "zeit": p["Zeit"], "ng": p["Ng"],
            })
        self.status.set(f"Programm {name}: {len(points)} Nietpunkt(e) geladen.")

    def _insert_point_row(self, p_dict):
        values = [self._fmt(p_dict.get(FIELD_TO_KEY[c], 0.0)) for c in FIELD_ORDER]
        self.tree.insert("", tk.END, values=values)

    @staticmethod
    def _fmt(v):
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return "0.00"

    # ------------------------------------------------------------------
    # Zeilen bearbeiten
    # ------------------------------------------------------------------
    def add_row(self):
        self._open_row_editor(None)

    def edit_row(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Hinweis", "Bitte zuerst eine Zeile auswaehlen.")
            return
        self._open_row_editor(sel[0])

    def delete_row(self):
        sel = self.tree.selection()
        for item in sel:
            self.tree.delete(item)

    def _open_row_editor(self, item_id):
        dlg = tk.Toplevel(self)
        dlg.title("Nietpunkt bearbeiten")
        dlg.geometry("300x420")
        entries = {}

        current = {}
        if item_id is not None:
            vals = self.tree.item(item_id, "values")
            current = dict(zip(FIELD_ORDER, vals))

        for i, field in enumerate(FIELD_ORDER):
            ttk.Label(dlg, text=field).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            e = ttk.Entry(dlg, width=14)
            e.insert(0, current.get(field, "0"))
            e.grid(row=i, column=1, padx=8, pady=4)
            entries[field] = e

        def save():
            try:
                values = [f"{float(entries[f].get()):.2f}" for f in FIELD_ORDER]
            except ValueError:
                messagebox.showerror("Fehler", "Bitte fuer alle Felder gueltige Zahlen eingeben.")
                return
            if item_id is not None:
                self.tree.item(item_id, values=values)
            else:
                self.tree.insert("", tk.END, values=values)
            dlg.destroy()

        ttk.Button(dlg, text="Speichern", command=save).grid(
            row=len(FIELD_ORDER), column=0, columnspan=2, pady=12)

    # ------------------------------------------------------------------
    # Patchen & Speichern
    # ------------------------------------------------------------------
    def _ask_program_options(self, new_program):
        """Dialog fuer Warentraeger-Auswahl (und bei Neuanlage: Vorwahl).
        Bei new_program=False gibt es zusaetzlich die Option 'Beibehalten'
        (aktuellen Warentraeger des Zielprogramms nicht aendern).
        Gibt (carrier, vorwahl) zurueck - carrier ist None bei 'Beibehalten'
        oder bei Abbruch (dann ist vorwahl auch None)."""
        result = {}
        dlg = tk.Toplevel(self)
        dlg.title("Neues Programm - Optionen" if new_program else "Warentraeger")
        dlg.geometry("320x180" if new_program else "320x140")
        dlg.grab_set()

        ttk.Label(dlg, text="Warentraeger:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        default = "A" if new_program else "KEEP"
        carrier_var = tk.StringVar(value=default)
        col = 1
        if not new_program:
            ttk.Radiobutton(dlg, text="Beibehalten", variable=carrier_var,
                             value="KEEP").grid(row=0, column=col, sticky="w")
            col += 1
        ttk.Radiobutton(dlg, text="A", variable=carrier_var, value="A").grid(row=0, column=col, sticky="w")
        ttk.Radiobutton(dlg, text="B", variable=carrier_var, value="B").grid(row=0, column=col + 1, sticky="w")

        vorwahl_entry = None
        if new_program:
            ttk.Label(dlg, text="Vorwahl (Sollstueckzahl):").grid(row=1, column=0, sticky="w", padx=8, pady=8)
            vorwahl_entry = ttk.Entry(dlg, width=8)
            vorwahl_entry.insert(0, "0")
            vorwahl_entry.grid(row=1, column=1, columnspan=2, sticky="w")

        def ok():
            if new_program:
                try:
                    result["vorwahl"] = int(vorwahl_entry.get())
                except ValueError:
                    messagebox.showerror("Fehler", "Vorwahl muss eine Ganzzahl sein.")
                    return
            c = carrier_var.get()
            result["carrier"] = None if c == "KEEP" else c
            dlg.destroy()

        def cancel():
            dlg.destroy()

        btnf = ttk.Frame(dlg)
        btnf.grid(row=2, column=0, columnspan=4, pady=12)
        ttk.Button(btnf, text="OK", command=ok).pack(side="left", padx=6)
        ttk.Button(btnf, text="Abbrechen", command=cancel).pack(side="left")

        dlg.wait_window()
        if "carrier" not in result:
            return "CANCELLED", None
        return result["carrier"], result.get("vorwahl")

    def patch_and_save(self):
        if self.img_data is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst eine Datei laden.")
            return
        target = self.target_entry.get().strip()
        if not target:
            messagebox.showinfo("Hinweis", "Bitte eine Zielprogrammnummer angeben.")
            return

        points = []
        for item in self.tree.get_children():
            vals = dict(zip(FIELD_ORDER, self.tree.item(item, "values")))
            try:
                points.append(dict(
                    x=float(vals["X"]), y=float(vals["Y"]),
                    z1=float(vals["Z1"]), z1tol=float(vals["Z1-Tol"]),
                    unbekannt=float(vals["Abh."]),
                    druck=float(vals["Druck"]), z2=float(vals["Z2"]),
                    z2tol=float(vals["Z2-Tol"]), zeit=float(vals["Zeit"]),
                    ng=float(vals["Ng"]),
                ))
            except ValueError:
                messagebox.showerror("Fehler", "Ungueltiger Zahlenwert in der Tabelle.")
                return

        if not points:
            messagebox.showinfo("Hinweis", "Keine Nietpunkte in der Tabelle.")
            return

        carrier = None
        vorwahl = 0
        if self.creating_new:
            if not target.isdigit() or not (1 <= len(target) <= 10):
                messagebox.showerror(
                    "Fehler", "Programmnummer muss aus 1 bis 10 Ziffern bestehen "
                              "(z.B. '17' wird automatisch zu 0000000017 ergaenzt).")
                return
            target = target.zfill(10)
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, target)
        carrier, vorwahl_res = self._ask_program_options(self.creating_new)
        if carrier == "CANCELLED":
            return  # abgebrochen
        if self.creating_new:
            vorwahl = vorwahl_res

        carrier_desc = f"Warentraeger {carrier}" if carrier else "Warentraeger beibehalten"
        if not messagebox.askyesno(
                "Sicherheitsabfrage",
                (f"NEUES Programm '{target}' mit {len(points)} Punkt(en) anlegen "
                 f"({carrier_desc}, Vorwahl {vorwahl})?\n\n"
                 if self.creating_new else
                 f"Programm '{target}' mit {len(points)} Punkt(en) ueberschreiben "
                 f"({carrier_desc})?\n\n") +
                "Nur mit einem TESTPROGRAMM fortfahren, wenn du dir nicht "
                "sicher bist! Ein neues File wird gespeichert, das Original "
                "bleibt unveraendert."):
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".hfe" if self.current_is_hfe else ".img",
            filetypes=[("HFE-Datei", "*.hfe"), ("IMG-Datei", "*.img")],
            title="Datei speichern unter...")
        if not save_path:
            return

        try:
            self.status.set("Verarbeite...")
            self.update_idletasks()

            tmp_img = tempfile.mktemp(suffix=".img")
            if self.creating_new:
                ok, msg = kc.create_program(self.img_data, target, points, tmp_img,
                                             carrier=carrier, vorwahl=vorwahl)
            else:
                ok, msg = kc.patch_program(self.img_data, target, points, tmp_img,
                                            carrier=carrier)
            if not ok:
                messagebox.showerror("Fehler", msg)
                self.status.set("Fehler.")
                return

            out_ext = os.path.splitext(save_path)[1].lower()
            if out_ext == ".hfe":
                self.status.set("Konvertiere zu HFE...")
                self.update_idletasks()
                hc.img_to_hfe(tmp_img, save_path)
            else:
                import shutil
                shutil.copyfile(tmp_img, save_path)

            self.status.set(f"Gespeichert: {save_path}")
            messagebox.showinfo(
                "Fertig",
                f"Gepatchte Datei gespeichert:\n{save_path}\n\n"
                "Bitte vor produktivem Einsatz an der Maschine pruefen!")

            # Direkt zur Kontrolle neu laden
            self._load_path(save_path)

        except Exception as e:
            messagebox.showerror("Fehler", f"{e}\n\n{traceback.format_exc()}")
            self.status.set("Fehler.")


def main():
    app = KellerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
