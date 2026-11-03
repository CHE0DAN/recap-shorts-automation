import { Check, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

export function cx(...a: (string | false | null | undefined)[]) { return a.filter(Boolean).join(" "); }

export const ICON = { strokeWidth: 1.5 } as const; // lucide 선 굵기는 1.5 만 쓴다

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("rounded-[14px] border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]", className)} {...rest}>{children}</div>;
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "secondary", size = "md", icon, children, className, ...rest }:
  { variant?: Variant; size?: "sm" | "md" | "lg"; icon?: ReactNode; children?: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const v: Record<Variant, string> = {
    primary: "bg-accent text-white hover:brightness-[1.06] disabled:opacity-40",
    secondary: "bg-fill text-ink hover:bg-[color-mix(in_srgb,var(--c-ink)_9%,var(--c-fill))] disabled:text-sub disabled:opacity-60",
    ghost: "text-sub hover:bg-fill hover:text-ink disabled:opacity-40",
    danger: "bg-fill text-bad-text hover:bg-[color-mix(in_srgb,var(--c-bad)_14%,var(--c-fill))] disabled:opacity-40",
  };
  const s = { sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg", md: "h-10 px-4 text-[15px] gap-2 rounded-[10px]", lg: "h-12 px-5 text-[15px] gap-2 rounded-[10px]" }[size];
  return (
    <button className={cx("press inline-flex select-none items-center justify-center whitespace-nowrap font-semibold disabled:cursor-not-allowed", v[variant], s, className)} {...rest}>
      {icon}{children}
    </button>
  );
}

export function IconButton({ title, children, active, className, ...rest }: { title: string; children: ReactNode; active?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button title={title} aria-label={title}
      className={cx("press inline-flex h-8 w-8 items-center justify-center rounded-lg text-sub hover:bg-fill hover:text-ink disabled:opacity-40", active && "bg-fill text-ink", className)} {...rest}>
      {children}
    </button>
  );
}

export type Tone = "ok" | "warn" | "bad" | "accent" | "mute";
const DOT: Record<Tone, string> = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", accent: "bg-accent", mute: "bg-line-strong" };
const TEXT: Record<Tone, string> = { ok: "text-ok-text", warn: "text-warn-text", bad: "text-bad-text", accent: "text-accent", mute: "text-sub" };
/** 상태 점 + 글자. 상태 색은 점과 글자에만 쓰고 배경은 칠하지 않는다. */
export function Status({ tone = "mute", pulse, children, className }: { tone?: Tone; pulse?: boolean; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-[13px] font-medium leading-none", TEXT[tone], className)}>
      <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full", DOT[tone], pulse && "pulse")} />
      {children}
    </span>
  );
}
/** strong: 눈에 띄는 진한 칩(만든 적 있음), outline: 테두리만 있는 가벼운 칩(비슷한 이야기). 나머지는 Tone. */
export function Chip({ children, tone = "mute", className, title }: { children: ReactNode; tone?: Tone | "strong" | "outline"; className?: string; title?: string }) {
  const c = tone === "strong" ? "bg-ink text-surface"
    : tone === "outline" ? "border border-line-strong text-sub"
    : tone === "mute" ? "bg-fill text-sub"
    : tone === "accent" ? "bg-[color-mix(in_srgb,var(--c-accent)_12%,transparent)] text-accent"
    : tone === "warn" ? "bg-[color-mix(in_srgb,var(--c-warn)_16%,transparent)] text-warn-text"
    : tone === "bad" ? "bg-[color-mix(in_srgb,var(--c-bad)_13%,transparent)] text-bad-text"
    : "bg-[color-mix(in_srgb,var(--c-ok)_15%,transparent)] text-ok-text";
  return <span title={title} className={cx("inline-flex h-[22px] items-center whitespace-nowrap rounded-lg px-2 text-[11px] font-medium", c, className)}>{children}</span>;
}

export function Progress({ value, className, tone = "accent" }: { value: number; className?: string; tone?: "accent" | "ok" }) {
  return (
    <div className={cx("h-1 overflow-hidden rounded-full bg-fill", className)} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx("bar h-full rounded-full", tone === "ok" ? "bg-ok" : "bg-accent")} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}

export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return <div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-[20px] font-semibold tracking-[-0.01em]">{children}</h2>{right}</div>;
}
export function Label({ children }: { children: ReactNode }) { return <div className="text-[11px] font-medium text-sub">{children}</div>; }

export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return (
    <div className="inline-flex rounded-[10px] bg-fill p-0.5" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={cx("press h-8 rounded-lg px-3 text-[13px] font-medium", o.value === value ? "bg-surface text-ink shadow-[0_1px_2px_rgba(0,0,0,0.08)]" : "text-sub hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fade fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-label={title} className={cx("sheet-in flex max-h-[88vh] w-full flex-col overflow-hidden rounded-t-[14px] border border-line bg-surface shadow-[0_12px_40px_rgba(0,0,0,0.14)] sm:rounded-[14px]", wide ? "sm:max-w-[920px]" : "sm:max-w-[560px]")}>
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-[20px] font-semibold tracking-[-0.01em]">{title}</h2>
          <IconButton title="닫기" onClick={onClose}><X size={18} {...ICON} /></IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

export function StepMark({ status, size = 16 }: { status: string; size?: number }) {
  if (status === "done") return <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-ok text-white" style={{ width: size, height: size }}><Check size={size - 6} strokeWidth={2.5} /></span>;
  const c = status === "running" ? "border-accent" : status === "waiting" ? "border-warn" : status === "error" ? "border-bad" : "border-line-strong";
  const f = status === "running" ? "bg-accent pulse" : status === "waiting" ? "bg-warn" : status === "error" ? "bg-bad" : "";
  return <span className={cx("inline-flex shrink-0 items-center justify-center rounded-full border-[1.5px]", c)} style={{ width: size, height: size }}>{f && <span className={cx("rounded-full", f)} style={{ width: size - 9, height: size - 9 }} />}</span>;
}

export const fmtTime = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
export const fmtClock = (iso: string) => { const d = new Date(iso); return isNaN(+d) ? "" : d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); };
export const fmtAgo = (iso: string) => {
  const m = Math.round((Date.now() - +new Date(iso)) / 60000);
  if (isNaN(m)) return "";
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  if (m < 1440) return `${Math.round(m / 60)}시간 전`;
  return `${Math.round(m / 1440)}일 전`;
};
export const fmtNum = (n: number) => n.toLocaleString("ko-KR");
