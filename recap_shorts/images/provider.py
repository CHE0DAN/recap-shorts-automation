"""자료 이미지 생성: 로컬 이미지 서버(이 저장소 밖에서 따로 띄우는 프로그램) 또는 Gemini 이미지 — 설정의 image_engine 대로.

로컬 서버: POST http://127.0.0.1:8791/api/image  {"prompt","aspect":"landscape","format":"png"} → 응답 본문 = PNG 바이트.
한 장 33~76초(평균 51초). 서버가 꺼져 있고 Gemini 키도 없으면 available()=False 이고 호출자는 이미지 생성을 건너뛴다.
실패는 예외 대신 {"ok": False, "error": 이유} 로 돌려줘 다른 단계가 계속되게 한다.

image_engine: local = 로컬 서버(한도면 Gemini 대체) / gemini = Gemini 만 / off = 안 만듦 (기본 gemini — settings.py).
"자동"(서버가 켜져 있으면 local, 아니면 gemini)은 쓰지 않는다. 로컬 서버 켜짐 확인 결과는 60초 캐시(local_server_up).
"""
from __future__ import annotations

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE_URL = os.environ.get("RECAP_IMAGE_URL", "http://127.0.0.1:8791")
TIMEOUT = 300.0
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 공통 규칙: 사진처럼 사실적, 4:3 가로, 스톡 사진 티 금지, 실존 인물 닮게 금지, 글자는 설명이 따옴표로 준 짧은 한글만.
# 참고한 쇼츠의 AI 그림은 '문장이 말한 그 장면'을 정면으로 보여 주고(한국 단서 40%, 표정이 읽히는 지어낸 사람 14%,
# 읽히는 한글 8.5%), 분위기·소품 위주 그림보다 내용이 잘 전달됐다.
COMMON_PREFIX = ("Photorealistic camera photograph, horizontal landscape composition, target aspect ratio 4:3 or the "
                 "closest available landscape ratio. ")
COMMON_SUFFIX = (" Candid editorial news-photo look: the real lighting of that place (fluorescent, flash, overcast "
                 "daylight), realistic everyday wear and clutter, not staged stock photography. Avoid stock clichés: no "
                 "sunset or golden-hour glow unless the scene needs it, no decorative potted plants, tea cups or cozy "
                 "living-room filler, no neon glow, no floating icons or speech bubbles, no blank glowing screens. "
                 "Natural photographic lighting and realistic materials, documentary photography, not an illustration "
                 "or render. No real or recognizable people and no likeness of any real person, celebrity, athlete or "
                 "politician; any person shown is a fictional ordinary person, otherwise show the back view or just hands. "
                 "Absolutely no text, letters, numbers, logos, brands, team emblems or watermarks anywhere, except a "
                 "short Korean word only when the description quotes it exactly; all other surfaces are clean and unmarked.")

HINT_INSTRUCTION = """아래는 한국어 쇼츠의 문장별 (내레이션)과 '화면 설명'(image_hint) 목록이다. 각 항목을 사진 이미지 생성용 영어 장면 묘사로 바꿔라.
- 항목마다 1~2문장. **그 문장이 말한 사건을 문자 그대로**: 누가·무엇을·어디서. 주인공 하나가 화면 가운데 60~80%를 채운다.
  분위기·상징으로 바꾸지 말 것(예: '돈 문제' → 지갑 소품 X, 문장의 그 영수증·그 창구 O).
- 장소는 이야기의 실제 나라 그대로. 한국 이야기면 한국 단서 하나를 꼭 넣는다: 한국 아파트·병원 원무과·편의점·지하철·
  관공서·한국 번호판·원화 지폐·한국 강변 등. 서양식 도시 풍경·서양식 거실·서양 병원 금지.
- 뻔한 스톡 사진 금지: 노을·골든아워, 화분, 찻잔, 아늑한 거실, 빈 화면이 빛나는 스마트폰, 네온 빛, 공중에 뜬 말풍선·아이콘,
  '스마트폰을 든 손'(문장에 휴대폰이 실제로 나올 때만).
- 조명은 문장의 분위기에 맞춘다: 사실 전달 = 밝은 낮빛, 위기·손해·충격 = 어둡고 붉은 톤, 반전·결론 = 위에서 내리는 스포트라이트.
- 사람: 놀람·걱정·분노·어색함 같은 감정이 핵심인 문장은 "an ordinary Korean adult (fictional), medium shot, clearly <감정>
  facial expression"처럼 표정이 보이는 지어낸 보통 사람을 써도 된다. 단, 이야기 속 실제 인물(글쓴이·기사 속 사람·연예인·
  선수·정치인)의 대역처럼 보이면 안 된다 — '그 소식을 본 보통 사람'의 반응으로만. 그 밖의 문장은 사람 없이 또는 뒷모습·손.
- 글자: 핵심 낱말이 짧은 한글(6자 이하)이고 도장·손글씨 쪽지·표지판에 자연스럽게 들어갈 수 있으면
  "a rubber stamp that reads '…' in Korean"처럼 따옴표로 정확히 적는다. 그 밖에는 글자가 안 보이는 구도
  (영수증·화면·간판은 비스듬한 각도나 얕은 초점).
- 앞뒤 문장이 같은 사건을 말하면 같은 주인공·같은 장소를 각도만 바꿔 이어 간다("same <대상>, closer / different angle /
  aftermath"). 다른 사건이면 대상과 구도를 겹치지 말 것(클로즈업·중간·넓은 장면을 섞는다).
- 반드시 JSON 객체 하나: {"prompts": ["영어 묘사 1", "영어 묘사 2", ...]} — 입력과 같은 개수·같은 순서.

[목록]
"""


