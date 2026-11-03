# 03. v2 설계 — 웹 앱 · Clef-omni 활용 · 대본 품질 · 화면

`docs/02_program_design.md` 의 제작 프로그램(단계·규격표·데이터 형식)을 **웹 앱**으로 감싼 설계다. 백엔드가 단계를 돌리고, 프론트가 그 상태를 보여 주며 사람이 확인할 곳에서 멈춘다.

## 1. 구조

```
recap_shorts/
  pipeline.py          # 단계 실행기(오케스트레이터): job 하나를 단계별로 돌리고 state.json 갱신
  llm/gemini_api.py    # Gemini API 텍스트·비전(대본=gemini-4-argon, 이미지 글자 읽기=gemini-3.8-flash)
  clef/                # Cloudflare Clef-omni 클라이언트 + 질문 모음(3절)
  images/provider.py   # 자료 이미지 생성(AI 그림 엔진 고르기) — 5절
  app/                 # FastAPI: REST + 미디어 파일 제공 + 빌드된 프론트 제공
web/                   # 프론트(React + Vite + Tailwind), 빌드 결과 web/dist 를 app 이 제공
```
작업 폴더: `work/<job_id>/` — `state.json`(단계 상태)와 하위 폴더(`post/`, `assets/`, `script_final/`, `voice/`, `timeline.json`, `out/`).

### 1.1 단계 (state.json 의 steps 순서)

| key | 이름(화면) | 하는 일 | 사람 확인 |
|---|---|---|---|
| `source` | 글 가져오기 | 디시인사이드·블라인드 글 본문·첨부 이미지(닉네임·IP·회사명 저장 안 함), 글 캡처(댓글은 따로) | |
| `read` | 자료 읽기 | 첨부 이미지·댓글 캡처의 글자를 Gemini 비전으로 옮겨 적어 topic.json 을 만든다(그림 종류·얼굴·아이디 포함 여부 표시) | topic 확인·수정 가능 |
| `script` | 대본 | 대본 모델 초안 → 다듬기 패스(같은 모델, 소리 내어 읽기 기준) → 사실 가드 | **대본 편집 화면** |
| `voice` | 목소리 | TTS 1회 합성 → 문장 분할 → 받아쓰기 확인, 문장 하나만 다시(redo) | 문장별 듣기·다시 |
| `assets` | 자료 화면 | 글 캡처 카드(가림 자동), 대상 사진 찾기, AI 그림 생성(문장별 image_hint), 이미지 검사(Clef) | 이미지 바꾸기·가리기 |
| `scenes` | 장면 배치 | 캡처 우선으로 문장×그림 배치(점수 계산, 겹치지 않게), 필요하면 Clef 적합도(3.2, 기본 꺼짐) | **장면 편집기** |
| `render` | 영상 만들기 | timeline → mp4 | |
| `review` | 검수 | Clef-omni 영상 점검(3.4), 같은 자로 측정, 설명 문구 생성 | 승인 |

- 사람 확인 단계(`read`·`script`·`scenes`·`review`)는 일을 마친 뒤 `waiting` 으로 멈춘다. `continue` 로 진행하고, 이미 `done` 인 단계는 건너뛰며, `error` 단계는 그 단계부터 다시 한다.
- Gemini 를 부르는 단계는 `read`·`script`·`voice`·`assets` — 서버는 키가 없으면 이 단계로 넘어가는 것을 막고 설정 화면을 안내한다.

### 1.2 REST (프론트와 백엔드의 계약 — 둘이 이 형식에 맞춘다)

