"""Lightweight data-holder for annotations."""


class Annotation:
    """Lightweight data holder for an annotation."""
    HIGHLIGHT = "highlight"
    NOTE = "note"
    FREEHAND = "freehand"
    TEXT = "text"
    RECT = "rectangle"

    def __init__(self, kind, page, **kwargs):
        self.kind = kind
        self.page = page
        self.data = kwargs  # rect, points, text, color, …
