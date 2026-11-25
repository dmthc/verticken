#!/usr/bin/env python3
"""Baut die ISBN-Datenbank für die App aus den Open-Library-Datendumps.

Aufruf (liest die Dumps als Datei oder Pipe):
    python3 tools/build_db.py EDITIONS_DUMP AUTHORS_DUMP AUSGABE_ORDNER

Auswahl: Ausgaben mit gültiger ISBN, die entweder eine deutsche ISBN (978-3…)
haben oder als Sprache Deutsch eingetragen sind.

Ausgabe (statische Dateien, im Browser abrufbar):
    isbn/NN.tsv   – je Zeile: isbn13 \t titel \t autor \t jahr \t verlag
                    Datei NN = die zwei Ziffern vor der Prüfziffer
    title/NNN.tsv – je Zeile: suchwort \t isbn13,isbn13,…
                    Datei NNN = Hash des Suchworts modulo TITLE_SHARDS
    meta.json     – Anzahl Einträge, Stand, Quelle
"""
import gzip, json, os, re, sys, unicodedata, zlib, datetime

TITLE_SHARDS = 300
STOP = set("""der die das den dem des ein eine einer eines einem einen und oder mit von vom zum zur
im in am an auf aus bei für fur über uber unter nach vor bis wie was wer ist sind the and for with from
of to a an on at by band teil roman buch bücher bucher edition ausgabe auflage neue neu""".split())


def open_any(path):
    if path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def valid13(c):
    if not re.fullmatch(r"\d{13}", c):
        return False
    s = sum(int(c[i]) * (3 if i % 2 else 1) for i in range(12))
    return (10 - s % 10) % 10 == int(c[12])


def to13(raw):
    c = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(c) == 13 and valid13(c) and c.startswith(("978", "979")):
        return c
    if len(c) == 10 and re.fullmatch(r"\d{9}[\dX]", c):
        s = sum((10 if ch == "X" else int(ch)) * (10 - i) for i, ch in enumerate(c))
        if s % 11:
            return None
        b = "978" + c[:9]
        s = sum(int(b[i]) * (3 if i % 2 else 1) for i in range(12))
        return b + str((10 - s % 10) % 10)
    return None


def fold(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")
    return s


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", fold(text)) if len(t) >= 3 and t not in STOP]


def clean(s, n=200):
    return re.sub(r"[\t\r\n]+", " ", str(s or "")).strip()[:n]


def year_of(s):
    m = re.search(r"(1[5-9]\d\d|20\d\d)", str(s or ""))
    return m.group(1) if m else ""


def main():
    editions_path, authors_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(os.path.join(out, "isbn"), exist_ok=True)
    os.makedirs(os.path.join(out, "title"), exist_ok=True)

    # Pass 1: Ausgaben filtern
    records = {}        # isbn13 -> [titel, autor-schlüssel|by_statement, jahr, verlag]
    need_authors = set()
    seen = kept = 0
    for line in open_any(editions_path):
        seen += 1
        if seen % 2_000_000 == 0:
            print(f"  Ausgaben gelesen: {seen:,}  behalten: {kept:,}", flush=True)
        parts = line.rstrip("\n").split("\t", 4)
        if len(parts) < 5 or parts[0] != "/type/edition":
            continue
        try:
            d = json.loads(parts[4])
        except ValueError:
            continue
        isbns = {x for x in (to13(i) for i in (d.get("isbn_13") or []) + (d.get("isbn_10") or [])) if x}
        if not isbns:
            continue
        langs = {l.get("key", "") for l in d.get("languages") or [] if isinstance(l, dict)}
        german = "/languages/ger" in langs
        title = clean(d.get("title"))
        if not title:
            continue
        if d.get("subtitle"):
            title = clean(title + ": " + clean(d["subtitle"]), 250)
        akeys = [a.get("key") for a in d.get("authors") or [] if isinstance(a, dict) and a.get("key")]
        by = clean(d.get("by_statement"), 120)
        pub = clean((d.get("publishers") or [""])[0], 80)
        yr = year_of(d.get("publish_date"))
        for isbn in isbns:
            if not (german or isbn.startswith("9783")):
                continue
            if isbn in records:
                continue
            records[isbn] = [title, akeys[:3] or by, yr, pub]
            need_authors.update(akeys[:3])
            kept += 1
    print(f"Ausgaben gesamt: {seen:,}, ausgewählt: {kept:,}, benötigte Autoren: {len(need_authors):,}", flush=True)

    # Pass 2: Autorennamen
    names = {}
    for line in open_any(authors_path):
        parts = line.rstrip("\n").split("\t", 4)
        if len(parts) < 5 or parts[1] not in need_authors:
            continue
        try:
            names[parts[1]] = clean(json.loads(parts[4]).get("name"), 80)
        except ValueError:
            pass
    print(f"Autorennamen gefunden: {len(names):,}", flush=True)

    # Ausgabe schreiben
    isbn_shards = {}
    title_index = {}
    for isbn, (title, who, yr, pub) in records.items():
        author = ", ".join(n for n in (names.get(k, "") for k in who) if n) if isinstance(who, list) else who
        isbn_shards.setdefault(isbn[10:12], []).append("\t".join([isbn, title, author, yr, pub]))
        words = set(tokens(title)) | set(tokens(author)[:4])
        for w in words:
            title_index.setdefault(w, []).append(isbn)
    for k, rows in isbn_shards.items():
        rows.sort()
        with open(os.path.join(out, "isbn", f"{k}.tsv"), "w", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
    shards = {}
    for w, lst in title_index.items():
        shards.setdefault(zlib.crc32(w.encode()) % TITLE_SHARDS, []).append(w + "\t" + ",".join(sorted(lst)))
    for k, rows in shards.items():
        rows.sort()
        with open(os.path.join(out, "title", f"{k:03d}.tsv"), "w", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
    meta = {"records": len(records), "words": len(title_index), "title_shards": TITLE_SHARDS,
            "source": "Open Library Datendumps (openlibrary.org/developers/dumps)",
            "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "filter": "ISBN 978-3… oder Sprache Deutsch"}
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
