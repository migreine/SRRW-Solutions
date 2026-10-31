"""Tests for the judges' story demo (scripts/build_story.py -> demo/story.html)."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_story.py"
OUT = ROOT / "demo" / "story.html"


@pytest.fixture(scope="module")
def html() -> str:
    proc = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert OUT.exists()
    return OUT.read_text(encoding="utf-8")


def _blob(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="story-data">(.*?)</script>', html, re.S)
    assert m, "embedded data blob missing"
    return json.loads(m.group(1))


def _summary(metric: str, mode: str = "haiku") -> str:
    with open(ROOT / "eval" / "results" / "summary.csv", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["metric"] == metric and r["mode"] == mode:
                return r["value"]
    raise KeyError(metric)


def test_builder_writes_html(html):
    assert html.startswith("<!DOCTYPE html>")
    assert len(html) > 20_000


def test_no_external_resources(html):
    assert not re.search(r"https?://", html, re.I), "page must not reference http(s) URLs"
    assert not re.search(r"<link\b[^>]*href=", html, re.I)
    assert not re.search(r"<script\b[^>]*\bsrc=", html, re.I)
    assert "@import" not in html and "url(" not in html


def test_contains_key_real_values(html):
    data = _blob(html)
    showcase = json.loads((ROOT / "runs" / "showcase.json").read_text(encoding="utf-8"))
    for s in ("AA334", "N469AA", "DL1501", "R-DUTY-01", showcase["meta"]["scenario_id"]):
        assert s in html, s
    # consensus rate straight from summary.csv
    assert data["summary"]["haiku"]["consensus_rate"]["value"] == _summary("consensus_rate")
    assert _summary("consensus_rate") in html
    assert data["summary"]["haiku"]["agent_top_pick_rule_fail_rate"]["value"] == _summary("agent_top_pick_rule_fail_rate")


def test_tail_day_from_flights_csv(html):
    legs = _blob(html)["tail_day"]["legs"]
    assert [l["arr_delay"] for l in legs] == [101, 102, 264, 256]
    assert legs[0]["flight"] == "AA334"


def test_runs_embedded(html):
    data = _blob(html)
    run = json.loads((ROOT / "runs" / "showcase.json").read_text(encoding="utf-8"))
    assert len(data["showcase"]["candidates"]) == len(run["candidates"])
    assert len(data["showcase"]["rules"]) == len(run["rule_results"])
    assert data["showcase"]["recommendation"]["chosen"]["candidate_id"] == run["recommendation"]["chosen"]["candidate_id"]
    assert data["failure"]["reviewer"]["verdict"] == "REJECT"
    assert data["failure"]["recommendation"]["chosen"] is None
    assert any(e["event"] == "agent_message" for e in data["showcase"]["timeline"])


def test_brief_figures_labelled(html):
    data = _blob(html)
    assert data["brief"], "brief figures should be found in the docs"
    assert all(b["cite"] for b in data["brief"])
    assert "reported in our industry brief" in html


JS_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const blob = src.match(/<script type="application\/json" id="story-data">([\s\S]*?)<\/script>/)[1];
const code = src.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const els = {};
function el(id){
  if (!els[id]) els[id] = { id, innerHTML:"", textContent: id==="story-data"?blob:"", style:{}, disabled:false,
    classList:{toggle(){}, add(){}, remove(){}}, addEventListener(){}, querySelectorAll(){ return []; } };
  return els[id];
}
let keyHandler = null;
global.document = { getElementById: el, addEventListener(t, f){ if (t==="keydown") keyHandler = f; } };
global.location = { hash: "" };
global.history = { replaceState(_a,_b,h){ location.hash = h; } };
global.window = { scrollTo(){} };
eval(code);
const out = [];
for (let i = 0; i < 12; i++) {
  const html = el("stage").innerHTML;
  out.push({ counter: el("counter").textContent, ok: !/Could not render/.test(html), len: html.length,
             err: (html.match(/Could not render this chapter: ([^<]*)/)||[])[1] || null });
  keyHandler({ key: "ArrowRight", preventDefault(){} });
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_chapter_renders(html, tmp_path):
    harness = tmp_path / "harness.js"
    harness.write_text(JS_HARNESS, encoding="utf-8")
    proc = subprocess.run(["node", str(harness), str(OUT)], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    pages = json.loads(proc.stdout)
    seen = {p["counter"]: p for p in pages}
    assert len(seen) == 10, seen.keys()
    bad = {k: p["err"] for k, p in seen.items() if not p["ok"] or p["len"] < 500}
    assert not bad, bad