def build_prompt(hint: str) -> str:
    """영어 장면 묘사(hint) 앞뒤에 공통 규칙을 붙인다."""
    return COMMON_PREFIX + hint.strip().rstrip(".") + "." + COMMON_SUFFIX


def hints_to_prompts(hints: list[str], text_fn=None) -> list[str]:
    """한국어 image_hint 들을 영어 장면 묘사로(한 번의 gemini-3.8-flash 호출). 개수가 안 맞으면 예외."""
    if not hints:
        return []
    if text_fn is None:
        from recap_shorts.llm.gemini_api import VISION_MODEL, generate_text

        def text_fn(p):
            return generate_text(p, VISION_MODEL, json=True)
    lines = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(hints))
    out = text_fn(HINT_INSTRUCTION + lines)
    prompts = out.get("prompts") if isinstance(out, dict) else None
    if not isinstance(prompts, list) or len(prompts) != len(hints):
        raise RuntimeError(f"영어 프롬프트 개수가 맞지 않음(요청 {len(hints)}, 응답 {len(prompts) if isinstance(prompts, list) else '없음'})")
    return [str(p).strip() for p in prompts]


def local_url() -> str:
    """로컬 이미지 서버 주소(환경변수 RECAP_IMAGE_URL, 부를 때 읽는다)."""
    return os.environ.get("RECAP_IMAGE_URL", BASE_URL)


def local_available(base_url: str | None = None, timeout: float = 3.0) -> bool:
    """로컬 서버가 응답하는가(캐시 없이 바로 확인)."""
    try:
        r = requests.get((base_url or local_url()) + "/", timeout=timeout)
        return r.status_code < 500
    except requests.RequestException:
        return False


_PROBE = {"at": 0.0, "up": False}       # 로컬 서버 켜짐 확인 60초 캐시(계약서 3절)
_PROBE_TTL = 60.0


def local_server_up() -> bool:
    """로컬 서버 켜짐(60초 캐시) — 설정 화면·상태 점검용. 생성 여부 판단은 available() 가 캐시 없이 한다."""
    now = time.time()
    if now - _PROBE["at"] >= _PROBE_TTL:
        _PROBE["up"], _PROBE["at"] = local_available(), now
    return bool(_PROBE["up"])


def _gemini_key() -> bool:
    from recap_shorts import settings
    return bool(settings.get_key("gemini_api_key"))


def engine() -> str:
    """지금 쓸 엔진: local | gemini | off (설정 그대로)."""
    from recap_shorts import settings
    return settings.image_engine()


def engine_detail() -> str:
    """화면·상태 점검에 쓰는 한 줄 설명."""
    e = engine()
    if e == "off":
        return "AI 그림 꺼짐 — 캡처 카드만"
    return "로컬 이미지 서버로 만듦" if e == "local" else "Gemini 이미지로 만듦"


