import { ChevronDown, ChevronLeft, ChevronRight, Play, Plus, RotateCcw, Square, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, libraryFileUrl } from "../api";
import { ApiError } from "../apiError";
import { go } from "../hooks";
import { Button, Card, Chip, ICON, IconButton, Progress, Status, cx } from "../ui";
import type { LibKind, LibraryChange, MemeItem, PackDetail, PackState, SfxItem } from "../types";

const RUNNING: PackState[] = ["queued", "measuring", "listening", "building"];
const isRunning = (s: PackState) => RUNNING.includes(s);
const STATE_LABEL: Record<PackState, string> = { queued: "기다리는 중", measuring: "재는 중", listening: "듣는 중", building: "꾸러미 만드는 중", done: "분석 끝", error: "분석 실패", stopped: "멈춤" };
const SELECT = "h-8 min-w-0 rounded-lg border border-line bg-fill px-2 text-[13px] text-ink outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-60";
const FIELD = "w-full rounded-[10px] border border-line bg-fill px-2.5 text-[14px] text-ink outline-none placeholder:text-sub/70 focus:border-accent disabled:opacity-60";
const CHECKER = { background: "conic-gradient(var(--c-fill) 25%, var(--c-surface) 0 50%, var(--c-fill) 0 75%, var(--c-surface) 0) 0 0 / 16px 16px" } as const;

const errText = (e: unknown) => (e instanceof ApiError && e.status === 409 ? "분석 중에는 고칠 수 없습니다" : (e as Error).message);
const sec = (n: number) => `${n.toFixed(2)}초`;
const edited = (it: { user: object }) => Object.keys(it.user).length > 0;

/** 소리 하나씩만 튼다. url 이 비었거나 못 틀면 조용히 안내만 남긴다. */
function usePlayer() {
  const [playing, setPlaying] = useState<string | null>(null);
  const [note, setNote] = useState<{ tag: string; msg: string } | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const stop = () => { audio.current?.pause(); audio.current = null; setPlaying(null); };
  useEffect(() => () => { audio.current?.pause(); }, []);
  async function play(tag: string, url: string) {
    if (playing === tag) { stop(); return; }
    audio.current?.pause();
    audio.current = null;
    setNote(null);
    if (!url) { setPlaying(null); setNote({ tag, msg: "이 소리는 틀 수 없습니다" }); return; }
    const a = new Audio(url);
    audio.current = a;
    a.onended = () => { if (audio.current === a) { audio.current = null; setPlaying(null); } };
    a.onerror = () => { if (audio.current === a) { audio.current = null; setPlaying(null); setNote({ tag, msg: "이 소리를 틀 수 없습니다 (파일을 못 읽었습니다)" }); } };
    setPlaying(tag);
    try { await a.play(); } catch { if (audio.current === a) { audio.current = null; setPlaying(null); setNote({ tag, msg: "이 소리를 틀 수 없습니다" }); } }
  }
  return { playing, note, play, stop };
}
type Player = ReturnType<typeof usePlayer>;

function PlayButton({ tag, url, player, label }: { tag: string; url: string; player: Player; label: string }) {
  const on = player.playing === tag;
  return (
    <IconButton title={on ? `${label} 멈춤` : `${label} 듣기`} active={on} onClick={() => player.play(tag, url)}>
      {on ? <Square size={15} {...ICON} /> : <Play size={15} {...ICON} />}
    </IconButton>
  );
}

/** 접었다 펴는 제목 줄. */
function Fold({ open, onToggle, children }: { open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} className="press flex w-full items-center gap-1.5 rounded-lg py-1 text-left text-[15px] font-semibold hover:text-accent">
      {open ? <ChevronDown size={16} {...ICON} /> : <ChevronRight size={16} {...ICON} />}{children}
    </button>
  );
}

