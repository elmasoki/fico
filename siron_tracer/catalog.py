"""In-memory view of the Siron data dictionary (tables, columns, comments,
constraints) loaded from the local store."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

ObjectKey = Tuple[Optional[str], str]
ColumnKey = Tuple[Optional[str], str, str]

CHAR_TYPES = {"VARCHAR2", "VARCHAR", "CHAR", "NVARCHAR2", "NCHAR"}
NUMBER_TYPES = {"NUMBER", "FLOAT", "INTEGER", "BINARY_FLOAT", "BINARY_DOUBLE"}
DATE_TYPES = {"DATE"}


def type_family(data_type: Optional[str]) -> str:
    t = (data_type or "").upper()
    if t in CHAR_TYPES:
        return "char"
    if t in NUMBER_TYPES:
        return "number"
    if t in DATE_TYPES or t.startswith("TIMESTAMP"):
        return "date"
    if t in ("CLOB", "NCLOB", "BLOB", "LONG", "RAW", "LONG RAW"):
        return "lob"
    return "other"


def label(key) -> str:
    """'OWNER.NAME' or 'OWNER.NAME.COLUMN' (owner omitted when unknown)."""
    parts = [p for p in key if p]
    return ".".join(parts)


@dataclass
class Column:
    owner: str
    table: str
    name: str
    position: int
    data_type: str
    length: Optional[int]
    precision: Optional[int]
    scale: Optional[int]
    nullable: bool
    comment: Optional[str]

    @property
    def family(self) -> str:
        return type_family(self.data_type)

    @property
    def type_label(self) -> str:
        t = self.data_type or ""
        if self.family == "char" and self.length:
            return "%s(%s)" % (t, self.length)
        if t == "NUMBER" and self.precision:
            return "NUMBER(%s%s)" % (self.precision, ",%s" % self.scale if self.scale else "")
        return t


@dataclass
class Table:
    owner: str
    name: str
    obj_type: str
    num_rows: Optional[int]
    last_analyzed: Optional[str]
    comment: Optional[str]
    columns: List[Column] = field(default_factory=list)

    @property
    def key(self) -> ObjectKey:
        return (self.owner, self.name)


@dataclass
class Constraint:
    owner: str
    name: str
    ctype: str  # P, U, R
    table: str
    r_owner: Optional[str]
    r_name: Optional[str]
    columns: Tuple[str, ...] = ()


class Catalog:
    def __init__(self, tables: List[Table], objects: Dict[ObjectKey, str],
                 constraints: List[Constraint], version: str = ""):
        self.version = version
        self.tables: Dict[ObjectKey, Table] = {t.key: t for t in tables}
        self.objects: Dict[ObjectKey, str] = dict(objects)
        for t in tables:
            self.objects.setdefault(t.key, t.obj_type)
        self.constraints = constraints
        self._by_name: Dict[str, Set[str]] = {}
        for owner, name in self.objects:
            self._by_name.setdefault(name, set()).add(owner)
        self._cols: Dict[ObjectKey, Dict[str, Column]] = {
            t.key: {c.name: c for c in t.columns} for t in tables}
        self._cons_by_name = {(c.owner, c.name): c for c in constraints}
        self._fks = None

    def __bool__(self) -> bool:
        return bool(self.objects)

    # ------------------------------------------------------------------ lookup
    def resolve(self, owner: Optional[str], name: str, default_owner: Optional[str] = None) -> Optional[ObjectKey]:
        if owner:
            return (owner, name) if (owner, name) in self.objects else None
        owners = self._by_name.get(name)
        if not owners:
            return None
        if default_owner in owners:
            return (default_owner, name)
        return (sorted(owners)[0], name)

    def object_keys(self) -> Set[ObjectKey]:
        return set(self.objects)

    def has_columns(self, key: ObjectKey) -> bool:
        return bool(self._cols.get(key))

    def column(self, key: ObjectKey, name: str) -> Optional[Column]:
        return self._cols.get(key, {}).get(name)

    def columns(self, key: ObjectKey) -> List[Column]:
        table = self.tables.get(key)
        return table.columns if table else []

    # ------------------------------------------------------------------ keys
    def keys_of(self, key: ObjectKey) -> List[Tuple[str, Tuple[str, ...]]]:
        """Primary and unique keys: [(type, columns)] with the primary key first."""
        found = [(c.ctype, c.columns) for c in self.constraints
                 if (c.owner, c.table) == key and c.ctype in ("P", "U") and c.columns]
        return sorted(found, key=lambda x: x[0] != "P")

    def primary_key(self, key: ObjectKey) -> Tuple[str, ...]:
        for ctype, cols in self.keys_of(key):
            if ctype == "P":
                return cols
        return ()

    def is_key(self, key: ObjectKey, cols) -> bool:
        cols = tuple(cols)
        return any(set(k) == set(cols) for _, k in self.keys_of(key))

    def foreign_keys(self):
        """[(child_key, child_cols, parent_key, parent_cols, constraint_name)]"""
        if self._fks is not None:
            return self._fks
        out = []
        for c in self.constraints:
            if c.ctype != "R" or not c.columns:
                continue
            ref = self._cons_by_name.get((c.r_owner, c.r_name))
            if ref is None or not ref.columns:
                continue
            out.append(((c.owner, c.table), c.columns, (ref.owner, ref.table), ref.columns, c.name))
        self._fks = out
        return out

    def fk_columns(self, key: ObjectKey) -> Set[str]:
        return {col for child, cols, _, _, _ in self.foreign_keys() if child == key for col in cols}