| 메서드·경로 | 설명 |
|---|---|
| `GET /api/health` | 키·도구 상태: gemini_key, cf_keys, gpu, image_server, asr_model, ffmpeg (bool + 설명) |
| `GET/PUT /api/settings` | 설정 읽기/저장(키는 저장만 하고 돌려주지 않음). `POST /api/settings/test`, `GET /api/settings/gemini-models`, `POST /api/settings/voice/preview`, `GET /api/settings/models`·`POST /api/settings/models/{id}/install`(로컬 모델 파일) |
| `GET/PUT /api/channel` | 채널 대주제(주제 고르기의 거르기 기준). 없음/프리셋/custom |
| `GET /api/topics?source=dcbest` | 주제 후보 목록 + Clef 분류(3.1). `source` 는 `dcbest`(디시 실시간 베스트, 기본)·`blind`(블라인드 인기글)·`gallery`(갤러리 개념글, `gallery=…&pages=2`). 캐시 10분, `refresh=1` 로 새로 불러오기 |
| `POST /api/topics/refresh` | 목록 새로 불러오기(캐시 무시). 이미 분류한 글은 다시 묻지 않음 |
| `POST /api/jobs` `{url}` 또는 `{gallery, no}` | job 만들기 → `{id}` 후 백그라운드 실행 시작(사람 확인 단계에서 멈춤). 같은 글로 이미 만든 job 이 있으면 409 `{code:"duplicate", message, count, jobs}` — `allow_duplicate: true` 를 넣으면 만든다(`collect/made.py`) |
| `GET /api/jobs` / `GET /api/jobs/{id}` | 목록 / state.json 전체(목록은 log 를 최근 5줄만) |
| `POST /api/jobs/{id}/continue` | 확인 단계 다음으로 진행 |
| `POST /api/jobs/{id}/rerun` `{from:"assets"｜"scenes"｜"render"}` | 앞 단계 결과는 두고 그 단계부터 다시 |
| `POST /api/jobs/{id}/archive` · `GET /api/storage` | 끝난 job 을 구글 드라이브로 보관(손으로) · 보관 설정·드라이브 상태 |
| `GET/PUT /api/jobs/{id}/script` | 대본 읽기/고치기(PUT 하면 가드 다시) → `{script, check, draft}`. `POST …/script/refine` 은 바로 돌아오고 백그라운드로 돈다 |
| `POST /api/jobs/{id}/voice/redo` `{index, variants?}` | 문장 하나 다시 녹음 |
| `GET/PUT /api/jobs/{id}/scenes` | 장면 배치(문장별 그림 목록·점수·컷 시각) |
| `GET /api/jobs/{id}/intro_preview` | 장면 편집기 미리보기용 인트로 카드 그림과 시간 값 |
| `GET /api/jobs/{id}/assets` · `POST …/assets/regenerate` `{file, prompt?}` | 자료 목록 · 이미지 하나 다시 만들기 |
| `POST /api/jobs/{id}/assets/blur` `{file, boxes}` | 사람이 그린 사각형으로 모자이크(그 원본에서 나온 카드를 모두 다시 만듦) |
| `POST /api/jobs/{id}/assets/sensitive` `{file, treatment}` | 자극적인 그림 처리: `none`｜`gray`｜`gray_blur` |
| `POST /api/jobs/{id}/render` | 렌더 |
| `GET /api/capcut/status` · `POST /api/capcut/open` · `GET/POST /api/jobs/{id}/capcut` | 캡컷 설치·실행 확인, 캡컷 초안으로 내보내기 |
| `GET/PUT /api/jobs/{id}/topic` | 옮겨 적은 글·주제 문장 고치기(고치면 대본부터 다시) |
| `GET /media/{id}/{path}` | 작업 폴더 파일(이미지·wav·mp4) |

state.json 형식:
```json
{"id":"20261102-101500_test_1001","title":"…","source":{"site":"dcinside","gallery":"test","no":1001,"url":"…","title":"…"},
 "created_at":"…","status":"running|waiting|done|error","progress":0.0,"options":{},
 "steps":[{"key":"script","label":"대본","status":"todo|running|waiting|done|error","progress":0.0,
           "detail":"지금 하는 일 한 줄","sub":[{"label":"초안","status":"done","note":"236초"}],
           "started_at":"…","ended_at":"…","error":null}],
 "artifacts":{"script":"script_final/script.json","voice":"voice/voice.wav","video":"out/final.mp4",
              "images":["assets/ai/…png"],"description":"out/description.txt"},
 "log":[{"t":"…","msg":"…"}]}
```
- `source.site` 는 `dcinside`｜`blind`. 블라인드 글은 `gallery:"blind"` 에 토픽 이름이 `source.topic` 으로 들어간다.
- `artifacts` 는 단계가 끝날 때마다 붙는다. 화면은 이 목록으로 결과 카드를 그린다.

## 2. 대본 품질