/** 이유 걸러 보기 칩(누르면 그 이유만, 다시 누르면 전체). */
function ReasonFilter({ reasons, value, onChange }: { reasons: [string, number][]; value: string | null; onChange: (v: string | null) => void }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {reasons.map(([r, n]) => (
        <button key={r} type="button" aria-pressed={value === r} onClick={() => onChange(value === r ? null : r)}
          className={cx("press inline-flex h-7 items-center rounded-lg px-2.5 text-[12px] font-medium", value === r ? "bg-ink text-surface" : "bg-fill text-sub hover:text-ink")}>{r} {n}</button>
      ))}
    </div>
  );
}
function countReasons(lists: string[][]): [string, number][] {
  const m = new Map<string, number>();
  for (const l of lists) for (const r of l) m.set(r, (m.get(r) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

type ChangeFn = (c: LibraryChange) => void;
interface RowCtx { d: PackDetail; busy: Set<string>; errs: Record<string, string>; change: ChangeFn; player: Player }

// ---------------------------------------------------------------- 효과음

function SfxRow({ it, ctx, dropped }: { it: SfxItem; ctx: RowCtx; dropped?: boolean }) {
  const { d, busy, errs, change, player } = ctx;
  const b = busy.has(it.key);
  const url = !dropped && it.out ? libraryFileUrl("sfx", d.id, { out: it.out.id }) : libraryFileUrl("sfx", d.id, { key: it.key });
  const len = it.out?.duration ?? it.active_len;
  const h = it.heard;
  const why = it.auto.why.length ? it.auto.why : ["내가 뺌"];
  const back = edited(it);
  // 넣을 때 종류: 자동으로 정한 종류 → 들은 결과 중 가장 어울리는 종류 → 첫 종류
  const fitType = () => {
    if (it.auto.type) return it.auto.type;
    const fit = Object.entries(h?.fit ?? {}).filter(([t]) => d.groups_def.some((g) => g.id === t)).sort((x, y) => y[1] - x[1])[0];
    return fit?.[0] ?? d.groups_def[0]?.id;
  };
  return (
    <div className={cx("border-b border-line py-2.5 last:border-b-0", b && "opacity-60")}>
      <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
        <PlayButton tag={it.key} url={url} player={player} label={it.name} />
        <div className="min-w-0 flex-1 basis-[200px]">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 break-words text-[15px] font-medium">{it.name}</span>
            <span className="shrink-0 text-[12px] tabular-nums text-sub">{sec(len)}</span>
          </div>
          {h?.desc && <div className="mt-0.5 text-[13px] text-sub">{h.desc}</div>}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {h && h.speech === "words" && h.words && <Chip tone="warn">낱말 대사 "{h.words}"</Chip>}
            {!h && <Chip tone="mute" title="Gemini 가 듣지 않아 파일 이름으로 정했습니다">이름으로 정함</Chip>}
            {back && <Chip tone="accent">고침</Chip>}
            {dropped && why.map((w) => <Chip key={w} tone="bad">{w}</Chip>)}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-1.5 pl-10 sm:w-auto sm:flex-nowrap sm:pl-0">
          {!dropped && (
              <select value={it.type ?? ""} disabled={b} aria-label={`${it.name} 종류`} onChange={(e) => change({ key: it.key, type: e.target.value })} className={SELECT}>
                {d.groups_def.map((g) => <option key={g.id} value={g.id}>{g.id} — {g.label}</option>)}
              </select>
            )}
            {dropped
              ? <Button size="sm" variant="secondary" disabled={b} icon={<Plus size={14} {...ICON} />} onClick={() => change({ key: it.key, keep: true, type: fitType() })}>넣기</Button>
              : <Button size="sm" variant="ghost" disabled={b} icon={<X size={14} {...ICON} />} onClick={() => change({ key: it.key, keep: false })}>빼기</Button>}
            {back && <Button size="sm" variant="ghost" disabled={b} icon={<RotateCcw size={14} {...ICON} />} onClick={() => change({ key: it.key, reset: true })}>되돌리기</Button>}
        </div>
      </div>
      {errs[it.key] && <p role="status" className="mt-1 pl-10 text-[13px] text-bad-text">{errs[it.key]}</p>}
      {player.note?.tag === it.key && <p role="status" className="mt-1 pl-10 text-[13px] text-sub">{player.note.msg}</p>}
    </div>
  );
}

function SfxBody({ ctx }: { ctx: RowCtx }) {
  const { d } = ctx;
  const items = d.items as SfxItem[];
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);
  const kept = items.filter((i) => i.keep);
  const dropped = items.filter((i) => !i.keep);
  const known = new Set(d.groups_def.map((g) => g.id));
  const other = kept.filter((i) => !i.type || !known.has(i.type));
  const reasons = countReasons(dropped.map((i) => (i.auto.why.length ? i.auto.why : ["내가 뺌"])));
  const shown = dropped.filter((i) => !why || (i.auto.why.length ? i.auto.why : ["내가 뺌"]).includes(why));
  return (
    <>
      {d.groups_def.map((g) => {
        const rows = kept.filter((i) => i.type === g.id);
        return (
          <Card key={g.id} className="mt-4 p-4 sm:p-5">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="min-w-0 text-[17px] font-semibold tracking-[-0.01em]"><span className="font-mono text-[15px]">{g.id}</span> — {g.label}</h2>
              <span className={cx("shrink-0 text-[13px] tabular-nums", rows.length >= g.want ? "text-ok-text" : "text-sub")}>{rows.length}/{g.want}</span>
            </div>
            {rows.length === 0 ? <p className="mt-2 text-[13px] text-sub">이 종류로 고른 소리가 없습니다.</p>
              : <div className="mt-1">{rows.map((it) => <SfxRow key={it.key} it={it} ctx={ctx} />)}</div>}
          </Card>
        );
      })}
      {other.length > 0 && (
        <Card className="mt-4 p-4 sm:p-5">
          <h2 className="text-[17px] font-semibold">그 밖의 종류</h2>
          <div className="mt-1">{other.map((it) => <SfxRow key={it.key} it={it} ctx={ctx} />)}</div>
        </Card>
      )}
      <Card className="mt-4 p-4 sm:p-5">
        <Fold open={open} onToggle={() => setOpen(!open)}>뺀 소리 ({dropped.length})</Fold>
        {open && (dropped.length === 0 ? <p className="mt-2 text-[13px] text-sub">뺀 소리가 없습니다.</p> : (
          <>
            <ReasonFilter reasons={reasons} value={why} onChange={(v) => { setWhy(v); setLimit(50); }} />
            <div className="mt-2">{shown.slice(0, limit).map((it) => <SfxRow key={it.key} it={it} ctx={ctx} dropped />)}</div>
            {shown.length > limit && <Button size="sm" variant="secondary" className="mt-2" onClick={() => setLimit(limit + 50)}>더 보기 ({shown.length - limit}개 남음)</Button>}
          </>
        ))}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- 짤

function MemeCard({ it, ctx, dropped }: { it: MemeItem; ctx: RowCtx; dropped?: boolean }) {
  const { d, busy, errs, change } = ctx;
  const b = busy.has(it.key);
  const [name, setName] = useState(it.name);
  const [meaning, setMeaning] = useState(it.meaning);
  useEffect(() => setName(it.name), [it.name]);
  useEffect(() => setMeaning(it.meaning), [it.meaning]);
  const saveName = () => { const v = name.trim(); if (v && v !== it.name) change({ key: it.key, name: v }); else setName(it.name); };
  const saveMeaning = () => { const v = meaning.trim(); if (v !== it.meaning) change({ key: it.key, meaning: v }); };
  const toggleBeat = (id: string) => {
    const has = it.beats.includes(id);
    if (has && it.beats.length <= 1) return;       // 하나는 남겨야 한다
    change({ key: it.key, beats: has ? it.beats.filter((x) => x !== id) : [...it.beats, id] });
  };
  const fam = d.families_def.find((f) => f.id === it.family)?.label ?? it.family;
  const why = it.auto.why.length ? it.auto.why : ["내가 뺌"];
  const back = edited(it);
  return (
    <Card className={cx("flex min-w-0 flex-col overflow-hidden", b && "opacity-60")}>
      <div className="flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-line bg-fill" style={it.transparent ? CHECKER : undefined}>
        <img src={libraryFileUrl("meme", d.id, { key: it.key })} alt={it.name} loading="lazy" className="h-full w-full object-contain" />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        {dropped ? <div className="break-words text-[14px] font-medium">{it.name}</div> : (
          <input value={name} disabled={b} aria-label="짤 이름" maxLength={40} onChange={(e) => setName(e.target.value)} onBlur={saveName}
            onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} className={cx(FIELD, "h-9 font-medium")} />
        )}
        {!dropped && (
          <textarea value={meaning} disabled={b} aria-label="뜻 (어떤 문장 뒤에 붙는 반응인지)" rows={3} maxLength={200} placeholder="어떤 문장 바로 뒤에 붙는 반응인지"
            onChange={(e) => setMeaning(e.target.value)} onBlur={saveMeaning} className={cx(FIELD, "resize-y py-1.5 text-[13px] leading-snug")} />
        )}
        {dropped && <div className="flex flex-wrap gap-1.5">{why.map((w) => <Chip key={w} tone="bad">{w}</Chip>)}</div>}
        <div className="flex flex-wrap items-center gap-1.5">
          {fam && <Chip tone="outline">{fam}</Chip>}
          {it.has_text && <Chip tone="mute" title={it.seen?.text || undefined}>글씨 있음</Chip>}
          {it.real_person && <Chip tone="warn" title="실제 사람 사진입니다. 쓰기 전에 직접 확인하세요">실제 인물</Chip>}
          {it.transparent && <Chip tone="mute">투명 배경</Chip>}
          {!it.seen && <Chip tone="mute" title="Gemini 가 보지 않아 파일 이름으로 정했습니다">이름으로 정함</Chip>}
          {back && <Chip tone="accent">고침</Chip>}
        </div>
        {!dropped && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="분위기 (맨 앞이 대표)">
            {d.beats_def.map((be) => {
              const idx = it.beats.indexOf(be.id);
              return (
                <button key={be.id} type="button" aria-pressed={idx >= 0} disabled={b} onClick={() => toggleBeat(be.id)}
                  title={idx === 0 ? "대표 분위기" : undefined}
                  className={cx("press inline-flex h-7 items-center rounded-lg px-2.5 text-[12px] font-medium disabled:opacity-60",
                    idx === 0 ? "bg-accent text-white" : idx > 0 ? "bg-[color-mix(in_srgb,var(--c-accent)_14%,transparent)] text-accent" : "bg-fill text-sub hover:text-ink")}>{be.label}</button>
              );
            })}
          </div>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
          {dropped
            ? <Button size="sm" variant="secondary" disabled={b} icon={<Plus size={14} {...ICON} />} onClick={() => change({ key: it.key, keep: true })}>넣기</Button>
            : <Button size="sm" variant="ghost" disabled={b} icon={<X size={14} {...ICON} />} onClick={() => change({ key: it.key, keep: false })}>빼기</Button>}
          {back && <Button size="sm" variant="ghost" disabled={b} icon={<RotateCcw size={14} {...ICON} />} onClick={() => change({ key: it.key, reset: true })}>되돌리기</Button>}
        </div>
        {errs[it.key] && <p role="status" className="text-[13px] text-bad-text">{errs[it.key]}</p>}
      </div>
    </Card>
  );
}

const GRID = "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

function MemeBody({ ctx }: { ctx: RowCtx }) {
  const items = ctx.d.items as MemeItem[];
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState<string | null>(null);
  const kept = items.filter((i) => i.keep);
  const dropped = items.filter((i) => !i.keep);
  const reasons = countReasons(dropped.map((i) => (i.auto.why.length ? i.auto.why : ["내가 뺌"])));
  const shown = dropped.filter((i) => !why || (i.auto.why.length ? i.auto.why : ["내가 뺌"]).includes(why));
  return (
    <>
      <h2 className="mt-6 text-[17px] font-semibold">고른 짤 ({kept.length})</h2>
      {kept.length === 0 ? <p className="mt-2 text-[13px] text-sub">고른 짤이 없습니다.</p>
        : <div className={cx("mt-3", GRID)}>{kept.map((it) => <MemeCard key={it.key} it={it} ctx={ctx} />)}</div>}
      <div className="mt-6">
        <Fold open={open} onToggle={() => setOpen(!open)}>뺀 짤 ({dropped.length})</Fold>
        {open && (dropped.length === 0 ? <p className="mt-2 text-[13px] text-sub">뺀 짤이 없습니다.</p> : (
          <>
            <ReasonFilter reasons={reasons} value={why} onChange={setWhy} />
            <div className={cx("mt-3", GRID)}>{shown.map((it) => <MemeCard key={it.key} it={it} ctx={ctx} dropped />)}</div>
          </>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- 쪽

export default function Library({ kind, id }: { kind: LibKind; id: string }) {
  const [d, setD] = useState<PackDetail | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [act, setAct] = useState<"" | "use" | "again" | "stop" | "delete">("");
  const [actErr, setActErr] = useState<string | null>(null);
  const player = usePlayer();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const running = !!d && isRunning(d.state);

  // 처음 한 번 읽고, 분석 중이면 1.5초마다 다시 읽는다
  useEffect(() => {
    let dead = false;
    let timer: number | undefined;
    const loop = async () => {
      let again = true;
      try {
        const v = await api.libraryPack(kind, id);
        if (dead) return;
        setD((old) => (old && busy.size ? old : v));
        setLoadErr(null);
        again = isRunning(v.state);
      } catch (e) { if (!dead) { setLoadErr((e as Error).message); again = false; } }
      if (!dead && again) timer = window.setTimeout(loop, 1500);
    };
    loop();
    return () => { dead = true; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, id, running]);

  async function change(c: LibraryChange) {
    setBusy((s) => new Set(s).add(c.key));
    setErrs((e) => { const n = { ...e }; delete n[c.key]; return n; });
    try {
      const v = await api.libraryChange(kind, id, [c]);
      if (alive.current) setD(v);
    } catch (e) {
      if (alive.current) setErrs((m) => ({ ...m, [c.key]: errText(e) }));
    } finally {
      if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(c.key); return n; });
    }
  }

  async function run(what: typeof act, fn: () => Promise<void>) {
    setAct(what);
    setActErr(null);
    try { await fn(); } catch (e) { if (alive.current) setActErr((e as Error).message); } finally { if (alive.current) setAct(""); }
  }
  const merge = (s: Partial<PackDetail>) => setD((old) => (old ? { ...old, ...s } as PackDetail : old));

  const back = <a href="#/settings" className="inline-flex items-center gap-1 text-[13px] font-medium text-sub no-underline hover:text-ink"><ChevronLeft size={15} {...ICON} />설정</a>;
  const title = kind === "sfx" ? "효과음 꾸러미" : "짤 꾸러미";
  if (!d) {
    return (
      <div className="mx-auto max-w-[960px]">
        {back}
        <h1 className="mt-2 text-[28px] font-semibold tracking-[-0.02em]">{title}</h1>
        <p className={cx("mt-4 text-[15px]", loadErr ? "text-bad-text" : "text-sub")}>{loadErr ?? "불러오는 중…"}</p>
      </div>
    );
  }

  const ctx: RowCtx = { d, busy, errs, change, player };
  const tone = d.state === "done" ? "ok" : d.state === "error" ? "bad" : d.state === "stopped" ? "warn" : "accent";
  const sheetUrl = libraryFileUrl("sfx", d.id, { out: "_sheet" });

  return (
    <div className="mx-auto max-w-[960px]">
      {back}
      <h1 className="mt-2 text-[28px] font-semibold tracking-[-0.02em]">{title}</h1>
      <div className="mt-1 text-[12px] text-sub">원래 폴더</div>
      <div className="break-all font-mono text-[13px]">{d.source_dir}</div>

      <Card className="mt-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Status tone={tone} pulse={running}>{running ? d.progress.step || STATE_LABEL[d.state] : STATE_LABEL[d.state]}</Status>
          {!running && d.counts.files > 0 && <span className="text-[14px]">파일 {d.counts.files}개 중 {d.counts.kept}개 고름</span>}
          {d.used && !running && <Status tone="ok">영상에 쓰는 중</Status>}
        </div>

        {running && (
          <div role="status" className="mt-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[13px] font-medium">{d.progress.step} {d.progress.done}/{d.progress.total}</span>
              <Button size="sm" variant="secondary" disabled={act === "stop"} icon={<Square size={14} {...ICON} />}
                onClick={() => run("stop", async () => merge(await api.libraryStop(kind, id)))}>{act === "stop" ? "멈추는 중…" : "멈춤"}</Button>
            </div>
            <Progress className="mt-2" value={d.progress.done / Math.max(d.progress.total, 1)} />
          </div>
        )}
        {d.state === "error" && <p role="status" className="mt-2 text-[13px] text-bad-text">{d.message || "분석에 실패했습니다"}</p>}
        {!running && d.state !== "error" && d.message && <p role="status" className="mt-2 text-[13px] text-warn-text">{d.message}</p>}
        {!running && !d.listened && d.state !== "error" && !d.message && (
          <p role="status" className="mt-2 text-[13px] text-warn-text">Gemini 키가 없어 파일 이름으로만 정했습니다</p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {d.used
            ? <Button size="sm" variant="secondary" disabled={running || !!act} icon={<X size={14} {...ICON} />} onClick={() => run("use", async () => merge(await api.libraryUse(kind, id, false)))}>영상에서 빼기</Button>
            : <Button size="sm" variant="primary" disabled={running || !!act || d.counts.kept === 0} onClick={() => run("use", async () => merge(await api.libraryUse(kind, id, true)))}>영상에 쓰기</Button>}
          <Button size="sm" variant="secondary" disabled={running || !!act} icon={<RotateCcw size={14} {...ICON} />}
            onClick={() => run("again", async () => merge(await api.libraryAnalyze(kind, d.source_dir, d.used)))}>다시 분석</Button>
          {kind === "sfx" && (
            <Button size="sm" variant="secondary" disabled={running || d.counts.kept === 0} icon={player.playing === "sheet" ? <Square size={14} {...ICON} /> : <Play size={14} {...ICON} />}
              onClick={() => player.play("sheet", sheetUrl)}>{player.playing === "sheet" ? "멈춤" : "전체 들어보기"}</Button>
          )}
          <Button size="sm" variant="danger" disabled={running || !!act} className="sm:ml-auto" icon={<Trash2 size={14} {...ICON} />}
            onClick={() => {
              if (!window.confirm(`만들어 둔 꾸러미만 지웁니다. 원래 폴더(${d.source_dir})의 파일은 그대로 남습니다. 지울까요?`)) return;
              void run("delete", async () => { await api.libraryDelete(kind, id); go("/settings"); });
            }}>꾸러미 지우기</Button>
        </div>
        {(actErr || player.note?.tag === "sheet") && <p role="status" className={cx("mt-2 text-[13px]", actErr ? "text-bad-text" : "text-sub")}>{actErr ?? player.note?.msg}</p>}
        {!running && d.counts.files > 0 && <p className="mt-2 text-[12px] text-sub">고치면 꾸러미가 바로 다시 만들어집니다. 영상은 다음에 만들 때부터 새 꾸러미를 씁니다.</p>}
      </Card>

      {running ? <p className="mt-6 text-[14px] text-sub">분석이 끝나면 결과가 여기에 나옵니다. 분석 중에는 고칠 수 없습니다.</p>
        : kind === "sfx" ? <SfxBody ctx={ctx} /> : <MemeBody ctx={ctx} />}
    </div>
  );
}
