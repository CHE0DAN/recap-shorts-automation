# 효과음·짤 폴더 분석 (재료 꾸러미)

내 효과음 폴더나 짤 폴더를 고르면 프로그램이 파일을 하나씩 재고(무료) Gemini 가 듣거나 보고 매긴 뒤,
영상 규칙이 쓰는 종류별로 골라 **따로 꾸러미를 만든다**. 원본 폴더는 읽기만 하고 아무것도 쓰지 않는다.

- 꾸러미 자리: `assets_local/analyzed/<kind>/<id>/` (`kind` = `sfx` | `meme`, `id` = 폴더 이름 + 경로 해시 6자리)
- 꾸러미 안: `analysis.json`(파일마다 잰 값·들은/본 결과·고른 이유·사람이 고친 것), `manifest.json`(영상이 읽는 목록),
  효과음은 다듬은 소리(`pop_01.wav` …)와 `_들어보기_전체.wav`, 짤은 복사한 그림(`m_001.png` …).
- 같은 폴더를 다시 분석하면 파일 이름·크기·수정 시각이 같은 파일은 예전 결과를 그대로 쓴다(Gemini 를 다시 부르지 않음). 사람이 고친 것은 남는다.
- Gemini 키가 없으면: 효과음은 파일 이름(`pop_01.wav`, `pop\아무이름.mp3`)으로만 종류를 정하고, 짤은 파일 이름을 뜻으로 쓴다.
- **비용**: 재는 것은 이 컴퓨터에서 해서 무료지만, 듣기·보기는 Gemini 요청이라 돈이 든다(입력 단가는 `config/prices.json` 의 그 모델 값).
  파일 6개에 요청 1번이라 효과음 800개(`sfx.max_files`)면 134번, 짤 400장(`meme.max_files`)이면 67번이다. 다시 분석하면 바뀐 파일만 묻는다.
  쓴 양은 다른 Gemini 호출과 같이 `work/_usage.jsonl` 에 한 줄씩 남는다.

## 효과음 고르는 규칙

1. 재기: 길이, 소리 시작·끝, 피크, 찢어짐(클리핑) 비율. 40초가 넘는 파일은 효과음이 아니라고 보고 듣지 않는다.
2. 듣기: Gemini 3.8 Flash 가 6개씩 듣고 종류별 어울림(0~3), 말소리(없음·낱말·문장), 음악 여부, 출처 갈래, 권리자가 분명한지,
   욕설·성적 소리, 일부러 찢은 소리, 품질(1~5)을 매긴다. 종류 목록은 `config/fx.json` 의 효과음 자리들이 쓰는 종류다.
3. 빼기: 욕설·성적 / 음악 / 문장 대사 / 품질 2 이하 / 일부러 찢은 소리 / 찢어짐 2% 넘음 / 권리자 분명(`analyze.sfx.drop_owner_clear`).
4. 고르기: 종류마다 `analyze.sfx.want` 개까지, 점수 = 어울림×2 + 품질 (− 짧은 소리 자리에 낱말 대사면 0.5). 후보가 적은 종류부터 채우고
   한 파일은 한 종류에만. 같은 소리 사본·이름이 같은 사본은 하나만(이름이 짧은 쪽).
   파일 이름에 영상 규칙이 쓰는 종류가 적혀 있으면(사람이 정리한 폴더, `pop_01.wav`) 그 종류로 개수 제한 없이 두고
   욕설·일부러 찢은 소리만 뺀다. 규칙이 안 쓰는 종류 이름(내려받은 `whoosh-sound-effect.mp3` 등)은 이름을 믿지 않고 들은 결과로 고른다.
5. 다듬기: 앞 무음 떼기, 종류별 길이 상한(넘으면 끝을 0.06초 페이드), 피크 −1 dBFS, 48 kHz 모노 16 bit.

## 짤 고르는 규칙

1. 재기: 크기, 투명 배경, 같은 그림(가로세로 비율 8% 안 + 16×16 차이 해시 거리 12 이하면 사본으로 보고 큰 것 하나만. 단색처럼 밝기 차가 거의 없어 해시로 가릴 수 없는 그림끼리는 같은 그림으로 보지 않는다).
2. 보기: Gemini 3.8 Flash 가 6장씩 보고 이름, 반응 짤인지, 뜻(어떤 문장 바로 뒤에 붙는 반응인지), 분위기(beats), 계열(페페 등),
   글씨, 품질, 그리고 거를 것(혐오 상징·성적·잔인)·실제 인물 사진인지를 적는다.
3. 빼기: 혐오 상징 / 성적 / 잔인 / 반응 짤이 아님 / 품질 1 / 짧은 변 120 px 미만 / 같은 그림. 저작권은 따지지 않는다.
4. 실제 인물 사진은 빼지 않고 표시만 한다(화면에 '실제 인물').
5. 영상에서는 짤의 **뜻(meaning)** 을 보고 문장에 맞는 짤을 고른다(`fx/meme_fit.py`). 그래서 확인 화면에서 뜻을 고칠 수 있다.

