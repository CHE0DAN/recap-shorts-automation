import type { BestTopic, Made, Topic } from "../types";

// 이미 만든 소재 표시 예시(화면 확인용 가짜 값) — 같은 글 / 비슷한 이야기
const madeAt = (daysAgo: number) => new Date(Date.now() - daysAgo * 86400e3).toISOString().replace(/\.\d+Z$/, "+00:00");
export const same = (title: string, daysAgo: number, count = 1, finished = true): Made => ({ kind: "same_post", job_id: "mock_made", our_title: title, source_title: title, created_at: madeAt(daysAgo), score: 1, count, finished, archived: true });
export const similar = (title: string, daysAgo: number, score: number): Made => ({ kind: "similar", job_id: "mock_made", our_title: title, source_title: title, created_at: madeAt(daysAgo), score, count: 1, finished: true, archived: false });

// 형식만 실제 응답과 같은 가짜 후보 목록(제목·수치는 화면 확인용).
const T = (no: number, title: string, recommends: number, views: number, comments: number, date: string, cat: string | null, interest: number | null, hidden_by: string[] = []): Topic => ({
  no, title, recommends, views, comments, date, url: `https://gall.dcinside.com/board/view/?id=baseball_new13&no=${no}`,
  triage: cat ? { category: { [cat]: 0.8 }, risks: {}, interest, hidden: hidden_by.length > 0, hidden_by } : null, made: null,
});

export const TOPICS: Topic[] = [
  { ...T(1001, "[가상] 가게 벽 뜯었더니 삼십 년 전 편지가 나왔다", 412, 48120, 187, "11.01 20:12", "생활·경제", 4.4), made: similar("벽 속 삼십 년 된 편지의 주인을 찾아라", 9, 0.31) },
  T(1002, "[가상] 새로 온 사장이 바꾼 가게 규칙들", 388, 31002, 142, "11.01 19:05", "생활·경제", 3.9),
  T(1003, "[가상] 시장에서 본 진상 손님 대처법", 231, 40519, 203, "11.01 17:40", "기타", 4.1),
  T(1004, "[가상] 이십 년 만에 다시 만난 단골", 301, 24410, 96, "11.01 15:22", "생활·경제", 3.6),
  T(1005, "[가상] 동네 빵집 메뉴가 바뀐 이유", 256, 19987, 121, "11.01 13:48", "생활·경제", 3.3),
  T(1006, "[가상] 올해 손님 수로 본 동네 상권", 168, 12307, 52, "11.01 12:10", "생활·경제", 3.5),
  { ...T(1007, "[가상] 벽에서 나온 봉투, 주인을 찾아 나섰다", 244, 18211, 88, "11.01 10:31", "생활·경제", 3.1), made: same("가게 주인이 편지 주인을 찾아 나선 사연", 0) },
  T(1008, "[가상] 모 방송 출연자 발언 진위 논란", 344, 52330, 311, "10.31 20:01", "사건·범죄", 2.4, ["unverified_claim"]),
  T(1009, "[가상] 특정 가수 가족 과거 행적 퍼온 글", 198, 20881, 155, "10.31 18:37", "연예", 2.2, ["person_attack"]),
  T(1010, "[가상] 행사장 치어리더 직캠 모음", 187, 60112, 98, "10.31 16:09", "선정적", 1.8, ["sexual"]),
];

// 실시간 베스트 예시(화면 확인용 가짜 값)
const B = (no: number, tag: string, title: string, views: number, comments: number, age_hours: number, cat: string | null, check: string | null = null, hide: string[] = []): BestTopic => ({
  no, tag, title, views, comments, recommends: Math.round(views / 300), age_hours, posted_at: new Date(Date.now() - age_hours * 3600e3).toISOString(),
  url: `https://gall.dcinside.com/board/view/?id=dcbest&no=${no}`, category: cat ? { id: cat, label: cat } : null,
  hidden: hide.length > 0, hidden_reason: hide, triaged: !!cat, source_check: !!check, source_check_reason: check, made: null,
});
// 채널 대주제 맞춤 점수 예시(번호 → 0|1|2). 실제로는 서버가 제목을 보고 Gemini 로 매긴다.
export const BEST_FIT: Record<number, 0 | 1 | 2> = { 2001: 2, 2002: 0, 2003: 2, 2004: 1, 2005: 0, 2006: 1 };
export const BEST: BestTopic[] = [
  { ...B(2001, "싱갤", "[가상] 20대 남녀 고민 상담 글 모음", 63000, 750, 3.3, "생활·경제", "[싱갤] 해외 짤·트위터·기사 퍼오기가 대부분"), made: similar("20대 연애 고민, 이렇게 다를 수 있나", 5, 0.27) },
  B(2002, "리갤", "[가상] 오늘 경기 역전 장면 다시 보기", 40000, 350, 22.1, "스포츠"),
  { ...B(2003, "냥갤", "[가상] 길고양이 급식소 두고 이웃끼리 다툰 사연", 15000, 280, 11.5, "생활·경제"), made: same("길고양이 급식소 때문에 이웃이 갈라섰다", 3, 2) },
  { ...B(2004, "싱갤", "[가상] 규제 풀린 경주장에서 벌어진 일", 7400, 50, 2.8, "기타", "[싱갤] 해외 짤·트위터·기사 퍼오기가 대부분"), made: same("규제가 사라진 경주장의 괴짜 기계들", 1, 1, false) },
  B(2005, "디갤", "[가상] 시골 밤 사진이 없다는 글", 1500, 20, 2.4, "기타"),
  B(2006, "더갤", "[가상] 확인 안 된 발언 사과 요구 글", 800, 40, 0.3, "정치", null, ["특정인 비난·조롱이 중심"]),
];

/** 목 모드에서 POST /api/jobs 가 409(중복)로 답하는 글 번호 → 이미 만든 job (BEST·TOPICS 의 same 표시와 같은 값). */
export const MADE_JOBS: Record<number, { title: string; created_at: string; count: number; finished: boolean }> = Object.fromEntries(
  [...BEST, ...TOPICS].filter((t) => t.made?.kind === "same_post").map((t) => [t.no, { title: t.made!.our_title, created_at: t.made!.created_at, count: t.made!.count, finished: t.made!.finished }]));
