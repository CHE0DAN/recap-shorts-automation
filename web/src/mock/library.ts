// ?mock=1 — 효과음·짤 폴더 분석(docs/library_analysis.md)의 가짜 서버. 상태는 메모리에만 있다.
// 분석은 시작한 뒤 흐른 시간으로 진행률을 계산한다(약 6초: 재기 1.5 → 듣기·보기 3 → 만들기 1.5).
import { ApiError } from "../apiError";
import type { LibKind, LibraryChange, MemeFolder, MemeItem, MemeSettings, PackDetail, PackState, PackSummary, Settings, SfxFolder, SfxHeard, SfxItem } from "../types";

/** 설정에 넣어 둔 폴더(영상이 쓰는 것). mock/index.ts 의 설정 화면이 읽고 쓴다. */
export const usedDirs: Record<LibKind, string[]> = { sfx: ["C:\\Users\\나\\효과음 모음"], meme: ["C:\\Users\\나\\반응 짤"] };

const GROUPS = [
  { id: "hit", label: "타격 (퍽·탕)", want: 4 }, { id: "pop", label: "뽁·톡 (컷)", want: 4 }, { id: "ding", label: "딩동 (정답)", want: 3 },
  { id: "sparkle", label: "반짝 (강조)", want: 3 }, { id: "boom", label: "쿵·폭발", want: 3 }, { id: "huh", label: "의문 (허?)", want: 3 },
  { id: "scream", label: "비명·놀람", want: 2 }, { id: "awkward", label: "어색한 정적", want: 3 }, { id: "sad", label: "슬픔", want: 3 },
  { id: "laugh", label: "웃음", want: 3 }, { id: "sus", label: "수상함", want: 2 }, { id: "punchline", label: "개그 마무리", want: 3 },
];
const BEATS = [
  { id: "question", label: "의문" }, { id: "shock", label: "충격" }, { id: "laugh", label: "웃음" }, { id: "sad", label: "슬픔" },
  { id: "angry", label: "분노" }, { id: "smug", label: "의기양양" }, { id: "awkward", label: "어색" }, { id: "agree", label: "공감" },
];
const FAMILIES = [{ id: "frog", label: "개구리" }, { id: "cat", label: "고양이" }, { id: "blob", label: "동글이" }, { id: "etc", label: "기타" }];