## REST (모두 이 컴퓨터에서만 — `/api/settings` 와 같은 검사)

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| GET | `/api/library` | | `{"running": {"kind","id"} \| null, "packs": [PackSummary]}` |
| POST | `/api/library/pick` | `{"kind"}` | `{"path": str \| null}` — Windows 폴더 고르기 창. 못 띄우면 501 |
| POST | `/api/library/add` | `{"kind", "dir"}` | 폴더에 `manifest.json` 이 있으면 바로 설정에 넣고 `{"added": true, "settings": Settings}`, 없으면 분석을 시작하고 `{"analysis": PackSummary}` (끝나면 설정에 저절로 들어감). 폴더가 없거나 파일이 없으면 400, 다른 분석이 도는 중이면 409 |
| POST | `/api/library/analyze` | `{"kind", "dir", "use"?: bool}` | 분석 시작(다시 분석 포함) → PackSummary. `use` 가 true 면 끝난 뒤 설정에 넣음 |
| GET | `/api/library/{kind}/{id}` | | PackDetail |
| PUT | `/api/library/{kind}/{id}/items` | `{"changes": [Change]}` | 고친 뒤 꾸러미를 다시 만든 PackDetail. 분석 중이면 409 |
| POST | `/api/library/{kind}/{id}/use` | `{"on": bool}` | PackSummary (설정의 폴더 목록에 넣기·빼기) |
| POST | `/api/library/{kind}/{id}/stop` | | PackSummary (멈춘 데까지 남음, analyze 로 이어 함) |
| DELETE | `/api/library/{kind}/{id}` | | 204. 만든 꾸러미만 지운다(원본 폴더는 안 건드림), 설정에서도 뺀다. 분석 중이면 409 |
| GET | `/api/library/{kind}/{id}/file?key=…` | | 원본 파일(효과음 소리·짤 그림) |
| GET | `/api/library/{kind}/{id}/file?out=…` | | 꾸러미 파일(`pop_01`, 효과음 `_sheet` = 들어보기 전체) |

### PackSummary

```json
{"kind": "sfx", "id": "my_sounds-3f9a1c", "source_dir": "C:\\Users\\나\\효과음", "out_dir": "C:\\…\\assets_local\\analyzed\\sfx\\my_sounds-3f9a1c",
 "state": "queued | measuring | listening | building | done | error | stopped",
 "progress": {"done": 120, "total": 340, "step": "듣는 중"},
 "counts": {"files": 340, "kept": 35, "dropped": 305, "groups": {"pop": 4, "boom": 3}},
 "used": true, "listened": true, "model": "gemini-3.8-flash", "message": null,
 "created_at": "2026-11-03T12:00:00+09:00", "updated_at": "2026-11-03T12:03:10+09:00"}
```

`groups` 는 효과음이면 종류별, 짤이면 계열(family)별 개수. `listened` 가 false 면 Gemini 없이 이름으로만 정한 것.

### PackDetail = PackSummary + 아래

```json
{"groups_def": [{"id": "pop", "label": "뽁·톡 (컷)", "want": 4}],
 "beats_def": [{"id": "question", "label": "의문"}],
 "families_def": [{"id": "pepe", "label": "페페"}],
 "items": [SfxItem | MemeItem]}
```

효과음 `SfxItem`:

```json
{"key": "모음/뽁.mp3", "name": "뽁", "dur": 2.31, "active_len": 0.42,
 "heard": {"desc": "짧고 가벼운 뽁", "speech": "none", "words": "", "music": false, "source": "generic",
           "owner_clear": false, "offensive": false, "earrape": false, "quality": 4, "fit": {"pop": 3, "hit": 1}},
 "keep": true, "type": "pop", "score": 10.0,
 "auto": {"keep": true, "type": "pop", "why": []}, "user": {},
 "out": {"id": "pop_01", "duration": 0.42}}
```

짤 `MemeItem`:

```json
{"key": "페페/물음표.png", "w": 345, "h": 216, "transparent": false, "dup_of": null,
 "seen": {"reaction": true, "name": "물음표 으쓱 페페", "meaning": "…", "beats": ["question"], "family": "pepe",
          "has_text": false, "text": "", "hate": false, "sexual": false, "gore": false, "real_person": false, "quality": 4},
 "keep": true, "name": "물음표 으쓱 페페", "meaning": "…", "beats": ["question"], "family": "pepe", "has_text": false,
 "real_person": false,
 "auto": {"keep": true, "why": []}, "user": {},
 "out": {"id": "m_001"}}
```

- `heard`/`seen` 이 null 이면 Gemini 결과가 없는 것(키 없음·실패·안 들음).
- `auto.why` = 뺀 이유(한국어 짧은 말, 예: `"음악"`, `"성적"`, `"같은 그림(다른.png)"`).
- `keep`·`type`·`name`·`meaning`·`beats` 는 사람이 고친 값(`user`)이 있으면 그것, 없으면 자동 값.

### Change

`{"key": "…", "keep"?: bool, "type"?: str, "name"?: str, "meaning"?: str, "beats"?: [str], "reset"?: true}` —
준 것만 바꾼다. `reset` 은 그 파일의 사람 값을 지워 자동 값으로 되돌린다.

## 설정(`GET /api/settings`) 에 더해지는 것

- `sfx.dirs[]`·`sfx.default[]` 의 폴더 항목(SfxFolder)에 `label`(분석 꾸러미면 원본 폴더 경로, 아니면 null)과
  `pack`(`{"kind","id"}` 또는 null)이 붙는다.
- 새 묶음 `memes`: `{"using": "custom" | "default" | "none", "dirs": [MemeFolder], "default": [MemeFolder], "max_dirs": 8}`
  MemeFolder = `{"path", "label", "pack", "exists", "count", "manifest", "error"}`. `none` = 고른 폴더도 기본 짤도 없어서 영상에 짤을 넣지 않음.
- `PUT /api/settings` 에 `{"memes": {"dirs": [폴더…] | null}}`.
