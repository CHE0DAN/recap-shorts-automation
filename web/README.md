# web — 커뮤니티 쇼츠 자동 제작 화면

React 19 + Vite 8 + TypeScript 7 + Tailwind 4 + lucide-react(버전 고정). 디자인 지시서는 `docs/03_v2_app_design.md` 4절.

## 실행

```
cd web
npm install
npm run dev        # http://localhost:5173  (API 는 http://127.0.0.1:8020 으로 프록시)
npm run build      # tsc --noEmit && vite build → web/dist  (백엔드가 / 에서 제공)
```

- 백엔드 없이 보기: 주소 뒤에 `?mock=1` (예: `http://localhost:5173/?mock=1`). 한 번 켜면 그 탭에서는 계속 유지, 끄려면 `?mock=0`.
  가짜 응답은 `src/mock/`에 있고 설계서 1.2 형식과 같다. 이미지·소리·영상·대본·timeline 은 로컬 작업 폴더 하나(`work/<작업 id>/`)를 읽는다. 저장소에는 작업 폴더가 없어서, 그 폴더가 없으면 그림·영상 자리가 비어 보인다.
  지금 목 모드는 폴더 이름을 코드에 고정해 두었다(`src/api.ts` 의 `mediaUrl` 이 `mock…` 작업 id 를 `sample` 로 바꾼다) — 목으로 그림·영상을 보려면 작업 폴더 이름을 그 값에 맞춘다.
  **개발 서버(`npm run dev`)에서만** `/media/<작업>/…` 을 `../work/<작업>/…`, `/fonts/…` 를 `../assets/fonts/…` 로 직접 읽어 준다(`vite.config.ts`의 `local-media`). 운영에서는 백엔드가 같은 경로를 제공해야 한다.
- 화면 주소(해시 라우터): `#/` 홈 · `#/find` 인기글 찾기(홈 위에 뜨는 시트) · `#/job/:id` 제작 · `#/job/:id/script` 대본 · `#/job/:id/scenes` 장면 편집기 · `#/job/:id/review` 검수.

## 백엔드와 맞춘 형식

`python -m recap_shorts.app`(기본 포트 8020) 으로 띄우면 `web/dist` 를 `/` 에서 제공한다(`npm run build` 먼저). 프론트가 쓰는 응답 형식:

- `GET /api/topics`: `{triage:"ok"|"unavailable", items:[{no,title,date,views,recommends,comments,url,triage:{category:{영문키:확률},interest,hidden,hidden_by[]}}]}` — 분야 영문 키는 프론트가 한글로 바꾸고, `hidden`만 "숨긴 후보"로 접는다.
- 이미 만든 소재: `/api/topics` 항목마다 `made: {kind: same_post|same_original|similar, job_id, our_title, created_at, score, count, finished, archived} | null`(칩 "만든 적 있음"·"비슷한 이야기 만듦"), 응답에 `made_count`·`made_same_count`. `POST /api/jobs` 는 같은 글이 있으면 409 `{code:"duplicate", message, count, jobs[]}` → `createJobAsking`(api.ts)이 한 번 묻고 `allow_duplicate:true` 로 다시 보낸다. `made.py` 참고.
- `GET/PUT /script`: `{script, check, draft}` (PUT 본문 `{script}`). 사실 확인 줄은 `check`(deleted·flags·warnings·checks)에서 만든다. `POST /script/refine` 은 바로 돌아오고 백그라운드로 돈다 → job 이 `running` 을 벗어날 때까지 기다린 뒤 다시 읽는다.
- `GET/PUT /scenes`: `{sentences[{index,text,start,end,images[{file,kind,score}]}], candidates[], scores{문장:{파일:점수}}, scored_by}`, PUT 본문 `{plan:{문장:[파일…]}}`. 미리보기용 timeline 은 `/media/{id}/timeline.json`.
- `GET /assets`(assets.json), `POST /assets/blur {file, boxes}`(가리기), `POST /assets/regenerate`, `GET/PUT /topic`.
- 검수: `/media/{id}/out/review.json`(+ `/assets`로 가림 확인 여부), 승인은 검수 단계 `waiting` 에서 `POST /continue`.
- 헬스: 각 항목 `{ok, detail}`. 글꼴: `/fonts/Pretendard-ExtraBold.otf`·`Pretendard-Black.otf`(server.py 가 `assets/fonts` 를 제공).

## 구조

```
src/App.tsx            해시 라우터 + 위쪽 막대(키·도구 상태 점)
src/api.ts             REST 클라이언트(mock 스위치) · mediaUrl
src/types.ts           계약 형식
src/pages/             Home, TopicSheet, Job, ScriptEdit, SceneEditor, Review
src/editor/engine.ts   timeline.json → 캔버스 한 프레임(백엔드 compose.py/layout.py 와 같은 수식)
src/editor/player.ts   재생기(소리 요소 시계, 그리기 요청)
src/editor/TimelineStrip.tsx  눈금·문장·그림(끌어서 맞바꾸기)·자막·파형
src/components/        Waveform, JobHeader
src/mock/              가짜 응답
```