// ---- 효과음 시드: 종류마다 (이름, 설명) 몇 개씩 → 30개 고름 ----
const SFX_KEPT: Record<string, [string, string][]> = {
  hit: [["퍽 1", "묵직하게 한 번 치는 소리"], ["퍽 2", "가벼운 따귀 같은 소리"], ["탕 1", "짧고 단단한 두드림"]],
  pop: [["뽁 1", "짧고 가벼운 뽁"], ["뽁 2", "물방울 터지는 뽁"], ["톡 1", "손끝으로 튕기는 톡"], ["톡 2", "나무 블록 톡"]],
  ding: [["딩동 1", "맑은 종 두 번"], ["딩동 2", "정답 맞힌 듯한 종소리"]],
  sparkle: [["반짝 1", "위로 올라가는 방울 소리"], ["반짝 2", "작은 종이 흩어지는 소리"], ["반짝 3", "하프 한 줄 훑기"]],
  boom: [["쿵 1", "낮고 긴 울림"], ["쿵 2", "무거운 물건이 떨어지는 소리"], ["펑 1", "짧은 폭발"]],
  huh: [["허? 1", "올라가는 물음표 소리"], ["허? 2", "고개 갸웃하는 듯한 소리"]],
  scream: [["꺅 1", "짧은 놀람 비명"], ["악 1", "낮은 비명"]],
  awkward: [["귀뚜라미 1", "조용한 방의 귀뚜라미"], ["정적 1", "바람 소리만 나는 정적"], ["까마귀 1", "멀리서 우는 새"]],
  sad: [["뿌우 1", "힘 빠지는 나팔"], ["띠로링 1", "내려가는 건반 소리"]],
  laugh: [["웃음 1", "여럿이 웃는 짧은 소리"], ["웃음 2", "작게 키득"], ["웃음 3", "환호가 섞인 웃음"]],
  sus: [["수상 1", "낮게 깔리는 현악 한 음"]],
  punchline: [["빠밤 1", "북 두 번과 심벌"], ["빠밤 2", "트럼펫 짧은 마무리"]],
};
const SFX_DROPPED: [string, string, string[]][] = [
  ["배경음악 루프 1", "잔잔한 피아노 곡", ["음악"]], ["배경음악 루프 2", "신나는 전자 음악", ["음악"]], ["노래 조각 1", "가사가 있는 노래 일부", ["음악", "문장 대사"]],
  ["오프닝 곡", "기타와 드럼이 나오는 곡", ["음악"]], ["벨소리 모음", "여러 벨소리가 이어짐", ["음악"]],
  ["인사말 1", "안녕하세요 하고 말하는 목소리", ["문장 대사"]], ["인사말 2", "오늘 날씨가 좋네요 하는 목소리", ["문장 대사"]], ["뉴스 멘트", "아나운서가 읽는 소리", ["문장 대사"]],
  ["대사 조각 3", "두 사람이 대화함", ["문장 대사"]], ["소감 발표", "길게 이야기하는 소리", ["문장 대사"]], ["안내 방송", "역 안내 방송", ["문장 대사"]],
  ["먹먹한 쿵", "너무 멀리서 녹음된 소리", ["품질"]], ["지직 뽁", "잡음이 심한 뽁", ["품질"]], ["녹음 실패 1", "거의 안 들림", ["품질"]], ["울리는 종", "방 울림이 너무 큼", ["품질"]],
  ["바람 소리 섞인 박수", "바람이 크게 섞임", ["품질"]], ["끊긴 효과음", "중간이 잘려 있음", ["품질"]],
  ["욕설 섞인 외침", "거친 말이 섞인 외침", ["욕설·성적"]], ["야한 신음 1", "성적인 소리", ["욕설·성적"]], ["야한 신음 2", "성적인 소리", ["욕설·성적"]], ["욕 연발", "욕설이 이어짐", ["욕설·성적", "문장 대사"]],
  ["유명 게임 시작음", "어떤 게임의 시작 소리", ["권리자 분명"]], ["영화 로고 소리", "영화사 로고 소리", ["권리자 분명"]], ["방송 시그널", "방송 프로그램 시그널", ["권리자 분명", "음악"]],
  ["회사 알림음", "알려진 회사의 알림음", ["권리자 분명"]], ["만화 효과음 원본", "만화 방영분에서 떼어 낸 소리", ["권리자 분명"]],
  ["찢어진 폭발", "소리가 심하게 찢어짐", ["찢어짐"]], ["찢어진 비명", "마이크가 터진 비명", ["찢어짐", "품질"]], ["일부러 찢은 쿵", "일부러 키운 소리", ["찢어짐"]], ["최대 음량 벨", "깨질 만큼 큰 소리", ["찢어짐"]],
  ["너무 짧은 클릭", "0.05초도 안 됨", ["품질"]], ["긴 환경음 1", "1분짜리 거리 소리", ["음악", "품질"]], ["합창 조각", "여럿이 노래함", ["음악"]],
  ["감탄사 모음", "여러 사람이 말함", ["문장 대사"]], ["강의 일부", "강의 목소리", ["문장 대사"]], ["랩 한 소절", "가사가 있음", ["음악", "문장 대사"]],
  ["깨진 파일 (재생 안 됨)", "열 수 없는 파일", ["품질"]],
  ["비슷한 뽁 3", "뽁 1 과 거의 같음", ["다른 소리와 겹침"]], ["비슷한 쿵 3", "쿵 1 과 거의 같음", ["다른 소리와 겹침"]],
];