- 규칙: `script/prompt.py` 의 [문장 흐름 규칙] F1~F8 — 이야기 순서(상황 → 반전 → 구체적 장면 → 대비·결말 → 반응), 문장 하나에 생각 하나, 반말 하나로 끝맺음, 압축 금지(풀어 쓰기), 한 문장 15~30음절, 줄임말·전문어 풀어 쓰기, 끝 한 줄은 새 사실 없는 반응. 말한 사람이 둘 이상이면 문장마다 누가 한 말인지 밝힌다(F11).
- **F9 우리 해석**: 남의 글에 내레이션만 얹은 영상은 재사용 콘텐츠로 본다. 본문에 정리·맥락·비교·관점 문장을 1~2개 넣고 `take: true` 로 표시한다. 가드는 표시가 없거나, 표시한 문장이 원문과 글자 3-gram 35% 이상 겹치거나(베낌), 12음절 미만이면 경고 flag 만 남긴다(막지 않음). 표시 필드가 없는 대본(옛 대본·손으로 쓴 대본)은 근거(evidence) 없는 본문 문장 중 베낌이 아닌 12음절 이상 문장이 있으면 통과. 끝 한 줄·훅은 해석으로 세지 않는다. 대본 편집 화면에서 문장을 열면 "우리 해석 문장" 체크로 직접 표시할 수 있다.
- **F10 인용**: 글의 재미가 사람이 한 말(리뷰 답글·댓글·문자·대사)에 있으면 가장 어이없는 말 2~4개를 작은따옴표로 원문 글자 그대로 옮겨 들려준다.
- **다듬기 패스**: 초안 → 같은 모델에 "소리 내어 읽었을 때 어색한 곳을 고쳐라, 사실·evidence 는 그대로 두라" 두 번째 호출 → 사실 가드. 두 판을 모두 저장(`script_draft.json`, `script.json`).
- 모델: Gemini API `gemini-4-argon`(기본, 설정 화면에서 고른 대본 모델). `RECAP_SCRIPT_LLM=agy` 로 Antigravity CLI(`gemini-3.8-flash-high`)를 쓸 수 있다. 키는 앱 설정 화면에서 넣고, 파일에 있는 값을 화면·기록에 내보내지 않는다.

## 3. Clef-omni 활용 (검수만이 아니라)

클라이언트는 `recap_shorts/clef/client.py`, 쓰는 모델은 `clef`·`clef-flash`·`clef-omni`(그림·소리·영상은 `clef-omni`). 한 번에 질문 64개까지, 그림 4장·영상 2개(16MB). 키는 `RECAP_CF_ACCOUNT_ID`, `RECAP_CF_API_TOKEN`(출력 금지), Cloudflare 무료 하루 10,000뉴런.

**원칙**: 같은 영상도 질문 문장을 바꾸면 답이 흔들린다. 그래서 (1) 새 질문은 정답을 아는 재료로 "예"·"아니오" 양쪽을 먼저 시험하고, (2) 두 번 물어 평균하고, (3) 점수는 **순위·추천·경고**에 쓰고 사람이 바꿀 수 있게 한다(자동으로 지우거나 막지 않는다 — 단 3.1의 안전 경고는 목록에서 아래로 내림).

| 자리 | 질문 | 입력 | 쓰임 |
|---|---|---|---|
| 3.1 주제 고르기 | choice: 분야(정치/사건·범죄/선정적/연예/스포츠/생활·경제/기타), noul: 특정인 비난·조롱 중심인가, 성적 대상화인가, 확인 안 된 의혹인가, score: 그 분야를 안 보는 사람도 흥미로울까(1~5) | 제목 + 본문 텍스트(+2차에서 첫 이미지) | 후보 목록 정렬·배지, 위험 후보는 접힘 |
| 3.2 장면 자동 배치 | noul: "이 그림은 '{문장}'이 나오는 동안 보여 주기에 어울리나" | 그림 1장 + 문장 | 문장×그림 적합도 표 → 겹치지 않게 배치(헝가리안), 장면 편집기에 점수 표시. **기본 꺼짐** — 캡처 우선 배치에서는 켜나 안 켜나 결과가 거의 같고(18컷 중 17컷 동일), 그림마다 호출해 하루치 뉴런을 대부분 쓴다. 켜려면 옵션 `clef_scene_fit` |
| 3.3 자료 검사 | noul: 사람 얼굴이 또렷한가, 아이디·닉네임·전화번호 같은 개인정보 글자가 보이나, (AI 그림) 글자·로고가 보이나, 실존 인물처럼 보이나 | 그림 | 가림 필요 표시, AI 그림 다시 만들기 추천 |
| 3.4 영상 점검 | 첫 장면·얼굴·음악·내레이션·주제 일치 + "자막이 화면 밖으로 잘렸나" | 360px·10fps 사본(58초까지) | 검수 화면(참고용) |
| 3.5 목소리 확인(시험) | noul: "이 소리는 '{문장}'이라고 또렷하게 말하나" | 문장 wav | 받아쓰기 일치율과 함께 표시(둘 다 낮으면 다시 녹음 추천) |

