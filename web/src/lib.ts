import type { JobState, Script } from "./types";

/** "2026-01-02T12:38:45+09:00" → "01-02 12:38" (서버가 한국 시각으로 적어 문자열 그대로 자른다). */
export const fmtWhen = (iso: string) => { const m = /^\d{4}-(\d\d-\d\d)[T ](\d\d:\d\d)/.exec(iso ?? ""); return m ? `${m[1]} ${m[2]}` : (iso ?? ""); };

/** 구글 드라이브로 옮겨진 작업 — 화면에서 고칠 수 없다(서버도 409). */
export const isArchived = (j: Pick<JobState, "archive">) => j.archive?.status === "done";

/** render/captions.py 의 syllables() 와 같은 셈: 한글·영문·숫자 글자 수. */
export const syl = (t: string) => [...t].filter((c) => /[0-9A-Za-z가-힣]/.test(c)).length;
/** 훅 + 본문 문장 + 끝 한 줄. 목소리 길이의 기준이 되는 전체 음절 수. */
export const scriptSyllables = (s: Script) => syl(s.hook) + s.sentences.reduce((n, x) => n + syl(x.text), 0) + syl(s.closing ?? "");
export const scriptLines = (s: Script) => 1 + s.sentences.length + (s.closing ? 1 : 0);
/** script_check.json 의 flags·deleted 한 항목 → 글과 문장 번호(문자열이면 그대로). */
export const flagText = (x: unknown): { msg: string; index: number | null } => {
  if (typeof x === "string") return { msg: x, index: null };
  const o = (x ?? {}) as Record<string, unknown>;
  const m = o.msg ?? o.message ?? o.reason ?? o.text ?? JSON.stringify(x);
  const i = typeof o.index === "number" ? o.index : typeof o.sentence === "number" ? o.sentence : null;
  return { msg: String(m), index: i };
};
/** 영상 안의 시각(초) → "0:12.3" */
export const clock = (sec: number) => { const t = Math.round(sec * 10), m = Math.floor(t / 600); return `${m}:${((t - m * 600) / 10).toFixed(1).padStart(4, "0")}`; };