// ---- 짤 시드 ----
const MEME_KEPT: { name: string; meaning: string; beats: string[]; family: string; text?: string; person?: boolean; transparent?: boolean; w: number; h: number }[] = [
  { name: "물음표 개구리", meaning: "이해가 안 될 때, 어이없는 말 바로 뒤에 붙이는 의문", beats: ["question"], family: "frog", w: 345, h: 216, transparent: true },
  { name: "놀란 개구리", meaning: "믿기 힘든 사실이 나왔을 때의 충격", beats: ["shock"], family: "frog", w: 400, h: 400 },
  { name: "의기양양 개구리", meaning: "내가 맞았다고 뽐낼 때", beats: ["smug"], family: "frog", w: 300, h: 300, transparent: true },
  { name: "멍한 고양이", meaning: "말문이 막혔을 때, 어색한 정적", beats: ["awkward", "question"], family: "cat", w: 480, h: 360 },
  { name: "박수 치는 고양이", meaning: "잘했다고 칭찬하거나 비꼴 때", beats: ["agree", "laugh"], family: "cat", w: 360, h: 360, text: "짝짝짝" },
  { name: "울먹이는 동글이", meaning: "억울하거나 슬픈 일이 나왔을 때", beats: ["sad"], family: "blob", w: 320, h: 320, transparent: true },
  { name: "빵 터진 동글이", meaning: "웃긴 말 바로 뒤의 큰 웃음", beats: ["laugh"], family: "blob", w: 420, h: 300 },
  { name: "화난 동글이", meaning: "어이없고 화나는 상황", beats: ["angry", "shock"], family: "blob", w: 300, h: 300 },
  { name: "고개 끄덕이는 사람", meaning: "맞다고 공감할 때", beats: ["agree"], family: "etc", w: 540, h: 304, person: true },
  { name: "민망한 표정 사진", meaning: "부끄럽거나 민망한 순간", beats: ["awkward"], family: "etc", w: 600, h: 400, person: true, text: "아 몰라" },
];
const MEME_DROPPED: { name: string; why: string[]; w: number; h: number }[] = [
  { name: "분위기 나쁜 그림", why: ["혐오 상징"], w: 400, h: 400 },
  { name: "야한 그림", why: ["성적"], w: 500, h: 500 },
  { name: "피 묻은 그림", why: ["잔인"], w: 450, h: 450 },
  { name: "풍경 사진", why: ["반응 짤이 아님"], w: 800, h: 600 },
  { name: "작은 이모티콘", why: ["너무 작음", "품질 낮음"], w: 96, h: 96 },
  { name: "물음표 개구리 복사본", why: ["같은 그림(물음표.png)"], w: 345, h: 216 },
];

const hash6 = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h.toString(16).padStart(6, "0").slice(-6); };
const baseName = (dir: string) => dir.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "폴더";
const packId = (dir: string) => `${baseName(dir)}-${hash6(dir)}`;

function sfxItems(listened: boolean): SfxItem[] {
  const items: SfxItem[] = [];
  const heard = (desc: string, fit: Record<string, number>, words = ""): SfxHeard => ({ desc, speech: words ? "words" : "none", words, music: false, source: "generic", owner_clear: false, offensive: false, earrape: false, quality: 4, fit });
  let n = 0;
  for (const g of GROUPS) {
    for (const [name, desc] of SFX_KEPT[g.id] ?? []) {
      n += 1;
      const words = name === "꺅 1" ? "꺅" : "";
      const h = listened && n % 9 !== 0 ? heard(desc, { [g.id]: 3, ...(g.id === "pop" ? { hit: 1 } : {}) }, words) : null;
      items.push({ key: `모음/${name}.wav`, name, dur: 0.6 + (n % 7) * 0.35, active_len: 0.18 + (n % 6) * 0.11, heard: h, keep: true, type: g.id, score: h ? 10 - (n % 3) : null,
        auto: { keep: true, type: g.id, why: [] }, user: {}, out: null });
    }
  }
  SFX_DROPPED.forEach(([name, desc, why], i) => {
    const music = why.includes("음악");
    const h = listened ? { ...heard(desc, { huh: 1, boom: i % 2 }), music, speech: why.includes("문장 대사") ? "sentence" as const : "none" as const, owner_clear: why.includes("권리자 분명"), offensive: why.includes("욕설·성적"), earrape: why.includes("찢어짐"), quality: why.includes("품질") ? 2 : 4 } : null;
    items.push({ key: `기타/${name}.mp3`, name, dur: 1 + (i % 5) * 4.2, active_len: 0.8 + (i % 5) * 3.9, heard: h, keep: false, type: null, score: null,
      auto: { keep: false, type: null, why }, user: {}, out: null });
  });
  // 사람이 고친 예: 종류를 바꾼 소리, 일부러 뺀 소리, 일부러 넣은 소리
  const e1 = items.find((i) => i.name === "퍽 2")!; e1.user = { type: "pop" }; e1.type = "pop";
  const e2 = items.find((i) => i.name === "정적 1")!; e2.user = { keep: false }; e2.keep = false; e2.type = null;
  const e3 = items.find((i) => i.name === "비슷한 뽁 3")!; e3.user = { keep: true, type: "pop" }; e3.keep = true; e3.type = "pop";
  return renumber(items);
}

