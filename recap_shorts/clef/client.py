"""Cloudflare Clef-omni (Workers AI) 클라이언트: 정해진 질문을 넣으면 답마다 확률이 돌아온다.

요청·응답 형식은 실제로 불러 확인한 그대로다(설정 객체 대신 앱 설정 파일,
그림 줄이기, 뉴런 집계 추가).

키: recap_shorts.settings(환경변수 RECAP_CF_ACCOUNT_ID / RECAP_CF_API_TOKEN → config/settings.local.json 의
cf_account_id / cf_api_token). 없으면 Clef 를 쓰는 점검만 건너뛴다. 키 값은 어디에도 출력·저장하지 않는다.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
MODELS = ("clef", "clef-flash", "clef-omni")
MEDIA_MODELS = {"audio": ("clef-omni",), "videos": ("clef-omni",)}
MAX_QUESTIONS = 64
MAX_OPTIONS, MAX_LEVELS = 255, 10
MAX_IMAGES, MAX_IMAGE_BYTES = 4, 4 * 2 ** 20
MAX_AUDIO, MAX_AUDIO_BYTES = 4, 8 * 2 ** 20
MAX_VIDEOS, MAX_VIDEO_BYTES = 2, 16 * 2 ** 20
MAX_MEDIA_BYTES = 16 * 2 ** 20
RETRY_STATUS = (429, 500, 502, 503, 504)
NO_RETRY_CODES = (3036, 4006)    # 하루 무료 한도 소진(3036, 4006 "used up your daily free allocation"): 다시 물어도 소용없음
RETRY_AFTER = 2.0
DEFAULT_MODEL = "clef-omni"
DEFAULT_TIMEOUT = 40.0
NEURONS_PER_TOKEN = 13636 / 1_000_000      # 입력 100만 토큰 = 13,636뉴런
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4", ".webm": "video/webm"}
MEDIA_TYPES = {"audio": ("audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3"), "video": ("video/mp4", "video/webm")}
_ID = re.compile(r"[A-Za-z0-9_.-]{1,100}")
EPS = 1e-6
IMAGE_MAX_SIDE = 640        # 보내기 전에 긴 변을 이 크기로 줄인다(비용 절약, 판단에는 충분)


class ClefError(RuntimeError):
    """질문을 넣지 못했거나 답을 읽지 못함; str(e) 는 로그용."""


class DailyLimitError(ClefError):
    """하루 무료 한도 소진(3036·4006). 다시 묻지 않는다."""


@dataclass(frozen=True)
class Answer:
    """kind "noul": value = 예 확률. "choice": value = 가장 유력한 옵션 id, probabilities = 옵션별 확률.
    "score": value = 확률 가중 단계(0 = 첫 단계), probabilities = 단계 index 별 확률."""
    kind: str
    value: float | str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


# --------------------------------------------------------------------------- 사용량(뉴런) 집계
class Meter:
    """이 프로세스에서 쓴 토큰·뉴런. 예산(budget, 뉴런)을 넘기면 ClefError 로 막는다."""

    def __init__(self) -> None:
        self.tokens = 0
        self.calls = 0
        self.budget: float | None = None
        self._lock = threading.Lock()

    @property
    def neurons(self) -> float:
        return self.tokens * NEURONS_PER_TOKEN

    def add(self, tokens: int | None) -> None:
        with self._lock:
            self.calls += 1
            self.tokens += int(tokens or 0)

    def check(self) -> None:
        if self.budget is not None and self.neurons >= self.budget:
            raise ClefError(f"뉴런 예산 {self.budget:g} 소진 ({self.neurons:.0f})")

    def reset(self) -> None:
        with self._lock:
            self.tokens = self.calls = 0


METER = Meter()


# --------------------------------------------------------------------------- 질문 만들기
def yes_no(instructions: str, yes: str | None = None, no: str | None = None) -> dict:
    q: dict = {"type": "noul", "instructions": instructions}
    if yes or no:
        q["criteria"] = {k: v for k, v in (("true", yes), ("false", no)) if v}
    return q


def choice(instructions: str, options: dict[str, str]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score(instructions: str, levels: list[str]) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# --------------------------------------------------------------------------- 키
def credentials() -> tuple[str, str]:
    """(계정 ID, 토큰). 환경변수 → 설정 파일, 없는 칸은 ""."""
    from recap_shorts import settings
    return settings.get_key("cf_account_id"), settings.get_key("cf_api_token")


def configured() -> bool:
    acc, tok = credentials()
    return bool(acc and tok)


# --------------------------------------------------------------------------- 파일 → data URL
def shrink_image(raw: bytes, max_side: int = IMAGE_MAX_SIDE) -> tuple[bytes, str]:
    """긴 변을 max_side 로 줄여 JPEG 로(투명은 흰 바탕). 열 수 없으면 원본 그대로."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return raw, ""


