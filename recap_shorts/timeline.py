"""(짤·효과음은 recap_shorts/fx 가 이 결과에 `overlays`, 전체화면 짤 샷(kind="meme"), `audio.sfx` 를 덧붙인다 — docs/fx_config.md)

script.json + 목소리 timings.json + 장면 배치표(shot_plan.json) → timeline.json (렌더 입력, docs/02_program_design.md 3.1절).

장면 배치표는 문장마다 보여 줄 그림 목록이다: {"0": ["assets/ai/a.png"], "1": ["...", "..."], ...} (키 = timings 의 문장 index).
- 문장 구간(다음 문장 시작까지)을 그 문장의 그림 수로 나눠 샷을 만든다. 규격 1.2~1.6초에 맞도록 문장당 2~3장을 권장.
  나누는 자리: word_cuts(recap_shorts/wordcuts.py)가 주어지면 같은 간격 자리에 가까운 어절 경계(가능하면 말 사이 쉼)에 컷을 놓고
  (그림은 문장이 끝날 때, 말 중간에서는 바꾸지 않는다), 없으면(config timing.cuts_at_word_gaps false) 똑같이 나눈다.
- 첫 샷(훅)은 천천히 확대(zoom_in), 그 뒤는 정지(static)를 기본으로 하고 세 장마다 한 장은 등장 효과(enter).
- 훅 흰 띠는 훅 문장이 끝나고 첫 본문 문장이 시작하는 시각(= 첫 컷)까지. 자막 카드는 본문·끝 문장에서 만든다.
- cuts: 사람이 장면 편집기에서 끌어 옮긴 문장 안 경계(shot_plan.json "cuts"). {"<문장 index>": {"t": [...], "span": [start, end]}}.
  그 문장 그림이 n장이면 t 는 n-1개. 저장할 때의 문장 구간(span)과 지금 구간이 다르면 비율로 옮겨 쓴다(목소리를 다시 녹음한 경우).
  쓸 수 없으면(개수 다름·순서 뒤집힘·샷이 0.4초보다 짧아짐) 그 문장만 지금처럼 자동으로 나눈다.
"""
from __future__ import annotations

import json
from pathlib import Path

from .render.captions import make_cards

USER_CUT_MIN_S = 0.4      # 사람이 끌어 옮긴 경계로 만든 샷의 최소 길이


def sentence_spans(timings: dict, tail: float = 0.45) -> dict[int, tuple[float, float]]:
    """문장 index -> (그 문장의 그림이 차지하는 구간 start, end). build 와 서버(scenes_view·put_scenes)가 같이 쓴다.
    첫 문장(훅)은 0초부터 첫 본문 문장 시작까지, 나머지는 자기 start ~ 다음 문장 start, 마지막은 영상 끝(duration + tail)."""
    sents = timings["sentences"]
    duration = round(float(timings["duration"]) + tail, 3)
    hook = next((s for s in sents if s.get("role") == "hook"), None)
    first_cut = next((float(s["start"]) for s in sents if s.get("role") != "hook"), float(hook["end"]) if hook else duration)
    out: dict[int, tuple[float, float]] = {}
    for i, s in enumerate(sents):
        start = 0.0 if i == 0 else float(s["start"])
        end = float(sents[i + 1]["start"]) if i + 1 < len(sents) else duration
        if i == 0 and hook is not None:
            end = first_cut
        out[int(s["index"])] = (round(start, 3), round(end, 3))
    return out


