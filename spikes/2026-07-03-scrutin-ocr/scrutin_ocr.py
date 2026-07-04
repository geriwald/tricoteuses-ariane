"""scrutin_ocr — lire l'écran-résultat de scrutin public incrusté dans la vidéo AN.

Sur un scrutin public, la régie de l'Assemblée incruste un écran à template fixe :
chiffres navy sur fond gris clair, hémicycle coloré en bas, fronton AN en haut-droite.
Il porte les compteurs GLOBAUX (votants / exprimés / majorité absolue / POUR / CONTRE)
mais AUCUN numéro de scrutin ni nom de député. C'est la SEULE source live du chiffré
global : le dérouleur ne donne que l'annonce, Eliasse le sort qualitatif.

Ce module détecte cet écran dans une frame et en extrait les chiffres + le timecode,
pour émettre un `scrutin_result` réutilisable par B1. On NE fait PAS le nominatif :
l'identification des députés vient de l'open-data (résolue plus tard par matching).

Comme b1-weaver, le cœur est PUR : `read_result_screen` prend une image PIL et rend
un dict (ou None), sans toucher au disque ni à la vidéo. Le plumbing ffmpeg vit dans
`scan_video`, et la CLI en bas. Aucune ROI hardcodée : l'association chiffre↔label est
spatiale et relative à la taille du texte, donc robuste aux variations de résolution.
"""
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter

import pytesseract
from PIL import Image

# Les cinq labels de l'écran-résultat, en forme normalisée (sans accent, minuscule) et
# tronqués à la racine : l'OCR rate parfois l'accent ("exprim�s") ou une lettre finale.
_KEYWORDS = ("votant", "exprim", "majorit", "pour", "contre")


def _strip_accents(s):
    """café -> cafe. Rend la comparaison robuste aux accents mal reconnus par l'OCR."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(s):
    return _strip_accents(s).strip().lower()


class _Tok:
    """Un mot OCR avec sa boîte : centre x, haut, bas — le strict nécessaire à
    l'association spatiale."""

    __slots__ = ("text", "cx", "top", "bot", "h")

    def __init__(self, text, left, top, width, height):
        self.text = text
        self.cx = left + width / 2.0
        self.top = top
        self.bot = top + height
        self.h = height


def _tokens_from_ocr(data):
    """Transforme la sortie image_to_data(dict) en une liste de _Tok non vides."""
    toks = []
    for i in range(len(data["text"])):
        t = data["text"][i].strip()
        if not t:
            continue
        toks.append(_Tok(t, data["left"][i], data["top"][i],
                         data["width"][i], data["height"][i]))
    return toks


def _find_label(toks, keyword):
    """Premier token dont la forme normalisée contient le mot-clé (sous-chaîne)."""
    for tk in toks:
        if keyword in _norm(tk.text):
            return tk
    return None


def _value_above(label, toks):
    """Chiffre associé à un label : le token numérique situé JUSTE AU-DESSUS et centré
    horizontalement dessus.

    Deux pièges vus sur la vraie image : (1) « 81 exprimés » est quasi à la même
    verticale que « CONTRE », donc on ne peut pas prendre le plus proche en x — on prend
    le plus proche VERTICALEMENT (gap minimal) parmi les candidats alignés ; (2) certains
    chiffres corrects sortent avec conf=0, donc on ne filtre jamais sur la confiance.

    Tolérances relatives à la taille du texte (pas de pixels absolus, donc résolution-
    invariantes) :
      - « juste au-dessus » : bas du chiffre au-dessus du haut du label (petite marge de
        chevauchement), et pas plus loin que 2× la hauteur du label ;
      - alignement : |Δcx| <= 5× la hauteur. Généreux à dessein — « 41 » est centré sur
        « majorité absolue » entier mais on ne détecte que le mot « majorité », d'où un
        Δcx non nul. Le tri se fait de toute façon sur le gap vertical, pas sur x, donc
        cette borne ne sert qu'à écarter les colonnes voisines.
    """
    best = None
    best_gap = None
    for tk in toks:
        if not tk.text.isdigit():
            continue
        gap = label.top - tk.bot           # >0 si le chiffre est au-dessus du label
        if gap < -0.3 * label.h:           # pas en dessous (tolère un léger chevauchement)
            continue
        if gap > 2.0 * label.h:            # pas trop loin au-dessus
            continue
        if abs(tk.cx - label.cx) > 5.0 * label.h:  # colonne alignée (voir docstring)
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = tk, gap
    return int(best.text) if best is not None else None