def _data_url(item, kind: str, limit: int, sizes: list[int] | None = None, shrink: bool = True) -> str:
    if isinstance(item, (str, Path)):
        p = Path(item)
        try:
            raw = p.read_bytes()
        except OSError as e:
            raise ClefError(f"the {kind} file cannot be read ({type(e).__name__}): {p.name}") from None
        mime = TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or ""
    else:
        try:
            raw, mime = item
        except (TypeError, ValueError):
            raise ClefError(f"a {kind} is a file path or (bytes, mime type), not {type(item).__name__}") from None
        mime = mime if isinstance(mime, str) else ""
        if not isinstance(raw, (bytes, bytearray)):
            raise ClefError(f"a {kind} is a file path or (bytes, mime type), not {type(raw).__name__}")
        raw = bytes(raw)
    if kind == "image" and mime not in IMAGE_TYPES:
        raise ClefError(f"an image must be PNG, JPEG or WebP, not {mime or 'unknown'}")
    if kind != "image" and mime not in MEDIA_TYPES[kind]:
        raise ClefError(f"{'sound must be WAV or MPEG' if kind == 'audio' else 'a video must be MP4 or WEBM'}, not {mime or 'unknown'}")
    if kind == "image" and shrink:
        raw2, mime2 = shrink_image(raw)
        if mime2:
            raw, mime = raw2, mime2
    if len(raw) > limit:
        raise ClefError(f"{kind} of {len(raw)} bytes is over the service's limit of {limit}")
    if sizes is not None:
        sizes.append(len(raw))
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _check(questions: dict) -> None:
    if not isinstance(questions, dict) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ClefError(f"1 to {MAX_QUESTIONS} questions, not {len(questions) if isinstance(questions, dict) else type(questions).__name__}")
    for qid, q in questions.items():
        if not isinstance(qid, str) or not _ID.fullmatch(qid):
            raise ClefError(f"question id {qid!r}: a text of letters, digits, '_', '.', '-' only")
        if not isinstance(q, dict):
            raise ClefError(f"question {qid!r}: made with yes_no / choice / score, not {type(q).__name__}")
        kind, crit = q.get("type"), q.get("criteria")
        if kind not in ("noul", "choice", "score") or not q.get("instructions"):
            raise ClefError(f"question {qid!r}: a type (noul / choice / score) and instructions are needed")
        if kind == "choice" and not (isinstance(crit, dict) and 2 <= len(crit) <= MAX_OPTIONS):
            raise ClefError(f"question {qid!r}: a choice takes 2 to {MAX_OPTIONS} options")
        if kind == "score" and not (isinstance(crit, list) and 2 <= len(crit) <= MAX_LEVELS):
            raise ClefError(f"question {qid!r}: a score takes 2 to {MAX_LEVELS} levels")


def _answer(qid: str, asked: dict, got) -> Answer:
    if not isinstance(got, dict) or got.get("type") != asked["type"]:
        raise ClefError(f"answer to {qid!r} is not a {asked['type']} answer: {str(got)[:120]}")
    kind = asked["type"]

    def number(v, lo: float = 0.0, hi: float = 1.0) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo - EPS <= v <= hi + EPS:
            raise ValueError(f"{v!r} is not a number from {lo:g} to {hi:g}")
        return min(hi, max(lo, float(v)))

    try:
        if kind == "noul":
            return Answer("noul", number(got["noul"]))
        raw = got.get("probabilities")
        if raw is not None and not isinstance(raw, dict):
            raise ValueError(f"probabilities are {type(raw).__name__}, not an object")
        probs = {str(k): number(v) for k, v in (raw or {}).items()}
        conf = number(got["confidence"]) if got.get("confidence") is not None else None
        if kind == "choice":
            picked = got["choice"]
            if isinstance(picked, int) and not isinstance(picked, bool):
                picked = str(picked)
            if not isinstance(picked, str) or picked not in asked["criteria"]:
                raise ValueError(f"unknown option {picked!r}")
            return Answer("choice", picked, probs, conf)
        return Answer("score", number(got["score"], 0.0, len(asked["criteria"]) - 1.0), probs, conf)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ClefError(f"answer to {qid!r} cannot be read ({type(e).__name__}: {e}): {str(got)[:120]}") from None


