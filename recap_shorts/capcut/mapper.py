"""썰쇼츠 timeline.json -> CapCut 초안의 트랙·머티리얼.

렌더(recap_shorts/render)와 같은 화면이 나오게, 렌더가 쓰는 계산(띠 위치·글자 크기·줄바꿈·확대·소리 크기)을 그대로 불러 쓴다.
- 그림: 컷마다 사진 세그먼트 하나. 렌더처럼 4:3 으로 미리 잘라 넣고(cover_box + focus), 확대(zoom_in)는 배율 키프레임.
- 인트로 카드(0 ~ t_cut): 움직임이 많아 그 구간만 짧은 영상(그림 상자 크기)으로 만들어 넣는다.
- 제목 두 줄·자막: 고칠 수 있는 글자. 자막 줄바꿈은 렌더와 같은 곳에서, 강조 낱말은 같은 색.
- 짤(스티커): 테두리·그림자를 입힌 PNG 를 같은 자리·크기에, 튀어나옴·사라짐은 배율·투명도 키프레임.
- 그림 상자 밖 가림: 확대·짤이 제목·자막 띠로 넘치지 않게 검은 판(상자 자리만 뚫림)을 그림 위에 얹는다.
- 소리: 목소리는 렌더처럼 크기(LUFS)를 맞춘 사본, 효과음은 렌더의 크기(dB)·자르기를 입힌 사본이라 CapCut 볼륨은 모두 100%.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from recap_shorts.render import audio as RA
from recap_shorts.render import captions as cap
from recap_shorts.render import compose as C
from recap_shorts.render import intro as INTRO
from recap_shorts.render import layout as L
from recap_shorts.render import overlays as OV

from . import draft_format as F
from .media import MediaManager

EMPHASIS_HEX = "#{:02X}{:02X}{:02X}".format(*L.EMPHASIS_COLOR)
TITLE_HEX = ["#{:02X}{:02X}{:02X}".format(*L.TITLE_COLOR_1), "#{:02X}{:02X}{:02X}".format(*L.TITLE_COLOR_2)]
MAX_SHOT_PX = 2160          # 잘라 낸 그림의 가로 상한(상자 1080 의 2배 — 확대해도 흐리지 않을 만큼)


@dataclass
class ReportLine:
    element: str
    count: int
    mode: str               # native(그대로) | approx(비슷하게) | skipped(넣지 않음)
    note: str


@dataclass
class MappedDraft:
    tracks: list[dict]
    materials: dict
    duration_us: int
    report: list[ReportLine] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class _Lanes:
    """겹치는 세그먼트는 아래 트랙으로(CapCut 은 한 트랙 안 겹침을 허용하지 않음)."""

    def __init__(self):
        self.lanes: list[list[dict]] = []
        self._ends: list[int] = []

    def put(self, seg: dict) -> None:
        st = seg["target_timerange"]["start"]
        for i, end in enumerate(self._ends):
            if st >= end:
                self.lanes[i].append(seg)
                self._ends[i] = st + seg["target_timerange"]["duration"]
                return
        self.lanes.append([seg])
        self._ends.append(st + seg["target_timerange"]["duration"])


def _tx(cx_px: float) -> float:          # 화면 px -> 반 화면 단위(오른쪽 +)
    return (cx_px - L.W / 2) / (L.W / 2)


def _ty(cy_px: float) -> float:          # 화면 px -> 반 화면 단위(위쪽 +)
    return (L.H / 2 - cy_px) / (L.H / 2)


def _fit_scale(w: int, h: int, target_w: float) -> float:
    """CapCut 기본 배치(화면 안에 맞춤) 대비 배율 — 화면에서 가로 target_w px 가 되게."""
    fit = min(L.W / max(1, w), L.H / max(1, h))
    return target_w / (max(1, w) * fit)


def _runs(mask: list[bool], color: str) -> list[tuple[int, int, str]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j, color))
            i = j
        else:
            i += 1
    return out


def caption_layout(text: str, emphasis: str | None) -> tuple[int, str, list[tuple[int, int, str]]]:
    """렌더(make_caption_overlay)와 같은 (글자 px, 줄바꿈한 글, 강조 구간). 줄바꿈 자리는 공백 한 칸과 같은 길이라 강조 위치가 그대로 맞는다."""
    words = text.split()
    norm = " ".join(words)
    fit = cap.fit_text(norm) or cap.fit_text(norm, max_lines=3)
    if fit is None:
        size = L.CAPTION_SIZE_MIN
        k = max(1, len(words) // 2) if len(words) > 1 else len(words)
        lines = [" ".join(words[:k])] + ([" ".join(words[k:])] if words[k:] else [])
    else:
        size, lines, _ = fit
    out = "\n".join(lines)
    return size, out, _runs(cap.emphasis_mask(norm, emphasis), EMPHASIS_HEX)


def title_layout(title_lines) -> tuple[int, list[tuple[str, float, str]]]:
    """렌더(make_fixed_layer)와 같은 (글자 px, [(줄, 가운데 y px, 색)])."""
    lines = list(title_lines or [])[:2]
    while len(lines) < 2:
        lines.append("")
    sizes = [C._fit_size(t, L.TEXT_MAX_W, L.TITLE_SIZE_MAX, L.TITLE_SIZE_MIN, title=True) for t in lines if t]
    size = min(sizes) if sizes else L.TITLE_SIZE_MAX
    line_h = int(size * 1.3)
    cy = (L.TITLE_Y0 + L.TITLE_Y1) / 2
    return size, [(t, y, c) for t, y, c in zip(lines, (cy - line_h / 2, cy + line_h / 2), TITLE_HEX) if t]


def caption_blackout(tl: dict, intro_cut: float) -> float:
    """이 시각 전에는 자막을 그리지 않는다(렌더: 훅 띠가 보이는 동안·인트로 카드 동안 자막 없음)."""
    hook = tl.get("hook") or {}
    end = intro_cut
    if hook.get("text") and float(hook.get("start", 0)) <= 1e-6:
        end = max(end, float(hook.get("end", 0)))
    return end


class Mapper:
    def __init__(self, tl: dict, base_dir: Path, media: MediaManager, workdir: Path, *, px_per_size: float = 5.5,
                 bgm_mode: str | None = None):
        if list(tl.get("size", [L.W, L.H])) != [L.W, L.H]:
            raise ValueError(f"size 는 [1080, 1920] 만 지원합니다: {tl.get('size')}")
        self.tl = tl
        self.base = Path(base_dir)
        self.mm = media
        self.work = Path(workdir)
        self.k = max(0.5, float(px_per_size))
        self.fps = int(tl.get("fps", L.FPS))
        self.T = F.us(float(tl["duration"]))
        self.bgm_mode = RA.configured_bgm_mode() if bgm_mode is None else RA.normalize_bgm_mode(bgm_mode)
        self.materials = F.empty_materials()
        self.report: list[ReportLine] = []
        self._vmat: dict[str, dict] = {}
        self._amat: dict[str, dict] = {}
        self.comp = C.Composer(tl, str(self.base))        # 렌더와 같은 정렬·자막 컷 맞춤·짤 상자를 그대로 쓴다
        ic = tl.get("intro") or None
        self.intro = INTRO.IntroCard(ic) if ic and ic.get("style", "card") == "card" else None
        self.t_cut = self.intro.t_cut if self.intro else 0.0

    # ------------------------------------------------------------ 도구
    def _res(self, f: str) -> Path:
        p = Path(f)
        if p.is_absolute():
            return p
        q = self.base / f
        return q if q.exists() else p

    def _video_mat(self, path: Path, kind: str, name: str) -> tuple[dict, object]:
        item = self.mm.add(path, "image" if kind == "photo" else "video", name=name, copy=True)
        if item.id not in self._vmat:
            mat = F.video_material(item.id, item.json_path, kind=kind, duration_us=item.duration_us,
                                   width=item.width, height=item.height, name=name)
            self.materials["videos"].append(mat)
            self._vmat[item.id] = mat
        return self._vmat[item.id], item

    def _audio_mat(self, path: Path, name: str) -> tuple[dict, object]:
        item = self.mm.add(path, "audio", name=name, copy=True)
        if item.id not in self._amat:
            mat = F.audio_material(item.id, item.json_path, duration_us=item.duration_us, name=name)
            self.materials["audios"].append(mat)
            self._amat[item.id] = mat
        return self._amat[item.id], item

    def _photo_seg(self, png: Path, name: str, st: int, du: int, *, target_w: float, cx: float, cy: float,
                   kfs: list[dict] | None = None, scale_mul: float = 1.0) -> dict:
        mat, item = self._video_mat(png, "photo", name)
        s = _fit_scale(item.width, item.height, target_w) * scale_mul
        return F.segment(mat["id"], F.timerange(st, du), source=F.timerange(0, du),
                         clip=F.clip_settings(scale=s, tx=_tx(cx), ty=_ty(cy)), common_keyframes=kfs or [])

    def _ffmpeg(self, args: list[str], what: str) -> None:
        r = subprocess.run([RA.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"{what} 실패: {r.stderr[-600:]}")

    # ------------------------------------------------------------ 그림
    def _intro_video(self) -> Path:
        out = self.work / "intro_card.mp4"
        n = max(1, int(round(self.t_cut * self.fps)))
        cmd = [RA.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{L.IMAGE_W}x{L.IMAGE_H}", "-r", str(self.fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
               "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(self.fps), str(out)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for i in range(n):
                p.stdin.write(self.intro.frame(i / self.fps).convert("RGB").tobytes())
            p.stdin.close()
        except BrokenPipeError:
            pass
        err = p.stderr.read().decode("utf-8", "replace")
        if p.wait() != 0:
            raise RuntimeError("인트로 카드 영상 만들기 실패: " + err[-600:])
        return out

    def _shot_png(self, idx: int, shot: dict) -> Path:
        out = self.work / f"shot_{idx + 1:02d}_{Path(shot['file']).stem[:40]}.png"
        if shot.get("kind") == "meme":
            self.comp._meme_box(idx, 1.0).save(out)
            return out
        src = Image.open(self._res(shot["file"])).convert("RGB")
        crop = src.crop(C.cover_box(src.width, src.height, shot.get("focus") or (0.5, 0.5)))
        if crop.width > MAX_SHOT_PX:
            crop = crop.resize((MAX_SHOT_PX, int(round(MAX_SHOT_PX / L.IMAGE_RATIO))), Image.LANCZOS)
        crop.save(out)
        return out

    def _map_pictures(self) -> list[dict]:
        segs: list[dict] = []
        box_cy = (L.IMAGE_Y0 + L.IMAGE_Y1) / 2
        pos = 0
        n_zoom = n_enter = n_meme = 0
        if self.intro is not None and self.t_cut > 0:
            mp4 = self._intro_video()
            mat, item = self._video_mat(mp4, "video", "인트로 카드")
            du = min(F.us(self.t_cut), item.duration_us or F.us(self.t_cut))
            sp = F.speed_material(1.0)
            self.materials["speeds"].append(sp)
            segs.append(F.segment(mat["id"], F.timerange(0, du), source=F.timerange(0, du), volume=0.0, extra_refs=[sp["id"]],
                                  clip=F.clip_settings(scale=_fit_scale(item.width, item.height, L.IMAGE_W),
                                                       tx=0.0, ty=_ty(box_cy))))
            pos = du
            self.report.append(ReportLine("인트로 카드", 1, "approx", "글 머리 카드의 움직임을 그대로 담은 짧은 영상(글자는 고칠 수 없음)"))
        shots = self.comp.shots
        for i, shot in enumerate(shots):
            end = self.T if i == len(shots) - 1 else F.us(shots[i + 1]["start"])
            if end - pos < F.US // self.fps:      # 인트로 뒤에 가려진 컷
                continue
            png = self._shot_png(i, shot)
            du = end - pos
            kfs: list[dict] = []
            base = _fit_scale(*Image.open(png).size, L.IMAGE_W)
            motion = shot.get("motion", "static")
            if shot.get("kind") == "meme":
                n_meme += 1
            elif motion == "zoom_in":
                # 렌더: 컷 시작부터 끝까지 1.0 -> 1.08. 인트로에 앞부분이 가려졌으면 그 시각의 배율부터
                z0 = C.zoom_scale(pos / F.US, shot["start"], shot["end"])
                kfs.append(F.keyframes("KFTypeScaleX", [(0, base * z0), (max(0, du - 1), base * C.ZOOM_END)]))
                n_zoom += 1
            elif motion == "enter":
                rise = min(du - 1, F.us(C.ENTER_SEC))
                kfs.append(F.keyframes("KFTypePositionY", [(0, _ty(box_cy + C.ENTER_RISE)), (rise, _ty(box_cy))]))
                n_enter += 1
            name = f"{i + 1:02d} {Path(shot['file']).stem}"
            segs.append(self._photo_seg(png, name, pos, du, target_w=L.IMAGE_W, cx=L.W / 2, cy=box_cy, kfs=kfs))
            pos = end
        self.report.append(ReportLine("그림 컷", len(segs) - (1 if self.intro else 0), "native",
                                      "컷마다 사진 하나(렌더처럼 4:3 으로 잘라 둠, 바꿔 끼우기 가능)"))
        if n_zoom:
            self.report.append(ReportLine("확대(zoom_in)", n_zoom, "native", "배율 키프레임 1.0 -> 1.08"))
        if n_enter:
            self.report.append(ReportLine("등장(enter)", n_enter, "approx", "0.2초 올라오기만(흐림·겹침은 없음)"))
        if n_meme:
            self.report.append(ReportLine("짤 컷", n_meme, "approx", "배경 위 짤을 한 장으로, 튀어나오는 효과는 없음"))
        return segs

    def _map_hook(self) -> list[dict]:
        hook = self.tl.get("hook") or {}
        if not hook.get("text"):
            return []
        st, en = max(F.us(hook.get("start", 0)), F.us(self.t_cut)), min(self.T, F.us(hook.get("end", 0)))
        if en - st < F.US // self.fps:            # 인트로 카드에 가려져 안 보이는 훅 띠
            return []
        png = self.work / "hook_band.png"
        C.make_hook_overlay(hook["text"]).save(png)
        self.report.append(ReportLine("훅 띠", 1, "approx", "흰 둥근 띠 + 글씨를 그림 한 장으로"))
        return [self._photo_seg(png, "훅 띠", st, en - st, target_w=L.IMAGE_W, cx=L.W / 2, cy=(L.IMAGE_Y0 + L.IMAGE_Y1) / 2)]

    def _sticker_kfs(self, ov: dict, base: float, cy: float, du: int) -> tuple[list[dict], bool]:
        anim = ov.get("anim", "pop")
        if anim == "none":
            return [], False
        pop_s, fade_s = float(OV._p(ov, "pop_s")), float(OV._p(ov, "fade_s"))
        kfs, approx = [], anim == "shake"
        if anim in ("pop", "shake"):
            pts = [(F.us(pop_s * f), base * max(0.02, OV.pop_scale(pop_s * f, pop_s, float(OV._p(ov, "overshoot")))))
                   for f in (0.0, 0.25, 0.5, 0.65, 0.82, 1.0)]
            kfs.append(F.keyframes("KFTypeScaleX", [(min(t, du - 1), v) for t, v in pts]))
        elif anim == "slide_up":
            dy = OV.SLIDE_FRAC * L.IMAGE_H
            kfs.append(F.keyframes("KFTypePositionY", [(0, _ty(cy + dy)), (min(du - 1, F.us(pop_s * 0.35)), _ty(cy + dy * 0.27)),
                                                       (min(du - 1, F.us(pop_s)), _ty(cy))]))
        a_in = F.us(pop_s * (0.4 if anim in ("pop", "shake") else 0.5))
        alpha = [(0, 0.0), (min(du - 1, a_in), 1.0)]
        if fade_s > 1e-6 and du - F.us(fade_s) > a_in:
            alpha += [(du - F.us(fade_s), 1.0), (du - 1, 0.0)]
        kfs.append(F.keyframes("KFTypeAlpha", alpha))
        return kfs, approx

    def _map_stickers(self) -> list[dict]:
        cache = OV.StickerCache(str(self.base))
        segs, n_shake = [], 0
        for n, ov in enumerate(self.comp.overlays):
            st, en = F.us(ov["start"]), min(self.T, F.us(ov["end"]))
            if en - st < F.US // self.fps:
                continue
            styled, _rw, _rh = cache.base(ov)
            png = self.work / f"sticker_{n + 1:02d}_{Path(ov['file']).stem[:40]}.png"
            styled.save(png)
            full_w, full_h = styled.width / OV.PRE, styled.height / OV.PRE
            x0, y0 = OV.anchor_xy(ov.get("anchor", "box_br"), full_w, full_h, float(OV._p(ov, "margin_px")))
            cx, cy = x0 + full_w / 2, L.IMAGE_Y0 + y0 + full_h / 2
            base = _fit_scale(styled.width, styled.height, full_w)
            kfs, approx = self._sticker_kfs(ov, base, cy, en - st)
            n_shake += approx
            segs.append(self._photo_seg(png, f"짤 {ov.get('meme_id') or Path(ov['file']).stem}", st, en - st,
                                        target_w=full_w, cx=cx, cy=cy, kfs=kfs))
        if segs:
            self.report.append(ReportLine("짤(스티커)", len(segs), "native", "같은 자리·크기, 튀어나옴·사라짐은 배율·투명도 키프레임"))
        if n_shake:
            self.report.append(ReportLine("짤 흔들림", n_shake, "approx", "흔들림은 넣지 않음(튀어나옴만)"))
        return segs

    def _mask_seg(self) -> dict:
        png = self.work / "outside_box_mask.png"
        im = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 255))
        im.paste((0, 0, 0, 0), (0, L.IMAGE_Y0, L.W, L.IMAGE_Y1))
        im.save(png)
        self.report.append(ReportLine("그림 상자 밖 가림", 1, "native", "확대·짤이 제목·자막 띠로 넘치지 않게 상자 자리만 뚫린 검은 판"))
        return self._photo_seg(png, "그림 상자 밖 가림", 0, self.T, target_w=L.W, cx=L.W / 2, cy=L.H / 2)

    # ------------------------------------------------------------ 글자
    def _text(self, text: str, *, st: int, en: int, cy: float, px: int, color: str, font: Path, font_name: str,
              stroke_px: float = 0.0, runs: list | None = None) -> dict:
        stroke = None
        if stroke_px > 0:
            ui = max(0.0, min(100.0, stroke_px / max(1.0, px) * 400.0))   # CapCut 화면 값 0~100
            stroke = ("#000000", ui / 100.0 * 0.2)                         # 초안 값 0~0.2
        mat = F.text_material(text, size=px / self.k, color=color, font_path=self.mm.add(font, "font").json_path,
                              font_name=font_name, stroke=stroke, max_line_width=1.0, color_runs=runs or None)
        self.materials["texts"].append(mat)
        return F.segment(mat["id"], F.timerange(st, max(1, en - st)), clip=F.clip_settings(tx=0.0, ty=_ty(cy)))

    def _map_texts(self) -> list[tuple[str, list[dict]]]:
        groups: list[tuple[str, list[dict]]] = []
        size, lines = title_layout(self.tl.get("title_lines"))
        tfont = Path(L.find_font(title=True))
        for j, (t, y, color) in enumerate(lines):
            groups.append((f"제목 {j + 1}줄", [self._text(t, st=0, en=self.T, cy=y, px=size, color=color, font=tfont,
                                                        font_name=_font_name(tfont))]))
        if lines:
            self.report.append(ReportLine("제목", len(lines), "native", "줄마다 고칠 수 있는 글자(렌더와 같은 글꼴·크기·색)"))
        cfont = Path(L.find_font())
        blackout = F.us(caption_blackout(self.tl, self.t_cut))
        cy = (L.CAPTION_Y0 + L.CAPTION_Y1) / 2
        segs, n_emph = [], 0
        for c in self.comp.caps:                  # 렌더처럼 컷에 맞춘 자막
            st, en = max(F.us(c["start"]), blackout), min(self.T, F.us(c["end"]))
            if en - st < F.US // self.fps:
                continue
            px, text, runs = caption_layout(c["text"], c.get("emphasis"))
            n_emph += bool(runs)
            segs.append(self._text(text, st=st, en=en, cy=cy, px=px, color="#FFFFFF", font=cfont, font_name=_font_name(cfont),
                                   stroke_px=L.CAPTION_STROKE, runs=runs))
        if segs:
            groups.insert(0, ("자막", segs))
            self.report.append(ReportLine("자막", len(segs), "native",
                                          f"카드마다 고칠 수 있는 글자, 줄바꿈은 렌더와 같은 곳, 강조 낱말 색 {n_emph}곳"))
        return groups

    # ------------------------------------------------------------ 소리
    def _audio_seg(self, path: Path, name: str, st: int) -> dict | None:
        mat, item = self._audio_mat(path, name)
        du = min(item.duration_us, self.T - st)
        if du < 1000:
            return None
        sp = F.speed_material(1.0)
        self.materials["speeds"].append(sp)
        return F.segment(mat["id"], F.timerange(st, du), source=F.timerange(0, du), extra_refs=[sp["id"]], visual=False)

    def _map_audio(self) -> list[tuple[str, list[list[dict]]]]:
        a = self.tl.get("audio") or {}
        out: list[tuple[str, list[list[dict]]]] = []
        voice = a.get("voice")
        if voice:
            src = self._res(voice)
            wav = self.work / "voice_norm.wav"
            self._ffmpeg(["-i", str(src), "-af", f"{RA.voice_filter(str(src))},aresample=48000", "-ar", "48000",
                          "-c:a", "pcm_s16le", str(wav)], "목소리 크기 맞추기")
            seg = self._audio_seg(wav, "목소리", F.us(float(a.get("voice_offset_s") or 0.0)))
            if seg:
                out.append(("목소리", [[seg]]))
                self.report.append(ReportLine("목소리", 1, "native", f"렌더처럼 {RA.VOICE_LUFS:g} LUFS 로 맞춘 사본"))
        lanes, done = _Lanes(), {}
        for e in a.get("sfx") or []:
            t = float(e.get("t", 0))
            if not e.get("file") or not 0 <= t < self.T / F.US:
                continue
            f = self._res(e["file"])
            g = RA.sfx_gain_db(str(f), float(e.get("db", -12)))
            key = (str(f), round(g, 2), e.get("len_s"))
            if key not in done:
                wav = self.work / f"sfx_{len(done) + 1:02d}_{f.stem[:30]}.wav"
                trim = RA._trim(e)
                self._ffmpeg(["-i", str(f), "-af", f"aresample=48000,{trim}volume={g:.2f}dB", "-ar", "48000",
                              "-c:a", "pcm_s16le", str(wav)], "효과음 크기 맞추기")
                done[key] = wav
            seg = self._audio_seg(done[key], str(e.get("id") or f.stem), F.us(t))
            if seg:
                lanes.put(seg)
        n_sfx = sum(len(x) for x in lanes.lanes)
        if n_sfx:
            out.append(("효과음", lanes.lanes))
            self.report.append(ReportLine("효과음", n_sfx, "native", "렌더와 같은 크기·길이를 입힌 사본(볼륨 100%)"))
        bgm = a.get("bgm")
        if bgm and self.bgm_mode == "bake":
            src = self._res(bgm)
            wav = self.work / "bgm.wav"
            dur = self.T / F.US
            st = max(0.0, dur - RA.FADE_OUT_SEC)
            self._ffmpeg(["-stream_loop", "-1", "-i", str(src), "-af",
                          f"aresample=48000,volume={RA.bgm_gain_db(str(src), float(a.get('bgm_db', -22))):.2f}dB,"
                          f"atrim=0:{dur:.3f},afade=t=out:st={st:.3f}:d={RA.FADE_OUT_SEC}", "-t", f"{dur:.3f}",
                          "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], "배경음악 크기 맞추기")
            seg = self._audio_seg(wav, "배경음악", 0)
            if seg:
                out.append(("배경음악", [[seg]]))
                self.report.append(ReportLine("배경음악", 1, "native", "렌더처럼 크기를 맞추고 끝을 줄인 사본"))
        elif bgm:
            self.report.append(ReportLine("배경음악", 1, "skipped", "영상에 굽지 않는 설정(upload_note) — 올릴 때 넣습니다"))
        if n_sfx or voice:
            self.report.append(ReportLine("마지막 소리 제한(리미터)", 1, "approx", "렌더의 0.95 제한은 넣지 않음"))
        return out

    # ------------------------------------------------------------ 합치기
    def map(self) -> MappedDraft:
        self.work.mkdir(parents=True, exist_ok=True)
        tracks: list[dict] = [F.track("video", "그림", self._map_pictures(), lane=0)]
        lane = 1
        hook = self._map_hook()
        if hook:
            tracks.append(F.track("video", "훅 띠", hook, lane=lane))
            lane += 1
        st_lanes = _Lanes()
        for sg in self._map_stickers():
            st_lanes.put(sg)
        for j, segs in enumerate(st_lanes.lanes):
            tracks.append(F.track("video", "짤" + (f" {j + 1}" if j else ""), segs, lane=lane))
            lane += 1
        tracks.append(F.track("video", "그림 상자 밖 가림", [self._mask_seg()], lane=lane))
        for ti, (label, segs) in enumerate(self._map_texts()):
            tracks.append(F.track("text", label, segs, lane=ti))
        for label, lanes in self._map_audio():
            for j, segs in enumerate(lanes):
                tracks.append(F.track("audio", label + (f" {j + 1}" if j else ""), segs, lane=j))
        stats = {"tracks": len(tracks), "segments": sum(len(t["segments"]) for t in tracks),
                 "by_type": {k: sum(len(t["segments"]) for t in tracks if t["type"] == k) for k in ("video", "text", "audio")},
                 "materials": {k: len(v) for k, v in self.materials.items() if v}}
        return MappedDraft(tracks=tracks, materials=self.materials, duration_us=self.T, report=self.report, stats=stats)


def _font_name(path: Path) -> str:
    return path.stem.replace("-", " ")
