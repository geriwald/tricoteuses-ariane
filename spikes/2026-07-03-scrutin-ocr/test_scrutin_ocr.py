"""Test d'acceptation du spike scrutin-ocr.

Fixtures (régénérables, cf. README) extraites de la séance du 2026-06-26 :
  - scrutin_20260626_2529.jpg : l'écran-résultat (proclamation d'un scrutin public) ;
  - plateau_20260626_2520.jpg : un plan de perchoir, ~9 s plus tôt (cas négatif).
"""
import os

import pytest
from PIL import Image

import scrutin_ocr

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def _tesseract():
    """Auto-détecte tesseract (PATH, sinon install Windows type) comme le fait la CLI."""
    scrutin_ocr._resolve_tesseract(None)


def _open(name):
    path = os.path.join(FIX, name)
    if not os.path.exists(path):
        pytest.skip(f"fixture manquante ({name}) — voir README pour la régénérer")
    return Image.open(path)


def test_reads_result_screen_exactly():
    got = scrutin_ocr.read_result_screen(_open("scrutin_20260626_2529.jpg"))
    assert got == {
        "votants": 81,
        "exprimes": 81,
        "majorite": 41,
        "pour": 27,
        "contre": 54,
        "abstentions": 0,
        "confidence": 1.0,
        "ok": True,
    }


def test_plateau_is_not_a_result_screen():
    assert scrutin_ocr.read_result_screen(_open("plateau_20260626_2520.jpg")) is None
