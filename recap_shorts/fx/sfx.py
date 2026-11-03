"""효과음 라이브러리 읽기 + 효과음 놓을 자리 정하기.

라이브러리: 폴더마다 manifest.json {"version":1,"items":[{id,file,type,duration,...}]} (목록만 있어도 됨).
manifest 가 없는 폴더는 소리 파일 이름(pop_01.wav)이나 하위 폴더 이름(pop\\아무이름.mp3)에서 종류를 읽는다(scan_folder).
 - assets/sfx : scripts/make_sfx.py 로 합성한 것(made_by 표기)
 - assets/sfx_packs : 저장소에 같이 넣은 기본 꾸러미(source·license 필드 추가)
 - 설정 화면의 '효과음 폴더' : 사람이 고른 폴더(settings.sfx_dirs) — 있으면 기본 꾸러미 대신 쓴다
이벤트 = {"file","t","db"} (+ 기록용 type·why). db 는 "목소리 피크 목표(−1.5 dBTP) 대비" 상대값이다
(파일은 피크 정규화되어 있고, 믹스할 때 파일 피크를 읽어 맞춘다 — render/audio.py).
"""
from __future__ import annotations

import json
import hashlib
import re
import wave
from pathlib import Path

from . import rights as R
from .config import resolve_path

SFX_TYPES = ["whoosh", "swoosh", "pop", "ding", "boom", "click", "typing", "riser", "buzz", "boing", "shutter", "coin",
             "slidewhistle"]
# 겹칠 때 남길 우선순위(클수록 우선)
PRIORITY = {"ending": 5, "meme_pop": 4, "hook": 3, "beat": 2, "cut": 1}

# 저장소의 합성 꾸러미(assets/sfx, scripts/make_sfx.py)에는 자리 이름 몇 가지가 없다. 직접 넣은 꾸러미가 없는 PC 에서
# 합성음으로 대신할 때만 이 대응표를 쓴다(type_fallback 에 섞음) — 직접 넣은 꾸러미가 있으면 예전 그대로.
# 값은 SYNTH_TYPES 안의 종류여야 한다.
BUILTIN_TYPE_FALLBACK = {
    "hit": "pop",               # 영상 시작 '탁'(짧은 소리)
    "huh": "boing",             # 물음표 반응
    "scream": "buzz",           # 분노·비명 자리
    "awkward": "slidewhistle",  # 어색한 침묵
    "sad": "slidewhistle",      # 시무룩
    "laugh": "boing",           # 웃김
    "sus": "ding",              # 눈치·의심
    "punchline": "coin",        # 마무리 한 방
    "sparkle": "ding",          # 반짝(합성 꾸러미에 없음)
    "jingle": "ding",
    "whoosh_short": "whoosh",
    "cheer": "coin", "oooh": "boing", "aw": "slidewhistle", "gasp": "boom",
    "error": "buzz", "bleep": "buzz", "fanfare": "coin", "oof": "pop",
}


def builtin_type_fallback(fallback: dict | None) -> dict:
    """설정의 type_fallback 에 합성 꾸러미 대응표를 더한 것. 설정이 직접 적은 값이 먼저고, 설정이 합성 꾸러미에
    없는 종류로 보내면(예: cheer→laugh) 그 종류를 한 번 더 합성 종류로 바꾼다.
    합성 꾸러미(assets/sfx)를 대신 쓸 때만 apply_fx 가 덧씌운다 — 직접 넣은 꾸러미가 있으면 예전과 같다."""
    out = {str(k): str(v) for k, v in (fallback or {}).items()}
    for k, v in BUILTIN_TYPE_FALLBACK.items():
        out.setdefault(k, v)
    synth = set(SFX_TYPES)
    for k, v in list(out.items()):
        if v not in synth and v in BUILTIN_TYPE_FALLBACK:
            out[k] = BUILTIN_TYPE_FALLBACK[v]
    return out