def ask(questions: dict, *, state: str = "", images=(), audio=(), videos=(), model: str | None = None,
        timeout: float | None = None, client: httpx.Client | None = None, usage: dict | None = None,
        shrink: bool = True) -> dict[str, Answer]:
    """질문을 넣고 {질문 id: Answer} 를 돌려준다. 실패하면 ClefError(하루 한도는 DailyLimitError).
    images/audio/videos: 파일 경로 또는 (bytes, mime). images 는 기본으로 긴 변 640px JPEG 로 줄여 보낸다.
    usage: 호출 비용("input_tokens", "neurons", "attempts")을 받을 dict. 전체 합계는 METER."""
    account, token = credentials()
    if not (account and token):
        raise ClefError("Cloudflare 키가 없습니다 — 화면 오른쪽 위 '설정'에 계정 ID 와 API 토큰을 넣으세요")
    images, audio, videos = list(images), list(audio), list(videos)
    model = (model or DEFAULT_MODEL).strip()
    if model not in MODELS:
        raise ClefError(f"unknown model {model!r} (known: {', '.join(MODELS)})")
    for kind, items, most in (("audio", audio, MAX_AUDIO), ("videos", videos, MAX_VIDEOS)):
        if items and model not in MEDIA_MODELS[kind]:
            raise ClefError(f"{kind} needs the model {MEDIA_MODELS[kind][0]}, not {model}")
        if len(items) > most:
            raise ClefError(f"at most {most} {kind}")
    if len(images) > MAX_IMAGES:
        raise ClefError(f"at most {MAX_IMAGES} images")
    _check(questions)
    body: dict = {"model": model, "state": state or "-", "questions": questions}
    if images:
        body["images"] = [_data_url(x, "image", MAX_IMAGE_BYTES, shrink=shrink) for x in images]
    sizes: list[int] = []
    if audio:
        body["audio"] = [_data_url(x, "audio", MAX_AUDIO_BYTES, sizes) for x in audio]
    if videos:
        body["videos"] = [_data_url(x, "video", MAX_VIDEO_BYTES, sizes) for x in videos]
    if sum(sizes) > MAX_MEDIA_BYTES:
        raise ClefError(f"sound and video of {sum(sizes)} bytes together are over the service's limit of {MAX_MEDIA_BYTES}")
    METER.check()
    url = URL.format(account=account, model=model)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    attempt = 0
    for attempt in (1, 2):
        try:
            r = (client or httpx).post(url, json=body, headers=headers, timeout=timeout or DEFAULT_TIMEOUT)
        except httpx.HTTPError as e:
            raise ClefError(f"no answer from Cloudflare after {time.monotonic() - t0:.1f}s ({type(e).__name__})") from None
        text = r.text.replace(token, "<token>")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        codes = [e.get("code") for e in (data.get("errors") or []) if isinstance(e, dict)] if isinstance(data, dict) and isinstance(data.get("errors"), list) else []
        if attempt == 1 and r.status_code in RETRY_STATUS and not any(c in NO_RETRY_CODES for c in codes):
            time.sleep(RETRY_AFTER)
            continue
        break
    if usage is not None:
        usage["attempts"] = attempt
    if r.status_code != 200 or not isinstance(data, dict) or data.get("success") is False:
        errs = (data or {}).get("errors") if isinstance(data, dict) else None
        why = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errs if isinstance(e, dict)) if isinstance(errs, list) and errs else text[:200]
        exc = DailyLimitError if any(c in NO_RETRY_CODES for c in codes) else ClefError
        raise exc(f"Cloudflare answered HTTP {r.status_code}: {why}")
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    answers = result.get("answers")
    if not isinstance(answers, dict):
        raise ClefError(f"no answers in the reply: {str(data)[:200]}")
    missing = [q for q in questions if q not in answers]
    if missing:
        raise ClefError(f"no answer for {', '.join(missing[:5])}")
    spent = result["usage"].get("input_tokens") if isinstance(result.get("usage"), dict) else None
    from recap_shorts import usage as _usage
    _usage.log("clef", model=model, input_tokens=spent if isinstance(spent, int) else None,
               neurons=round(spent * NEURONS_PER_TOKEN, 2) if isinstance(spent, int) else None,
               images=len(images), audio=len(audio), videos=len(videos), questions=len(questions))
    if isinstance(spent, int) and not isinstance(spent, bool):
        METER.add(spent)
        if usage is not None:
            usage["input_tokens"] = spent
            usage["neurons"] = round(spent * NEURONS_PER_TOKEN, 2)
    else:
        METER.add(0)
    return {qid: _answer(qid, q, answers[qid]) for qid, q in questions.items()}
