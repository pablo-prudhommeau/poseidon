import unicodedata


def get_visual_width(text: str) -> int:
    width = 0.00
    for char in text:
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            width += 1.75
        elif ord(char) > 0xFFFF:
            width += 2.00
        else:
            width += 1.00
    return round(width)
