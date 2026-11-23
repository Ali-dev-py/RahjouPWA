"""Presentation-only cancellation markers for the customer's account feed."""
import unicodedata


def normalized_text(value):
    value = unicodedata.normalize('NFKD', value)
    return ''.join(char for char in value if not unicodedata.combining(char)
                   and not char.isspace() and char not in '\u200c\u200d\u200e\u200f')


def cancelled_factor_status(status):
    text = normalized_text(str(status or ''))
    return any(word in text for word in ('ابطال', 'باطل', 'لغو'))


def void_payment(*records):
    # Inspect loaded scalar text only: never traverse a FK or issue a lazy query.
    for record in records:
        for value in vars(record).values() if record is not None else ():
            if isinstance(value, str) and 'ابطال' in normalized_text(value):
                return True
    return False