/** 고른 소리에 꾸러미 파일 이름(pop_01 …)을 순서대로 붙인다. */
function renumber(items: SfxItem[]): SfxItem[] {
  const count: Record<string, number> = {};
  for (const it of items) {
    if (it.keep && it.type) {
      count[it.type] = (count[it.type] ?? 0) + 1;
      it.out = { id: `${it.type}_${String(count[it.type]).padStart(2, "0")}`, duration: +Math.max(0.1, it.active_len).toFixed(2) };
    } else it.out = null;
  }
  return items;
}

function memeItems(listened: boolean): MemeItem[] {
  const items: MemeItem[] = [];
  MEME_KEPT.forEach((m, i) => {
    const seen = listened ? { reaction: true, name: m.name, meaning: m.meaning, beats: m.beats, family: m.family, has_text: !!m.text, text: m.text ?? "", hate: false, sexual: false, gore: false, real_person: !!m.person, quality: 4 } : null;
    items.push({ key: `${m.family}/${m.name}.png`, w: m.w, h: m.h, transparent: !!m.transparent, dup_of: null, seen,
      keep: true, name: m.name, meaning: m.meaning, beats: m.beats, family: m.family, has_text: !!m.text, real_person: !!m.person,
      auto: { keep: true, why: [] }, user: {}, out: { id: `m_${String(i + 1).padStart(3, "0")}` } });
  });
  MEME_DROPPED.forEach((m, i) => {
    items.push({ key: `기타/${m.name}.png`, w: m.w, h: m.h, transparent: false, dup_of: m.why[0].startsWith("같은") ? "개구리/물음표.png" : null,
      seen: listened ? { reaction: !m.why.includes("반응 짤이 아님"), name: m.name, meaning: "", beats: [], family: null, has_text: false, text: "", hate: m.why[0] === "혐오 상징", sexual: m.why[0] === "성적", gore: m.why[0] === "잔인", real_person: false, quality: m.why.includes("품질 낮음") ? 1 : 3 } : null,
      keep: false, name: m.name, meaning: "", beats: [], family: null, has_text: false, real_person: false,
      auto: { keep: false, why: m.why }, user: {}, out: null });
    void i;
  });
  // 사람이 이름·뜻을 고친 예
  const e = items[3]; e.user = { name: "멍한 고양이", meaning: e.meaning };
  return items;
}

interface MockPack {
  kind: LibKind; id: string; source_dir: string; listened: boolean; items: (SfxItem | MemeItem)[];
  startedAt: number; stoppedAt: number | null; done: boolean; useOnDone: boolean; created_at: string;
}
const packs: MockPack[] = [];
const PHASES: [PackState, number, string][] = [["measuring", 1500, "재는 중"], ["listening", 4500, "듣는 중"], ["building", 6000, "꾸러미 만드는 중"]];

function seed(kind: LibKind, dir: string, listened: boolean, ago: number): MockPack {
  const p: MockPack = { kind, id: packId(dir), source_dir: dir, listened, items: kind === "sfx" ? sfxItems(listened) : memeItems(listened),
    startedAt: Date.now() - ago, stoppedAt: null, done: true, useOnDone: true, created_at: new Date(Date.now() - ago).toISOString() };
  packs.push(p);
  return p;
}
seed("sfx", "C:\\Users\\나\\효과음 모음", true, 3_600_000);
seed("meme", "C:\\Users\\나\\반응 짤", true, 7_200_000);