**평가(먼저 할 것)**: 정답을 아는 재료로 정답표를 만든다 — 3.2: 손으로 배치한 장면표(`work/<job>/shot_plan.json`)의 문장–그림 짝(정답 "예")과 다른 문장의 그림(정답 "아니오"), 3.3: SNS 캡처 원본(얼굴·아이디 있음 "예") vs 모자이크 카드(아니오), AI 그림(글자 없음, 아니오). 질문 문장 2가지 × 2회. 맞힌 비율·흔들림을 `recap_shorts/clef/eval_results.json` 에 남기고, 기준(문항별 `usable`·`threshold`)을 못 넘는 질문은 쓰지 않는다(`scripts/clef_eval.py`).

## 4. 화면(UI/UX) — 단정하고 차분한 화면

### 4.1 원칙
- 한 화면에 한 가지 주된 일. 사람이 결정할 곳(주제·대본·장면·승인)만 크게, 나머지는 진행 상태로.
- 실제 데이터를 보여 준다: 이미지 썸네일, 파형, 영상 미리보기, 숫자. 장식용 일러스트·이모지·그라디언트 없음.
- **쓰지 않는 것(과한 장식)**: 보라·핑크 그라디언트, 유리 효과 남발, 네온 글로우, 파티클, ✨🚀 이모지, "AI가 마법처럼" 같은 문구, 의미 없는 대형 히어로, 과한 그림자, 모든 걸 둥근 알약으로, 가운데 정렬 남발, 회색 위 회색 대비 부족.

### 4.2 토큰
- 글꼴: Pretendard Variable(jsDelivr, `pretendard@1.3.9` 고정), 숫자는 `font-variant-numeric: tabular-nums`.
- 크기: 34/28(화면 제목, -0.02em) · 20(섹션) · 15(본문) · 13(보조) · 11(라벨, 대문자 아님). 굵기 600/500/400만.
- 색(라이트): 바탕 `#F5F5F7`, 면 `#FFFFFF`, 글자 `#1D1D1F`, 보조 `#6E6E73`, 선 `rgba(0,0,0,.08)`, **포인트 하나 `#0071E3`**, 상태 점만 초록 `#34C759`/주황 `#FF9F0A`/빨강 `#FF3B30`. 글자색이 필요한 상태 문구는 `#1F8A3B`/`#B36B00`/`#D70015`.
- 다크(시스템 설정 따라): 바탕 `#0A0A0B` + 미리보기 영역에만 옅은 점 격자, 면 `#161618`, 채움 `#232326`, 글자 `#F5F5F7`, 보조 `#8E8E93`, 선 `rgba(255,255,255,.08)`, 포인트 `#0A84FF`.
- 모서리 14(카드)·10(입력)·8(칩·작은 버튼), 그림자 `0 1px 2px rgba(0,0,0,.04)`만. 간격 8pt 격자.
- 움직임: 180~260ms, `cubic-bezier(.2,.8,.2,1)`; 눌림·등장에만 작은 스프링(`cubic-bezier(.2,.9,.3,1.03)`, 오버슈트 ≤ 3%), 진행 막대는 부드럽게. 글로우·파티클·하드컷 금지. `prefers-reduced-motion` 존중.
- 아이콘: lucide 1.5px 선 굵기만.

### 4.3 화면
1. **홈(새로 만들기)**: 위 "커뮤니티 쇼츠 자동 제작" + 한 줄 설명. 입력 한 줄(디시·블라인드 글 주소) + "인기글에서 찾기" 버튼. 아래 최근 작업 카드(썸네일·제목·상태).
2. **인기글 찾기(시트/모달)**: 출처 선택(실시간 베스트·블라인드·갤러리), 후보 목록 — 제목, 추천·조회, Clef 분야 배지, 흥미 점수, 위험 표시(위험 후보는 아래 "숨긴 후보 n개"로 접힘), "출처 확인 필요" 표시. 고르면 job 시작.
3. **제작 화면**: 위 단계 레일(8단계 카드: 이름·상태·진행 막대), "지금 하는 일" 카드(큰 퍼센트, 하위 단계 체크), "만들어진 것" 결과 카드(대본 요약, 파형, 이미지 그리드, 영상)가 쌓인다. 오른쪽 열: 제작 기록(log)과 설명 문구(복사 버튼).
4. **대본 편집**: 문장 목록(번호·문장·근거 구절·음절 수), 문장 클릭 → 고치기, 전체 음절 수 막대(190~220), 사실 가드 결과. "다듬기 다시"(LLM) 버튼.
5. **장면 편집기**: 세로 9:16 미리보기 + 아래 타임라인(문장별 구간에 그림 썸네일, 점수 작은 숫자). 그림 끌어서 바꾸기·순서 바꾸기·이미지 다시 만들기·문장 다시 녹음. 캔버스 미리보기·타임라인·재생기 구조(`web/src/editor/`)로 미리보기를 브라우저에서 바로 재생(렌더 전). 미리보기는 백엔드 `render/compose.py`·`render/layout.py` 와 같은 수식으로 그린다.
6. **검수**: 최종 영상, Clef 점검 결과, 규격표 대비 측정표, 설명 문구, 승인 버튼(업로드는 하지 않음).