def synth_cast(types_db: dict | None, cuts: dict | None = None) -> tuple[dict, dict]:
    """설정의 크기(types_db)·컷 종류 가중치(cuts.types)를 합성 꾸러미 종류에 맞춘 사본.
    합성 꾸러미에 없는 종류(sparkle 등)는 대응표 종류의 크기·비중으로 합친다 — 'sparkle' 크기가 없어져
    그 자리가 기본 db 로 커지는 일을 막는다. 대응표에 없는 종류는 그대로 둔다(고르기에서 건너뜀)."""
    out = dict(types_db or {})
    for k in list(out):
        if k not in BUILTIN_TYPE_FALLBACK:
            continue
        dst = BUILTIN_TYPE_FALLBACK[k]
        out.setdefault(dst, out.pop(k))
    if isinstance(cuts, dict) and isinstance(cuts.get("types"), dict):
        cut = dict(cuts)
        weights = dict(cuts["types"])
        for k in list(weights):
            if k not in BUILTIN_TYPE_FALLBACK:
                continue
            dst = BUILTIN_TYPE_FALLBACK[k]
            weights[dst] = float(weights.get(dst, 0.0)) + float(weights.pop(k))
        cut["types"] = weights
        return out, cut
    return out, cuts


def _base(why: str) -> str:
    """'hook:open' 같은 자리 이름에서 큰 갈래('hook')."""
    return why.split(":", 1)[0]


AUDIO_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a")
# manifest 없는 폴더에서 이름으로 알아보는 종류 = 합성 종류 + 기본 꾸러미·설정에 나오는 자리 이름
KNOWN_TYPES = sorted(set(SFX_TYPES) | set(BUILTIN_TYPE_FALLBACK))
SCAN_MAX_FILES = 3000   # 폴더 하나에서 볼 소리 파일 수(효과음 모음 전체를 고르는 실수로 오래 걸리지 않게)
_NUM_TAIL = re.compile(r"[\s_\-]*\(?\d+\)?$")


def slot_types(scfg: dict) -> set[str]:
    """효과음 설정(sfx)의 자리들이 고를 수 있는 종류 — 훅·컷·짤·분위기·끝의 type, 컷 비중 종류, 박자별 종류,
    그리고 그 종류들의 type_fallback 대상. "enabled": false 인 자리는 뺀다. 설정에 자리가 하나도 없으면 빈 집합."""
    out: set[str] = set()
    for sec in ("hook", "cuts", "meme_pop", "beat_events", "ending"):
        v = scfg.get(sec)
        if not isinstance(v, dict) or v.get("enabled") is False:
            continue
        for d in [v] + [x for x in v.values() if isinstance(x, dict) and x.get("enabled") is not False]:
            for k in ("type", "default_type"):
                if isinstance(d.get(k), str):
                    out.add(d[k])
        for k in ("types", "by_beat"):
            if isinstance(v.get(k), dict):
                out |= {str(t) for t in (v[k].keys() if k == "types" else v[k].values())}
    fb = scfg.get("type_fallback") or {}
    out |= {str(fb[t]) for t in list(out) if t in fb}
    return out


def type_from_name(rel: Path) -> str | None:
    """폴더 기준 상대 경로에서 효과음 종류. 하위 폴더 이름이 종류면 그것(pop/아무이름.mp3), 아니면 파일 이름
    (pop_01.wav, boom.wav, whoosh_short-2.mp3, pop_cartoon.wav 처럼 앞 낱말). 모르는 이름이면 None."""
    for part in rel.parts[:-1]:
        if part.lower() in KNOWN_TYPES:
            return part.lower()
    stem = _NUM_TAIL.sub("", rel.stem.lower()).strip()
    if stem in KNOWN_TYPES:
        return stem
    head = re.split(r"[\s_\-]+", stem)[0] if stem else ""
    return head if head in KNOWN_TYPES else None


def _duration(f: Path) -> float:
    try:
        import soundfile
        return round(float(soundfile.info(str(f)).duration), 3)
    except Exception:  # noqa: BLE001 — 길이를 못 읽으면 0(길이로 고르는 자리에서만 덜 맞음)
        pass
    try:
        with wave.open(str(f), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 3)
    except Exception:  # noqa: BLE001
        return 0.0