def _coherence(votants, exprimes, majorite, pour, contre):
    """Glass-box : contrôles d'intégrité arithmétique de l'écran.

    Rend (abstentions, confidence, ok). Les trois checks :
        pour + contre == exprimes
        exprimes <= votants
        majorite == exprimes // 2 + 1
    ok = tous vrais ET aucun chiffre manquant. confidence = fraction de checks passés,
    pénalisée proportionnellement au nombre de chiffres non lus.
    """
    nums = (votants, exprimes, majorite, pour, contre)
    missing = sum(1 for n in nums if n is None)

    checks = [
        pour is not None and contre is not None and exprimes is not None
        and pour + contre == exprimes,
        exprimes is not None and votants is not None and exprimes <= votants,
        majorite is not None and exprimes is not None
        and majorite == exprimes // 2 + 1,
    ]
    passed = sum(1 for c in checks if c)
    confidence = passed / len(checks)
    if missing:
        confidence *= 1.0 - missing / len(nums)
    confidence = round(confidence, 3)
    ok = all(checks) and missing == 0

    abstentions = (votants - exprimes
                   if votants is not None and exprimes is not None else None)
    return abstentions, confidence, ok


def _screen_from_tokens(toks):
    """Cœur pur : de la liste de tokens OCR au dict résultat (ou None).

    None si le jeu de mots-clés n'est pas au complet — ce n'est alors pas un
    écran-résultat.
    """
    labels = {kw: _find_label(toks, kw) for kw in _KEYWORDS}
    if any(lbl is None for lbl in labels.values()):
        return None

    votants = _value_above(labels["votant"], toks)
    exprimes = _value_above(labels["exprim"], toks)
    majorite = _value_above(labels["majorit"], toks)
    pour = _value_above(labels["pour"], toks)
    contre = _value_above(labels["contre"], toks)

    abstentions, confidence, ok = _coherence(votants, exprimes, majorite, pour, contre)
    return {
        "votants": votants,
        "exprimes": exprimes,
        "majorite": majorite,
        "pour": pour,
        "contre": contre,
        "abstentions": abstentions,
        "confidence": confidence,
        "ok": ok,
    }


def read_result_screen(pil_image, lang="fra"):
    """Fonction PURE (I/O = 0 disque) : image PIL -> dict résultat | None.

    Lance tesseract en mode image_to_data (mots + boîtes), reconnaît l'écran-résultat
    au jeu de mots-clés (comparaison accent-insensible, sous-chaîne), puis extrait
    chaque chiffre par association spatiale. Voir `_value_above` / `_coherence`.
    """
    try:
        data = pytesseract.image_to_data(pil_image, lang=lang,
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        # Pack de langue absent : le français aide au texte mais les chiffres et la
        # détection (sous-chaîne accent-insensible) marchent aussi sans lui.
        data = pytesseract.image_to_data(pil_image,
                                         output_type=pytesseract.Output.DICT)
    return _screen_from_tokens(_tokens_from_ocr(data))


# --------------------------------------------------------------------------- I/O

def _ffprobe_duration(path, ffmpeg):
    """Durée de la vidéo en secondes via ffprobe (voisin de ffmpeg)."""
    ffprobe = ffmpeg[:-len("ffmpeg")] + "ffprobe" if ffmpeg.endswith("ffmpeg") \
        else ffmpeg.replace("ffmpeg.exe", "ffprobe.exe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _grab_frame(path, t_s, ffmpeg, tmp_jpg):
    """Extrait une frame à t_s via input-seek (`-ss` AVANT `-i`) : ffmpeg saute au
    keyframe le plus proche puis décode jusqu'à t_s — rapide, et comme l'écran-résultat
    reste affiché plusieurs secondes il tombe forcément sur une image pleine. Le timecode
    est exactement t_s (connu), donc pas besoin de le relire."""
    subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-ss", f"{t_s}",
         "-i", path, "-frames:v", "1", "-q:v", "2", "-y", tmp_jpg],
        check=True)
    return Image.open(tmp_jpg)