const find = (kind: string, id: string) => packs.find((p) => p.kind === kind && p.id === id);
const need = (kind: string, id: string) => {
  const p = find(kind, id);
  if (!p) throw new ApiError("꾸러미를 찾을 수 없습니다", 404, { message: "꾸러미를 찾을 수 없습니다" });
  return p;
};
const running = () => packs.find((p) => stateOf(p).state !== "done" && stateOf(p).state !== "stopped" && stateOf(p).state !== "error");

function stateOf(p: MockPack): { state: PackState; done: number; total: number; step: string } {
  const total = p.items.length;
  if (p.done) return { state: "done", done: total, total, step: "끝" };
  const e = (p.stoppedAt ?? Date.now()) - p.startedAt;
  if (p.stoppedAt) return { state: "stopped", done: Math.min(total, Math.round(total * Math.min(1, e / 4500))), total, step: "멈춤" };
  if (e < 300) return { state: "queued", done: 0, total, step: "기다리는 중" };
  let from = 0;
  for (const [state, until, step] of PHASES) {
    if (e < until) {
      const frac = (e - from) / (until - from);
      return { state, done: Math.min(total, Math.round(total * frac)), total, step: state === "listening" && p.kind === "meme" ? "보는 중" : state === "listening" && !p.listened ? "이름으로 정하는 중" : step };
    }
    from = until;
  }
  // 끝남: 한 번만 마무리해서 설정에 넣는다
  p.done = true;
  if (p.useOnDone && !usedDirs[p.kind].includes(p.source_dir)) usedDirs[p.kind].push(p.source_dir);
  return { state: "done", done: total, total, step: "끝" };
}

function counts(p: MockPack): PackSummary["counts"] {
  const kept = p.items.filter((i) => i.keep);
  const groups: Record<string, number> = {};
  for (const i of kept) { const g = p.kind === "sfx" ? (i as SfxItem).type : (i as MemeItem).family; if (g) groups[g] = (groups[g] ?? 0) + 1; }
  return { files: p.items.length, kept: kept.length, dropped: p.items.length - kept.length, groups };
}

function summary(p: MockPack): PackSummary {
  const s = stateOf(p);
  const fin = s.state === "done" || s.state === "stopped";
  return { kind: p.kind, id: p.id, source_dir: p.source_dir, out_dir: outDir(p.kind, p.id), state: s.state,
    progress: { done: s.done, total: s.total, step: s.step }, counts: fin || p.done ? counts(p) : { files: s.total, kept: 0, dropped: 0, groups: {} },
    used: usedDirs[p.kind].includes(p.source_dir), listened: p.listened, model: p.listened ? "gemini-3.8-flash" : null, message: null,
    created_at: p.created_at, updated_at: new Date().toISOString() };
}
const detail = (p: MockPack): PackDetail => ({ ...summary(p), groups_def: p.kind === "sfx" ? GROUPS : [], beats_def: BEATS, families_def: FAMILIES, items: p.items });

function start(kind: LibKind, dir: string, use: boolean): MockPack {
  const r = running();
  if (r) throw new ApiError("다른 분석이 돌고 있습니다. 끝난 뒤 다시 해 주세요", 409, { message: "다른 분석이 돌고 있습니다. 끝난 뒤 다시 해 주세요" });
  if (dir.includes("없는")) throw new ApiError("폴더가 없습니다", 400, { message: "폴더가 없습니다" });
  const listened = !/nokey/i.test(dir);
  let p = find(kind, packId(dir));
  if (!p) p = seed(kind, dir, listened, 0);
  else if (p.listened !== listened) { p.listened = listened; p.items = kind === "sfx" ? sfxItems(listened) : memeItems(listened); }
  p.done = false; p.stoppedAt = null; p.startedAt = Date.now(); p.useOnDone = use; p.created_at = new Date().toISOString();
  return p;
}