def scan_folder(d: str | Path, durations: bool = True) -> tuple[list[dict], int]:
    """manifest 없는 폴더(한 단계 하위 폴더까지)의 소리 파일 → (항목, 종류를 몰라 뺀 파일 수).
    id 는 폴더 기준 상대 경로(확장자 뺌) — 같은 이름이 하위 폴더에 있어도 겹치지 않게."""
    dd = resolve_path(d)
    items, skipped = [], 0
    files = [p for p in sorted(dd.glob("*")) + sorted(dd.glob("*/*")) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    for f in files[:SCAN_MAX_FILES]:
        rel = f.relative_to(dd)
        typ = type_from_name(rel)
        if not typ:
            skipped += 1
            continue
        it = {"id": rel.with_suffix("").as_posix(), "file": rel.as_posix(), "type": typ}
        if durations:
            it["duration"] = _duration(f)
        items.append(it)
    return items, skipped + max(0, len(files) - SCAN_MAX_FILES)


def folder_items(d: str | Path, durations: bool = True) -> tuple[list[dict], int, bool]:
    """(manifest 또는 이름에서 읽은 항목, 뺀 파일 수, manifest 로 읽었는지). manifest 가 깨졌으면 ValueError."""
    dd = resolve_path(d)
    mf = dd / "manifest.json"
    if not mf.is_file():
        items, skipped = scan_folder(dd, durations)
        return items, skipped, False
    try:
        doc = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"효과음 manifest 를 읽지 못함: {mf}")
    raw = (doc.get("items", []) if isinstance(doc, dict) else doc) or []
    items = [it for it in raw if isinstance(it, dict) and it.get("id") and it.get("type") and (dd / str(it.get("file", ""))).is_file()]
    return items, len(raw) - len(items), True


def load_library(dirs: list[str | Path]) -> tuple[list[dict], list[str]]:
    items, notes = [], []
    for di, d in enumerate(dirs):
        dd = resolve_path(d)
        if not dd.is_dir():
            continue
        try:
            found, _, _ = folder_items(dd)
        except ValueError as e:
            notes.append(str(e))
            continue
        for it in found:
            items.append({**it, "file": str(dd / str(it["file"])), "priority": it.get("priority", di)})
    if not items:
        notes.append("효과음 라이브러리가 비어 있음(python scripts/make_sfx.py 로 합성) — 효과음은 건너뜀")
    return items, notes


class _Chooser:
    """같은 종류 안에서 고른다(결정적).
    - 라이브러리 항목에 role(또는 roles 목록: cut·hook·meme_pop·ending·beat)이 있으면 그 자리용을 먼저 쓴다
      (쇼츠 효과음을 자리별로 정리해 두기 위한 것).
    - mode "rotate"(기본) = 돌려 가며(같은 파일 연속 방지), "fixed" = 한 영상에서 종류·자리마다 한 파일만."""

    def __init__(self, library: list[dict], mode: str = "rotate", max_same: int = 0, avoid_last: int = 0):
        self.by_type: dict[str, list[dict]] = {}
        for it in sorted(library, key=lambda x: (x.get("priority", 0), x["id"])):
            self.by_type.setdefault(it["type"], []).append(it)
        self.n: dict[str, int] = {}
        self.mode = mode
        # 같은 파일은 영상당 최대 2번, 직전 몇 개와는 다른 파일(측정 규칙 R8)
        self.max_same, self.avoid_last = int(max_same or 0), int(avoid_last or 0)
        self.used: dict[str, int] = {}
        self.recent: list[str] = []

    def _ok(self, it: dict) -> bool:
        if self.max_same and self.used.get(it["id"], 0) >= self.max_same:
            return False
        return not (self.avoid_last and it["id"] in self.recent[-self.avoid_last:])

    def _take(self, it: dict) -> dict:
        self.used[it["id"]] = self.used.get(it["id"], 0) + 1
        self.recent.append(it["id"])
        return it

    @staticmethod
    def _has_role(it: dict, role: str) -> bool:
        return it.get("role") == role or role in (it.get("roles") or [])

    def get(self, typ: str, want_len: float | None = None, role: str | None = None):
        pool = self.by_type.get(typ)
        if not pool:
            return None
        if role:
            fit = [it for it in pool if self._has_role(it, role)]
            pool = fit or pool
        if want_len:
            return self._take(min(pool, key=lambda it: abs(float(it.get("duration", 0)) - want_len)))
        key = f"{typ}|{role or ''}"
        if self.mode == "fixed":
            return self._take(pool[0])
        k = self.n.get(key, 0)
        for step in range(len(pool)):
            it = pool[(k + step) % len(pool)]
            if self._ok(it):
                self.n[key] = k + step + 1
                return self._take(it)
        self.n[key] = k + 1
        return self._take(pool[k % len(pool)])


