import { useCallback, useEffect, useRef, useState } from "react";

/** 불러온 값. every(ms)가 있으면 그 간격으로 계속 다시 불러온다. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], every: number | null = null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    try { setData(await fnRef.current()); setError(null); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => {
    let dead = false;
    let timer: number | undefined;
    const loop = async () => {
      try { const v = await fnRef.current(); if (!dead) { setData(v); setError(null); } } catch (e) { if (!dead) setError((e as Error).message); }
      if (!dead && every) timer = window.setTimeout(loop, every);
    };
    loop();
    return () => { dead = true; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, every]);
  return { data, error, reload, setData };
}

export function useRoute() {
  const [h, setH] = useState(location.hash || "#/");
  useEffect(() => {
    const f = () => setH(location.hash || "#/");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h.replace(/^#/, "") || "/";
}
export const go = (path: string) => { location.hash = path; };

export function useCopy() {
  const [done, setDone] = useState(false);
  const copy = async (t: string) => {
    try { await navigator.clipboard.writeText(t); } catch { const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); }
    setDone(true);
    setTimeout(() => setDone(false), 1600);
  };
  return { done, copy };
}
