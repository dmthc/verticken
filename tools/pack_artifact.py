#!/usr/bin/env python3
"""Verkleinert data/ (aus build_db.py) auf ein Format, das in ein Claude-Artefakt passt
(nur Textdateien, insgesamt unter 256 MB).

Aufruf: python3 tools/pack_artifact.py data AUSGABE_ORDNER

Inhalt: nur ISBNs 978-3… (deutscher Sprachraum), Titel auf 40 und Autor auf 25 Zeichen gekürzt.
    rows/NNN.txt  – je 20.000 Bücher, nach ISBN sortiert. Zeile: isbn-abstand(base36) \t titel \t autor \t jahr
                    Die erste Zeile einer Datei enthält den Abstand zu 9783000000000.
    words/NNN.txt – Suchwort \t Zeilennummern als Abstände (base36), Komma-getrennt
    meta.json     – Erste ISBN je rows-Datei, Anzahl, Stand
"""
import json, os, re, sys, zlib

CTRL = re.compile(r"[\x00-\x1f\x7f\ufffd\u200b-\u200f\u2028\u2029\ufeff]")

SRC, OUT = sys.argv[1], sys.argv[2]
CHUNK, SHARDS, BASE = 20000, 300, 9783000000000
os.makedirs(OUT + "/rows", exist_ok=True)
os.makedirs(OUT + "/words", exist_ok=True)


def b36(n):
    d, s = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        n, r = divmod(n, 36)
        s = d[r] + s
        if not n:
            return s


recs = []
for f in os.listdir(SRC + "/isbn"):
    for line in open(SRC + "/isbn/" + f, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if p[0].startswith("9783"):
            recs.append((int(p[0]), CTRL.sub("", p[1])[:40].strip(), CTRL.sub("", p[2]).split(",")[0][:25].strip(), p[3] if len(p) > 3 else ""))
recs.sort()
row_of = {r[0]: i for i, r in enumerate(recs)}
firsts = []
for c in range(0, len(recs), CHUNK):
    part = recs[c:c + CHUNK]
    firsts.append(str(part[0][0]))
    prev, lines = BASE, []
    for isbn, t, a, y in part:
        lines.append(f"{b36(isbn - prev)}\t{t}\t{a}\t{y}")
        prev = isbn
    with open(f"{OUT}/rows/{c // CHUNK:03d}.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

shards = {}
for f in os.listdir(SRC + "/title"):
    for line in open(SRC + "/title/" + f, encoding="utf-8"):
        w, _, lst = line.rstrip("\n").partition("\t")
        rows = sorted(row_of[int(x)] for x in lst.split(",") if x and int(x) in row_of)
        if not rows:
            continue
        prev, parts = 0, []
        for r in rows:
            parts.append(b36(r - prev))
            prev = r
        shards.setdefault(zlib.crc32(w.encode()) % SHARDS, []).append(w + "\t" + ",".join(parts))
for k, lines in shards.items():
    lines.sort()
    with open(f"{OUT}/words/{k:03d}.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

meta = {"records": len(recs), "chunk": CHUNK, "shards": SHARDS, "firsts": firsts,
        "source": "Open Library Datendumps", "built": json.load(open(SRC + "/meta.json"))["built"]}
json.dump(meta, open(OUT + "/meta.json", "w"))
tot = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
print(f"Bücher: {len(recs):,}  Dateien: {len(firsts)} + {len(shards)}  Größe: {tot / 1e6:.1f} MB")
