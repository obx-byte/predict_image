def clean_text(s):
    if s is None:
        return ""
    return s.replace("\x00", "").strip()