def _mode(values):
    """Valeur modale (lecture stable sur une fenêtre), None ignorés."""
    vals = [v for v in values if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else None


def _emit_window(window):
    """Une fenêtre de frames-hit contiguës -> un seul event `scrutin_result`.

    Lecture STABLE = valeur modale de chaque compteur sur la fenêtre ; on recalcule la
    cohérence dessus. t_ms = milieu de la fenêtre (instant de proclamation)."""
    t0, t1 = window[0][0], window[-1][0]
    reads = [r for _, r in window]
    votants = _mode(r["votants"] for r in reads)
    exprimes = _mode(r["exprimes"] for r in reads)
    majorite = _mode(r["majorite"] for r in reads)
    pour = _mode(r["pour"] for r in reads)
    contre = _mode(r["contre"] for r in reads)
    abstentions, confidence, ok = _coherence(votants, exprimes, majorite, pour, contre)
    return {
        "type": "scrutin_result",
        "t_ms": int(round((t0 + t1) / 2.0 * 1000)),
        "votants": votants,
        "exprimes": exprimes,
        "majorite": majorite,
        "pour": pour,
        "contre": contre,
        "abstentions": abstentions,
        "confidence": confidence,
        "ok": ok,
    }


def scan_video(path, step_s=3.0, start_s=0, end_s=None, lang="fra", ffmpeg="ffmpeg"):
    """Balaye la vidéo à intervalle step_s et rend la liste des events scrutin_result.

    Les détections consécutives du MÊME écran (frames contiguës) sont dédupliquées en un
    seul event (voir `_emit_window`).
    """
    if end_s is None:
        end_s = _ffprobe_duration(path, ffmpeg)

    events = []
    window = []  # frames-hit contiguës : liste de (t_s, read)
    fd, tmp_jpg = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        t = float(start_s)
        while t <= end_s + 1e-9:
            img = _grab_frame(path, t, ffmpeg, tmp_jpg)
            read = read_result_screen(img, lang=lang)
            img.close()
            if read is not None:
                window.append((t, read))
            elif window:
                events.append(_emit_window(window))
                window = []
            t += step_s
        if window:
            events.append(_emit_window(window))
    finally:
        try:
            os.remove(tmp_jpg)
        except OSError:
            pass
    return events


# --------------------------------------------------------------------------- CLI

def _resolve_tesseract(explicit):
    """Auto-détecte tesseract : --tesseract, sinon PATH, sinon l'install Windows type."""
    if explicit:
        pytesseract.pytesseract.tesseract_cmd = explicit
        return
    from shutil import which
    if which("tesseract"):
        return
    fallback = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(fallback):
        pytesseract.pytesseract.tesseract_cmd = fallback


def _hhmmss(ms):
    s = ms // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        description="Détecte l'écran-résultat de scrutin AN et en lit les chiffres.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--frame", help="lit un seul écran (image) -> dict JSON sur STDOUT")
    src.add_argument("--video", help="balaye une vidéo -> events NDJSON sur STDOUT")
    p.add_argument("--step", type=float, default=3.0, help="pas d'échantillonnage (s)")
    p.add_argument("--start", type=float, default=0, help="début du scan (s)")
    p.add_argument("--end", type=float, default=None, help="fin du scan (s)")
    p.add_argument("--lang", default="fra", help="langue tesseract (défaut: fra)")
    p.add_argument("--tesseract", default=None, help="chemin de l'exe tesseract")
    p.add_argument("--ffmpeg", default="ffmpeg", help="chemin de l'exe ffmpeg")
    args = p.parse_args(argv)

    _resolve_tesseract(args.tesseract)

    if args.frame:
        res = read_result_screen(Image.open(args.frame), lang=args.lang)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    events = scan_video(args.video, step_s=args.step, start_s=args.start,
                        end_s=args.end, lang=args.lang, ffmpeg=args.ffmpeg)
    for ev in events:
        print(json.dumps(ev, ensure_ascii=False))            # NDJSON -> STDOUT (pipe B1)
    print(f"[scrutin_ocr] {len(events)} scrutin(s) détecté(s) dans {args.video}",
          file=sys.stderr)
    for ev in events:
        print(f"  {_hhmmss(ev['t_ms'])}  votants={ev['votants']} exprimés={ev['exprimes']}"
              f" maj={ev['majorite']} POUR={ev['pour']} CONTRE={ev['contre']}"
              f" abst={ev['abstentions']}  ok={ev['ok']} conf={ev['confidence']}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
