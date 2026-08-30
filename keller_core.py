#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keller-Nietprogramm-Tool (Lesen & Schreiben)
==============================================

Liest ein IMG-Abbild einer KELLER-GmbH-Steuerungsdiskette (Nietmaschine,
Betriebssystem TI pdOS auf TI-990/TMS9900-Basis) aus, zeigt Nietpunkt-
Programme tabellarisch an, und kann ein bestehendes Programm mit neuen
Punktwerten ueberschreiben ("patchen").

================================================================
WICHTIGER SICHERHEITSHINWEIS - BITTE UNBEDINGT LESEN
================================================================
Das Schreiben wurde bisher NUR per Round-Trip-Test (eigene Werte
zurueckschreiben und pruefen, dass exakt das Original wieder rauskommt)
verifiziert - NICHT an der echten Maschine getestet!

Bevor du ein gepatchtes Programm an der echten Maschine laedst:
  1. Teste NUR mit einem Programm, das KEINE Produktionsdaten enthaelt
     (z.B. eines der Testprogramme 0000000005-0000000018).
  2. Lies das Ergebnis mit --read hinterher nochmal aus und vergleiche
     die angezeigten Werte sorgfaeltig mit dem, was du eingegeben hast.
  3. Lade das gepatchte Programm zuerst und pruefe an der Maschine
     SELBST (Bildschirmanzeige), ob alle Werte stimmen, BEVOR du einen
     echten Nietvorgang startest.
  4. Behalte immer eine Kopie des unveraenderten Original-Images.

Offene Punkte im Format (koennten im Zweifel relevant sein):
  * Bedeutung von Slot 8 (Offset 48) unbekannt - wird beim Schreiben
    immer auf 0 gesetzt.
  * Nicht 100% sicher, ob/wie die Maschine Pruefsummen ueber die Daten
    bildet - dieses Tool aendert nur die Nietpunkt-Records selbst,
    laesst Sektor-Verkettung und alle anderen Bereiche unangetastet.

================================================================
FORMAT-ZUSAMMENFASSUNG
================================================================
  * Sektorgroesse 256 Byte, 4-Byte-Verkettungsheader pro Sektor.
  * Programme = "0000000NN"-Verzeichniseintraege.
  * Zahlenformat: TI-990 6-Byte-Hex-Float (Byte0=Vorzeichen+Exponent
    excess-64 Basis 16, Byte1-5=40-Bit-Mantisse). Ganzzahlen werden in
    einer Kurzform gespeichert (Byte0=0, Byte2-3=16-Bit-Integer).
  * Nietpunkt-Record = 78 Byte = 13 Slots a 6 Byte:
      Offset  0: Marker (Warentraeger-Kennung, programmweit konstant)
      Offset  6: Ng (Nietgruppe, 0=Einzelniet, sonst Gruppennummer)
      Offset 12: X
      Offset 18: Y
      Offset 24: Niederhalter-Messwert (0 falls nicht verbaut)
      Offset 30: Niederhalter-Toleranz (0 falls nicht verbaut)
      Offset 36: Z1
      Offset 42: Z1-Toleranz
      Offset 48: Abh. (Spindel hebt vor Nietmotorstart ab; 0/1-Flag,
                 bestaetigt durch einen einzelnen realen Fund im Datenbestand)
      Offset 54: Druck
      Offset 60: Z2
      Offset 66: Z2-Toleranz
      Offset 72: Zeit

Benutzung (Windows cmd):
    Lesen:   python keller_niettool.py DSKA0000_hfe.img
    Schreiben: siehe Funktion patch_program() unten / Beispiel im
               __main__-Block (write_example()).