def cut_times(timeline: dict, cfg_cuts: dict, sentence_starts: list[float]) -> list[float]:
    """효과음을 놓을 컷 시각. 훅 컷(0초)·짤 샷 시작은 제외한다."""
    mode = cfg_cuts.get("mode", "none")
    if mode == "none":
        return []
    shots = sorted(timeline["shots"], key=lambda s: s["start"])
    cuts = [s["start"] for s in shots if s["start"] > 1e-6 and s.get("kind") != "meme"]
    if cfg_cuts.get("skip_first", True) and cuts:
        cuts = cuts[1:]
    if mode == "sentence_start":
        cuts = [c for c in cuts if any(abs(c - s) <= 0.06 for s in sentence_starts)]
    elif mode == "every_k":
        k = max(1, int(cfg_cuts.get("k", 2)))
        cuts = cuts[::k]
    return cuts


def _h(*parts) -> float:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def pick_type_weighted(weights: dict, idx: int) -> str:
    """결정적 순환(황금비 수열): idx 번째 컷의 종류. 가중치대로 고르게 퍼진다."""
    names = list(weights)
    tot = sum(float(weights[n]) for n in names) or 1.0
    u = (idx * 0.6180339887498949) % 1.0
    acc = 0.0
    for n in names:
        acc += float(weights[n]) / tot
        if u < acc:
            return n
    return names[-1]


def voice_energy(path: str | Path, hop_s: float = 0.01):
    """voice wav 의 10ms RMS 곡선(numpy 배열)과 hop. 못 읽으면 (None, hop)."""
    try:
        import numpy as np
        with wave.open(str(path)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2:
            return None, hop_s
        x = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
        n = int(sr * hop_s)
        m = len(x) // n
        return np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1)), hop_s
    except Exception:  # noqa: BLE001
        return None, hop_s


def snap_to_gap(t: float, rms, hop_s: float, voice_offset_s: float = 0.0, window_s: float = 0.25) -> float:
    """t(영상 시계)를 ±window_s 안에서 목소리 에너지가 가장 낮은 시각(숨 고르기)으로 옮긴다.
    목소리가 voice_offset_s 만큼 늦게 나오므로 영상 시각 t 의 목소리 표본은 t - voice_offset_s."""
    if rms is None or len(rms) == 0:
        return t
    import numpy as np
    sm = np.convolve(rms, np.ones(3) / 3, mode="same")
    lo = int(round((t - voice_offset_s - window_s) / hop_s))
    hi = int(round((t - voice_offset_s + window_s) / hop_s))
    idx = np.arange(max(0, lo), min(len(sm) - 1, hi) + 1)
    if len(idx) == 0:
        return t
    c = int(round((t - voice_offset_s) / hop_s))
    tol = float(sm[idx].min()) * 1.05 + 1e-4  # 거의 같은 골이 여럿이면 원래 시각에 가까운 것
    cand = idx[sm[idx] <= tol]
    best = int(cand[np.argmin(np.abs(cand - c))])
    return round(best * hop_s + voice_offset_s, 3)


