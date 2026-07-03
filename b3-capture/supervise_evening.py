#!/usr/bin/env python3
"""Wait for an AN sitting to open, discover its live direct-id, then record it.

Built for an unattended evening launch: the direct-id changes each broadcast and
is only known once the session is live, so we cannot hardcode it. This watcher
polls the (global, id-free) dérouleur until a real legislative phase repopulates
(off the "PROVIDÉO …" slate), discovers the live direct-id from direct.php
(confirmed by data.nvs status=='live'), then *execs* record_sitting.py — the
process becomes the recorder, so a single SIGTERM stops it cleanly.

Robustness: the dérouleur and Eliasse need NO direct-id, and they are the
irreplaceable dynamic streams (the NVS is recoverable post-hoc as status=vod).
So if the direct-id can't be discovered, we still record id-free
(dérouleur + Eliasse) rather than miss the session.

Usage:
    python supervise_evening.py --outdir demo/captures/2026-06-26-evening
No third-party deps. Logs detection to <outdir>/supervisor.log.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

# Mnémosyne notification via the mnemo-send skill: it auto-detects where the bot
# token lives (local/ssh), url-encodes, and fails loudly (set -euo pipefail +
# curl -fsS). We pass the message on stdin → no shell escaping (accents, parens,
# newlines all pass through verbatim).
MNEMO_SEND = str(pathlib.Path("~/.claude/skills/mnemo-send/send.sh").expanduser())


def notify(text: str):
    """Best-effort Mnémosyne ping. Never raises (a notify failure must not break
    detection/recording)."""
    try:
        subprocess.run([MNEMO_SEND], input=text, text=True, timeout=30, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
DEROULEUR_URL = "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json"
DIRECT_PHP = "https://videos.assemblee-nationale.fr/direct.php"
VIDEOS_BASE = "https://videos.assemblee-nationale.fr"
SLATE_MARKERS = ("PROVID",)          # slate phases: "PROVIDÉO - VENDREDI … 21H45"
DID_RE = re.compile(r"direct\.(\d+_[0-9a-f]+)")
HERE = os.path.dirname(os.path.abspath(__file__))
RECORDER = os.path.join(HERE, "record_sitting.py")


def fetch(url: str, referer: str) -> bytes:
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}modulo={int(time.time() * 1000)}", headers={
        "User-Agent": UA, "Referer": referer, "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, application/xml, text/xml, */*; q=0.01",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def derouleur_state():
    """Summarize the dérouleur for open-detection → (content_phase, has_slate, content_lines).

    The file can carry TWO phases at once: a slate phase (type 'IS', libelle
    'PROVIDÉO …', NEXTSEANCE* lines) announcing the next sitting, AND the real
    legislative phase (type 'DA', ARTICLE/ADT) pre-loaded before it starts.
    Verified 2026-06-26 21h02: slate + 705 ADT coexisted while NOT yet on air.
    So we track the slate and the content separately, never collapsing them."""
    d = json.loads(fetch(DEROULEUR_URL,
                         "https://www.assemblee-nationale.fr/dyn/seance-publique/derouleur"))
    phases = d["racine"]["contenu"].get("phase", [])
    phases = phases if isinstance(phases, list) else [phases]
    has_slate, content_lines, content_phase = False, 0, ""
    for ph in phases:
        lg = ph.get("ligne", [])
        lg = lg if isinstance(lg, list) else [lg]
        libelle = ph.get("phase_libelle", "")
        is_slate = (ph.get("phase_type") == "IS"
                    or any(m in libelle.upper() for m in SLATE_MARKERS)
                    or any((ln.get("ligne_type") or "").startswith("NEXTSEANCE") for ln in lg))
        if is_slate:
            has_slate = True
        elif any(ln.get("ligne_type") in ("ADT", "ARTICLE", "SSADT") for ln in lg):
            content_lines += len(lg)
            content_phase = content_phase or libelle
    return content_phase, has_slate, content_lines


def is_open(has_slate: bool, content_lines: int) -> bool:
    """Live (via the dérouleur) = the inter-session slate is gone AND a real
    legislative phase carries lines. While the 'PROVIDÉO …' slate is present the
    content is only pre-loaded, not on air. The authoritative live signal stays
    the discoverable direct-id (data.nvs status=='live'); this is the fallback."""
    return (not has_slate) and content_lines >= 20


def discover_direct_id():
    """Best-effort live direct-id: candidates from direct.php, confirmed by a
    data.nvs that reports status=='live'. Returns the id or None."""
    try:
        html = fetch(DIRECT_PHP, VIDEOS_BASE).decode("utf-8", "replace")
    except Exception:
        return None
    for did in dict.fromkeys(DID_RE.findall(html)):   # unique, ordered
        try:
            raw = fetch(f"{VIDEOS_BASE}/Datas/an/{did}/content/data.nvs",
                        f"{VIDEOS_BASE}/direct.{did}")
            if b'status="live"' in raw or b"status='live'" in raw:
                return did
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--poll", type=float, default=30.0, help="detection poll (s)")
    ap.add_argument("--interval", type=float, default=2.0, help="recorder poll (s)")
    ap.add_argument("--max-wait", type=float, default=18000.0,
                    help="give up waiting for the session to open after N s (default 5h)")
    ap.add_argument("--id-grace", type=float, default=180.0,
                    help="keep trying to discover the direct-id for N s after open")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    log = open(os.path.join(args.outdir, "supervisor.log"), "a", encoding="utf-8", buffering=1)

    def say(msg):
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line, flush=True)
        log.write(line + "\n")

    say(f"supervisor armed; waiting for a sitting to open (poll {args.poll}s, "
        f"max wait {args.max_wait / 3600:.1f}h)")
    notify(f"Ariane: superviseur arme sur {os.uname().nodename}. J'attends l'ouverture de la seance. "
           f"Je te previens au debut de seance et au lancement de la capture.")

    # 1) wait until the session is actually LIVE — either the live direct-id is
    #    discoverable (authoritative: data.nvs status=='live'), or the slate is
    #    gone with real content loaded (fallback). Pre-loaded content under the
    #    slate is NOT open.
    t0, did = time.time(), None
    while time.time() - t0 < args.max_wait:
        try:
            phase, has_slate, n = derouleur_state()
            cand = discover_direct_id() if n >= 20 else None  # try once content is loaded
            if cand or is_open(has_slate, n):
                did = cand
                how = f"direct-id live {cand}" if cand else "slate gone"
                say(f"OPEN ({how}): phase={phase!r} lines={n} slate={has_slate}")
                notify(f"Ariane: debut de seance detecte (phase: {phase}). Je lance la capture.")
                break
            say(f"closed: phase={phase!r} lines={n} slate={has_slate} (waiting)")
        except Exception as e:
            say(f"derouleur poll error: {e}")
        time.sleep(args.poll)
    else:
        say("gave up: no sitting opened within max-wait")
        return 1

    # 2) if we don't have the id yet, keep trying briefly (it may appear at start)
    t1 = time.time()
    while not did and time.time() - t1 < args.id_grace:
        did = discover_direct_id()
        if did:
            say(f"direct-id discovered & confirmed live: {did}")
            break
        say("direct-id not found yet, retrying…")
        time.sleep(10)
    if did:
        notify(f"Ariane: direct-id confirme live ({did}). Capture des 4 sources (derouleur, data.nvs, liveplayer, Eliasse).")
    else:
        say("direct-id NOT discovered — recording id-free (dérouleur + Eliasse). "
            "NVS recoverable post-hoc as status=vod.")
        notify("Ariane: direct-id non trouve. Capture id-free (derouleur + Eliasse) ; le NVS du soir sera recuperable apres coup en vod.")

    # 3) become the recorder (exec → single process, clean SIGTERM)
    cmd = [sys.executable, RECORDER, "--outdir", args.outdir, "--interval", str(args.interval)]
    if did:
        cmd += ["--direct-id", did]
    say(f"exec: {' '.join(cmd)}")
    log.close()
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main())
