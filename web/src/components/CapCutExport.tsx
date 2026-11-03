import { Clapperboard } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtWhen } from "../lib";
import { Button, Chip, ICON, Status } from "../ui";
import type { CapCutResult } from "../types";

const MODE: Record<string, [string, "ok" | "warn" | "mute"]> = { native: ["그대로", "ok"], approx: ["비슷하게", "warn"], skipped: ["안 넣음", "mute"] };

/** 검수 화면: 영상 파일 대신 CapCut 에서 그림·글자·소리를 따로 고칠 수 있는 초안으로 넘긴다. */
export default function CapCutExport({ id, disabled }: { id: string; disabled?: boolean }) {
  const [res, setRes] = useState<CapCutResult | null>(null);
  const [fresh, setFresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openMsg, setOpenMsg] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.capcut(id).then((r) => { if (live && r.last) setRes(r.last); }).catch(() => { /* 기록이 없어도 버튼은 쓴다 */ });
    return () => { live = false; };
  }, [id]);

  const send = async () => {
    setBusy(true); setErr(null); setOpenMsg(null);
    try { setRes(await api.capcutExport(id)); setFresh(true); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const open = async () => {
    setOpenMsg(null);
    try { const r = await api.capcutOpen(); setOpenMsg(r.launched ? "캡컷을 여는 중입니다." : r.reason || "캡컷을 열지 못했습니다."); } catch (e) { setOpenMsg((e as Error).message); }
  };

  return (
    <div className="space-y-2">
      <Button variant="secondary" className="w-full" icon={<Clapperboard size={16} {...ICON} />} disabled={busy || disabled} onClick={send}>
        {busy ? "캡컷 초안을 만드는 중" : "캡컷으로 넘기기"}
      </Button>
      {err && <p className="text-[13px] text-bad-text">{err}</p>}
      {res && (
        <div className="space-y-2 rounded-[10px] bg-fill p-3 text-[13px]">
          {fresh ? (
            <Status tone={res.registered ? "ok" : "warn"}>{res.registered ? "캡컷 프로젝트 맨 앞에 넣었습니다" : "초안 폴더만 만들었습니다"}</Status>
          ) : (
            <Status tone={res.exists === false ? "mute" : "ok"}>{res.exists === false ? "지난번 초안이 지워졌습니다" : `지난번에 넘김 · ${fmtWhen(res.exported_at)}`}</Status>
          )}
          <div className="break-all text-sub">{res.draft_name}</div>
          {fresh && res.warnings.map((w) => <p key={w} className="text-warn-text">{w}</p>)}
          {(fresh || res.exists !== false) && <Button size="sm" variant="ghost" className="w-full" onClick={open}>캡컷 열기</Button>}
          {openMsg && <p className="text-sub">{openMsg}</p>}
          {fresh && res.report.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sub">캡컷에 어떻게 들어갔나</summary>
              <ul className="mt-2 space-y-1.5">
                {res.report.map((r) => (
                  <li key={r.element} className="flex items-start gap-2">
                    <Chip tone={MODE[r.mode]?.[1] ?? "mute"} className="shrink-0">{MODE[r.mode]?.[0] ?? r.mode}</Chip>
                    <span><span className="font-medium text-ink">{r.element}</span> <span className="text-sub">{r.note}</span></span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
