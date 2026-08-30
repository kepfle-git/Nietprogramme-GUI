Keller Nietprogramm-Tool
=========================

INHALT DIESES ORDNERS
----------------------
  keller_gui.py        - Die grafische Anwendung (Hauptprogramm)
  keller_core.py        - Kernlogik: Lesen/Schreiben der Nietprogramm-Daten
  hfe_convert.py         - Wrapper fuer die HFE<->IMG-Konvertierung
  keller_diskdef.cfg     - Beschreibung des Diskettenformats (80 Zyl., 2
                           Seiten, 16x256-Byte-Sektoren MFM)
  greaseweazle/           - Gebuendelte Greaseweazle-Bibliothek (fuer die
                           HFE<->IMG-Konvertierung, MIT/Unlicense-lizenziert)
  requirements.txt       - Benoetigte Python-Zusatzpakete


SCHNELLSTART (Python bereits installiert)
-------------------------------------------
1. Python 3.9 oder neuer installieren (falls noch nicht vorhanden):
   https://www.python.org/downloads/  (beim Installer "Add to PATH" ankreuzen!)

2. In diesem Ordner (Shift+Rechtsklick -> "PowerShell hier oeffnen" oder
   "Terminal hier oeffnen") folgenden Befehl ausfuehren:

       pip install -r requirements.txt

3. Programm starten:

       python keller_gui.py

Das war's - die Anwendung oeffnet sich als Fenster. Du kannst direkt eine
.hfe-Datei oeffnen (keine HxC-Software mehr noetig!) oder eine .img-Datei.


EINE STANDALONE .EXE BAUEN (optional)
----------------------------------------
Wenn du das Tool als einzelne .exe-Datei haben moechtest (z.B. um es ohne
Python-Installation an Kollegen weiterzugeben):

1. Schritte 1+2 von oben durchfuehren, zusaetzlich:

       pip install pyinstaller

2. In diesem Ordner ausfuehren:

       pyinstaller --onefile --windowed ^
           --add-data "greaseweazle;greaseweazle" ^
           --add-data "keller_diskdef.cfg;." ^
           keller_gui.py

   (Das "^" ist der Windows-Zeilenumbruch fuer cmd - bei PowerShell
   stattdessen ein Backtick "`" verwenden, oder alles in eine Zeile
   schreiben.)

3. Die fertige .exe liegt danach in: dist\keller_gui.exe

   Diese eine Datei kann jetzt eigenstaendig (ohne Python-Installation)
   auf jedem Windows-Rechner ausgefuehrt werden.


BENUTZUNG
----------
1. "Datei oeffnen" -> .hfe oder .img auswaehlen.
2. Links in der Liste ein Programm anklicken -> die Nietpunkte werden
   rechts in der Tabelle angezeigt.
3. Zum Bearbeiten: Zeile auswaehlen -> "Ausgewaehlte Zeile bearbeiten",
   oder "Zeile hinzufuegen" fuer einen neuen Punkt.
4. Feld "Ziel-Programmnummer": Zielprogrammnummer eintragen (z.B.
   0000000005 fuer ein Testprogramm) und "Speichern (patchen / neu
   anlegen)..." klicken. Es wird eine NEUE Datei gespeichert - das
   Original bleibt unveraendert.
5. Die gespeicherte Datei kann direkt als .hfe gewaehlt werden (dann wird
   automatisch passend konvertiert) oder als .img.

NEUES PROGRAMM ANLEGEN (statt ein bestehendes zu ueberschreiben)
--------------------------------------------------------------------
1. Datei laden (wie oben) - wird als Vorlage fuer Warentraeger-
   Kalibrierwerte benoetigt.
2. Button "Neues Programm anlegen" klicken -> Tabelle wird geleert.
3. Ziel-Programmnummer eingeben: 1 bis 10 Ziffern, die noch nicht
   vergeben sind - wird automatisch auf 10 Stellen aufgefuellt
   (z.B. "17" wird zu 0000000017). Die Liste links zeigt, welche
   Nummern schon belegt sind.
4. Punkte ueber "Zeile hinzufuegen" eintragen.
5. "Speichern (patchen / neu anlegen)..." klicken -> es erscheint ein
   Dialog fuer Warentraeger (A/B) und Vorwahl (Sollstueckzahl) - dann
   Speicherort waehlen.

Das Tool sucht sich automatisch freien Speicherplatz und einen freien
Verzeichnis-Slot; bestehende Programme werden dabei nicht angetastet
(im Test verifiziert: alle 62 Original-Programme blieben beim Anlegen
eines neuen Programms byte-identisch unveraendert).


