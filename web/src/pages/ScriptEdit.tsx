import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import JobHeader from "../components/JobHeader";
import { go, useLoad } from "../hooks";
import { Button, Card, Chip, ICON, Label, SectionLabel, Status, cx } from "../ui";
import type { Script, ScriptCheck, ScriptSentence } from "../types";

interface Issue { index: number | null; level: "ok" | "warn" | "bad"; msg: string }
const txt = flagText;
/** script_check.json → 사실 확인 줄. index 는 본문 문장 0부터. */
function issuesOf(c: ScriptCheck | null): Issue[] {
  if (!c) return [];
  const out: Issue[] = [];
  const del = c.deleted ?? [];
  out.push(del.length ? { index: null, level: "bad", msg: `근거가 없어 지운 문장 ${del.length}개` } : { index: null, level: "ok", msg: "근거가 없는 사실 문장 없음" });
  for (const d of del) out.push({ ...txt(d), level: "bad" });
  if (c.checks?.title_lines) out.push({ index: null, level: c.checks.title_lines.ok ? "ok" : "warn", msg: c.checks.title_lines.ok ? "제목 두 줄 길이 알맞음" : "제목 두 줄이 깁니다" });
  const h = c.checks?.hook;
  if (h) out.push({ index: null, level: h.ok ? "ok" : "warn", msg: h.ok ? `훅 ${h.syllables ?? h.chars ?? ""}${h.syllables != null ? "음절" : "자"}, 알맞음`
    : h.ends_noun === false ? "훅이 문장으로 끝남 — '~라는 ○○ 이유'처럼 명사로" : `훅 길이가 규격(${(h.range ?? [12, 20]).join("~")}음절)을 벗어남` });
  for (const f of [...(c.flags ?? []), ...(c.warnings ?? [])]) out.push({ ...txt(f), level: "warn" });
  return out;
}

import { flagText, isArchived, syl } from "../lib";
const BAR_MAX = 260;

function TotalBar({ total, range }: { total: number; range: [number, number] }) {
  const [lo, hi] = range;
  const state = total < lo ? { tone: "warn" as const, text: "조금 짧습니다" } : total > hi ? { tone: "warn" as const, text: "조금 깁니다" } : { tone: "ok" as const, text: "알맞습니다" };
  const p = (v: number) => `${(Math.min(v, BAR_MAX) / BAR_MAX) * 100}%`;
  return (
    <div>
      <div className="flex items-baseline justify-between"><span className="text-[34px] font-semibold leading-none tracking-[-0.02em]">{total}</span><Status tone={state.tone}>{state.text}</Status></div>
      <div className="relative mt-4 h-2 rounded-full bg-fill">
        <div className="absolute inset-y-0 rounded-full bg-[color-mix(in_srgb,var(--c-ok)_28%,transparent)]" style={{ left: p(lo), width: `calc(${p(hi)} - ${p(lo)})` }} />
        <div className="bar absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: p(total) }} />
      </div>
      <div className="relative mt-1.5 h-4 text-[11px] text-sub"><span className="absolute -translate-x-1/2" style={{ left: p(lo) }}>{lo}</span><span className="absolute -translate-x-1/2" style={{ left: p(hi) }}>{hi}</span></div>
      <p className="mt-2 text-[13px] text-sub">전체 음절 수. 목소리로 읽으면 30초 안팎이 되는 길이입니다.</p>
    </div>
  );
}

