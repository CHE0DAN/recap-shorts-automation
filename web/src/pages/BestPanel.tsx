import { ChevronDown, RefreshCw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { api, createJobAsking, type TopicSource } from "../api";
import { go, useLoad } from "../hooks";
import { fmtWhen } from "../lib";
import { Button, Chip, ICON, Segmented, cx, fmtNum } from "../ui";
import type { BestResponse, BestSort, BestTopic, Channel, Made } from "../types";

const HOURS = [12, 24, 48];
const withDot = (s: string) => (/[.!?]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`);   // 서버 안내 뒤에 문장을 이어 붙일 때
const ago = (h: number) => (h < 1 ? `${Math.max(1, Math.round(h * 60))}분 전` : h < 24 ? `${Math.round(h)}시간 전` : `${Math.round(h / 24)}일 전`);

/** 같은 글(또는 같은 원본)로 이미 만들었다 — 'similar'(비슷한 이야기)는 해당하지 않는다. */
export const isSameMade = (m?: Made | null) => m?.kind === "same_post" || m?.kind === "same_original";
/** 만든 적 있음 / 비슷한 이야기 칩의 마우스 설명: 우리 영상 제목과 날짜. */
export const madeTip = (m: Made) => m.kind === "similar"
  ? `제목이 비슷한 이야기를 이미 만들었습니다 (겹침 ${Math.round(m.score * 100)}%) — ${fmtWhen(m.created_at)} · ${m.our_title}`
  : `이미 만든 글입니다${m.count > 1 ? ` (${m.count}번)` : ""} — ${fmtWhen(m.created_at)} · ${m.our_title}${m.finished ? "" : " (영상까지는 안 끝남)"}`;
export function MadeChip({ m }: { m?: Made | null }) {
  if (!m) return null;
  return isSameMade(m)
    ? <Chip tone="strong" className="cursor-help" title={madeTip(m)}>만든 적 있음</Chip>
    : <Chip tone="outline" className="cursor-help" title={madeTip(m)}>비슷한 이야기 만듦</Chip>;
}

function Card({ t, busy, onMake, muted, topic }: { t: BestTopic; busy: boolean; onMake: () => void; muted?: boolean; topic?: string }) {
  const dup = isSameMade(t.made);
  return (
    <div className="flex flex-col rounded-[14px] border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="flex flex-wrap items-center gap-1.5">
        <MadeChip m={t.made} />
        {t.fit === 2 && <Chip tone="accent"><span title={`채널 대주제 '${topic}'에 딱 맞는 글`}>딱 맞음</span></Chip>}
        {t.fit === 1 && <Chip><span title={`채널 대주제 '${topic}'에 조금 맞는 글`}>조금</span></Chip>}
        {t.tag && <Chip>{t.tag}</Chip>}
        {t.category && <Chip tone="mute">{t.category.label}</Chip>}
        {t.source_check && <Chip tone="warn" className="cursor-help"><span title={t.source_check_reason ?? "원본 출처를 확인해야 하는 글"}>출처 확인 필요</span></Chip>}
      </div>
      <div className={cx("mt-2.5 line-clamp-2 min-h-[2.9em] text-[15px] font-semibold leading-snug", (muted || t.fit === 0 || dup) && "text-sub")}>{t.title}</div>
      <div className="mt-2 text-[13px] text-sub">조회 {fmtNum(t.views)} · 댓글 {fmtNum(t.comments)} · {ago(t.age_hours)}</div>
      {t.hidden_reason.length > 0 && <div className="mt-1 text-[13px] text-warn-text">주의: {t.hidden_reason.join(", ")}</div>}
      <div className="mt-3 flex items-center justify-between gap-2">
        <a href={t.url} target="_blank" rel="noreferrer" className="text-[13px] text-sub hover:text-ink">원문 보기</a>
        <Button size="sm" variant={muted || dup ? "secondary" : "primary"} disabled={busy} onClick={onMake}>만들기</Button>
      </div>
    </div>
  );
}

export default function BestPanel({ source = "dcbest" }: { source?: TopicSource }) {
  const [sort, setSort] = useState<BestSort>("views");
  const [hours, setHours] = useState(48);
  const [pages, setPages] = useState(3);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hideUnfit, setHideUnfit] = useState(false);
  const [hideMade, setHideMade] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [customText, setCustomText] = useState<string | null>(null);      // null = 아직 안 고침(저장된 글을 보여 줌)
  const [applying, setApplying] = useState(false);
  const blind = source === "blind";
  const { data, error, setData } = useLoad<BestResponse>(() => api.topicsBest(sort, hours, pages, source), [sort, hours, pages, source]);
  const ch = useLoad<Channel>(() => api.channel(), []);
  const channel = ch.data;

  const refresh = useCallback(async () => {
    setRefreshing(true); setErr(null);
    try { setData(await api.refreshBest(sort, hours, pages, source)); } catch (e) { setErr((e as Error).message); }
    setRefreshing(false);
  }, [sort, hours, pages, source, setData]);

  const { shown, hidden, fitN, madeN } = useMemo(() => {
    const all = data?.items ?? [];
    const unfitOk = hideUnfit ? all.filter((t) => t.fit !== 0) : all;      // 순서(딱 맞음 → 조금 → 아님)는 서버가 정해서 보낸다
    const items = hideMade ? unfitOk.filter((t) => !isSameMade(t.made)) : unfitOk;       // 같은 글만 숨김 — 비슷한 이야기는 표시만
    return { shown: items.filter((t) => !t.hidden), hidden: items.filter((t) => t.hidden),
      fitN: { 2: all.filter((t) => t.fit === 2).length, 1: all.filter((t) => t.fit === 1).length, 0: all.filter((t) => t.fit === 0).length },
      madeN: { same: all.filter((t) => isSameMade(t.made)).length, similar: all.filter((t) => t.made?.kind === "similar").length } };
  }, [data, hideUnfit, hideMade]);

  /** 채널 대주제를 바꾸고(저장) 목록을 다시 받는다 — 서버가 새 대주제로 점수를 매겨 순서를 바꿔 보낸다. */
  async function applyChannel(body: { main_topic: string | null; custom?: string | null }) {
    setApplying(true); setErr(null);
    try { ch.setData(await api.setChannel(body)); setCustomOpen(false); setData(await api.topicsBest(sort, hours, pages, source)); }
    catch (e) { setErr((e as Error).message); }
    setApplying(false);
  }
  function pickTopic(v: string) {
    if (v !== "custom") { setCustomOpen(false); applyChannel({ main_topic: v === "none" ? null : v }); return; }
    if (channel?.custom) applyChannel({ main_topic: "custom" }); else setCustomOpen(true);
  }
  const selValue = customOpen ? "custom" : (channel?.main_topic ?? "none");
  const customVal = customText ?? channel?.custom ?? "";

  async function make(t: BestTopic) {
    setBusy(true); setErr(null);
    try {
      const r = await createJobAsking({ url: t.url, title: (t.tag ? `[${t.tag}] ` : "") + t.title });      // 이미 만든 글이면 한 번 묻는다
      if (r) go(`/job/${encodeURIComponent(r.id)}`); else setBusy(false);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-3">
        <Segmented value={sort} onChange={setSort} options={[{ value: "views", label: "조회순" }, { value: "comments", label: "댓글순" }, { value: "recent", label: "최신순" }]} />
        <label className="flex items-center gap-2 text-[13px] text-sub">기간
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-fill px-2 text-[13px] text-ink">
            {HOURS.map((h) => <option key={h} value={h}>{h}시간</option>)}
          </select>
        </label>
        {!blind && (
          <label className="flex items-center gap-2 text-[13px] text-sub">쪽 수
            <select value={pages} onChange={(e) => setPages(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-fill px-2 text-[13px] text-ink">
              {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p}쪽</option>)}
            </select>
          </label>
        )}
        <Button size="sm" className="ml-auto" disabled={refreshing} onClick={refresh} icon={<RefreshCw size={15} {...ICON} className={cx(refreshing && "animate-spin")} />}>{refreshing ? "불러오는 중" : "새로 불러오기"}</Button>
      </div>
      {(channel || madeN.same > 0) && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-2.5">
          {channel && <label className="flex items-center gap-2 text-[13px] text-sub">채널 대주제
            <select value={selValue} disabled={applying} onChange={(e) => pickTopic(e.target.value)} className="h-8 rounded-lg border border-line bg-fill px-2 text-[13px] text-ink">
              <option value="none">없음</option>
              {channel.presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              <option value="custom">직접 입력</option>
            </select>
          </label>}
          {channel && selValue === "custom" && (
            <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (customVal.trim()) applyChannel({ main_topic: "custom", custom: customVal }); }}>
              <input value={customVal} onChange={(e) => setCustomText(e.target.value)} maxLength={200} placeholder="예: 게임 업계 소식과 논란" aria-label="직접 입력한 채널 대주제"
                className="h-8 w-56 rounded-lg border border-line bg-fill px-2 text-[13px] text-ink outline-none placeholder:text-sub/70 focus-visible:border-accent" />
              <Button size="sm" type="submit" disabled={applying || !customVal.trim()}>적용</Button>
            </form>
          )}
          {applying && <span className="text-[13px] text-sub">맞춤 점수를 매기는 중</span>}
          {!applying && data?.channel && data.fit !== "unavailable" && (
            <span className="text-[13px] text-sub">딱 맞음 {fitN[2]} · 조금 {fitN[1]} · 아님 {fitN[0]}</span>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-4">
            {data?.channel && data.fit !== "unavailable" && (
              <label className="flex items-center gap-2 text-[13px] text-sub">
                <input type="checkbox" checked={hideUnfit} onChange={(e) => setHideUnfit(e.target.checked)} />안 맞는 글 숨기기{fitN[0] > 0 && ` (${fitN[0]})`}
              </label>
            )}
            {madeN.same > 0 && (
              <label className="flex items-center gap-2 text-[13px] text-sub" title="이미 만든 글(같은 글)만 숨깁니다. 비슷한 이야기는 표시만 하고 남겨 둡니다.">
                <input type="checkbox" checked={hideMade} onChange={(e) => setHideMade(e.target.checked)} />만든 글 숨기기 ({madeN.same})
              </label>
            )}
          </div>
        </div>
      )}
      <div className="scroll-thin min-h-[320px] flex-1 overflow-y-auto px-6 py-4">
        {data && (data.fit === "unavailable" || data.fit === "partial") && <div className="mb-3 text-[13px] text-warn-text">{data.fit_note}</div>}
        {data && data.triage === "skipped" && <div className="mb-3 text-[13px] text-sub">{data.triage_note}</div>}
        {data && data.triage !== "ok" && data.triage !== "skipped" && <div className="mb-3 text-[13px] text-warn-text">{withDot(data.triage_note || "Clef 분류를 쓸 수 없어 분야·위험 표시 없이 목록만 보여 줍니다.")} 제목을 직접 읽고 골라 주세요.</div>}
        {!data && !error && <div className="py-10 text-[15px] text-sub">{blind
          ? "블라인드 인기글을 불러오는 중입니다. 블라인드에 부담을 주지 않도록 3초 쉬었다 받습니다."
          : "인기글을 불러오는 중입니다. 디시에 부담을 주지 않도록 쪽마다 3초씩 쉬어서 처음에는 10초쯤 걸립니다."}{channel?.main_topic && " 채널 대주제에 맞는지 제목마다 점수도 매기느라 몇 초 더 걸릴 수 있습니다."}</div>}
        {error && <div className="py-10 text-[15px] text-bad-text">목록을 불러오지 못했습니다. {error}</div>}
        {data && shown.length === 0 && hidden.length === 0 && (
          <div className="py-10 text-[15px] text-sub">{hideUnfit && data.items.length > 0 ? "채널 대주제에 맞는 글이 없습니다. '안 맞는 글 숨기기'를 끄거나 기간·쪽 수를 늘려 보세요." : hideMade && data.items.length > 0 ? "이미 만든 글을 빼고 나니 남은 글이 없습니다. '만든 글 숨기기'를 끄거나 기간·쪽 수를 늘려 보세요." : blind ? "이 기간에 올라온 블라인드 인기글이 없습니다. 기간을 늘려 보세요." : "이 기간에 올라온 글이 없습니다. 기간이나 쪽 수를 늘려 보세요."}</div>
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {shown.map((t) => <Card key={t.no} t={t} busy={busy} topic={data?.channel?.label} onMake={() => make(t)} />)}
        </div>
        {hidden.length > 0 && (
          <div className="mt-4 border-t border-line pt-2">
            <button onClick={() => setOpen(!open)} className="press flex w-full items-center gap-1.5 rounded-lg px-1 py-2 text-left text-[13px] font-medium text-sub hover:text-ink">
              <ChevronDown size={16} {...ICON} className={cx("transition-transform duration-200", !open && "-rotate-90")} />숨김 {hidden.length}개
              <span className="font-normal">— 특정인 비난, 성적 대상화, 확인 안 된 의혹 같은 위험 표시가 붙은 글</span>
            </button>
            {open && <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">{hidden.map((t) => <Card key={t.no} t={t} busy={busy} muted topic={data?.channel?.label} onMake={() => make(t)} />)}</div>}
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-line px-6 py-3 text-[13px] text-sub">
        <span>만들기를 누르면 이 글의 주소로 바로 제작을 시작합니다. {blind
          ? "블라인드 글은 Clef 분류 없이 제목·조회수만 보여 줍니다. 채널 대주제 맞춤 점수는 Gemini가 제목만 보고 매긴 참고 값입니다."
          : "분야·위험 표시는 Clef가, 대주제 맞춤 점수는 Gemini가 제목만 보고 매긴 참고 값입니다."} '만든 적 있음'·'비슷한 이야기 만듦'은 우리가 만든 작업(드라이브 보관 포함)과 글 주소·제목만 견준 표시이고, 다른 채널이 이미 올렸는지는 알 수 없습니다.</span>
        {err && <span className="text-bad-text">{err}</span>}
      </div>
    </>
  );
}