def place_sfx(timeline: dict, sentences: list[dict], meme_events: list[dict], library: list[dict], cfg: dict,
              *, energy=None, voice_offset_s: float = 0.0) -> dict:
    """반환 {"events":[{file,t,db,type,why}], "notes":[...]}. t 는 영상 시계. energy=(rms, hop) 이면 place_on 에 따라 말 사이 쉼으로 옮긴다."""
    notes: list[str] = []
    # 저작권 위험 소리 회피(기본 꺼짐: sfx.avoid_rights_risk null — 이때 library 는 그대로라 고르기가 예전과 같다)
    library, risk_notes = R.filter_library(library, cfg.get("avoid_rights_risk"))
    notes += risk_notes
    # 다시 쓰지 말자고 한 소리(sfx.ban_sources: 원본 파일 이름 앞부분). 꾸러미마다 id 가 겹쳐서 원본 이름으로 본다.
    ban = [str(b).lower() for b in cfg.get("ban_sources") or []]
    if ban:
        kept = [it for it in library if not any(Path(str(it.get("source_file") or "")).stem.lower().startswith(b) for b in ban)]
        if len(kept) != len(library):
            notes.append(f"쓰지 않기로 한 효과음 {len(library) - len(kept)}개 뺌(sfx.ban_sources)")
        library = kept
    ch = _Chooser(library, cfg.get("choose", "rotate"), cfg.get("max_same_file", 0), cfg.get("avoid_last_n", 0))
    tdb = cfg.get("types_db") or {}
    raw: list[tuple[str, str, float, float]] = []  # (why, type, t, db)

    c = cfg.get("cuts", {})
    skip_ratio = float(c.get("skip_ratio", 0.0))
    for n, t in enumerate(cut_times(timeline, c, [s["start"] for s in sentences])):
        if skip_ratio > 0 and _h("skip", round(t, 3)) < skip_ratio:
            continue
        typ = pick_type_weighted(c["types"], n) if c.get("types") else c.get("type", "swoosh")
        raw.append(("cut", typ, t + float(c.get("offset_s", 0.0)), float(c.get("db", -18))))

    mp = cfg.get("meme_pop", {})
    for k_ev, ev in enumerate(meme_events):
        typ = (mp.get("by_beat") or {}).get(ev["beat"])
        if typ is None:   # 충격·웃김·마무리 말고는 컷과 같은 소리 순환(R7)
            typ = (pick_type_weighted(c["types"], 1000 + k_ev) if (mp.get("rest_from_cuts") and c.get("types"))
                   else mp.get("default_type", "pop"))
        raw.append(("meme_pop", typ, ev["start"] + float(mp.get("offset_s", 0.0)), float(mp.get("db", -10))))

    h = cfg.get("hook", {})
    hook = timeline.get("hook")
    if h.get("enabled") and hook:
        if any(k in h for k in ("open", "pop", "first_cut")):
            # 인트로의 세 자리: 영상 시작 '탁', 카드 튀는 순간 '휙-쿵', 첫 컷 '톡'
            # 자리마다 "enabled": false 로 끌 수 있다(값은 기록으로 남김)
            o, p_, fc = (x if isinstance(x, dict) and x.get("enabled", True) else None
                         for x in (h.get("open"), h.get("pop"), h.get("first_cut")))
            if o:
                raw.append(("hook:open", o.get("type", "hit"), float(o.get("t", 0.06)), float(o.get("db", -3))))
            intro = timeline.get("intro")
            if p_ and intro and intro.get("t_pop") is not None:
                raw.append(("hook:pop", p_.get("type", "whoosh_short"),
                            float(intro["t_pop"]) + float(p_.get("offset_s", 0.06)), float(p_.get("db", -8))))
            elif p_:
                notes.append("인트로 카드가 없어 카드 튐 효과음(hook.pop)은 건너뜀")
            if fc:
                raw.append(("hook:first_cut", fc.get("type", "pop"), float(hook["end"]) + float(fc.get("offset_s", 0.02)),
                            float(fc.get("db", -15))))
        else:   # 예전 한 개짜리 형식
            base = float(hook["end"]) if h.get("at") == "first_cut" else float(hook["start"])
            raw.append(("hook", h.get("type", "whoosh"), base + float(h.get("offset_s", 0.0)), float(h.get("db", -12))))

    be = cfg.get("beat_events", {})
    if be.get("enabled"):
        for s in sentences:
            typ = (be.get("by_beat") or {}).get(s.get("beat"))
            if typ and s.get("role") != "hook":
                raw.append(("beat", typ, float(s["start"]) + float(be.get("offset_s", 0.0)), float(be.get("db", -10))))

    en = cfg.get("ending")
    if isinstance(en, dict) and not en.get("enabled", True):
        en = None
    ending_len = None
    if en and en.get("types") and not en.get("type"):   # 상승 미끄럼 휘슬 60%·띠용 40%(R6) — 영상마다 결정적으로
        en = {**en, "type": pick_type_weighted(en["types"], int(_h("ending", round(float(timeline["duration"]), 2)) * 1000))}
    if en and en.get("type"):
        last_meme = max((e["start"] for e in meme_events), default=None)
        # 마지막 짤이 영상 끝 4초 안에 있을 때만 거기에(끝 효과음은 마지막 4초 안, 짤로 거의 안 끝남)
        if en.get("at_end_s") is not None:     # 마지막 효과음은 영상 끝 1.1초 전
            t_end = float(timeline["duration"]) - float(en["at_end_s"])
        elif last_meme is not None and last_meme >= float(timeline["duration"]) - 4.0:
            t_end = last_meme + float(mp.get("offset_s", 0.0))
        else:
            starts = [s["start"] for s in timeline["shots"] if s["start"] > 1e-6]
            t_end = (starts[-1] if starts else 0.0) + float((cfg.get("cuts") or {}).get("offset_s", 0.0))
        raw.append(("ending", en["type"], t_end, float(en.get("db", -18))))
        ending_len = float(en.get("len_s", 0)) or None

    dur = float(timeline["duration"])
    min_gap = float(cfg.get("min_gap_s", 0.25))
    if energy is not None and energy[0] is not None and cfg.get("place_on") == "speech_gap":
        w = float(cfg.get("gap_window_s", 0.25))
        raw = [(why, ty, t if _base(why) == "hook" else snap_to_gap(t, energy[0], energy[1], voice_offset_s, w), db)
               for why, ty, t, db in raw]
    elif cfg.get("place_on") == "speech_gap":
        notes.append("목소리 파일을 읽지 못해 효과음을 말 사이 쉼으로 옮기지 못함")
    cand = [(w_, ty, max(0.0, t), db) for w_, ty, t, db in raw if -0.5 < t < dur - 0.05]
    # 겹침 정리: 우선순위 높은 것부터 받고, 이미 받은 것과 min_gap 안이면 버린다
    accepted: list[tuple[str, str, float, float]] = []
    for r in sorted(cand, key=lambda r: (-PRIORITY.get(_base(r[0]), 0), r[2])):
        if all(abs(r[2] - a[2]) >= min_gap for a in accepted):
            accepted.append(r)
    # 개수 상한은 본문 효과음(컷·짤·박자)에만 건다. 인트로·끝 소리는 고정 틀이라 따로 둔다
    # (훅 3자리가 10초당 2.3개 상한을 먹어 본문 컷 효과음이 3개만 남는 경우가 있다).
    fixed = [r for r in accepted if _base(r[0]) in ("hook", "ending")]
    body = [r for r in accepted if _base(r[0]) not in ("hook", "ending")]
    mx = int(cfg.get("max_per_video", 24))
    if cfg.get("max_per_10s"):   # 10초당 2.3개(측정값 4.5개에서 줄임)
        body_dur = max(1.0, dur - float((timeline.get("hook") or {}).get("end", 0.0)))
        mx = min(mx, max(1, int(round(body_dur / 10.0 * float(cfg["max_per_10s"])))))
    if len(body) > mx:
        body = sorted(body, key=lambda r: (-PRIORITY.get(_base(r[0]), 0), r[2]))[:mx]
    accepted = sorted(fixed + body, key=lambda r: r[2])

    events = []
    missing = set()
    for why, typ, t, db in accepted:
        base = _base(why)
        role = why.replace(":", "_") if base == "hook" else why     # 'hook_open' 등: 그 자리용 파일을 먼저
        it = ch.get(typ, ending_len if base == "ending" else None, role=role)
        asked = typ
        if it is None and (cfg.get("type_fallback") or {}).get(typ):
            typ = cfg["type_fallback"][typ]
            it = ch.get(typ, None, role=role)
        if it is None:          # 대신할 종류로 채웠으면 '없는 종류'로 알리지 않는다
            missing.add(asked)
            continue
        # 훅·끝 효과음은 자기 db 가 우선(자리별로 잰 값), 나머지는 종류별 types_db 가 우선
        use_db = db if base in ("hook", "ending") else tdb.get(typ, db)
        ev = {"file": it["file"], "t": round(t, 3), "db": round(float(use_db), 2), "type": typ,
              "why": base, "id": it["id"]}
        if base == "hook":
            ev["slot"] = why.split(":", 1)[1] if ":" in why else "single"
        if base == "ending" and ending_len:
            ev["len_s"] = ending_len
        events.append(ev)
    if missing:
        notes.append("라이브러리에 없는 효과음 종류: " + ", ".join(sorted(missing)))
    return {"events": events, "notes": notes}