"""

import struct
import sys
import os
from collections import Counter

SECTOR_SIZE = 256
RECORD_LEN = 78
SLOT_LEN = 6

FIELD_SLOTS = [
    ("X", 12), ("Y", 18), ("Z1", 36), ("Z1-Tol", 42),
    ("Abh.", 48), ("Druck", 54), ("Z2", 60), ("Z2-Tol", 66),
    ("Zeit", 72), ("Ng", 6),
]


# ---------------------------------------------------------------------
# Dekodierung
# ---------------------------------------------------------------------

def decode_value(b6):
    """Dekodiert einen 6-Byte-Wert (TI-990-Hexfloat oder Integer-Kurzform)."""
    if len(b6) < 6:
        return float("nan")
    e = b6[0]
    if e == 0:
        return float(int.from_bytes(b6[2:4], "big", signed=True))
    sign = -1 if (e & 0x80) else 1
    exp = (e & 0x7F) - 64
    mant_int = int.from_bytes(b6[1:6], "big")
    frac = mant_int / (16 ** 10)
    return sign * frac * (16 ** exp)


# ---------------------------------------------------------------------
# Kodierung (Kehrfunktion zu decode_value)
# ---------------------------------------------------------------------

def encode_value(v):
    """Kodiert einen Zahlenwert in das 6-Byte-TI990-Format."""
    if v == 0:
        return bytes(6)
    if abs(v - round(v)) < 1e-9 and abs(v) < 32768:
        iv = int(round(v))
        return bytes([0, 0]) + iv.to_bytes(2, "big", signed=True) + bytes([0, 0])
    sign = 0
    x = v
    if x < 0:
        sign = 1
        x = -x
    exp = 0
    while x >= 1:
        x /= 16
        exp += 1
    while x < 1 / 16:
        x *= 16
        exp -= 1
    mant_int = round(x * (16 ** 10))
    if mant_int >= 16 ** 10:
        mant_int -= 16 ** 10
        exp += 1
    exp_byte = exp + 64
    if not (0 <= exp_byte <= 0x7F):
        raise ValueError(f"Wert {v} ausserhalb des darstellbaren Bereichs")
    if sign:
        exp_byte |= 0x80
    return bytes([exp_byte]) + mant_int.to_bytes(5, "big")


def build_record(marker, ng, x, y, niederhalter=0.0, niederhalter_tol=0.0,
                  z1=0.0, z1tol=0.0, unbekannt=0.0, druck=0.0, z2=0.0,
                  z2tol=0.0, zeit=0.0):
    """Baut einen kompletten 78-Byte-Nietpunkt-Record."""
    fields = [marker, ng, x, y, niederhalter, niederhalter_tol,
              z1, z1tol, unbekannt, druck, z2, z2tol, zeit]
    rec = b"".join(encode_value(f) for f in fields)
    assert len(rec) == 78
    return rec


# ---------------------------------------------------------------------
# Image- / Verzeichnis-Handling
# ---------------------------------------------------------------------

def load_image(path):
    with open(path, "rb") as f:
        return f.read()


def find_programs(data):
    entries = []
    i = 0
    n = len(data)
    while i < n - 32:
        if data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 0x44:
            name_bytes = data[i + 3:i + 13]
            if all(48 <= b <= 57 for b in name_bytes):
                name = name_bytes.decode("ascii")
                start_sector = data[i + 16] * 256 + data[i + 17]
                entries.append({
                    "dir_offset": i,
                    "name": name,
                    "start_sector": start_sector,
                })
                i += 32
                continue
        i += 1
    return entries


def guess_end_sector(entries, this_entry):
    sectors_sorted = sorted(e["start_sector"] for e in entries)
    idx = sectors_sorted.index(this_entry["start_sector"])
    if idx + 1 < len(sectors_sorted):
        return sectors_sorted[idx + 1]
    return this_entry["start_sector"] + 9


def strip_sector_headers(data, start_sector, end_sector):
    payload = b""
    for s in range(start_sector, end_sector):
        off = s * SECTOR_SIZE
        payload += data[off + 4: off + SECTOR_SIZE]
    return payload


# ---------------------------------------------------------------------
# Record-Erkennung (Lesen)
# ---------------------------------------------------------------------

def _plausible_coord(v):
    return v == v and abs(v) < 500


def _plausible_z(v):
    return v == v and 0.3 <= abs(v) <= 60


def _plausible_tol(v):
    return v == v and 0 < v <= 5


def _plausible_druck(v):
    return v == v and 0.3 <= v <= 10


def _looks_like_record(rec):
    if len(rec) < 78:
        return False
    x = decode_value(rec[12:18])
    y = decode_value(rec[18:24])
    z1 = decode_value(rec[36:42])
    z1tol = decode_value(rec[42:48])
    druck = decode_value(rec[54:60])
    if x == 0 and y == 0:
        return False
    return (_plausible_coord(x) and _plausible_coord(y)
            and _plausible_z(z1) and _plausible_tol(z1tol)
            and _plausible_druck(druck))


def find_record_positions(payload, max_points=40):
    """Liefert die Byte-Offsets bestehender Nietpunkt-Records."""
    positions = []
    n = len(payload)
    i = 0
    fails = 0
    while i <= n - 78 and fails < 100 and len(positions) < max_points:
        rec = payload[i:i + 78]
        if _looks_like_record(rec):
            positions.append(i)
            i += 78
            fails = 0
        else:
            i += 6
            fails += 1
    return positions


def extract_points(payload):
    points = []
    for pos in find_record_positions(payload):
        rec = payload[pos:pos + 78]
        vals = {name: decode_value(rec[off:off + 6]) for name, off in FIELD_SLOTS}
        points.append(vals)
    return points


def print_table(points, prog_name):
    if not points:
        print("Keine Nietpunkte gefunden.")
        return
    headers = [name for name, _ in FIELD_SLOTS]
    print(f"\nProgramm {prog_name}: {len(points)} Nietpunkt(e)\n")
    col_w = 12
    print("Nr.".ljust(5) + "".join(h.ljust(col_w) for h in headers))
    print("-" * (5 + col_w * len(headers)))
    for n, pt in enumerate(points, start=1):
        row = str(n).ljust(5)
        for name, _ in FIELD_SLOTS:
            v = pt[name]
            txt = f"{v:.2f}" if v == v else "-"
            row += txt.ljust(col_w)
        print(row)


# ---------------------------------------------------------------------
# Schreiben / Patchen
# ---------------------------------------------------------------------

HEADER_LEN = 108
CARRIER_TEMPLATES = {}  # wird von _learn_carrier_templates() gefuellt

# --- Sektor-Bitmap in Sektor 0 (offiziell dokumentiert in PDOS 2.4
#     Handbuch, Appendix D "PDOS Disk Layout") ---
BITMAP_OFFSET = 32       # Byte-Offset innerhalb Sektor 0
NPS_OFFSET = 26          # Byte-Offset des NPS-Feldes (Number of PDOS Sectors)
FILECOUNT_OFFSET = 18    # Byte-Offset des Dateizaehler-Feldes


def get_nps(data):
    """Liest NPS (Number of PDOS Sectors) aus Sektor 0 - nur Sektoren
    unterhalb dieser Grenze werden von der pdOS-Bitmap verwaltet."""
    return int.from_bytes(data[NPS_OFFSET:NPS_OFFSET + 2], "big")


def mark_sectors_used(out_data, sectors):
    """Setzt die entsprechenden Bits in der pdOS-Sektor-Bitmap (Sektor 0)
    auf 'belegt' (1) fuer die gegebenen Sektornummern. Sektoren >= NPS
    werden ignoriert (liegen ausserhalb des von pdOS verwalteten Bereichs
    und brauchen daher kein Bitmap-Update)."""
    nps = get_nps(out_data)
    for s in sectors:
        if s >= nps:
            continue
        byte_i = BITMAP_OFFSET + s // 8
        bit_i = 7 - (s % 8)
        out_data[byte_i] |= (1 << bit_i)


def increment_file_count(out_data, delta=1):
    cur = int.from_bytes(out_data[FILECOUNT_OFFSET:FILECOUNT_OFFSET + 2], "big")
    new = cur + delta
    out_data[FILECOUNT_OFFSET:FILECOUNT_OFFSET + 2] = new.to_bytes(2, "big")


def _learn_carrier_templates(data):
    """Ermittelt fuer beide bekannten Warentraeger-Marker die zugehoerigen
    Kalibrierwerte aus dem Programm-Header (Slots 42/48/54/60), indem ein
    bestehendes Programm mit diesem Marker als Vorlage genutzt wird."""
    entries = find_programs(data)
    templates = {}
    for e in entries:
        end = guess_end_sector(entries, e)
        payload = strip_sector_headers(data, e["start_sector"], end)
        positions = find_record_positions(payload)
        if not positions:
            continue
        header = payload[:positions[0]]
        if len(header) < HEADER_LEN:
            continue
        votes = Counter()
        for pos in positions:
            v = decode_value(payload[pos:pos + 6])
            if v != 0:
                votes[round(v, 4)] += 1
        if not votes:
            continue
        marker_key = votes.most_common(1)[0][0]
        if marker_key not in templates:
            exact_marker = None
            for pos in positions:
                v = decode_value(payload[pos:pos + 6])
                if v != 0 and round(v, 4) == marker_key:
                    exact_marker = v
                    break
            templates[marker_key] = {
                "marker": exact_marker,
                "h42": decode_value(header[42:48]),
                "h48": decode_value(header[48:54]),
                "h54": decode_value(header[54:60]),
                "h60": decode_value(header[60:66]),
            }
    return templates


def find_free_directory_slot(data):
    """Sucht einen freien (komplett Null) 32-Byte-Verzeichnis-Slot
    innerhalb des bestehenden Directory-Sektorbereichs."""
    entries = find_programs(data)
    if not entries:
        return None
    offsets = sorted(e["dir_offset"] for e in entries)
    dir_start_sector = offsets[0] // SECTOR_SIZE
    dir_end_sector = offsets[-1] // SECTOR_SIZE + 1
    region_start = dir_start_sector * SECTOR_SIZE
    region_end = dir_end_sector * SECTOR_SIZE
    for off in range(region_start, region_end, 32):
        if data[off:off + 32].count(0) == 32:
            return off
    return None


def find_free_sector_run(data, n_sectors, search_start=None):
    """Sucht n_sectors zusammenhaengende, komplett leere Sektoren
    (Header UND Inhalt = 0) - beginnend ab search_start (Standard:
    direkt nach dem zuletzt vergebenen Programm)."""
    entries = find_programs(data)
    if search_start is None:
        search_start = max(guess_end_sector(entries, e) for e in entries)
    total_sectors = len(data) // SECTOR_SIZE
    run_start = None
    for s in range(search_start, total_sectors):
        off = s * SECTOR_SIZE
        is_free = data[off:off + SECTOR_SIZE].count(0) == SECTOR_SIZE
        if is_free:
            if run_start is None:
                run_start = s
            if s - run_start + 1 >= n_sectors:
                return run_start
        else:
            run_start = None
    return None


def _next_free_id_byte(data):
    """Liefert eine bisher unbenutzte Kennnummer fuer Directory-Byte 27
    (Bedeutung nicht abschliessend geklaert - vermutlich eine fortlaufende
    interne ID; wir vergeben sicherheitshalber eine bisher unbenutzte)."""
    entries = find_programs(data)
    used = set()
    for e in entries:
        b27 = data[e["dir_offset"] + 27]
        used.add(b27)
    for candidate in range(1, 256):
        if candidate not in used:
            return candidate
    return 255


def create_program(data, new_name, points, out_path, carrier="A", vorwahl=0,
                    template_name=None):
    """
    Legt ein KOMPLETT NEUES Programm an (eigener Verzeichniseintrag +
    eigene Sektoren) - im Gegensatz zu patch_program(), das nur ein
    bestehendes Programm ueberschreibt.

    new_name: 10-stelliger Programmname (z.B. '0000000020')
    points: Liste von Punkt-dicts wie bei patch_program()
    carrier: 'A' oder 'B' (die zwei bekannten Warentraeger) - bestimmt
             Marker + Kalibrierwerte im Header. Alternativ template_name
             angeben, um die Werte von einem konkreten Programm zu uebernehmen.
    vorwahl: Startwert fuer den "Vorwahl"-Zaehler (Sollstueckzahl), Default 0.

    Gibt (success: bool, message: str) zurueck.
    """
    if len(new_name) != 10 or not new_name.isdigit():
        return False, "Programmname muss aus genau 10 Ziffern bestehen."

    entries = find_programs(data)
    if any(e["name"] == new_name for e in entries):
        return False, f"Programm '{new_name}' existiert bereits."

    # Kalibrierwerte / Marker bestimmen
    if template_name is not None:
        tmpl_entry = next((e for e in entries if e["name"] == template_name), None)
        if tmpl_entry is None:
            return False, f"Vorlage '{template_name}' nicht gefunden."
        end = guess_end_sector(entries, tmpl_entry)
        payload = strip_sector_headers(data, tmpl_entry["start_sector"], end)
        positions = find_record_positions(payload)
        if not positions:
            return False, f"Vorlage '{template_name}' hat keine gueltigen Records."
        header = payload[:positions[0]]
        votes = Counter()
        for pos in positions:
            v = decode_value(payload[pos:pos + 6])
            if v != 0:
                votes[round(v, 4)] += 1
        marker = None
        if votes:
            key = votes.most_common(1)[0][0]
            for pos in positions:
                v = decode_value(payload[pos:pos + 6])
                if v != 0 and round(v, 4) == key:
                    marker = v
                    break
        tmpl = {"marker": marker, "h42": decode_value(header[42:48]),
                "h48": decode_value(header[48:54]), "h54": decode_value(header[54:60]),
                "h60": decode_value(header[60:66])}
    else:
        templates = _learn_carrier_templates(data)
        sorted_keys = sorted(templates.keys())
        if len(sorted_keys) < 2:
            return False, "Konnte nicht genug Warentraeger-Vorlagen im Image finden."
        idx = 0 if carrier.upper() == "A" else 1
        if idx >= len(sorted_keys):
            idx = 0
        tmpl = templates[sorted_keys[idx]]

    # Speicherplatz berechnen und reservieren
    needed_bytes = HEADER_LEN + len(points) * RECORD_LEN
    n_sectors = -(-needed_bytes // 252)  # aufrunden
    n_sectors = max(n_sectors, 7)  # nicht kleiner als kleinste beobachtete Groesse
    start_sector = find_free_sector_run(data, n_sectors)
    if start_sector is None:
        return False, f"Kein zusammenhaengender freier Bereich fuer {n_sectors} Sektoren gefunden."

    dir_slot = find_free_directory_slot(data)
    if dir_slot is None:
        return False, "Kein freier Verzeichnis-Slot mehr vorhanden."

    # Header bauen: Gesamt=0, Vorwahl, Teil n.i.O.=0, Teil i.O.=0,
    # dann die vom Warentraeger abhaengigen Kalibrierwerte
    header = bytearray(HEADER_LEN)
    header[0:6] = encode_value(0.0)          # Gesamt
    header[6:12] = encode_value(float(vorwahl))
    header[12:18] = encode_value(0.0)        # Teil n.i.O.
    header[18:24] = encode_value(0.0)        # Teil i.O.
    header[42:48] = encode_value(tmpl["h42"])
    header[48:54] = encode_value(tmpl["h48"])
    header[54:60] = encode_value(tmpl["h54"])
    header[60:66] = encode_value(tmpl["h60"])

    # Records bauen
    records = bytearray()
    for p in points:
        rec = build_record(
            marker=tmpl["marker"],
            ng=p.get("ng", 0.0),
            x=p["x"], y=p["y"],
            niederhalter=p.get("niederhalter", 0.0),
            niederhalter_tol=p.get("niederhalter_tol", 0.0),
            z1=p["z1"], z1tol=p["z1tol"],
            unbekannt=p.get("unbekannt", 0.0),
            druck=p["druck"], z2=p["z2"], z2tol=p["z2tol"],
            zeit=p["zeit"],
        )
        records += rec

    full_payload = bytes(header) + bytes(records)
    full_payload = full_payload + bytes(n_sectors * 252 - len(full_payload))

    out_data = bytearray(data)

    # Sektoren schreiben (einfache zusammenhaengende Verkettung)
    for i in range(n_sectors):
        sector_num = start_sector + i
        off = sector_num * SECTOR_SIZE
        next_ptr = (sector_num + 1) if i < n_sectors - 1 else 0
        prev_ptr = (sector_num - 1) if i > 0 else 0
        out_data[off:off + 2] = next_ptr.to_bytes(2, "big")
        out_data[off + 2:off + 4] = prev_ptr.to_bytes(2, "big")
        chunk = full_payload[i * 252:(i + 1) * 252]
        out_data[off + 4:off + 256] = chunk

    # Directory-Eintrag schreiben
    new_id = _next_free_id_byte(data)
    entry = bytearray(32)
    entry[0:2] = b"\x00\x00"
    entry[2] = 0x44
    entry[3:13] = new_name.encode("ascii")
    entry[13:16] = b"\x01\x00\x00"
    entry[16:18] = start_sector.to_bytes(2, "big")
    entry[18:21] = b"\x00\x00\x00"
    entry[21] = 0x06
    entry[22] = 0x00
    entry[23] = 0x06
    entry[24] = 0x00
    entry[25] = 0xA8
    entry[26] = 0x00
    entry[27] = new_id
    entry[28:32] = b"\x00\x00\x00\x16"
    out_data[dir_slot:dir_slot + 32] = entry

    # pdOS-Sektor-Bitmap aktualisieren (Sektor 0) und Dateizaehler erhoehen
    mark_sectors_used(out_data, range(start_sector, start_sector + n_sectors))
    increment_file_count(out_data, 1)

    with open(out_path, "wb") as f:
        f.write(bytes(out_data))

    return True, (f"Programm '{new_name}' angelegt: Sektoren {start_sector}-"
                   f"{start_sector + n_sectors - 1}, {len(points)} Punkt(e) -> {out_path}")


def patch_program(data, program_name, points, out_path, marker=None, carrier=None):
    """
    Schreibt eine neue Punktliste in ein bestehendes Programm und
    speichert das Ergebnis als neues Image (das Original bleibt
    unveraendert).

    points: Liste von dicts mit Schluesseln
        x, y, z1, z1tol, druck, z2, z2tol, zeit
        optional: ng (default 0), niederhalter (default 0),
                  niederhalter_tol (default 0)
    marker: optional expliziter Marker-Wert - hat Vorrang vor carrier.
    carrier: optional 'A' oder 'B' - wenn gesetzt (und marker nicht
             explizit angegeben ist), wird der Marker/die Kalibrierwerte
             des gewaehlten Warentraegers verwendet statt den bisherigen
             Marker des Zielprogramms beizubehalten.

    Gibt (success: bool, message: str) zurueck.
    """
    entries = find_programs(data)
    target = None
    for e in entries:
        if e["name"] == program_name:
            target = e
            break
    if target is None:
        return False, f"Programm '{program_name}' nicht gefunden."

    end_sector = guess_end_sector(entries, target)
    payload = strip_sector_headers(data, target["start_sector"], end_sector)
    positions = find_record_positions(payload)

    if not positions:
        return False, (f"Keine bestehenden Nietpunkt-Records in "
                        f"'{program_name}' gefunden - Ueberschreiben nicht moeglich.")

    if len(points) > len(positions):
        return False, (f"Zu viele Punkte ({len(points)}): Programm '{program_name}' "
                        f"hat nur Platz fuer {len(positions)} Punkte in seinem "
                        f"aktuell zugewiesenen Speicherbereich.")

    if marker is None and carrier is not None:
        templates = _learn_carrier_templates(data)
        sorted_keys = sorted(templates.keys())
        idx = 0 if carrier.upper() == "A" else 1
        if idx < len(sorted_keys):
            marker = templates[sorted_keys[idx]]["marker"]

    if marker is None:
        rounded_counts = Counter()
        exact_by_rounded = {}
        for pos in positions:
            v = decode_value(payload[pos:pos + 6])
            if v != 0:
                key = round(v, 4)
                rounded_counts[key] += 1
                exact_by_rounded.setdefault(key, v)
        marker = exact_by_rounded[rounded_counts.most_common(1)[0][0]] if rounded_counts else 0.0

    new_payload = bytearray(payload)
    for idx, pos in enumerate(positions):
        if idx < len(points):
            p = points[idx]
            rec = build_record(
                marker=marker,
                ng=p.get("ng", 0.0),
                x=p["x"], y=p["y"],
                niederhalter=p.get("niederhalter", 0.0),
                niederhalter_tol=p.get("niederhalter_tol", 0.0),
                z1=p["z1"], z1tol=p["z1tol"],
                unbekannt=p.get("unbekannt", 0.0),
                druck=p["druck"], z2=p["z2"], z2tol=p["z2tol"],
                zeit=p["zeit"],
            )
        else:
            rec = bytes(78)
        new_payload[pos:pos + 78] = rec

    out_data = bytearray(data)
    for s in range(end_sector - target["start_sector"]):
        sector_num = target["start_sector"] + s
        off = sector_num * SECTOR_SIZE
        header = data[off:off + 4]
        chunk = bytes(new_payload[s * 252:(s + 1) * 252])
        if len(chunk) < 252:
            chunk = chunk + data[off + 4 + len(chunk):off + 256]
        out_data[off:off + 4] = header
        out_data[off + 4:off + 256] = chunk

    with open(out_path, "wb") as f:
        f.write(bytes(out_data))

    return True, f"Programm '{program_name}' erfolgreich gepatcht -> {out_path}"





# ---------------------------------------------------------------------
# Interaktiver Lese-Modus
# ---------------------------------------------------------------------

def interactive_read(img_path):
    data = load_image(img_path)
    entries = find_programs(data)
    if not entries:
        print("Keine Programme im Verzeichnis gefunden.")
        return

    print(f"{len(entries)} Verzeichniseintraege gefunden. Programme:\n")
    for idx, e in enumerate(entries, start=1):
        print(f"  {idx:3d}) {e['name']}   (Startsektor {e['start_sector']})")

    while True:
        choice = input(
            "\nProgrammnummer eingeben (z.B. '0000000002' oder Listenindex, "
            "'q' zum Beenden): "
        ).strip()
        if choice.lower() == "q":
            break

        match = None
        for e in entries:
            if e["name"] == choice:
                match = e
                break
        if match is None and choice.isdigit() and 1 <= int(choice) <= len(entries):
            match = entries[int(choice) - 1]
        if match is None:
            try:
                padded = f"{int(choice):010d}"
                for e in entries:
                    if e["name"] == padded:
                        match = e
                        break
            except ValueError:
                pass

        if match is None:
            print("Programm nicht gefunden, bitte erneut versuchen.")
            continue

        end_sector = guess_end_sector(entries, match)
        payload = strip_sector_headers(data, match["start_sector"], end_sector)
        points = extract_points(payload)
        print(f"(Datenblock Sektor {match['start_sector']}-{end_sector - 1})")
        print_table(points, match["name"])


# ---------------------------------------------------------------------
# Beispiel fuers Schreiben - als Vorlage zum Anpassen
# ---------------------------------------------------------------------

def write_example():
    """
    Beispiel: ueberschreibt Programm '0000000002' mit Beispielwerten.
    Diese Funktion ist eine VORLAGE - passe img_path, target_program
    und points an deinen Anwendungsfall an, bevor du sie ausfuehrst.
    """
    img_path = "DSKA0000_hfe.img"
    target_program = "0000000002"   # NUR ein Testprogramm verwenden!
    out_path = "DSKA0000_patched.img"

    points = [
        dict(x=78.00, y=-14.50, z1=9.80, z1tol=0.30, druck=2.0, z2=9.04, z2tol=0.10, zeit=3.00),
        dict(x=42.50, y=-9.00, z1=10.34, z1tol=0.30, druck=1.7, z2=8.95, z2tol=0.10, zeit=3.00),
        dict(x=-36.50, y=32.54, z1=8.95, z1tol=0.30, druck=2.4, z2=8.00, z2tol=0.10, zeit=3.00),
        dict(x=52.91, y=47.52, z1=11.40, z1tol=0.30, druck=2.7, z2=10.30, z2tol=0.10, zeit=3.00),
        dict(x=-54.30, y=-53.65, z1=9.59, z1tol=0.50, druck=2.6, z2=8.61, z2tol=0.10, zeit=3.00),
        dict(x=-16.50, y=34.30, z1=9.65, z1tol=0.30, druck=2.7, z2=8.70, z2tol=0.10, zeit=3.00),
        dict(x=-111.50, y=-0.50, z1=5.47, z1tol=1.00, druck=2.0, z2=4.40, z2tol=0.10, zeit=3.00),
        dict(x=-106.50, y=-40.50, z1=5.47, z1tol=1.00, druck=2.0, z2=4.40, z2tol=0.00, zeit=3.00, ng=1.0),
    ]

    data = load_image(img_path)
    ok, msg = patch_program(data, target_program, points, out_path)
    print(msg)
    if ok:
        print("\nZur Kontrolle direkt wieder auslesen:")
        new_data = load_image(out_path)
        entries = find_programs(new_data)
        target = [e for e in entries if e["name"] == target_program][0]
        end_sector = guess_end_sector(entries, target)
        payload = strip_sector_headers(new_data, target["start_sector"], end_sector)
        print_table(extract_points(payload), target_program)
        print(f"\n{'='*60}")
        print("NAECHSTER SCHRITT: Konvertiere die Datei")
        print(f"  {out_path}")
        print("mit HxC (wie beim urspruenglichen Einlesen) zurueck zu .hfe,")
        print("und teste sie NUR mit einem Test-/Nicht-Produktionsprogramm")
        print("an der Maschine, bevor du produktive Programme aenderst!")
        print(f"{'='*60}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write-example":
        write_example()
    else:
        if len(sys.argv) > 1:
            img_path = sys.argv[1]
        else:
            img_path = input("Pfad zur .img-Datei: ").strip().strip('"')
        if not os.path.isfile(img_path):
            print(f"Datei nicht gefunden: {img_path}")
        else:
            interactive_read(img_path)