function apply(p: MockPack, changes: LibraryChange[]) {
  for (const c of changes) {
    const it = p.items.find((i) => i.key === c.key);
    if (!it) throw new ApiError("그런 파일이 없습니다", 400, { message: "그런 파일이 없습니다" });
    if (c.reset) it.user = {};
    else {
      const u = it.user as Record<string, unknown>;
      if (c.keep !== undefined) u.keep = c.keep;
      if (c.type !== undefined) u.type = c.type;
      if (c.name !== undefined) u.name = c.name;
      if (c.meaning !== undefined) u.meaning = c.meaning;
      if (c.beats !== undefined) u.beats = c.beats;
    }
    const u = it.user as { keep?: boolean; type?: string; name?: string; meaning?: string; beats?: string[] };
    it.keep = u.keep ?? it.auto.keep;
    if (p.kind === "sfx") {
      const s = it as SfxItem;
      s.type = s.keep ? (u.type ?? s.auto.type ?? GROUPS[0].id) : null;
    } else {
      const m = it as MemeItem;
      const seen = m.seen;
      m.name = u.name ?? seen?.name ?? (m.key.split("/").pop() ?? "").replace(/\.[^.]+$/, "");
      m.meaning = u.meaning ?? seen?.meaning ?? "";
      m.beats = u.beats ?? seen?.beats ?? [];
    }
  }
  if (p.kind === "sfx") renumber(p.items as SfxItem[]);
  else { let n = 0; for (const i of p.items as MemeItem[]) i.out = i.keep ? { id: `m_${String(++n).padStart(3, "0")}` } : null; }
}

// ---- 파일 주소(목 전용) ----
const hue = (s: string) => { let h = 0; for (const c of s) h = (h * 37 + c.charCodeAt(0)) % 360; return h; };
const memeSvg = new Map<string, string>();
/** 짤 자리표시 그림: 색 동그라미 얼굴. 투명 배경 짤은 바탕 없이 얼굴만 그린다. */
function memeImage(key: string): string {
  const hit = memeSvg.get(key);
  if (hit) return hit;
  const spec = MEME_KEPT.find((m) => key.includes(m.name));
  const w = spec?.w ?? 400, h = spec?.h ?? 300, tr = !!spec?.transparent;
  const c = hue(key);
  const face = `<circle cx="${w / 2}" cy="${h / 2}" r="${Math.min(w, h) * 0.38}" fill="hsl(${c} 55% 62%)"/><circle cx="${w / 2 - w * 0.12}" cy="${h / 2 - h * 0.06}" r="${Math.min(w, h) * 0.05}" fill="#222"/><circle cx="${w / 2 + w * 0.12}" cy="${h / 2 - h * 0.06}" r="${Math.min(w, h) * 0.05}" fill="#222"/><path d="M${w / 2 - w * 0.12} ${h / 2 + h * 0.14} q${w * 0.12} ${h * (c % 2 ? 0.1 : -0.08)} ${w * 0.24} 0" stroke="#222" stroke-width="${Math.min(w, h) * 0.025}" fill="none" stroke-linecap="round"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${tr ? "" : `<rect width="${w}" height="${h}" fill="hsl(${c} 40% 90%)"/>`}${face}</svg>`;
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  memeSvg.set(key, url);
  return url;
}
let beep: string | null = null;
/** 0.6초 삐 소리(목소리 미리듣기 목 소리 재사용). 이름에 '깨진'이 든 파일은 일부러 빈 주소 → 못 트는 경우 확인용. */
export function mockLibraryFileUrl(kind: LibKind, q: { key?: string; out?: string }, wav: () => Blob): string {
  if (kind === "meme") return q.key ? memeImage(q.key) : "";
  if (q.key?.includes("깨진")) return "";
  if (!beep) beep = URL.createObjectURL(wav());
  return beep;
}

