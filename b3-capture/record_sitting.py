#!/usr/bin/env python3
"""Incremental recorder of a live AN sitting — the capture tool for the
hackathon causal replay (and the caladan cron).

Polls the four live sources under wall-clock stamps and persists each raw
snapshot ONLY when its content changed (sha1 dedup), so storage scales with
the number of transitions, not the number of ticks. A 4 h sitting at 2 s polls
is ~7000 ticks but only a few hundred real changes → tens of MB, not gigabytes.

Sources:
  - derouleur  : www.assemblee-nationale.fr/local/derouleur/derouleur.json
                 (structural trame: articles/amendments + canonical IDs)
  - data_nvs   : videos.assemblee-nationale.fr/Datas/an/<id>/content/data.nvs
                 (ground truth: chapters + effective speakers, tribun id in <speaker><url>)
  - liveplayer : .../content/liveplayer.nvs
                 (sync track: <player starttime=epoch> + <synchro id timecode_ms>,
                  joined to data.nvs by chapter id to place speakers on the video timeline)
  - eliasse    : eliasse.assemblee-nationale.fr/eliasse/{prochainADiscuter,amendement}.do
                 (live position pointer + sortEnSeance)

Output under --outdir:
  index.ndjson          one record per tick: per-source state summary,
                        raw_ref (the raw file holding the current content),
                        and a `changed` flag per source.
  raw/<source>/<ts>.*   full raw response, written only when the hash changed.

The full dérouleur trame is NOT inlined per tick (it would bloat index.ndjson);
it lives in the deduped raw derouleur.json, read back by the replayer/weaver.

Evolves record_sources.py (spike prototype): + liveplayer, + hash dedup,
+ trame summary. No third-party deps. Ctrl-C (or SIGTERM) to stop cleanly.
"""
import argparse
import hashlib
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
DEROULEUR_URL = "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json"
ELIASSE_BASE = "https://eliasse.assemblee-nationale.fr/eliasse"
_NUM = re.compile(r"n[°o]\s*(\d+)")
_INSECURE = ssl._create_unverified_context()

# Optional push notification when a sitting opens/closes. Best-effort: if the
# script is absent or fails, the recording is never affected. Point NOTIFY_SEND
# at any executable that reads a message on stdin; leave it unset to disable.
NOTIFY_SEND = os.environ.get("NOTIFY_SEND", "")  # unset = no notification

# Post-capture referential resolution: when the sitting ends, schedule this
# resolver ~30 min later (causal freeze, contemporary with the sitting — spec
# decision 10). It is plain HTTP against parlement.tricoteuses.fr, cron-able.
RESOLVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolve_referential.py")
RESOLVE_DELAY_MIN = 30


def resolution_command(outdir):
    """The command that resolves a record into its frozen referential snapshot."""
    return [sys.executable, RESOLVER, "--record", outdir]


def _unit_name(outdir):
    """A collision-free, filesystem-safe systemd unit name from the record dir."""
    base = re.sub(r"[^A-Za-z0-9-]", "-", os.path.basename(os.path.normpath(outdir)))
    return f"ariane-resolve-{base}"


def schedule_resolution_command(outdir, delay_min=RESOLVE_DELAY_MIN):
    """Build (don't run) the systemd --user one-shot timer that fires the resolver
    `delay_min` minutes out. --user + Linger=yes → survives logout (the unattended
    caladan run). Pure: returned verbatim so it is unit-testable."""
    return ["systemd-run", "--user", f"--on-active={delay_min}min",
            f"--unit={_unit_name(outdir)}", "--collect"] + resolution_command(outdir)