## 5. 자료 이미지 생성
`images/provider.py` 가 엔진을 고른다 — **기본은 Gemini 이미지**(`gemini-3.1-flash-image`, 유료·장당 약 0.07달러). 설정에서 ①로컬 이미지 서버 ②Gemini 이미지 ③AI 그림 안 만듦 중에 고르고, 로컬 서버가 없거나 실패하면 `RECAP_IMAGE_FALLBACK=gemini` 일 때 Gemini 로 대신한다.

로컬 이미지 서버는 **이 저장소에 없는, 따로 띄우는 프로그램**이다. 형식은 이렇다:
`POST http://127.0.0.1:8791/api/image`, JSON `{"prompt": 문자열, "aspect": "square|landscape|portrait", "format": "png|jpeg|webp", "background"?: "transparent", "images"?: [data: URL]}`, 인증 헤더 없음. 응답 본문이 이미지 바이트 그대로. landscape 결과 1448×1086. 한 장 33~76초(평균 51초) 걸린다. 서버가 없으면 "이미지 생성 꺼짐"으로 표시하고 기존 이미지·캡처만 쓴다. 프롬프트 규칙: 실존 인물 닮게 금지, 글자·로고 없음, 사람은 뒷모습·멀리.

## 5.1 캡처 위주 화면 (장면 배치 규칙)
AI 그림이 너무 많으면 화면이 실제 글에서 겉돈다. 그래서 캡처를 먼저 채우고 AI 그림은 남는 자리에만 보조로 넣는다.

| 바꾼 것 | 어디 | 내용 |
|---|---|---|
| 문장 부분 캡처 | `images/regions.py`, `pipeline.step_assets` | 대본 image_hint 의 "캡처: …"(줄·댓글 하나 단위)를 비전 모델에 물어 상자(0~1000)로 받아 그 부분만 잘라 카드로. 가는 줄은 위아래를 넓히고 빨간 테두리로 표시 |
| 자동 가림 | 같은 호출 | 아이디·닉네임·프로필 사진·얼굴·영수증 번호·욕설 낱말을 상자로 받아 모자이크(욕설은 줄 전체가 아니라 낱말만). 하나라도 찾으면 "자동 가림 N곳", 못 찾았고 아이디가 있을 수 있으면 "가림 확인 필요" → 사람이 `POST /assets/blur` 로 직접 가린다 |
| 디시 댓글 | `collect/dcinside.py`, `config/collect_sites.json`, `pipeline.step_read` | 글 캡처와 따로 `#focus_cmt .comment_box` 를 `post/comments.png` 로 찍음(닉네임·@멘션(IP 앞자리)은 흐림, 댓글돌이 뉴스 제목·파워링크 광고는 숨김). 자료 읽기에서 욕설·비하 댓글은 빼고 옮겨 대본 재료로. 화면에는 댓글 한 줄만 글자 띠로 잘라(길면 두 줄로 접어) 크게 |
| 디시 글 머리 | 같은 곳 | 제목·작성 시각 / 조회·추천·댓글 수를 잘라 붙인 카드 → 훅 화면 |
| 배치 | `images/arrange.py` | 1단계 캡처(문장용으로 잘라 낸 캡처는 제 문장에, 맞는 캡처가 없으면 칸을 비움), 2단계 AI 는 남는 자리에 문장당 1장까지 맨 끝(AI 컷 비율 상한 `max_ai_share` 0.34). 같은 그림 두 번 안 씀. 가림 확인이 안 된 위험 캡처는 자동 배치에서 빼고 편집기 후보에만 남긴다 |
| 장면 설명만 고치기 | `app/server.py` PUT /script | 대사가 그대로면 목소리(TTS 한도)는 두고 자료 화면부터 다시. `POST /api/jobs/{id}/rerun {"from": "assets|scenes|render"}` |
| 장면 배치의 Clef 적합도 기본 꺼짐 | `pipeline.build_plan`, 옵션 `clef_scene_fit` (기본 False) | 같은 작업을 Clef 점수 없이 다시 배치하니 18컷 중 17컷이 같았다(다른 1컷은 마지막 문장의 AI 그림). 그림마다 한 번씩 부르는 이 단계가 Clef 하루치(1만 뉴런)의 대부분을 써서 끔. Clef 는 주제 거르기·AI 그림 글자 점검·완성 영상 점검에 쓴다 |
