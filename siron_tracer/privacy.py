"""Sensitive-data detection and masking for exports and reports (KVKK/AML)."""
from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional, Sequence, Set

DEFAULT_PATTERN = (
    r"TCKN|TC_?KIML|KIMLIK|IDENTITY|NATIONAL_?ID|SSN|PASSPORT|PASAPORT|VKN|TAX_?(NO|ID|NUM)|VERGI_?NO|"
    r"IBAN|ACC(OUNT)?_?(NO|NUM)|HESAP_?NO|CARD_?NO|KART_?NO|PAN$|PHONE|TEL(EFON)?(_|$)|GSM|MOBILE|"
    r"E_?MAIL|E_?POSTA|ADDRESS|ADRES|BIRTH|DOGUM|FIRST_?NAME|LAST_?NAME|FULL_?NAME|SURNAME|SOYAD|"
    r"^AD$|^ADI$|AD_?SOYAD|NAME_?SURNAME|MOTHER|FATHER|ANNE_?AD|BABA_?AD|CUSTOMER_?NAME|MUSTERI_?AD"
)
MASK_MODES = {"sensitive": "Yalnızca hassas kolonlar", "all": "Tüm değerler", "none": "Maskeleme yok"}


class Privacy:
    def __init__(self, pattern: Optional[str] = None):
        self.regex = re.compile(pattern or DEFAULT_PATTERN, re.I)

    def guess(self, column_name: Optional[str]) -> bool:
        return bool(column_name) and bool(self.regex.search(column_name))

    def is_sensitive(self, column_name: Optional[str], annotation: Optional[dict] = None) -> bool:
        """Explicit annotation (1/0) wins over the name based guess."""
        flag = (annotation or {}).get("sensitive")
        if flag is not None:
            return bool(flag)
        return self.guess(column_name)

    def mask_indexes(self, columns: Sequence[str], sources: Sequence[Optional[str]], mode: str,
                     annotation_for: Callable[[str], Optional[dict]] = lambda s: None) -> Set[int]:
        """Indexes of result columns to mask. `sources` holds 'OWNER.TABLE.COLUMN' labels."""
        if mode == "all":
            return set(range(len(columns)))
        if mode == "none":
            return set()
        out = set()
        for i, name in enumerate(columns):
            src = sources[i] if i < len(sources) else None
            ann = annotation_for(src) if src else None
            col = src.rsplit(".", 1)[-1] if src else name
            if self.is_sensitive(col, ann) or (not src and self.guess(name)):
                out.add(i)
        return out


def mask_value(value):
    """Hide personal data while keeping the shape visible."""
    if value is None:
        return None
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()
    if len(text) <= 2:
        return "*" * len(text)
    keep = 2 if len(text) >= 8 else 1
    return text[:keep] + "*" * (len(text) - 2 * keep) + text[-keep:]


def mask_rows(rows: Iterable[Sequence], indexes: Optional[Set[int]] = None) -> List[tuple]:
    """Mask the given column indexes (all columns when indexes is None)."""
    out = []
    for row in rows:
        out.append(tuple(mask_value(v) if indexes is None or i in indexes else v for i, v in enumerate(row)))
    return out
