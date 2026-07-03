"""The NVS is a tree of nested chapters; B4 shows that tree and bolds the whole
ancestor chain of the last reached chapter. So B2 exposes the chapters WITH their
nesting (id + parent + depth), not a flat list.

nvs_tree(data_nvs, liveplayer_nvs) -> list of nodes in document order, each
{id, parent, depth, label, speaker, t_ms|None}. t_ms is the synchro timecode when
the chapter is placed on the video timeline, else None (present in the tree, never
current). The join is by chapter id, same as nvs_timeline.
"""
import replay as r


DATA = b"""<?xml version="1.0"?><data status="vod">
  <speakers>
    <speaker id="S1"><name>Mme Perrine Goulet</name></speaker>
    <speaker id="S2"><name>M. Edouard Geffray</name></speaker>
  </speakers>
  <chapters>
    <chapter id="A" label="Audition">
      <chapter id="A1" label="Mme Perrine Goulet, presidente"><speaker id="S1"/></chapter>
      <chapter id="Q" label="Questions">
        <chapter id="Q1" label="M. Edouard Geffray, ministre"><speaker id="S2"/></chapter>
      </chapter>
    </chapter>
  </chapters>
</data>"""

LP = b"""<?xml version="1.0"?><player starttime="1782845467">
  <synchro id="A"  timecode="561000"/>
  <synchro id="A1" timecode="561000"/>
  <synchro id="Q"  timecode="2441000"/>
  <synchro id="Q1" timecode="2449000"/>
</player>"""


def test_tree_keeps_nesting_and_parents():
    tree = r.nvs_tree(DATA, LP)
    by_id = {n["id"]: n for n in tree}
    # document order preserved
    assert [n["id"] for n in tree] == ["A", "A1", "Q", "Q1"]
    # depth and parent link
    assert by_id["A"]["depth"] == 0 and by_id["A"]["parent"] is None
    assert by_id["A1"]["depth"] == 1 and by_id["A1"]["parent"] == "A"
    assert by_id["Q1"]["depth"] == 2 and by_id["Q1"]["parent"] == "Q"


def test_tree_carries_timecode_and_speaker():
    by_id = {n["id"]: n for n in r.nvs_tree(DATA, LP)}
    assert by_id["Q1"]["t_ms"] == 2449000
    assert by_id["Q1"]["speaker"] == "M. Edouard Geffray"
    assert by_id["A"]["speaker"] is None


def test_unplaced_chapter_has_none_t():
    lp = LP.replace(b'<synchro id="Q1" timecode="2449000"/>', b"")
    by_id = {n["id"]: n for n in r.nvs_tree(DATA, lp)}
    assert by_id["Q1"]["t_ms"] is None