def user_cuts(entry, index: int, span: tuple[float, float], n: int) -> list[float] | None:
    """저장된 사용자 컷(shot_plan.json cuts 의 한 문장)을 지금 문장 구간에 쓸 수 있으면 컷 시각 목록, 아니면 None.
    저장할 때의 span 과 지금 span 이 다르면 비율로 옮긴다(목소리를 다시 녹음해 구간이 바뀐 경우)."""
    if not isinstance(entry, dict):
        return None
    ts = entry.get("t")
    if not isinstance(ts, list) or len(ts) != n - 1 or n < 2:
        return None
    try:
        vals = [float(t) for t in ts]
    except (TypeError, ValueError):
        return None
    start, end = span
    old = entry.get("span")
    if isinstance(old, (list, tuple)) and len(old) == 2:
        try:
            a0, b0 = float(old[0]), float(old[1])
        except (TypeError, ValueError):
            a0 = b0 = 0.0
        if b0 - a0 > 1e-6 and (abs(a0 - start) > 1e-3 or abs(b0 - end) > 1e-3):
            ratio = (end - start) / (b0 - a0)
            vals = [start + (t - a0) * ratio for t in vals]
    edges = [start] + vals + [end]
    if any(b - a < USER_CUT_MIN_S - 1e-9 for a, b in zip(edges, edges[1:])):   # 순서 뒤집힘·구간 밖·너무 짧은 샷
        return None
    return [round(t, 3) for t in vals]


