"""Who produced the audited SQL of a capture.

Siron usually connects with one database user, so anyone using Siron (or a batch
job) while you record lands in the same capture. Each audit record carries the
OS user, machine, program and client identifier of its session; grouping by
them shows whether a capture is clean, and lets the user drop the sources that
are not theirs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set

SOURCE_FIELDS = ("db_user", "os_user", "host", "program", "client_id")


def source_key(record: dict) -> str:
    return "|".join((record.get(f) or "").strip() for f in SOURCE_FIELDS)


@dataclass
class Source:
    key: str
    db_user: str
    os_user: str
    host: str
    program: str
    client_id: str
    records: int = 0
    sessions: Set[str] = field(default_factory=set)
    sql_ids: Set[str] = field(default_factory=set)
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    excluded: bool = False

    @property
    def label(self) -> str:
        who = self.os_user or "?"
        where = self.host or "?"
        prog = self.program or "program yok"
        text = "%s @ %s · %s" % (who, where, prog)
        if self.client_id:
            text += " · %s" % self.client_id
        return text


def breakdown(records: Iterable[dict], excluded: Sequence[str] = ()) -> List[Source]:
    """Sources ordered by record count (largest first)."""
    out = {}
    excluded = set(excluded or ())
    for r in records:
        key = source_key(r)
        src = out.get(key)
        if src is None:
            src = out[key] = Source(key, *[(r.get(f) or "").strip() for f in SOURCE_FIELDS], excluded=key in excluded)
        src.records += 1
        if r.get("session_id"):
            src.sessions.add(str(r["session_id"]))
        if r.get("sql_id"):
            src.sql_ids.add(r["sql_id"])
        ts = r.get("ts")
        if ts:
            src.first_ts = min(src.first_ts or ts, ts)
            src.last_ts = max(src.last_ts or ts, ts)
    return sorted(out.values(), key=lambda s: (-s.records, s.key))


def assess(sources: List[Source]) -> List[str]:
    """Plain-language warnings about mixing; empty when the capture looks clean."""
    active = [s for s in sources if not s.excluded]
    warnings = []
    people = {(s.os_user, s.host) for s in active if s.os_user or s.host}
    programs = {s.program for s in active if s.program}
    clients = {s.client_id for s in active if s.client_id}
    if len(people) > 1:
        warnings.append("%d farklı kullanıcı/makine SQL çalıştırmış: başka biri Siron'u kullanıyor olabilir." % len(people))
    if len(programs) > 1:
        warnings.append("%d farklı program görüldü (%s): batch işi veya başka bir araç karışmış olabilir."
                        % (len(programs), ", ".join(sorted(programs)[:4])))
    if len(clients) > 1:
        warnings.append("%d farklı client identifier var: uygulama kullanıcısını ayırt etmek için kullanılabilir."
                        % len(clients))
    sessions = sum(len(s.sessions) for s in active)
    if not warnings and sessions > 1 and len(active) == 1:
        warnings.append("Tek kaynak ama %d farklı oturum: Siron bağlantı havuzu kullanıyor olabilir. Aynı anda başka "
                        "kullanıcı varsa SQL'leri oturumdan ayırmak mümkün olmaz; yakalamayı test ortamında veya "
                        "mesai dışında tekrarlamak en güvenlisidir." % sessions)
    return warnings


def is_mixed(sources: List[Source]) -> bool:
    active = [s for s in sources if not s.excluded]
    return len({(s.os_user, s.host, s.program, s.client_id) for s in active}) > 1


def filter_records(records: Iterable[dict], excluded: Sequence[str]) -> List[dict]:
    excluded = set(excluded or ())
    if not excluded:
        return list(records)
    return [r for r in records if source_key(r) not in excluded]
