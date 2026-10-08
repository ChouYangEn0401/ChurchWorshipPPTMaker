"""網頁預覽（lyrics.js）和匯出的 PPT（lyrics.py）一定要做出同樣的決定：同樣的分頁、歌序、字級、折行。
用 node 跑 lyrics.js，跟 Python 的結果逐項比對。沒裝 node 就跳過。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from worship_ppt.lyrics import header_scale, lyrics_layout, parse_sequence, plan_song, title_page_size
from worship_ppt.styles import clean_style

JS = Path(__file__).resolve().parents[1] / "src" / "worship_ppt" / "web" / "static" / "js" / "lyrics.js"
NODE = shutil.which("node")

STYLES = [
    clean_style({}),
    clean_style({"lyrics": {"size": 54}, "lyricsTop": 1.4, "maxLines": 4, "showHeader": False}),
    clean_style({"lyrics": {"size": 80}, "autoFit": False, "lineSpacing": 1.3}),
    clean_style({"lyrics": {"size": 60}, "lyricsLeft": 0.05, "titleSlide": True}),
]
SEQUENCES = ["", "主 主 副前1 副 主 副前1 副 副前2 副 副", "1. 主\n2. 副\n3. 尾*2", "Verse 1, Chorus x2, 自由, 橋(×3)"]
EXTRA_LYRICS = [
    "[Verse 1]\nAmazing grace how sweet the sound\nThat saved a wretch like me\n[Chorus]\nMy chains are gone",
    "沒有段落標籤的一段\n第二行\n\n第二頁",
    "[主]\n一\n二\n三\n四\n五\n六\n七\n[副]\n很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長沒有空白",
    "【前奏】\n[副]\nA  B  C",
    "",
]


def _cases(sheet):
    lyrics = [s.lyrics for s in sheet.songs] + EXTRA_LYRICS
    cases = []
    for li, text in enumerate(lyrics):
        for si, seq in enumerate(SEQUENCES):
            for st_i, style in enumerate(STYLES):
                if (li + si + st_i) % 2:  # 取一半的組合就夠了
                    continue
                for size in ((10.0, 7.5), (13.333, 7.5)):
                    cases.append({"lyrics": text, "sequence": seq, "style": style, "w": size[0], "h": size[1],
                                  "follow": bool((li + si) % 3)})
    return cases


def _python(case):
    st = case["style"]
    plan = plan_song(case["lyrics"], case["sequence"], follow_sequence=case["follow"],
                     max_lines=st["maxLines"], title_slide=st["titleSlide"])
    layouts = [list(lyrics_layout(s["text"], st, case["w"], case["h"])) for s in plan["slides"]]
    heads = [header_scale("聖靈請祢來充滿我心", s["label"], st, case["w"]) for s in plan["slides"]]
    return {"plan": plan, "layouts": layouts, "heads": heads,
            "title": title_page_size("聖靈請祢來充滿我心", st, case["w"], case["h"]),
            "seq": [[t.label, t.repeat] for t in parse_sequence(case["sequence"])]}


NODE_SCRIPT = """
import { planSong, lyricsLayout, headerScale, titlePageSize, parseSequence } from %s;
const cases = JSON.parse(await new Promise((res) => { let d = ""; process.stdin.on("data", (c) => d += c); process.stdin.on("end", () => res(d)); }));
const out = cases.map((c) => {
  const st = c.style;
  const plan = planSong(c.lyrics, c.sequence, { followSequence: c.follow, maxLines: st.maxLines, titleSlide: st.titleSlide });
  return {
    plan,
    layouts: plan.slides.map((s) => lyricsLayout(s.text, st, c.w, c.h)),
    heads: plan.slides.map((s) => headerScale("聖靈請祢來充滿我心", s.label, st, c.w)),
    title: titlePageSize("聖靈請祢來充滿我心", st, c.w, c.h),
    seq: parseSequence(c.sequence).map((t) => [t.label, t.repeat]),
  };
});
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="沒有安裝 node")
def test_js_and_python_make_identical_decisions(sheet, tmp_path):
    mjs = tmp_path / "lyrics.mjs"
    mjs.write_text(JS.read_text(encoding="utf-8"), encoding="utf-8")
    runner = tmp_path / "run.mjs"
    runner.write_text(NODE_SCRIPT % json.dumps(mjs.as_uri()), encoding="utf-8")
    cases = _cases(sheet)
    proc = subprocess.run([NODE, str(runner)], input=json.dumps(cases, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    js_results = json.loads(proc.stdout.decode("utf-8"))
    assert len(js_results) == len(cases) > 50
    for case, js in zip(cases, js_results):
        py = json.loads(json.dumps(_python(case), ensure_ascii=False))
        assert js == py, (case["lyrics"][:40], case["sequence"], case["style"]["lyrics"]["size"])
