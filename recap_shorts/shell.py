"""한 창 여러 탭 껍데기: 위에 얇은 탭 줄, 아래에 iframe(둘 다 계속 살려 두고 display 로만 전환)."""
import json

SHELL_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"><title>커뮤니티 쇼츠 자동 제작</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
/* 앱(web/src/index.css)과 같은 색: 라이트가 기본, 시스템이 다크면 다크 */
:root{--bg:#f5f5f7;--surface:#fff;--ink:#1d1d1f;--sub:#6e6e73;--line:rgba(0,0,0,.08);--line-strong:rgba(0,0,0,.16);--accent:#0071e3;--ok:#34c759;--warn:#ff9f0a}
@media (prefers-color-scheme:dark){:root{--bg:#0a0a0b;--surface:#161618;--ink:#f5f5f7;--sub:#8e8e93;--line:rgba(255,255,255,.08);--line-strong:rgba(255,255,255,.18);--accent:#0a84ff}}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:500 13px/1.4 "Pretendard Variable",Pretendard,-apple-system,"Malgun Gothic",sans-serif;letter-spacing:-.011em;overflow:hidden;-webkit-font-smoothing:antialiased}
#bar{display:flex;align-items:stretch;height:34px;background:var(--surface);border-bottom:1px solid var(--line);padding:0 8px;gap:2px}
.tab{display:flex;align-items:center;gap:6px;padding:0 14px;border:0;background:none;color:var(--sub);font:inherit;cursor:pointer;border-bottom:2px solid transparent}
.tab:hover{color:var(--ink)}
.tab.on{color:var(--ink);font-weight:600;border-bottom-color:var(--accent)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--line-strong)}
.dot.starting{background:var(--warn)}.dot.on{background:var(--ok)}.dot.off{background:var(--line-strong)}
#main{position:absolute;top:34px;left:0;right:0;bottom:0}
.pane{position:absolute;inset:0;display:none;background:var(--bg)}
.pane.on{display:block}
iframe{position:absolute;inset:0;width:100%;height:100%;border:0;background:var(--bg)}
.msg{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--sub);font-size:15px;background:var(--bg)}
.msg[hidden]{display:none}
.msg button{background:var(--accent);color:#fff;border:0;border-radius:10px;height:40px;padding:0 16px;font-family:inherit;font-size:15px;font-weight:600;cursor:pointer}
</style></head><body>
<div id="bar"></div><div id="main"></div>
<script>
const TABS=__TABS__;
const bar=document.getElementById("bar"),main=document.getElementById("main"),T={};
let cur=TABS[0].id;
for(const t of TABS){
  const b=document.createElement("button");b.className="tab";b.type="button";
  b.innerHTML='<span class="dot starting"></span><span></span>';b.lastChild.textContent=t.title;
  b.onclick=()=>show(t.id);bar.appendChild(b);
  const p=document.createElement("div");p.className="pane";
  const f=document.createElement("iframe");f.title=t.title;
  const m=document.createElement("div");m.className="msg";m.innerHTML='<span></span>';
  p.append(f,m);main.appendChild(p);
  T[t.id]={t,b,p,f,m,loaded:false,state:"starting"};
}
function show(id){cur=id;for(const k in T){T[k].b.classList.toggle("on",k===id);T[k].p.classList.toggle("on",k===id)}}
function render(id,state){
  const x=T[id];x.state=state;x.b.firstChild.className="dot "+state;
  if(state==="on"&&!x.loaded){x.f.src=x.t.url;x.loaded=true}
  const msg=x.m,span=msg.firstChild;
  msg.hidden=x.loaded;
  if(!x.loaded){
    span.textContent=state==="off"?x.t.title+" 서버가 꺼져 있습니다":"켜는 중…";
    msg.querySelector("button")?.remove();
    if(state==="off"&&window.pywebview&&pywebview.api.relaunch){
      const r=document.createElement("button");r.textContent="다시 켜기";
      r.onclick=()=>pywebview.api.relaunch(id);msg.appendChild(r)}
  }
}
async function poll(){
  let st=null;
  try{
    if(window.pywebview&&pywebview.api&&pywebview.api.status)st=await pywebview.api.status();
    else{ // 창 밖(브라우저 미리보기): 응답이 오는지만 본다
      st={};for(const k in T){try{await fetch(T[k].t.probe,{mode:"no-cors"});st[k]="on"}catch(e){st[k]="starting"}}
    }
  }catch(e){}
  if(st)for(const k in T)if(st[k])render(k,st[k]);
  setTimeout(poll,T[cur].state==="on"&&Object.values(T).every(x=>x.state==="on")?5000:1500);
}
document.addEventListener("keydown",e=>{
  if(e.ctrlKey&&e.key>="1"&&e.key<=String(TABS.length)){show(TABS[e.key-1].id);e.preventDefault()}});
show(cur);poll();
</script></body></html>
"""


def shell_html(sul_url: str, tabs=()) -> str:
    """탭 정의(JSON)를 끼워 넣은 껍데기 HTML. tabs: [{id,title,url,probe}] — 첫 탭은 늘 썰쇼츠."""
    all_tabs = [{"id": "sul", "title": "썰쇼츠", "url": sul_url, "probe": sul_url}, *tabs]
    return SHELL_HTML.replace("__TABS__", json.dumps(all_tabs, ensure_ascii=False))