// ---- 요청 처리. 맞는 경로가 아니면 undefined ----
export function mockLibraryRequest(method: string, p: string, body: unknown, ctx: { settings: () => Settings; pick: number }): unknown {
  const b = (body ?? {}) as { kind?: LibKind; dir?: string; use?: boolean; on?: boolean; changes?: LibraryChange[] };
  if (p === "/api/library" && method === "GET") {
    const r = running();
    return { running: r ? { kind: r.kind, id: r.id } : null, packs: packs.map(summary) };
  }
  if (p === "/api/library/pick") return { path: b.kind === "meme" ? `C:\\Users\\나\\짤 모음 ${ctx.pick}` : `C:\\Users\\나\\효과음 폴더 ${ctx.pick}` };
  if (p === "/api/library/add") {
    const kind = b.kind === "meme" ? "meme" : "sfx";
    const dir = (b.dir ?? "").trim();
    if (!dir) throw new ApiError("폴더를 적어 주세요", 400, { message: "폴더를 적어 주세요" });
    if (/manifest/i.test(dir)) {       // 목록이 이미 있는 폴더: 분석 없이 바로 설정에
      if (dir.includes("없는")) throw new ApiError("폴더가 없습니다", 400, { message: "폴더가 없습니다" });
      if (!usedDirs[kind].includes(dir)) usedDirs[kind].push(dir);
      return { added: true, settings: ctx.settings() };
    }
    return { analysis: summary(start(kind, dir, true)) };
  }
  if (p === "/api/library/analyze") return summary(start(b.kind === "meme" ? "meme" : "sfx", (b.dir ?? "").trim(), !!b.use));
  const m = /^\/api\/library\/(sfx|meme)\/([^/]+)(\/[a-z]+)?$/.exec(p);
  if (!m) return undefined;
  const kind = m[1] as LibKind;
  const id = decodeURIComponent(m[2]);
  const pk = need(kind, id);
  const sub = m[3] ?? "";
  if (sub === "" && method === "GET") return detail(pk);
  if (sub === "" && method === "DELETE") {
    if (running() === pk) throw new ApiError("분석 중에는 지울 수 없습니다", 409, { message: "분석 중에는 지울 수 없습니다" });
    packs.splice(packs.indexOf(pk), 1);
    usedDirs[kind] = usedDirs[kind].filter((d) => d !== pk.source_dir);
    return null;
  }
  if (sub === "/items" && method === "PUT") {
    if (running() === pk) throw new ApiError("분석 중에는 고칠 수 없습니다", 409, { message: "분석 중에는 고칠 수 없습니다" });
    apply(pk, b.changes ?? []);
    return detail(pk);
  }
  if (sub === "/use") {
    if (b.on) { if (!usedDirs[kind].includes(pk.source_dir)) usedDirs[kind].push(pk.source_dir); }
    else usedDirs[kind] = usedDirs[kind].filter((d) => d !== pk.source_dir);
    return summary(pk);
  }
  if (sub === "/stop") { if (running() === pk) pk.stoppedAt = Date.now(); return summary(pk); }
  return undefined;
}

// ---- 설정 화면용 폴더 항목(끝난 분석을 먼저 설정에 넣은 뒤 읽는다) ----
export const mockSettle = () => { for (const p of packs) stateOf(p); };
const outDir = (kind: LibKind, id: string) => ["C:", "recap", "assets_local", "analyzed", kind, id].join("\\");
export function mockSfxFolderOf(dir: string): SfxFolder {
  const pk = find("sfx", packId(dir));
  if (!pk) return { path: dir, exists: true, count: 5, skipped: 0, manifest: true, types: { pop: 3, boom: 2 }, error: null, label: null, pack: null };
  const c = counts(pk);
  return { path: outDir("sfx", pk.id), exists: true, count: c.kept, skipped: 0, manifest: true, types: c.groups, error: null, label: dir, pack: { kind: "sfx", id: pk.id } };
}
export function mockMemeFolderOf(dir: string): MemeFolder {
  const pk = find("meme", packId(dir));
  if (!pk) return { path: dir, label: null, pack: null, exists: true, count: 8, manifest: true, error: null };
  return { path: outDir("meme", pk.id), label: dir, pack: { kind: "meme", id: pk.id }, exists: true, count: counts(pk).kept, manifest: true, error: null };
}
export function mockMemeSettings(): MemeSettings {
  const dirs = usedDirs.meme.map(mockMemeFolderOf);
  const def: MemeFolder[] = [{ path: "assets/memes/default", label: null, pack: null, exists: true, count: 24, manifest: true, error: null }];
  return { using: dirs.length ? "custom" : "default", dirs, default: def, max_dirs: 8 };
}
