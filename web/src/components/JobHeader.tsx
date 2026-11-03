import { ChevronLeft, Cloud, ExternalLink } from "lucide-react";
import { Segmented, Status, ICON, type Tone } from "../ui";
import { go } from "../hooks";
import { isArchived } from "../lib";
import type { JobState } from "../types";

export const GALLERY: Record<string, string> = { baseball_new13: "국내야구", mlb_new10: "해외야구" };

export function jobTone(s: JobState["status"]): { tone: Tone; label: string; pulse?: boolean } {
  if (s === "running") return { tone: "accent", label: "만드는 중", pulse: true };
  if (s === "waiting") return { tone: "warn", label: "확인 기다림" };
  if (s === "error") return { tone: "bad", label: "오류" };
  return { tone: "ok", label: "완료" };
}

type Tab = "make" | "script" | "scenes" | "review";
/** 글 출처 이름. source.site 가 없던 때의 작업은 디시로 읽는다(서버 pipeline.site_of 와 같은 규칙). */
export function sourceLabel(src: JobState["source"]): string {
  if (src.site === "blind") return `블라인드 ${src.topic || "블라인드"} 토픽 · 글 ${src.no}`;
  return `${GALLERY[src.gallery] ?? src.gallery} 갤러리 · 글 번호 ${src.no}`;
}

export default function JobHeader({ job, tab }: { job: JobState; tab: Tab }) {
  const st = jobTone(job.status);
  const base = `/job/${encodeURIComponent(job.id)}`;
  const paths: Record<Tab, string> = { make: base, script: `${base}/script`, scenes: `${base}/scenes`, review: `${base}/review` };
  return (
    <div className="mb-8">
      {isArchived(job) && (
        <div role="status" className="mb-4 rounded-[14px] border border-line bg-fill px-4 py-3 text-[14px] leading-snug">
          <div className="flex items-center gap-2 font-medium"><Cloud size={16} {...ICON} />구글 드라이브에 보관된 작업입니다. 고칠 수 없습니다.</div>
          <div className="mt-1 break-all text-[13px] text-sub">{job.archive?.path}{job.offline ? " — 드라이브를 읽을 수 없어 영상·그림이 보이지 않습니다. Google Drive 를 켜 주세요." : ""}</div>
        </div>
      )}
      <a href="#/" className="mb-3 inline-flex items-center gap-1 text-[13px] text-sub no-underline hover:text-ink"><ChevronLeft size={16} {...ICON} />처음으로</a>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold leading-[1.25] tracking-[-0.02em] sm:text-[34px]">{job.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-sub">
            <Status tone={st.tone} pulse={st.pulse}>{st.label}</Status>
            <span>{sourceLabel(job.source)}</span>
            <a href={job.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sub no-underline hover:text-ink">원문 열기<ExternalLink size={13} {...ICON} /></a>
          </div>
        </div>
        <Segmented<Tab> value={tab} onChange={(t) => go(paths[t])}
          options={[{ value: "make", label: "제작" }, { value: "script", label: "대본" }, { value: "scenes", label: "장면" }, { value: "review", label: "검수" }]} />
      </div>
    </div>
  );
}
