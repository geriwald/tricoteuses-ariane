"""Tests for the ground-truth NVS timeline (spec §B2, non-causal comparison pane).

B4 shows the post-prod NVS chapters/speakers positioned on the video timeline, in a
window around `t`. The positions come from joining data.nvs (chapter tree, speakers)
with liveplayer.nvs (<synchro id=chapterId timecode=ms>): a synchro whose id matches
a chapter id places that chapter at `timecode` ms. Synchros with no matching chapter
(the periodic 60s markers) are ignored. Pure join, tested on small XML.
"""
import replay as r


DATA_NVS = b"""<?xml version="1.0"?>
<data status="vod">
  <speakers>
    <speaker id="S1"><name>M. Philippe Juvin</name><url>721896</url></speaker>
  </speakers>
  <chapters>
    <chapter id="C1" label="Article 6">
      <chapter id="C2" label="M. Philippe Juvin"><speaker id="S1"/></chapter>
    </chapter>
    <chapter id="C3" label="Article 7"/>
  </chapters>
</data>"""

LIVEPLAYER_NVS = b"""<?xml version="1.0"?>
<player starttime="1782502269">
  <synchro id="M0" timecode="0"/>
  <synchro id="C1" timecode="60000"/>
  <synchro id="C2" timecode="90000"/>
  <synchro id="M60" timecode="120000"/>
  <synchro id="C3" timecode="150000"/>
</player>"""


def test_join_places_matching_chapters_on_the_timeline():
    tl = r.nvs_timeline(DATA_NVS, LIVEPLAYER_NVS)
    # only C1, C2, C3 match a chapter; M0/M60 (periodic markers) are dropped
    assert [(e["t_ms"], e["label"], e["speaker"]) for e in tl] == [
        (60000, "Article 6", None),
        (90000, "M. Philippe Juvin", "M. Philippe Juvin"),
        (150000, "Article 7", None),
    ]


def test_timeline_is_sorted_by_t():
    tl = r.nvs_timeline(DATA_NVS, LIVEPLAYER_NVS)
    assert [e["t_ms"] for e in tl] == sorted(e["t_ms"] for e in tl)