FORMAT-ERKENNTNISSE (fuer Interessierte / zur Fehlersuche)
--------------------------------------------------------------
- Jedes Programm hat einen 108-Byte-Kopfbereich vor den Nietpunkt-
  Records mit denselben Zaehlern, die auch am Maschinenbildschirm
  erscheinen: Slot 0 = Gesamt, Slot 6 = Vorwahl, Slot 12 = Teil n.i.O.,
  Slot 18 = Teil i.O. (verifiziert gegen echte Bildschirmwerte).
- Slots 42/48/54/60 im Kopfbereich sind Kalibrierwerte, die exakt mit
  dem Warentraeger-Marker (Slot 0 jedes Nietpunkt-Records) korrelieren -
  vermutlich ein Warentraeger-spezifisches Referenzprofil.
- Die Sektor-Verkettung (4-Byte-Header je 256-Byte-Sektor: naechster/
  vorheriger Sektor) ist nicht immer streng fortlaufend - es gibt
  vereinzelt "verwaiste" Sektoren mitten in einem Programmbereich, die
  laut ihrer eigenen Verkettung zu einem anderen (vermutlich geloeschten)
  Programm gehoeren. Das Tool folgt beim NEU ANLEGEN korrekt der echten
  Verkettung und nutzt nur echte freie Bereiche; beim Lesen bestehender
  Programme wird weiterhin der einfachere "von Start bis naechstes
  Programm"-Bereich verwendet, was sich in Tests als robust genug
  erwiesen hat.
- Byte 27 im 32-Byte-Verzeichniseintrag ist vermutlich eine interne
  ID/Seriennummer (nicht Sektor- oder Punktanzahl, wie zunaechst
  angenommen) - beim Anlegen wird automatisch eine bisher unbenutzte
  Nummer vergeben.
- GELOEST: Die pdOS-Sektor-Bitmap wurde gefunden (offiziell dokumentiert
  im PDOS 2.4 Handbuch, Appendix D) - sie liegt in Sektor 0, Byte 32-227
  (1 Bit pro Sektor, 1=belegt/0=frei, nur fuer Sektoren < NPS = "Number
  of PDOS Sectors", ein Feld in Sektor 0 Byte 26-27). Sektoren jenseits
  NPS werden von pdOS gar nicht verwaltet. "Neues Programm anlegen"
  aktualisiert diese Bitmap jetzt automatisch (verifiziert: nur die
  exakt erwarteten Bitmap-Bytes aendern sich, alles andere bleibt
  bit-identisch). Das fruehere Langzeit-Risiko (pdOS koennte neu belegte
  Sektoren spaeter faelschlich wieder freigeben) ist damit behoben.


WICHTIGE SICHERHEITSHINWEISE
-------------------------------
- "Neues Programm anlegen" ist etwas weniger erprobt als das Ueberschreiben
  bestehender Programme (Byte 27 im Verzeichniseintrag ist z.B. nicht
  abschliessend verstanden, siehe oben), aber das fruehere Bitmap-Risiko
  ist inzwischen behoben (siehe Format-Erkenntnisse). Testet trotzdem
  zuerst mit einer unkritischen Programmnummer und prueft das Ergebnis
  sorgfaeltig am Maschinenbildschirm, bevor produktiv damit gearbeitet wird.

- Das Schreiben/Patchen wurde bisher NUR software-seitig verifiziert
  (Round-Trip-Tests: eigene Werte zurueckschreiben und pruefen, dass exakt
  das Original wieder rauskommt) - NICHT an der echten Maschine getestet!

- Vor dem produktiven Einsatz:
    1. Nur mit einem Testprogramm ueben (z.B. 0000000005-0000000018 -
       das sind vermutlich Testprogramme mit wenigen Punkten).
    2. Ergebnis nach dem Schreiben nochmal im Tool auslesen und mit den
       eingegebenen Werten vergleichen.
    3. Die gepatchte Diskette/das Image an der Maschine laden und die
       Werte am MASCHINEN-BILDSCHIRM pruefen, BEVOR ein echter Nietvorgang
       gestartet wird.
    4. Immer eine Sicherungskopie des unveraenderten Original-Images
       aufheben.

- Offener Punkt: Die genaue Bedeutung von "Abh." (Spalte im Tool
  vorhanden) ist reverse-engineered, aber in keinem der bisher
  untersuchten Beispielprogramme mit einem von 0 verschiedenen Wert
  aufgetreten - die Kodierung fuer "Abh. aktiv" (Eingabe "1") ist daher
  nicht endgueltig verifiziert.

- Slot 0 (Warentraeger-Marker) wird beim Patchen automatisch vom
  Zielprogramm uebernommen (haeufigster vorhandener Wert) - falls du das
  Programm fuer den jeweils ANDEREN Warentraeger schreiben willst, sag
  Bescheid, dann bauen wir eine Auswahlmoeglichkeit dafuer ein.
