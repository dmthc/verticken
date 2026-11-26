#!/usr/bin/env python3
"""Baut die komprimierte Buchdatenbank für das Claude-Artefakt (Format 2).

Aufruf: python3 tools/pack_artifact2.py OL_DATA_ORDNER DNB_TSV AUSGABE_ORDNER

Quellen: Open Library (data/isbn/*.tsv aus build_db.py) und Deutsche Nationalbibliothek (build_dnb.py).
Nur ISBNs 978-3… Bei doppelten ISBNs gewinnt der DNB-Titel.
Jede Datei ist zlib-komprimiert und Base64-kodiert (reiner Text, im Browser per DecompressionStream lesbar).
    rows/NNN.txt  – Bücher nach ISBN sortiert. Zeile: isbn-abstand(base36) \t titel \t autor \t jahr
    words/NNN.txt – Suchwort \t Zeilennummern als Abstände (base36)
    meta.json     – Erste ISBN je rows-Datei, Anzahl, Stand (unkomprimiert)
"""
import base64, datetime, json, math, os, re, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_db import tokens  # gleiche Wortzerlegung wie in der App

CTRL = re.compile(r"[\x00-\x1f\x7f�​-‏  ﻿]")
SRC, DNB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SHARDS, BASE, MAX_ROW_FILES = 256, 9783000000000, 200
TITLE, AUTHOR = 40, 25
os.makedirs(OUT + "/rows", exist_ok=True)
os.makedirs(OUT + "/words", exist_ok=True)


def b36(n):
    d, s = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        n, r = divmod(n, 36)
        s = d[r] + s
        if not n:
            return s


def cl(s, n):
    return CTRL.sub("", s or "")[:n].strip()


def put(path, text):
    with open(path, "w", encoding="ascii") as fh:
        fh.write(base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii"))


recs = {}
n_ol = n_dnb = n_both = 0
for f in os.listdir(SRC + "/isbn"):
    for line in open(SRC + "/isbn/" + f, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if p[0].startswith("9783"):
            recs[int(p[0])] = [p[1], p[2].split(",")[0] if len(p) > 2 else "", p[3] if len(p) > 3 else ""]
            n_ol += 1
for line in open(DNB, encoding="utf-8"):
    p = line.rstrip("\n").split("\t")
    if len(p) < 4 or not p[0].startswith("9783"):
        continue
    k = int(p[0])
    old = recs.get(k)
    n_dnb += 1
    if old:
        n_both += 1
        recs[k] = [p[1], p[2] or old[1], p[3] or old[2]]
    else:
        recs[k] = [p[1], p[2], p[3]]
print(f"Open Library: {n_ol:,}  DNB: {n_dnb:,}  in beiden: {n_both:,}  zusammen: {len(recs):,}", flush=True)

keys = sorted(recs)
chunk = max(20000, math.ceil(len(keys) / MAX_ROW_FILES / 1000) * 1000)
firsts, index = [], {}
for c in range(0, len(keys), chunk):
    part = keys[c:c + chunk]
    firsts.append(str(part[0]))
    prev, lines = BASE, []
    for j, isbn in enumerate(part):
        t, a, y = recs[isbn]
        t, a = cl(t, TITLE), cl(a, AUTHOR)
        lines.append(f"{b36(isbn - prev)}\t{t}\t{a}\t{y}")
        prev = isbn
        row = c + j
        for w in set(tokens(recs[isbn][0])) | set(tokens(recs[isbn][1])[:4]):
            index.setdefault(w, []).append(row)
    put(f"{OUT}/rows/{c // chunk:03d}.txt", "\n".join(lines) + "\n")
recs = None

shards = {}
for w, rows in index.items():
    prev, parts = 0, []
    for r in rows:  # schon aufsteigend
        parts.append(b36(r - prev))
        prev = r
    shards.setdefault(zlib.crc32(w.encode()) % SHARDS, []).append(w + "\t" + ",".join(parts))
for k in range(SHARDS):
    lines = sorted(shards.get(k, []))
    put(f"{OUT}/words/{k:03d}.txt", "\n".join(lines) + "\n")

meta = {"v": 2, "enc": "zlib-base64", "records": len(keys), "chunk": chunk, "shards": SHARDS, "firsts": firsts,
        "source": "Open Library und Deutsche Nationalbibliothek (CC0)",
        "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")}
json.dump(meta, open(OUT + "/meta.json", "w"))
tot = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
nfiles = sum(len(fs) for _, _, fs in os.walk(OUT))
print(f"Bücher: {len(keys):,}  Dateien: {nfiles}  Größe: {tot / 1e6:.1f} MB", flush=True)
