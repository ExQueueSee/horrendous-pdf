"""Shared helper functions for data directories (stamps, signatures)."""

import os


def _get_data_dir():
    """Return the persistent data directory for custom stamps / signatures."""
    d = os.path.join(os.path.expanduser("~"), ".pdf-editor")
    os.makedirs(d, exist_ok=True)
    return d


def _get_stamp_dir():
    d = os.path.join(_get_data_dir(), "stamps")
    os.makedirs(d, exist_ok=True)
    return d


def _get_signature_dir():
    d = os.path.join(_get_data_dir(), "signatures")
    os.makedirs(d, exist_ok=True)
    return d


# Preset text stamps used by StampDialog and burn logic
STAMP_PRESETS = [
    {"text": "APPROVED",      "color": (0.0, 0.5, 0.0),  "border": (0.0, 0.5, 0.0)},
    {"text": "REJECTED",      "color": (0.8, 0.0, 0.0),  "border": (0.8, 0.0, 0.0)},
    {"text": "DRAFT",         "color": (0.4, 0.4, 0.4),  "border": (0.4, 0.4, 0.4)},
    {"text": "CONFIDENTIAL",  "color": (0.7, 0.0, 0.0),  "border": (0.7, 0.0, 0.0)},
    {"text": "FINAL",         "color": (0.0, 0.3, 0.6),  "border": (0.0, 0.3, 0.6)},
    {"text": "COPY",          "color": (0.3, 0.3, 0.6),  "border": (0.3, 0.3, 0.6)},
    {"text": "NOT APPROVED",  "color": (0.7, 0.2, 0.0),  "border": (0.7, 0.2, 0.0)},
    {"text": "FOR REVIEW",    "color": (0.5, 0.4, 0.0),  "border": (0.5, 0.4, 0.0)},
    {"text": "VOID",          "color": (0.6, 0.0, 0.0),  "border": (0.6, 0.0, 0.0)},
    {"text": "URGENT",        "color": (0.9, 0.1, 0.1),  "border": (0.9, 0.1, 0.1)},
]