def build(script: dict, timings: dict, plan: dict, *, voice: str, bgm: str | None = None, bgm_db: float = -22.0,
          tail: float = 0.45, focus: dict | None = None, sources: dict | None = None,
          bgm_title: str | None = None, bgm_start_s: float | None = None, word_cuts=None, cuts: dict | None = None) -> dict:
    """bgm 은 '요청'일 뿐이다: 기본 설정(config/fx.json bgm_mode "upload_note")에서는 렌더러가 영상에 섞지 않고
    out/upload_sound.txt 에 올릴 때 넣는 법만 적는다. bgm_title(곡 제목)·bgm_start_s(곡에서 시작할 위치, 초)는 그 안내문용 선택값.
    word_cuts: wordcuts.WordCuts(문장 안 컷을 어절 경계에 놓음) 또는 None(똑같이 나눔 — 예전 그대로). 못 고른 문장도 똑같이 나눈다.
    cuts: 장면 편집기에서 사람이 옮긴 문장 안 경계(shot_plan.json "cuts"). 쓸 수 있는 문장은 그 시각으로, 나머지는 자동."""
    sents = timings["sentences"]
    duration = round(float(timings["duration"]) + tail, 3)
    hook = next((s for s in sents if s.get("role") == "hook"), None)
    body = [s for s in sents if s.get("role") != "hook"]
    first_cut = body[0]["start"] if body else (hook["end"] if hook else 0.0)
    spans = sentence_spans(timings, tail)
    cuts = cuts if isinstance(cuts, dict) else {}

    shots, k = [], 0
    breaks: dict[int, list] = {}      # 문장 index -> [[자막 원문 어절 경계 번호, 컷 시각]] (고른 컷에 자막 카드도 맞추려고)
    for i, s in enumerate(sents):
        files = plan.get(str(s["index"])) or plan.get(s["index"]) or []
        if not files:
            raise ValueError(f"문장 {s['index']} 에 배치된 그림이 없습니다")
        start, end = spans[int(s["index"])]
        mine = user_cuts(cuts.get(str(s["index"]), cuts.get(s["index"])) if cuts else None,
                         int(s["index"]), (start, end), len(files))
        user = mine is not None
        if user:
            edges = [start] + mine + [end]          # 사람이 옮긴 경계 — 자막은 렌더가 컷에 맞춘다(breaks 안 만듦)
        else:
            step = (end - start) / len(files)
            picks = word_cuts.choose(s["index"], start, end, len(files)) if word_cuts is not None and len(files) > 1 else None
            if picks:                 # 어절 경계에 놓은 컷 — 못 골랐으면(None) 아래 똑같이 나누기
                edges = [start] + [c.t for c in picks] + [end]
                if s.get("role") != "hook":
                    tw = str(s.get("text", "")).split()
                    breaks[s["index"]] = [[word_cuts.text_k(s["index"], c.k, tw), c.t] for c in picks]
            else:
                edges = [start + j * step for j in range(len(files) + 1)]
        for j, f in enumerate(files):
            motion = "zoom_in" if k == 0 else ("enter" if k % 3 == 0 else "static")
            shots.append({"file": f, "start": round(edges[j], 3), "end": round(edges[j + 1], 3),
                          "motion": motion, "focus": (focus or {}).get(f, [0.5, 0.5]),
                          "source_id": (sources or {}).get(f, Path(f).stem),
                          **({"cut": "user"} if user else {})})
            k += 1

    emph = {i: (it.get("emphasis") or "") for i, it in enumerate(script.get("sentences", []), start=1)}
    cap_src = [{"text": s["text"], "start": s["start"], "end": s["end"], "emphasis": emph.get(s["index"], ""),
                **({"breaks": breaks[s["index"]]} if s["index"] in breaks else {})}
               for s in body]
    captions = make_cards(cap_src)

    audio = {"voice": voice, "bgm": bgm, "bgm_db": bgm_db, "sfx_on_cuts": False}
    if bgm_title:
        audio["bgm_title"] = bgm_title
    if bgm_start_s is not None:
        audio["bgm_start_s"] = bgm_start_s
    return {
        "fps": 30, "size": [1080, 1920], "duration": duration,
        "title_lines": script["title_lines"],
        "hook": {"text": script["hook"], "start": 0.0, "end": round(first_cut, 3)},
        "shots": shots,
        "captions": captions,
        "audio": audio,
        "options": {"snap_captions_to_cuts": True},
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.timeline")
    ap.add_argument("job_dir", help="work/<job> (script_final/script.json, voice/timings.json, shot_plan.json 이 있는 폴더)")
    ap.add_argument("--bgm", default=None, help="요청할 배경음악 파일. 기본 설정(bgm_mode upload_note)에서는 영상에 섞지 않고 out/upload_sound.txt 만 쓴다")
    ap.add_argument("--bgm-db", type=float, default=-22.0, help="목소리 대비 배경음악 크기(dB)")
    ap.add_argument("--bgm-title", default=None, help="곡 제목(upload_sound.txt 에 적음)")
    ap.add_argument("--bgm-start", type=float, default=None, help="곡에서 시작할 위치(초, upload_sound.txt 에 적음)")
    ap.add_argument("--no-word-cuts", action="store_true", help="문장 안 컷을 어절 경계에 놓지 않고 똑같이 나눈다(config timing.cuts_at_word_gaps 를 끈 것과 같음)")
    args = ap.parse_args()
    job = Path(args.job_dir)
    script = json.loads((job / "script_final" / "script.json").read_text(encoding="utf-8"))
    timings = json.loads((job / "voice" / "timings.json").read_text(encoding="utf-8"))
    plan_doc = json.loads((job / "shot_plan.json").read_text(encoding="utf-8"))
    from . import wordcuts
    wc = None if args.no_word_cuts else wordcuts.from_options(job, timings)
    tl = build(script, timings, plan_doc["plan"], voice="voice/voice.wav", bgm=args.bgm, bgm_db=args.bgm_db,
               bgm_title=args.bgm_title, bgm_start_s=args.bgm_start, focus=plan_doc.get("focus"), sources=plan_doc.get("sources"),
               word_cuts=wc, cuts=plan_doc.get("cuts"))
    (job / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    lens = [s["end"] - s["start"] for s in tl["shots"]]
    print(f"timeline.json: 샷 {len(lens)}개, 길이 {min(lens):.2f}~{max(lens):.2f}초 (중앙 {sorted(lens)[len(lens) // 2]:.2f}), "
          f"자막 카드 {len(tl['captions'])}장, 첫 컷 {tl['hook']['end']:.2f}초, 전체 {tl['duration']:.2f}초")


if __name__ == "__main__":
    main()
