"""Measure the canonical ID resolver on real data (spec 2026-07-01, §Test/eval).

Ground truth = data.nvs: each <name> is paired with its tribun id in <url>, so the
correct uid is "PA"+url. We resolve each name against the sitting's actor set and
count hits, three ways:
  1. clean   -- the NVS name as-is ("Mme Perrine Goulet")
  2. no-civ  -- "Perrine Goulet" (what the STT actually gives: no civility)
  3. noisy   -- a light phonetic perturbation on the surname (STT error proxy)

  python eval_resolve_id.py --record /mnt/data/ariane-capture/2026-06-30-soir
"""
import argparse
import glob
import html
import json
import os
import re

import resolve_id as R

_PAIR = re.compile(r"<name>(.*?)</name>(?:(?!<name>).)*?<url>(\d+)</url>", re.DOTALL)


def load_actors(record):
    with open(os.path.join(record, "referential", "acteurs.json"), encoding="utf-8") as f:
        return json.load(f)


def load_truth(record):
    """(name, 'PA'+tribun) pairs from the most recent data.nvs, deduped."""
    nvs = sorted(glob.glob(os.path.join(record, "raw", "data_nvs", "*.nvs")))
    if not nvs:
        return []
    text = open(nvs[-1], encoding="utf-8", errors="replace").read()
    seen, out = set(), []
    for name, tribun in _PAIR.findall(text):
        name = html.unescape(name).strip()
        uid = "PA" + tribun
        if name and (name, uid) not in seen:
            seen.add((name, uid))
            out.append((name, uid))
    return out


def _strip_civ(name):
    return re.sub(r"^\s*(M\.|Mme|Mlle|Monsieur|Madame|Mademoiselle)\s+", "", name)


def _noisy(name):
    """Drop the last vowel of the last word (crude phonetic-error proxy)."""
    words = _strip_civ(name).split()
    if not words:
        return name
    last = words[-1]
    for i in range(len(last) - 1, -1, -1):
        if last[i].lower() in "aeiouyàâäéèêëîïôöûü":
            words[-1] = last[:i] + last[i + 1:]
            break
    return " ".join(words)


def run(record):
    actors = load_actors(record)
    truth = load_truth(record)
    variants = {"clean": lambda n: n, "no-civ": _strip_civ, "noisy": _noisy}
    print(f"record: {record}")
    print(f"actors in set: {len(actors)}   |   NVS ground-truth names: {len(truth)}\n")
    for label, fn in variants.items():
        hit = miss = none = 0
        fails = []
        for name, uid in truth:
            res = R.resolve(fn(name), actors)
            if res is None:
                none += 1
                fails.append(f"  Ø  {fn(name)!r} (truth {uid})")
            elif res["uid"] == uid:
                hit += 1
            else:
                miss += 1
                fails.append(f"  ✗  {fn(name)!r} -> {res['uid']} (truth {uid})")
        tot = len(truth) or 1
        print(f"[{label:7}] resolved-correct {hit}/{tot} = {100*hit/tot:.0f}%   "
              f"| wrong {miss}   | no-match {none}")
        for line in fails[:8]:
            print(line)
        if len(fails) > 8:
            print(f"  ... (+{len(fails)-8} more)")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="/mnt/data/ariane-capture/2026-06-30-soir")
    run(ap.parse_args().record)