def available(base_url: str | None = None, timeout: float = 3.0) -> bool:
    """이미지를 만들 수 있는가. base_url 을 주면 예전처럼 로컬 서버만 확인한다(시험·수동 확인용)."""
    if base_url is not None:
        return local_available(base_url, timeout)
    e = engine()
    if e == "off":
        return False
    if e == "local":
        return local_available(timeout=timeout)
    return _gemini_key()


def engine_status() -> tuple[bool, str, str]:
    """(쓸 수 있음, 엔진, 상태 점검 detail)."""
    return available(), engine(), engine_detail()


FALLBACK = os.environ.get("RECAP_IMAGE_FALLBACK", "gemini")   # "gemini" | "" (끔)
_limit_until = [0.0]   # 로컬 서버가 한도에 걸리면 이 시각까지는 바로 대체 엔진으로


def generate(prompt: str, out_png: str | Path, aspect: str = "landscape", *, base_url: str | None = None,
             timeout: float = TIMEOUT) -> dict:
    """image_engine 대로 만든다. local 은 로컬 이미지 서버로 만들고, 그 서버가 사용 한도
    (usage_limit_reached)에 걸리면 Gemini 이미지(Nano Banana 2)로 대신 만든다.
    한도가 차면 한 영상의 AI 이미지가 모두 실패할 수 있다.
    base_url 을 주면 예전처럼 로컬 서버만 쓴다."""
    if base_url is None:
        e = engine()
    else:
        e = "local"
    if e == "off":
        return {"ok": False, "file": str(out_png), "seconds": 0.0,
                "error": "AI 그림을 만들지 않도록 설정되어 있습니다(image_engine=off)"}
    if e == "gemini":
        from recap_shorts.images import gemini_image
        return gemini_image.generate(prompt, out_png, aspect)
    if FALLBACK == "gemini" and time.time() < _limit_until[0]:
        from recap_shorts.images import gemini_image
        return gemini_image.generate(prompt, out_png, aspect)
    res = generate_local(prompt, out_png, aspect, base_url=base_url, timeout=timeout)
    if not res["ok"] and FALLBACK == "gemini" and "usage_limit" in (res.get("error") or ""):
        _limit_until[0] = time.time() + 1800
        from recap_shorts.images import gemini_image
        alt = gemini_image.generate(prompt, out_png, aspect)
        alt["fallback_from"] = res.get("error", "")[:160]
        return alt
    return res


def generate_local(prompt: str, out_png: str | Path, aspect: str = "landscape", *, base_url: str | None = None,
                   timeout: float = TIMEOUT) -> dict:
    """prompt(공통 규칙이 이미 붙은 완성 프롬프트) → out_png. {"ok","file","seconds","error","size"}"""
    out = Path(out_png)
    t0 = time.time()
    res: dict = {"ok": False, "file": str(out), "seconds": 0.0, "error": None}
    try:
        r = requests.post((base_url or local_url()) + "/api/image", json={"prompt": prompt, "aspect": aspect, "format": "png"},
                          timeout=timeout)
    except requests.RequestException as e:
        res.update(error=f"이미지 서버 연결 실패({type(e).__name__})", seconds=round(time.time() - t0, 1))
        return res
    res["seconds"] = round(time.time() - t0, 1)
    if r.status_code != 200:
        res["error"] = f"이미지 서버 HTTP {r.status_code}: {r.text[:200]}"
        return res
    data = r.content
    if not data.startswith(PNG_MAGIC):
        res["error"] = f"이미지 서버 응답이 PNG 가 아님({len(data)}바이트)"
        return res
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            res["size"] = list(im.size)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"이미지 검증 실패: {type(e).__name__}"
        return res
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    res["ok"] = True
    from recap_shorts import usage
    usage.log("image", model="local-image-server", seconds=res["seconds"], size=res.get("size"), aspect=aspect)
    return res


def generate_many(items: list[dict], workers: int = 2, on_done=None, gen=None) -> list[dict]:
    """items: [{"prompt","out"}] → 같은 순서의 결과. 동시에 workers(≤2)장. on_done(i, result) 는 한 장 끝날 때마다."""
    gen = gen or generate
    results: list[dict | None] = [None] * len(items)

    def one(i):
        r = gen(items[i]["prompt"], items[i]["out"], items[i].get("aspect", "landscape"))
        results[i] = r
        if on_done:
            on_done(i, r)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as ex:
        list(ex.map(one, range(len(items))))
    return results  # type: ignore[return-value]
