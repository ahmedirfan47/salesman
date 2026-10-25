"""Phone-number normalisation for prospects.

Every number is stored as +<country code><number> (E.164 style) so that the
same shop typed as "0501234567", "+966 50 123 4567" or "٠٥٠١٢٣٤٥٦٧" matches
one record, matches an existing customer, and builds a working wa.me link.
"""
import re
import unicodedata

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: object, default_country_code: str) -> str | None:
    """Return '+<digits>' or None for an empty value. Raises InvalidPhone if unreadable."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)  # Excel stores 966501234567 as 966501234567.0
    text = unicodedata.normalize("NFKC", str(raw)).translate(_DIGITS).strip()
    if not text:
        return None

    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise InvalidPhone(str(raw))

    cc = default_country_code
    if has_plus:
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = cc + digits[1:]          # local format: 05xxxxxxxx
    elif not digits.startswith(cc) and len(digits) <= 10:
        digits = cc + digits              # 5xxxxxxxx without the leading 0

    if not 8 <= len(digits) <= 15:
        raise InvalidPhone(str(raw))
    return "+" + digits


def phone_digits(phone: str | None) -> str | None:
    """Digits only -- the form wa.me links and number comparisons use."""
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    return d or None