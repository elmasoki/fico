"""Migration package: which tables and columns to move, in which order, with
which filter - turned into SQL scripts (zip) or extracted to CSV files."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .catalog import ann, label
from .relations import Relation, qi, qualified

ObjectKey = Tuple[Optional[str], str]
COLUMN_MODES = {
    "decided": "Taşınacak işaretli kolonlar (yoksa ekranda kullanılanlar)",
    "used": "Ekranlarda kullanılan kolonlar",
    "all": "Tüm kolonlar",
}


@dataclass
class Step:
    order: int
    key: ObjectKey
    columns: List[str]
    target: Optional[str] = None
    filter: Optional[str] = None
    num_rows: Optional[int] = None
    parents: List[ObjectKey] = field(default_factory=list)
    note: Optional[str] = None
    cycle: bool = False

    @property
    def file_stem(self) -> str:
        return "%02d_%s" % (self.order, self.key[1])

    def select_sql(self, catalog=None) -> str:
        cols = ",\n       ".join(qi(c) for c in self.columns) or "*"
        sql = "SELECT %s\n  FROM %s" % (cols, qualified(self.key))
        if self.filter:
            sql += "\n WHERE %s" % self.filter
        pk = catalog.primary_key(self.key) if catalog else ()
        if pk:
            sql += "\n ORDER BY %s" % ", ".join(qi(c) for c in pk)
        return sql

    def count_sql(self) -> str:
        sql = "SELECT COUNT(*) FROM %s" % qualified(self.key)
        return sql + (" WHERE %s" % self.filter if self.filter else "")


def load_order(tables: List[ObjectKey], relations: List[Relation], min_confidence: int = 50):
    """Parents before children (Kahn's algorithm); cycles are appended and flagged."""
    tset = set(tables)
    parents: Dict[ObjectKey, set] = {t: set() for t in tables}
    for r in relations:
        if (r.directed and r.child in tset and r.parent in tset and r.child != r.parent
                and r.confidence >= min_confidence):
            parents[r.child].add(r.parent)
    order, done = [], set()
    remaining = sorted(tables, key=lambda k: (k[0] or "", k[1]))
    while remaining:
        ready = [t for t in remaining if parents[t] <= done]
        if not ready:
            break
        for t in ready:
            order.append((t, False))
            done.add(t)
        remaining = [t for t in remaining if t not in done]
    order.extend((t, True) for t in remaining)  # part of a cycle
    return order, parents


def build_plan(catalog, annotations: dict, relations: List[Relation], used_columns: Dict[ObjectKey, set],
               mode: str = "decided", tables: Optional[List[ObjectKey]] = None) -> List[Step]:
    if tables is None:
        tables = [(o or None, t) for (o, t, c), a in annotations.items() if not c and a.get("status") == "migrate"]
    order, parents = load_order(tables, relations)
    # key columns must travel with the data even when nobody marked them:
    # primary keys and the columns of relations between the migrated tables
    tset = set(tables)
    key_cols: Dict[ObjectKey, set] = {}
    for r in relations:
        if r.child in tset and r.parent in tset and r.confidence >= 85:
            key_cols.setdefault(r.child, set()).update(r.child_cols)
            key_cols.setdefault(r.parent, set()).update(r.parent_cols)
    steps = []
    for i, (key, cycle) in enumerate(order, start=1):
        info = catalog.tables.get(key) if catalog else None
        all_cols = [c.name for c in info.columns] if info else []
        ignored = {c for c in all_cols if ann(annotations, key, c).get("status") == "ignore"}
        decided = [c for c in all_cols if ann(annotations, key, c).get("status") == "migrate"]
        used = [c for c in all_cols if c in used_columns.get(key, set())]
        if mode == "all":
            cols = all_cols
        elif mode == "used":
            cols = used or all_cols
        else:
            cols = decided or used or all_cols
        required = set(catalog.primary_key(key) if catalog else ()) | key_cols.get(key, set())
        cols = [c for c in all_cols if c in set(cols) | required] if all_cols else cols
        cols = [c for c in cols if c not in ignored]
        t_ann = ann(annotations, key)
        steps.append(Step(i, key, cols, t_ann.get("target"), t_ann.get("extract_filter"),
                          info.num_rows if info else None, sorted(parents.get(key, ()), key=lambda k: k[1]),
                          t_ann.get("note"), cycle))
    return steps


def package_zip(steps: List[Step], catalog, mapping_csv: str, generated: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = io.StringIO()
        w = csv.writer(manifest, delimiter=";")
        w.writerow(["sira", "tablo", "hedef", "kolon_sayisi", "filtre", "tahmini_satir", "bagli_oldugu", "dongu"])
        sqlplus = ["-- SQL*Plus / SQLcl ile çalıştırın: @extract_sqlplus.sql",
                   "SET MARKUP CSV ON DELIMITER ; QUOTE ON", "SET FEEDBACK OFF TERMOUT OFF PAGESIZE 0 TRIMSPOOL ON", ""]
        counts = []
        for s in steps:
            w.writerow([s.order, label(s.key), s.target or "", len(s.columns), s.filter or "",
                        s.num_rows if s.num_rows is not None else "", ", ".join(label(p) for p in s.parents),
                        "evet" if s.cycle else ""])
            z.writestr("sql/%s.sql" % s.file_stem, "-- %s\n%s;\n" % (label(s.key), s.select_sql(catalog)))
            sqlplus += ["SPOOL %s.csv" % s.file_stem, s.select_sql(catalog) + ";", "SPOOL OFF", ""]
            counts.append("SELECT '%s' AS tablo, (%s) AS satir FROM dual" % (label(s.key), s.count_sql()))
        z.writestr("manifest.csv", "﻿" + manifest.getvalue())
        z.writestr("extract_sqlplus.sql", "\n".join(sqlplus) + "\nSET TERMOUT ON\n")
        z.writestr("counts.sql", "\nUNION ALL\n".join(counts) + ";\n" if counts else "")
        z.writestr("kolon_esleme.csv", mapping_csv)
        z.writestr("README.txt", README % {"generated": generated, "count": len(steps)})
    return buf.getvalue()


README = """Siron SQL Tracer - Taşıma paketi
Oluşturulma: %(generated)s
Tablo sayısı: %(count)d

manifest.csv         Yükleme sırası (önce üst tablolar), hedef, filtre, tahmini satır sayısı
sql/NN_TABLO.sql     Her tablo için veri çekme sorgusu (kolonlar ve filtre ile)
extract_sqlplus.sql  SQL*Plus/SQLcl ile tüm tabloları CSV'ye çıkaran betik
counts.sql           Kaynak satır sayıları (taşıma sonrası mutabakat için)
kolon_esleme.csv     Kolon eşleme matrisi (durum, hedef alan, notlar)

"dongu" işaretli tablolar birbirine döngüsel bağlıdır; yüklemede kısıtları
geçici olarak devre dışı bırakmak gerekebilir.
"""


def extract(steps: List[Step], stream, out_dir: str, catalog=None, max_rows: int = 0, progress=None) -> dict:
    """Write each step to CSV via `stream(sql, max_rows)` (yields header, then row batches)."""
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for n, s in enumerate(steps):
        if progress:
            progress(100.0 * n / max(len(steps), 1), "%s çıkarılıyor" % label(s.key))
        path = os.path.join(out_dir, s.file_stem + ".csv")
        started = time.time()
        rows = 0
        digest = hashlib.sha256()
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            gen = stream(s.select_sql(catalog), max_rows or 10 ** 12)
            writer.writerow(next(gen))
            for batch in gen:
                writer.writerows(batch)
                rows += len(batch)
                if progress:
                    progress(100.0 * n / max(len(steps), 1), "%s: %d satır" % (label(s.key), rows))
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        files.append({"order": s.order, "table": label(s.key), "file": os.path.basename(path), "rows": rows,
                      "seconds": round(time.time() - started, 1), "sha256": digest.hexdigest(),
                      "bytes": os.path.getsize(path), "expected": s.num_rows})
    with open(os.path.join(out_dir, "manifest.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sira", "tablo", "dosya", "satir", "sure_sn", "boyut", "sha256"])
        for f in files:
            w.writerow([f["order"], f["table"], f["file"], f["rows"], f["seconds"], f["bytes"], f["sha256"]])
    return {"dir": out_dir, "files": files, "total_rows": sum(f["rows"] for f in files),
            "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