def systemd_user_env(env=None):
    """Environment for `systemd-run --user`. Under cron, XDG_RUNTIME_DIR is unset
    and the call fails to reach the user bus; inject it (Linger=yes keeps
    /run/user/<uid> alive). An already-set value wins."""
    env = dict(os.environ if env is None else env)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def spawn_resolution(outdir, say, delay_min=RESOLVE_DELAY_MIN):
    """At sitting end: schedule the resolver for +delay_min. Log the manual fallback
    command (Telegram stays event-only — read on a phone), and notify the event (or
    the problem if scheduling failed). Best-effort: never raises into the recorder."""
    manual = " ".join(resolution_command(outdir))
    say(f"referential resolution: to run manually -> {manual}")
    try:
        subprocess.run(
            schedule_resolution_command(outdir, delay_min), check=True,
            env=systemd_user_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        say(f"referential resolution scheduled in {delay_min} min (systemd --user timer "
            f"{_unit_name(outdir)})")
        notify(f"Ariane: resolution des referentiels programmee dans {delay_min} min "
               f"(fige le snapshot canutes de la seance). Dossier: {outdir}")
    except Exception as e:
        say(f"FAILED to schedule resolution: {e}; run manually: {manual}")
        notify(f"Ariane: PROBLEME — la resolution des referentiels n'a pas pu etre "
               f"programmee ({type(e).__name__}). A relancer a la main. Dossier: {outdir}")


def notify(text: str):
    if not NOTIFY_SEND:
        return  # unset: no notification (best-effort hook)
    try:
        subprocess.run([NOTIFY_SEND], input=text, text=True, timeout=30, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def stamp(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S.%f")[:-3]


def fetch(url: str, referer: str, insecure: bool = False) -> bytes:
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}modulo={int(time.time() * 1000)}"
    req = urllib.request.Request(full, headers={
        "User-Agent": UA,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, application/xml, text/xml, */*; q=0.01",
    })
    ctx = _INSECURE if insecure else None
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.read()


def amdt_num(label: str):
    m = _NUM.search(label or "")
    return m.group(1) if m else None


def canon_derouleur(raw: bytes) -> bytes:
    """Hash key for the dérouleur, ignoring the volatile generation timestamp.

    `extract_date_time` is bumped on every regeneration (~5 s) even when nothing
    substantive moves, so hashing the raw would defeat dedup and write a 260 KB
    snapshot per tick. Strip it (and jaune_date_time) so a snapshot is kept only
    when the trame/highlight/lines actually change. Falls back to raw on error."""
    try:
        d = json.loads(raw)
        j = d.get("racine", {}).get("jaune", {})
        j.pop("extract_date_time", None)
        j.pop("jaune_date_time", None)
        return json.dumps(d, ensure_ascii=False, sort_keys=True).encode()
    except Exception:
        return raw


# ---- per-source state extraction --------------------------------------------

def _phases(d: dict) -> list:
    phases = d["racine"]["contenu"].get("phase", [])
    return phases if isinstance(phases, list) else [phases]


def state_derouleur(raw: bytes) -> dict:
    d = json.loads(raw)
    lignes, active_label = [], ""
    for ph in _phases(d):
        pls = ph.get("ligne", [])
        pls = pls if isinstance(pls, list) else [pls]
        lignes.extend(pls)
        if any(ln.get("ligne_video_highlighted") == "true" for ln in pls):
            active_label = ph.get("phase_libelle", "")
    if not active_label:
        phs = _phases(d)
        active_label = phs[-1].get("phase_libelle", "") if phs else ""
    types = {}
    for ln in lignes:
        t = ln.get("ligne_type", "?")
        types[t] = types.get(t, 0) + 1
    hl = [ln for ln in lignes if ln.get("ligne_video_highlighted") == "true"]
    qag = sum(1 for ln in lignes if ln.get("ligne_type") == "INSCRITQAG")
    return {
        "extract": d["racine"]["jaune"].get("extract_date_time", ""),
        "jaune_id": d["racine"]["jaune"].get("id"),
        "phase": active_label,
        "n_lines": len(lignes),
        "types": types,
        "n_highlighted": len(hl),
        "n_inscritqag": qag,
    }


def _nvs_speakers(root):
    spk = {}
    sps = root.find("speakers")
    for s in (sps if sps is not None else []):
        spk[s.attrib.get("id")] = ((s.findtext("name") or "").strip(),
                                    (s.findtext("url") or "").strip())
    return spk


def state_nvs(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    spk = _nvs_speakers(root)
    seq = []

    def walk(e):
        label = (e.attrib.get("label") or "").strip()
        ty = e.find("type")
        sp = e.find("speaker")
        name, tribun = ("", "")
        if sp is not None:
            name, tribun = spk.get(sp.attrib.get("id"), ("", ""))
        if label:
            seq.append((label, ty.attrib.get("value") if ty is not None else "", name, tribun))
        for c in e:
            if c.tag == "chapter":
                walk(c)

    ch = root.find("chapters")
    if ch is not None:
        walk(ch)
    last = seq[-1] if seq else ("", "", "", "")
    return {
        "status": root.attrib.get("status", ""),
        "n_chapters": len(seq),
        "n_speakers": len(spk),
        "last_label": last[0],
        "last_type": last[1],
        "last_speaker": last[2] or None,
        "last_tribun": last[3] or None,
    }


def state_liveplayer(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    syn = root.findall(".//synchro")
    last = syn[-1].attrib if syn else {}
    return {
        "starttime": root.attrib.get("starttime"),
        "n_synchro": len(syn),
        "last_timecode_ms": last.get("timecode"),
        "last_id": last.get("id"),
    }


def fetch_eliasse(insecure: bool):
    """Fetch the two Eliasse responses and return their RAW bodies verbatim:
    (raw_prochain, raw_amendement). raw_amendement is None when the pointer has no
    current amendment (between amendments) or the detail call failed.

    B2 replays Eliasse byte-exact from these two bodies, so B3 must keep them whole
    (the old summary lost author/dispositif/cosignataires/… — see spec option B)."""
    ref = f"{ELIASSE_BASE}/index.html"
    raw_prochain = fetch(f"{ELIASSE_BASE}/prochainADiscuter.do?page=1&start=0&limit=25",
                         ref, insecure)
    proc = json.loads(raw_prochain).get("prochainADiscuter", {})
    raw_amendement = None
    if proc.get("numAmdt"):
        q = (f"{ELIASSE_BASE}/amendement.do?legislature={proc.get('legislature', '17')}"
             f"&bibard={proc['bibard']}&bibardSuffixe={proc.get('bibardSuffixe', '')}"
             f"&organeAbrv={proc.get('organeAbrv', 'AN')}&numAmdt={proc['numAmdt']}"
             f"&page=1&start=0&limit=25")
        try:
            raw_amendement = fetch(q, ref, insecure)
        except Exception:
            raw_amendement = None
    return raw_prochain, raw_amendement


def state_eliasse(raw_prochain: bytes, raw_amendement) -> dict:
    """Parse the change-log summary from the two raw bodies (pure, no network).

    The raw bodies are what B2 replays; this summary only feeds the console
    change-log and the index (which amendment is up, its sortEnSeance/etat/place)."""
    proc = json.loads(raw_prochain).get("prochainADiscuter", {})
    out = {
        "bibard": proc.get("bibard"),
        "numAmdt": proc.get("numAmdt"),
        "organe": proc.get("organeAbrv"),
        "sort": None, "etat": None, "place": None,
    }
    if raw_amendement is not None:
        try:
            amds = json.loads(raw_amendement).get("amendements", [])
            if amds:
                a = amds[0]
                out["sort"] = a.get("sortEnSeance")
                out["etat"] = a.get("etat")
                out["place"] = a.get("placeReference")
        except Exception as e:
            out["detail_error"] = str(e)
    return out


class RawSaver:
    """Writes a raw response only when its content changed (sha1 dedup), so storage
    scales with transitions, not ticks. One instance owns the per-source last-hash
    state; each source deduped independently."""

    def __init__(self, outdir: str):
        self.outdir = outdir
        self.last_hash, self.last_ref, self.n_saved = {}, {}, {}

    def maybe_save(self, source: str, ext: str, raw: bytes, ts: str, hash_src: bytes = None):
        """Write raw only when its content changed. Return (raw_ref, changed).

        Dedup is keyed on hash_src (a canonical form) when given, else on raw."""
        h = hashlib.sha1(hash_src if hash_src is not None else raw).hexdigest()
        if self.last_hash.get(source) == h:
            return self.last_ref.get(source), False
        fn = f"{ts}.{ext}"
        os.makedirs(os.path.join(self.outdir, "raw", source), exist_ok=True)
        with open(os.path.join(self.outdir, "raw", source, fn), "wb") as f:
            f.write(raw)
        self.last_hash[source] = h
        self.last_ref[source] = fn
        self.n_saved[source] = self.n_saved.get(source, 0) + 1
        return fn, True


# ---- main --------------------------------------------------------------------

_STOP = False


def _on_signal(signum, frame):
    global _STOP
    _STOP = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--direct-id", default=None,
                    help="id from videos.assemblee-nationale.fr/direct.<ID>. "
                         "If omitted, only the id-free sources (dérouleur, Eliasse) "
                         "are recorded — the two NVS need the direct-id.")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--outdir", default="record")
    ap.add_argument("--verify-eliasse", action="store_true",
                    help="verify Eliasse TLS (fails without the Gandi intermediate)")
    ap.add_argument("--stop-grace", type=float, default=120.0,
                    help="auto-stop after data.nvs has stayed status=vod for N s "
                         "(the sitting is over). Grace absorbs transient flips.")
    ap.add_argument("--no-auto-stop", action="store_true",
                    help="never auto-stop; run until SIGTERM (e.g. for id-free runs)")
    ap.add_argument("--no-resolve", action="store_true",
                    help="do not auto-schedule the referential resolution at sitting end")
    ap.add_argument("--resolve-delay", type=int, default=RESOLVE_DELAY_MIN,
                    help="minutes after sitting end to fire the resolver (default 30)")
    args = ap.parse_args()
    insecure = not args.verify_eliasse

    did = args.direct_id
    content = f"https://videos.assemblee-nationale.fr/Datas/an/{did}/content"
    ref_video = f"https://videos.assemblee-nationale.fr/direct.{did}"
    ref_der = "https://www.assemblee-nationale.fr/dyn/seance-publique/derouleur"

    # polled raw sources: (name, ext, url, referer, state_fn, canon)
    # canon(raw) -> bytes hashed for dedup (default: the raw itself)
    raw_sources = [
        ("derouleur", "json", DEROULEUR_URL, ref_der, state_derouleur, canon_derouleur),
    ]
    if did:
        raw_sources += [
            ("data_nvs", "nvs", f"{content}/data.nvs", ref_video, state_nvs, None),
            ("liveplayer", "nvs", f"{content}/liveplayer.nvs", ref_video, state_liveplayer, None),
        ]
    else:
        print("note: no --direct-id, recording id-free sources only "
              "(dérouleur + Eliasse); the two NVS are skipped.", file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)
    index = open(os.path.join(args.outdir, "index.ndjson"), "a", encoding="utf-8", buffering=1)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    saver = RawSaver(args.outdir)
    maybe_save = saver.maybe_save

    print(f"recording sitting {did} -> {args.outdir}/  "
          f"(interval {args.interval}s, incremental; Ctrl-C/SIGTERM to stop)",
          file=sys.stderr)
    if insecure:
        print("note: Eliasse TLS NOT verified (Gandi intermediate missing locally)",
              file=sys.stderr)

    prev = {"der": None, "nvs": None, "eli": None}
    ticks = 0
    started = datetime.now()
    over_since = None          # wall time when data.nvs first turned status=vod
    stop_reason = "signal"     # vs "session_over"

    while not _STOP:
        wall = datetime.now()
        ts = wall.strftime("%H%M%S_%f")[:-3]
        rec = {"wall": wall.isoformat(timespec="milliseconds"), "raw_ref": {}, "changed": {}}

        for source, ext, url, ref, state_fn, canon in raw_sources:
            try:
                raw = fetch(url, ref)
                raw_ref, changed = maybe_save(source, ext, raw, ts,
                                              canon(raw) if canon else None)
                rec[source] = state_fn(raw)
                rec["raw_ref"][source] = raw_ref
                rec["changed"][source] = changed
            except Exception as e:
                rec[source] = {"error": str(e)}
                rec["raw_ref"][source] = saver.last_ref.get(source)
                rec["changed"][source] = False

        # Eliasse: save the two HTTP bodies VERBATIM (option B), each deduped on its
        # own, so B2 replays prochainADiscuter.do / amendement.do byte-exact. The
        # summary stays in the index for the change-log only.
        try:
            raw_prochain, raw_amendement = fetch_eliasse(insecure)
            ref_p, changed_p = maybe_save("eliasse_prochain", "json", raw_prochain, ts)
            rec["raw_ref"]["eliasse_prochain"] = ref_p
            rec["changed"]["eliasse_prochain"] = changed_p
            if raw_amendement is not None:
                ref_a, changed_a = maybe_save("eliasse_amendement", "json", raw_amendement, ts)
                rec["raw_ref"]["eliasse_amendement"] = ref_a
                rec["changed"]["eliasse_amendement"] = changed_a
            rec["eliasse"] = state_eliasse(raw_prochain, raw_amendement)
        except Exception as e:
            rec["eliasse"] = {"error": str(e)}

        index.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ticks += 1

        # compact change-log on stdout (only when a key signal moves)
        der_k = (rec.get("derouleur") or {}).get("extract")
        nvs_k = (rec.get("data_nvs") or {}).get("last_label")
        eli_k = (rec.get("eliasse") or {}).get("numAmdt")
        if rec["changed"].get("derouleur") and der_k != prev["der"]:
            dd = rec["derouleur"]
            print(f"[{stamp(wall)}] DEROULEUR changed | phase={dd.get('phase')!r} "
                  f"lines={dd.get('n_lines')} hl={dd.get('n_highlighted')} "
                  f"qag={dd.get('n_inscritqag')} extract={der_k}", flush=True)
            prev["der"] = der_k
        if rec["changed"].get("eliasse") and eli_k != prev["eli"]:
            e = rec["eliasse"]
            print(f"[{stamp(wall)}] ELIASSE   prochain#{eli_k} bibard {e.get('bibard')} "
                  f"sort={e.get('sort')} place={e.get('place')}", flush=True)
            prev["eli"] = eli_k
        if rec["changed"].get("data_nvs") and nvs_k != prev["nvs"]:
            n = rec["data_nvs"]
            who = f" | {n.get('last_speaker')} (tribun {n.get('last_tribun')})" if n.get("last_speaker") else ""
            print(f"[{stamp(wall)}] NVS       {nvs_k!r}{who}", flush=True)
            prev["nvs"] = nvs_k

        # auto-stop: the sitting is over once data.nvs has been status=vod for
        # --stop-grace seconds (grace absorbs transient flips seen mid-sitting).
        # Needs the NVS, so only in id-bound runs (and unless disabled).
        if did and not args.no_auto_stop:
            if (rec.get("data_nvs") or {}).get("status") == "vod":
                if over_since is None:
                    over_since = wall
                    print(f"[{stamp(wall)}] NVS -> vod, sitting ending; "
                          f"stopping in {args.stop_grace:.0f}s unless it resumes", flush=True)
                elif (wall - over_since).total_seconds() >= args.stop_grace:
                    stop_reason = "session_over"
                    break
            elif over_since is not None:
                over_since = None  # resumed: cancel the pending stop

        # sleep in small slices so a stop signal is honored quickly
        slept = 0.0
        while slept < args.interval and not _STOP:
            time.sleep(min(0.25, args.interval - slept))
            slept += 0.25

    index.close()
    counts = {k: saver.n_saved.get(k, 0) for k in
              ('derouleur', 'data_nvs', 'liveplayer', 'eliasse_prochain', 'eliasse_amendement')}
    eliasse_total = counts['eliasse_prochain'] + counts['eliasse_amendement']
    dur = datetime.now() - started
    hh, mm = divmod(int(dur.total_seconds()) // 60, 60)
    print(f"\nstopped ({stop_reason}) after {ticks} ticks / {hh}h{mm:02d}. "
          f"raw snapshots saved: {counts}", file=sys.stderr)
    if stop_reason == "session_over":
        notify(f"Ariane: seance terminee (NVS passe en vod). Capture {hh}h{mm:02d} sur "
               f"{os.uname().nodename}, {ticks} ticks, transitions derouleur={counts['derouleur']} "
               f"nvs={counts['data_nvs']} eliasse={eliasse_total}. Dossier: {args.outdir}")
        # auto-chain the referential resolution (causal freeze, +30 min) unless
        # disabled. Only on a clean session_over: a SIGTERM stop is a human aborting,
        # they will resolve when they want.
        if not args.no_resolve:
            spawn_resolution(args.outdir, lambda m: print(m, file=sys.stderr), args.resolve_delay)


if __name__ == "__main__":
    main()