export default function ScriptEdit({ id }: { id: string }) {
  const job = useLoad(() => api.job(id), [id], 5000);
  const loaded = useLoad(() => api.script(id), [id]);
  const [draft, setDraft] = useState<Script | null>(null);
  const [check, setCheck] = useState<ScriptCheck | null>(null);
  const [orig, setOrig] = useState<string>("");
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<null | "save" | "refine" | "next">(null);
  const [msg, setMsg] = useState<string | null>(null);
  const rows = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => { if (loaded.data && !draft) { setDraft(structuredClone(loaded.data.script)); setCheck(loaded.data.check); setOrig(JSON.stringify(strip(loaded.data.script))); } }, [loaded.data, draft]);

  const dirty = draft ? JSON.stringify(strip(draft)) !== orig : false;
  const total = useMemo(() => (draft ? syl(draft.hook) + draft.sentences.reduce((n, s) => n + syl(s.text), 0) + syl(draft.closing ?? "") : 0), [draft]);
  const range: [number, number] = check?.checks?.syllables?.range ?? [190, 220];

  if (loaded.error && !draft) return <Card className="p-6 text-[15px] text-bad-text">대본을 불러오지 못했습니다. {loaded.error}</Card>;
  if (!draft || !job.data) return <div className="text-[13px] text-sub">불러오는 중</div>;

  const setS = (i: number, p: Partial<ScriptSentence>) => setDraft({ ...draft, sentences: draft.sentences.map((s, k) => (k === i ? { ...s, ...p } : s)) });
  const adopt = (d: { script: Script; check: ScriptCheck | null }) => { setDraft(structuredClone(d.script)); setCheck(d.check); setOrig(JSON.stringify(strip(d.script))); };
  async function save(): Promise<boolean> {
    setBusy("save"); setMsg(null);
    try { adopt(await api.saveScript(id, draft!)); setMsg("저장했고 사실 확인을 다시 했습니다."); return true; }
    catch (e) { setMsg(`저장하지 못했습니다. ${(e as Error).message}`); return false; }
    finally { setBusy(null); }
  }
  async function refine() {
    if (dirty && !confirm("저장하지 않은 수정이 있습니다. 다듬기를 다시 하면 이 수정이 사라집니다. 계속할까요?")) return;
    setBusy("refine"); setMsg("다듬는 중입니다. 20초쯤 걸립니다.");
    try {
      await api.refineScript(id);
      for (let i = 0; i < 120; i++) {           // 백그라운드 작업이 끝날 때까지 기다린다
        await new Promise((r) => setTimeout(r, 1500));
        if ((await api.job(id)).status !== "running") break;
      }
      const d = await api.script(id);
      adopt(d);
      setMsg(d.check?.refine?.applied === false ? `다듬기를 적용하지 못했습니다. ${d.check.refine.error ?? ""}` : "다듬기를 다시 했습니다. 바뀐 곳을 읽어 보세요.");
      job.reload();
    } catch (e) { setMsg(`다듬지 못했습니다. ${(e as Error).message}`); }
    finally { setBusy(null); }
  }
  async function saveNext() {
    if (dirty && !(await save())) return;
    setBusy("next");
    try { if ((await api.job(id)).steps.find((s) => s.key === "script")?.status === "waiting") await api.next(id); go(`/job/${encodeURIComponent(id)}`); }
    catch (e) { setMsg((e as Error).message); setBusy(null); }
  }
  const issues = issuesOf(check);
  const issueAt = (i: number) => issues.find((x) => x.index === i && x.level !== "ok");

  return (
    <div>
      <JobHeader job={job.data} tab="script" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section>
          <SectionLabel>대본 편집</SectionLabel>
          <Card className="mb-4 p-5">
            <Label>영상 위쪽 제목 두 줄</Label>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {[0, 1].map((k) => (
                <input key={k} value={draft.title_lines[k] ?? ""} onChange={(e) => { const t = [...draft.title_lines]; t[k] = e.target.value; setDraft({ ...draft, title_lines: t }); }}
                  aria-label={`제목 ${k + 1}줄`} className={cx("h-10 rounded-[10px] border border-line bg-fill px-3 text-[15px] font-medium outline-none focus:border-accent", k === 1 && "text-[#a07800] dark:text-[#FFD400]")} />
              ))}
            </div>
          </Card>
          <Card className="divide-y divide-line">
            <Row n={0} label="훅" text={draft.hook} sylN={syl(draft.hook)} open={open === -1} onOpen={() => setOpen(open === -1 ? null : -1)}
              onText={(t) => setDraft({ ...draft, hook: t })} />
            {draft.sentences.map((s, i) => (
              <div key={i} ref={(el) => { rows.current[i] = el; }}>
                <Row n={i + 1} text={s.text} sylN={syl(s.text)} evidence={s.evidence} emphasis={s.emphasis} issue={issueAt(i)?.msg} open={open === i} onOpen={() => setOpen(open === i ? null : i)}
                  onText={(t) => setS(i, { text: t })} onEmph={(t) => setS(i, { emphasis: t || null })} hint={s.image_hint} onHint={(t) => setS(i, { image_hint: t })}
                  take={!!s.take} onTake={(v) => setS(i, { take: v })} />
              </div>
            ))}
            {draft.closing != null && <Row n={draft.sentences.length + 1} label="끝" text={draft.closing} sylN={syl(draft.closing)} open={open === -2} onOpen={() => setOpen(open === -2 ? null : -2)} onText={(t) => setDraft({ ...draft, closing: t })} />}
          </Card>
        </section>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <Card className="p-5"><Label>전체 음절 수</Label><div className="mt-3"><TotalBar total={total} range={range} /></div></Card>
          <Card className="p-5">
            <Label>사실 확인</Label>
            <ul className="mt-3 space-y-2.5">
              {issues.length === 0 && <li className="text-[13px] text-sub">확인 결과가 없습니다.</li>}
              {issues.map((x, k) => (
                <li key={k}>
                  <button disabled={x.index == null} onClick={() => { if (x.index != null) { setOpen(x.index); rows.current[x.index]?.scrollIntoView({ behavior: "smooth", block: "center" }); } }}
                    className="flex w-full items-start gap-2.5 text-left text-[13px] leading-snug disabled:cursor-default">
                    <span className={cx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", x.level === "ok" ? "bg-ok" : x.level === "warn" ? "bg-warn" : "bg-bad")} />
                    <span>{x.index != null && <span className="text-sub">{x.index + 1}번 · </span>}{x.msg}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {check?.refine?.changed && check.refine.changed.length > 0 && (
            <Card className="p-5">
              <details>
                <summary className="cursor-pointer text-[11px] font-medium text-sub">다듬기에서 바뀐 곳 {check.refine.changed.length}개</summary>
                <ul className="mt-3 space-y-3">
                  {check.refine.changed.map((c, k) => (
                    <li key={k} className="text-[13px] leading-snug"><div className="text-sub line-through">{c.before}</div><div>{c.after}</div></li>
                  ))}
                </ul>
              </details>
            </Card>
          )}
          <Card className="space-y-2 p-5">
            <Button variant="primary" className="w-full" disabled={busy !== null || isArchived(job.data)} onClick={saveNext}>{dirty ? "저장하고 계속" : "이대로 계속"}</Button>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" disabled={!dirty || busy !== null || isArchived(job.data)} onClick={save}>{busy === "save" ? "저장하는 중" : "저장"}</Button>
              <Button variant="secondary" disabled={busy !== null || isArchived(job.data)} icon={<RefreshCw size={15} {...ICON} className={busy === "refine" ? "animate-spin" : ""} />} onClick={refine}>다듬기 다시</Button>
            </div>
            <p className="pt-1 text-[13px] text-sub">{msg ?? (dirty ? "저장하지 않은 수정이 있습니다." : "다듬기 다시는 같은 모델로 소리 내어 읽는 기준으로 한 번 더 고칩니다.")}</p>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function strip(s: Script) { return { t: s.title_lines, h: s.hook, s: s.sentences, c: s.closing }; }

function Row({ n, label, text, sylN, evidence, emphasis, issue, open, onOpen, onText, onEmph, hint, onHint, take, onTake }: {
  n: number; label?: string; text: string; sylN: number; evidence?: string | null; emphasis?: string | null; issue?: string; open: boolean; onOpen: () => void;
  onText: (t: string) => void; onEmph?: (t: string) => void; hint?: string | null; onHint?: (t: string) => void;
  take?: boolean; onTake?: (v: boolean) => void;       // 우리 해석 문장(대본 규칙 F9) 표시
}) {
  return (
    <div className={cx("px-5 py-4", open && "bg-fill/60")}>
      <button onClick={onOpen} className="grid w-full grid-cols-[32px_minmax(0,1fr)_auto] items-baseline gap-x-3 text-left" aria-expanded={open}>
        <span className="text-[13px] text-sub">{label ?? n}</span>
        <span className="text-[15px] leading-relaxed">{take && <Chip tone="accent" className="mr-2 align-middle">해석</Chip>}{text}</span>
        <span className="text-[13px] text-sub">{sylN}음절</span>
      </button>
      {issue && !open && <div className="ml-11 mt-1 text-[13px] text-warn-text">{issue}</div>}
      {!open && evidence && <div className="ml-11 mt-1 truncate text-[13px] text-sub">근거: {evidence}</div>}
      {open && (
        <div className="rise ml-11 mt-3 space-y-3">
          <textarea value={text} onChange={(e) => onText(e.target.value)} rows={2} autoFocus aria-label="문장"
            className="w-full resize-y rounded-[10px] border border-line bg-surface p-3 text-[15px] leading-relaxed outline-none focus:border-accent" />
          {issue && <div className="text-[13px] text-warn-text">{issue}</div>}
          {evidence && <div className="text-[13px] text-sub">근거 구절: {evidence}</div>}
          {onEmph && <label className="flex items-center gap-2 text-[13px] text-sub">색을 줄 낱말<input value={emphasis ?? ""} onChange={(e) => onEmph(e.target.value)} className="h-8 w-40 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink outline-none focus:border-accent" /></label>}
          {onTake && <label className="flex items-center gap-2 text-[13px] text-sub"><input type="checkbox" checked={!!take} onChange={(e) => onTake(e.target.checked)} />우리 해석 문장 (글 내용을 다시 전하는 말이 아니라 정리·맥락·비교·관점)</label>}
          {onHint && <label className="flex items-center gap-2 text-[13px] text-sub">그림 설명<input value={hint ?? ""} onChange={(e) => onHint(e.target.value)} className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink outline-none focus:border-accent" /></label>}
        </div>
      )}
    </div>
  );
}
