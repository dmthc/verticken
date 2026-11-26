#!/usr/bin/env python3
"""Liest den DNB-Gesamtabzug (N-Triples, vorgefiltert per grep) und schreibt eine TSV mit
isbn13 \t titel \t autor \t jahr \t verlag   (nur ISBNs mit dem Präfix PREFIX, Standard 9783).

Aufruf: ... | python3 tools/build_dnb.py - AUSGABE.tsv [PREFIX]
Datensätze stehen im Abzug zusammenhängend; ein Datensatz endet, wenn das Subjekt wechselt.
"""
import re, sys, unicodedata

OUT = sys.argv[2]
PREFIX = sys.argv[3] if len(sys.argv) > 3 else "9783"
P = {
    "<http://purl.org/ontology/bibo/isbn13>": "i", "<http://purl.org/ontology/bibo/isbn10>": "i",
    "<http://purl.org/ontology/bibo/gtin14>": "g", "<http://purl.org/dc/elements/1.1/title>": "t",
    "<http://rdaregistry.info/Elements/u/P60327>": "a", "<http://purl.org/dc/elements/1.1/publisher>": "p",
    "<http://purl.org/dc/terms/issued>": "y",
    "<http://purl.org/dc/terms/medium>": "m", "<http://rdaregistry.info/Elements/u/P60048>": "m",
}
ONLINE = "RDACarrierType/1018"  # Online-Ressource (E-Book, PDF) – wird nicht angekauft
skipped = 0
LIT = re.compile(r'^"((?:[^"\\]|\\.)*)"')
ESC = re.compile(r'\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)')
CTRL = re.compile(r"[\x00-\x1f\x7f�]+")


def unesc(m):
    e = m.group(1)
    if e[0] in "uU":
        return chr(int(e[1:], 16))
    return {"t": " ", "n": " ", "r": " ", '"': '"', "\\": "\\"}.get(e, e)


def lit(o):
    m = LIT.match(o)
    if not m:
        return ""
    s = ESC.sub(unesc, m.group(1))
    s = unicodedata.normalize("NFC", s)
    return CTRL.sub(" ", s).strip()


def to13(raw):
    c = re.sub(r"[^0-9Xx]", "", raw).upper()
    if len(c) == 14 and c[0] == "0":
        c = c[1:]
    if len(c) == 13 and c.startswith(("978", "979")) and c.isdigit():
        s = sum(int(c[i]) * (3 if i % 2 else 1) for i in range(12))
        return c if (10 - s % 10) % 10 == int(c[12]) else None
    if len(c) == 10 and re.fullmatch(r"\d{9}[\dX]", c):
        if sum((10 if ch == "X" else int(ch)) * (10 - i) for i, ch in enumerate(c)) % 11:
            return None
        b = "978" + c[:9]
        s = sum(int(b[i]) * (3 if i % 2 else 1) for i in range(12))
        return b + str((10 - s % 10) % 10)
    return None


def author_of(stmt):
    # "Jane Roberts. [Übers. aus d. Amerikan.: ...]" -> "Jane Roberts"
    s = re.split(r"\s*(?:;|\[|\. \[| / )\s*", stmt)[0]
    s = re.sub(r"^(?:von|by|hrsg\.? von|hg\.? von)\s+", "", s, flags=re.I)
    return s.strip(" .,:")[:80]


out = open(OUT, "w", encoding="utf-8")
online = open(OUT + ".online", "w", encoding="utf-8")  # ISBNs von E-Books, werden auch aus Open Library entfernt
cur, rec = None, {}
n = kept = 0


def flush():
    global kept, skipped
    if any(ONLINE in m for m in rec.get("m", [])):
        skipped += 1
        for x in {to13(v) for v in rec.get("i", []) + rec.get("g", [])}:
            if x and x.startswith(PREFIX):
                online.write(x + "\n")
        return
    isbns = {x for x in (to13(v) for v in rec.get("i", []) + rec.get("g", [])) if x and x.startswith(PREFIX)}
    t = rec.get("t", [""])[0]
    if not isbns or not t:
        return
    a = author_of(rec.get("a", [""])[0])
    y = next((m.group(0) for v in rec.get("y", []) for m in [re.search(r"1[5-9]\d\d|20\d\d", v)] if m), "")
    p = rec.get("p", [""])[0][:80]
    for i in isbns:
        out.write(f"{i}\t{t[:250]}\t{a}\t{y}\t{p}\n")
        kept += 1


for line in sys.stdin if sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8"):
    n += 1
    if n % 20_000_000 == 0:
        print(f"  Zeilen: {n:,}  ISBN-Einträge: {kept:,}", flush=True)
    s, _, rest = line.partition(" ")
    pr, _, o = rest.partition(" ")
    k = P.get(pr)
    if not k:
        continue
    if s != cur:
        if cur is not None:
            flush()
        cur, rec = s, {}
    v = o.split(">")[0] if k == "m" else lit(o)
    if v:
        rec.setdefault(k, []).append(v)
if cur is not None:
    flush()
out.close()
online.close()
print(f"Fertig: {n:,} Zeilen, {kept:,} ISBN-Einträge mit Präfix {PREFIX}, {skipped:,} Online-Ressourcen übersprungen", flush=True)
