#!/usr/bin/env python3
"""Render the collected usage model into a single self-contained HTML file.

No external assets: all CSS/JS inline, every chart hand-rolled SVG, so the file
opens from disk with no network access.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Atlas</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --panel-2:#fbfbfd; --line:#e2e5ea;
  --fg:#16181d; --fg-dim:#5c6472; --fg-faint:#8b93a1;
  --accent:#4c6ef5; --hover:#eef1f7; --sel:#e0e8ff;
  --good:#0ca678; --warn:#f08c00; --bad:#e03131;
  --c-input:#4c6ef5; --c-output:#f08c00; --c-read:#0ca678; --c-write:#ae3ec9;
  --shadow:0 1px 3px rgba(16,20,30,.07),0 8px 24px rgba(16,20,30,.05);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0e1014; --panel:#161920; --panel-2:#1b1f27; --line:#282d38;
  --fg:#e8eaf0; --fg-dim:#a2abbb; --fg-faint:#6f7889;
  --accent:#748ffc; --hover:#20252f; --sel:#25304a;
  --good:#38d9a9; --warn:#ffa94d; --bad:#ff8787;
  --c-input:#748ffc; --c-output:#ffa94d; --c-read:#38d9a9; --c-write:#da77f2;
  --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}}
:root[data-theme="dark"]{
  --bg:#0e1014; --panel:#161920; --panel-2:#1b1f27; --line:#282d38;
  --fg:#e8eaf0; --fg-dim:#a2abbb; --fg-faint:#6f7889;
  --accent:#748ffc; --hover:#20252f; --sel:#25304a;
  --good:#38d9a9; --warn:#ffa94d; --bad:#ff8787;
  --c-input:#748ffc; --c-output:#ffa94d; --c-read:#38d9a9; --c-write:#da77f2;
  --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:11px 16px;
  background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30}
header h1{font-size:15px;margin:0;font-weight:650;letter-spacing:-.01em}
header h1 span{color:var(--fg-faint);font-weight:400}
.spacer{flex:1}
.meta{font-size:12px;color:var(--fg-faint);font-variant-numeric:tabular-nums}
button,select,input{font:inherit;font-size:12px;color:var(--fg-dim);background:var(--panel-2);
  border:1px solid var(--line);border-radius:7px;padding:5px 9px}
button{cursor:pointer}
button:hover{background:var(--hover);color:var(--fg)}
button[aria-pressed="true"]{background:var(--sel);color:var(--fg);border-color:var(--accent)}
select,input{color:var(--fg)}
input[type=search]{min-width:190px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.seg button{border:0;border-radius:0;border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}

#filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 16px;
  background:var(--panel-2);border-bottom:1px solid var(--line);position:sticky;top:53px;z-index:29}
#filters label{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--fg-faint);font-weight:700;margin-right:-4px}
.chip{font-size:11px;color:var(--fg-faint);font-variant-numeric:tabular-nums;margin-left:2px}

.layout{display:grid;grid-template-columns:280px minmax(0,1fr) 352px;
  height:calc(100vh - 100px);align-items:stretch}
.col{overflow-y:auto;overflow-x:hidden;padding:13px}
#nav{border-right:1px solid var(--line);background:var(--panel)}
#side{border-left:1px solid var(--line);background:var(--panel)}

.sec{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--fg-faint);margin:14px 0 7px;padding:0 4px}
.sec:first-child{margin-top:0}
.row{display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:6px;
  cursor:pointer;font-size:13px;white-space:nowrap}
.row:hover{background:var(--hover)}
.row.on{background:var(--sel)}
.tw{width:12px;flex:none;color:var(--fg-faint);font-size:9px;text-align:center;transition:transform .12s}
.tw.open{transform:rotate(90deg)}
.ico{width:15px;flex:none;text-align:center;font-size:11px;opacity:.85}
.lbl{overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}
.tag{font-size:10px;color:var(--fg-faint);font-variant-numeric:tabular-nums;
  font-family:var(--mono);flex:none}
.kids{margin-left:11px;border-left:1px solid var(--line);padding-left:4px;display:none}
.kids.open{display:block}
.sub{font-size:11px;color:var(--fg-faint);padding:2px 6px 6px 30px}

.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;
  padding:14px;margin-bottom:12px;box-shadow:var(--shadow)}
.card h2{margin:0 0 3px;font-size:14px;font-weight:650}
.card h3{margin:0 0 10px;font-size:10.5px;font-weight:700;letter-spacing:.09em;
  text-transform:uppercase;color:var(--fg-faint);display:flex;justify-content:space-between}
.path{font-family:var(--mono);font-size:11.5px;color:var(--fg-dim);word-break:break-all;margin-bottom:10px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:8px}
.kpi{background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:9px}
.kpi .k{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--fg-faint)}
.kpi .v{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em;margin-top:2px}
.kpi .s{font-size:10.5px;color:var(--fg-faint);font-variant-numeric:tabular-nums}

table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--fg-faint);font-weight:700;padding:5px 7px;border-bottom:1px solid var(--line);
  cursor:pointer;white-space:nowrap}
th:hover{color:var(--fg)}
td{padding:6px 7px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--hover)}
td.n{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono);font-size:11.5px}
.scroll{overflow-x:auto}

.legend{display:flex;flex-direction:column;gap:5px;margin-top:11px}
.li{display:flex;align-items:center;gap:7px;font-size:12px}
.sw{width:9px;height:9px;border-radius:2.5px;flex:none}
.li .nm{flex:1;color:var(--fg-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.li .vl{font-variant-numeric:tabular-nums;font-family:var(--mono);font-size:11px}
.li .pc{font-variant-numeric:tabular-nums;color:var(--fg-faint);font-size:11px;width:42px;text-align:right}
.bar{height:7px;border-radius:4px;background:var(--panel-2);overflow:hidden;display:flex}
.bar i{display:block;height:100%}
.mrow{margin-bottom:10px}
.mtop{display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  margin-bottom:4px;font-size:12px}
.mtop b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mtop span{font-family:var(--mono);font-size:11px;color:var(--fg-faint);flex:none}

.rec{border:1px solid var(--line);border-left:3px solid var(--good);border-radius:9px;
  padding:11px;margin-bottom:9px;background:var(--panel-2)}
.rec.low{border-left-color:var(--warn)}
.rec-h{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.rec-h b{font-size:13px}
.save{font-family:var(--mono);font-size:13px;font-weight:650;color:var(--good);white-space:nowrap}
.badge{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;padding:1.5px 6px;
  border-radius:999px;border:1px solid var(--line);color:var(--fg-faint)}
.badge.high{color:var(--good);border-color:var(--good)}
.badge.medium{color:var(--accent);border-color:var(--accent)}
.badge.low{color:var(--warn);border-color:var(--warn)}
.why{margin:7px 0 0;padding-left:15px;font-size:11.5px;color:var(--fg-dim)}
.why li{margin:1px 0}
.swap{font-family:var(--mono);font-size:11px;color:var(--fg-faint);margin-top:5px}
.empty{color:var(--fg-faint);font-size:12.5px;padding:8px 2px}
.note{font-size:11px;color:var(--fg-faint);margin-top:9px;line-height:1.45}
.warnbox{border:1px solid var(--warn);background:color-mix(in srgb,var(--warn) 8%,transparent);
  border-radius:9px;padding:10px;font-size:12px;margin-bottom:10px}
svg{display:block;max-width:100%}
.donut-mid{text-anchor:middle;font-variant-numeric:tabular-nums}
.donut-mid .big{font-size:19px;font-weight:650;fill:var(--fg)}
.donut-mid .small{font-size:9.5px;fill:var(--fg-faint);text-transform:uppercase;letter-spacing:.07em}
.axis{font-size:9px;fill:var(--fg-faint)}
.hm{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;margin-top:4px}
.hm i{display:block;height:22px;border-radius:2px;background:var(--accent)}
.hml{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;font-size:8px;
  color:var(--fg-faint);margin-top:2px;text-align:center}

@media (max-width:1180px){
  .layout{grid-template-columns:240px minmax(0,1fr);height:auto}
  #side{grid-column:1/-1;border-left:0;border-top:1px solid var(--line)}
  .col{overflow:visible}
  #nav{max-height:56vh;overflow-y:auto}
}
@media (max-width:760px){.layout{grid-template-columns:1fr}#nav{border-right:0}}
</style>
</head>
<body>
<header>
  <h1>Claude Atlas <span id="hcount"></span></h1>
  <div class="spacer"></div>
  <div class="seg" role="group" aria-label="Measure">
    <button id="mTok" aria-pressed="true">Tokens</button>
    <button id="mCost" aria-pressed="false">Cost</button>
  </div>
  <button id="theme">Theme</button>
  <div class="meta" id="hmeta"></div>
</header>

<div id="filters">
  <label for="fq">Filter</label>
  <input type="search" id="fq" placeholder="title, project, branch…" autocomplete="off">
  <select id="fproj"><option value="">All projects</option></select>
  <select id="fmodel"><option value="">All models</option></select>
  <select id="frange">
    <option value="0">Any time</option>
    <option value="7">Last 7 days</option>
    <option value="30">Last 30 days</option>
    <option value="90">Last 90 days</option>
  </select>
  <select id="fcost">
    <option value="0">Any cost</option>
    <option value="1">≥ $1</option>
    <option value="10">≥ $10</option>
    <option value="100">≥ $100</option>
  </select>
  <button id="frec" aria-pressed="false">Savings only</button>
  <button id="freset">Reset</button>
  <span class="chip" id="fcount"></span>
</div>

<div class="layout">
  <div class="col" id="nav"></div>
  <div class="col" id="main"></div>
  <div class="col" id="side"></div>
</div>

<script id="atlas-data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
const P = DATA.pricing;
const KEYS  = ["input","output","cache_read","cache_creation"];
const LABEL = {input:"Input",output:"Output",cache_read:"Cache read",cache_creation:"Cache write"};
const CVAR  = {input:"--c-input",output:"--c-output",cache_read:"--c-read",cache_creation:"--c-write"};

let measure = "tokens";
let sel = {kind:"all"};
let sortBy = {key:"cost", dir:-1};
const filters = {q:"", project:"", model:"", days:0, minCost:0, recOnly:false};

const ALL = [];
DATA.projects.forEach(p => p.sessions.forEach(s => ALL.push({s, p})));

/* ---------- format ---------- */
const esc = s => String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function abbr(n){n=n||0;
  if(n>=1e9)return (n/1e9).toFixed(n<1e10?2:1)+"B";
  if(n>=1e6)return (n/1e6).toFixed(n<1e7?2:1)+"M";
  if(n>=1e3)return (n/1e3).toFixed(n<1e4?1:0)+"K";
  return String(Math.round(n));}
const num=n=>(n||0).toLocaleString();
const usd=c=>((c||0)<0.01?"$0.00":"$"+(c||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}));
function bytes(b){if(b>=1e9)return (b/1e9).toFixed(1)+" GB";if(b>=1e6)return (b/1e6).toFixed(1)+" MB";
  if(b>=1e3)return (b/1e3).toFixed(0)+" KB";return b+" B";}
function when(iso){if(!iso)return "—";const d=new Date(iso);return isNaN(d)?"—":
  d.toLocaleString(undefined,{month:"short",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit"});}
function dur(m){if(!m)return "—";if(m<60)return m.toFixed(0)+"m";
  const h=Math.floor(m/60);return h+"h "+Math.round(m%60)+"m";}
const totalOf=u=>KEYS.reduce((a,k)=>a+(u&&u[k]||0),0);
const fmt=v=>measure==="cost"?usd(v):abbr(v);

/* ---------- cost (mirrors collect.py exactly) ---------- */
function rateFor(model, fast){
  let r = P.models[model];
  if(!r){const low=(model||"").toLowerCase();
    for(const t of P.fallback_order){if(low.includes(t)){r=P.models[P.fallback_tiers[t]];break;}}
    if(!r) r=P.models[P.fallback_tiers._default];}
  if(fast){ if(r.fast) return r.fast;
    const m=P.fast_fallback_multiplier||2; return {input:r.input*m, output:r.output*m}; }
  return r;
}
function costOf(u, model, fast){
  const r=rateFor(model,fast), inp=r.input;
  const cw1=u.cache_write_1h||0, cw5=u.cache_write_5m||0;
  const left=Math.max(0,(u.cache_creation||0)-cw1-cw5);
  return ((u.input||0)*inp + (u.output||0)*r.output
        + (u.cache_read||0)*inp*P.cache_read_multiplier
        + cw1*inp*P.cache_write_1h_multiplier
        + (cw5+left)*inp*P.cache_write_5m_multiplier)/1e6;
}
function costParts(models){
  const out={input:0,output:0,cache_read:0,cache_creation:0};
  for(const [m,slot] of Object.entries(models||{})){
    for(const variant of ["std","fast"]){
      const uv=slot[variant]; if(!uv) continue;
      const fast = variant==="fast";
      for(const k of KEYS){
        const one={input:0,output:0,cache_read:0,cache_creation:0,cache_write_1h:0,cache_write_5m:0};
        if(k==="cache_creation"){one.cache_write_1h=uv.cache_write_1h||0;
          one.cache_write_5m=uv.cache_write_5m||0;
          one.cache_creation=uv.cache_creation||0;}
        else one[k]=uv[k]||0;
        out[k]+=costOf(one,m,fast);
      }
    }
  }
  return out;
}

/* ---------- aggregation over a filtered session list ---------- */
function blankU(){return {input:0,output:0,cache_read:0,cache_creation:0,cache_write_1h:0,cache_write_5m:0};}
function addU(d,s){for(const k in d) d[k]+=(s[k]||0);}
function aggregate(list){
  const a={usage:blankU(),models:{},daily:{},hours:{},tools:{},
    tool_classes:{read:0,write:0,exec:0,other:0},stop_reasons:{},
    turns:0,thinking_turns:0,fast_turns:0,duration_minutes:0,cost:0,savings:0};
  for(const {s} of list){
    addU(a.usage,s.usage);
    for(const [m,sl] of Object.entries(s.models)){
      const t=a.models[m] || (a.models[m]={std:blankU(),fast:blankU(),messages:0,fast_messages:0,thinking_turns:0});
      addU(t.std,sl.std); addU(t.fast,sl.fast);
      t.messages+=sl.messages; t.fast_messages+=sl.fast_messages; t.thinking_turns+=sl.thinking_turns;
    }
    for(const [d,u] of Object.entries(s.daily)){ a.daily[d]=a.daily[d]||blankU(); addU(a.daily[d],u); }
    for(const [h,v] of Object.entries(s.hours)) a.hours[h]=(a.hours[h]||0)+v;
    for(const [n,v] of Object.entries(s.tools)) a.tools[n]=(a.tools[n]||0)+v;
    for(const k in a.tool_classes) a.tool_classes[k]+=s.tool_classes[k]||0;
    for(const [k,v] of Object.entries(s.stop_reasons)) a.stop_reasons[k]=(a.stop_reasons[k]||0)+v;
    a.turns+=s.turns; a.thinking_turns+=s.thinking_turns; a.fast_turns+=s.fast_turns;
    a.duration_minutes+=s.duration_minutes||0;
    a.cost+=s.cost;
    if(s.recommendation) a.savings+=s.recommendation.saving;
  }
  for(const [m,sl] of Object.entries(a.models)){
    const u=blankU(); addU(u,sl.std); addU(u,sl.fast);
    sl.usage=u; sl.total=totalOf(u);
    sl.cost=costOf(sl.std,m,false)+costOf(sl.fast,m,true);
  }
  a.total_tokens=totalOf(a.usage);
  return a;
}

/* ---------- filtering ---------- */
function passes({s,p}){
  if(filters.project && p.id!==filters.project) return false;
  if(filters.model && !(filters.model in s.models)) return false;
  if(filters.minCost && s.cost<filters.minCost) return false;
  if(filters.recOnly && !s.recommendation) return false;
  if(filters.days){
    const cutoff=Date.now()-filters.days*864e5;
    const t=Date.parse(s.ended||s.started||0);
    if(!t || t<cutoff) return false;
  }
  if(filters.q){
    const q=filters.q.toLowerCase();
    const hay=[(s.title||""),p.name,p.path,(s.branch||""),(s.primary_model||"")].join(" ").toLowerCase();
    if(!hay.includes(q)) return false;
  }
  return true;
}
function visible(){
  let list=ALL.filter(passes);
  if(sel.kind==="project") list=list.filter(x=>x.p.id===sel.id);
  else if(sel.kind==="session") list=list.filter(x=>x.s.id===sel.id);
  return list;
}
function scope(){
  const list=visible();
  const a=aggregate(list);
  if(sel.kind==="session" && list.length===1){
    const {s,p}=list[0];
    return {...a,title:s.title||"Untitled session",sub:p.path,session:s,project:p,list};
  }
  if(sel.kind==="project"){
    const p=DATA.projects.find(x=>x.id===sel.id);
    return {...a,title:p?p.name:"Project",sub:p?p.path:"",project:p,list};
  }
  return {...a,title:"All projects",sub:DATA.projects_root,list};
}

/* ---------- charts ---------- */
function donut(parts,label){
  const total=KEYS.reduce((s,k)=>s+(parts[k]||0),0);
  if(!total) return '<div class="empty">No usage in this selection.</div>';
  const R=54,r=36,cx=64,cy=64,C=2*Math.PI*((R+r)/2),W=R-r;
  let off=0,arcs="";
  for(const k of KEYS){
    const v=parts[k]||0; if(v<=0) continue;
    const len=C*(v/total);
    arcs+=`<circle cx="${cx}" cy="${cy}" r="${(R+r)/2}" fill="none" stroke="var(${CVAR[k]})"
      stroke-width="${W}" stroke-dasharray="${len.toFixed(3)} ${(C-len).toFixed(3)}"
      stroke-dashoffset="${(-off).toFixed(3)}" transform="rotate(-90 ${cx} ${cy})"><title>${LABEL[k]}: ${fmt(v)}</title></circle>`;
    off+=len;
  }
  const rows=KEYS.map(k=>{const v=parts[k]||0,pc=total?v/total*100:0;
    return `<div class="li"><span class="sw" style="background:var(${CVAR[k]})"></span>
      <span class="nm">${LABEL[k]}</span><span class="vl">${fmt(v)}</span>
      <span class="pc">${pc<0.1&&pc>0?"<0.1":pc.toFixed(1)}%</span></div>`;}).join("");
  return `<svg viewBox="0 0 128 128" width="128" height="128" style="margin:0 auto" role="img"
    aria-label="Composition">${arcs}<g class="donut-mid"><text x="64" y="62" class="big">${fmt(total)}</text>
    <text x="64" y="76" class="small">${esc(label)}</text></g></svg><div class="legend">${rows}</div>`;
}
function modelBars(models){
  const rows=Object.entries(models||{}).map(([m,sl])=>({m,sl,
    val:measure==="cost"?sl.cost:sl.total})).filter(r=>r.val>0).sort((a,b)=>b.val-a.val);
  if(!rows.length) return '<div class="empty">No model activity.</div>';
  const max=rows[0].val;
  return rows.map(({m,sl,val})=>{
    const parts=measure==="cost"?costParts({[m]:sl}):sl.usage;
    const tot=KEYS.reduce((s,k)=>s+(parts[k]||0),0)||1;
    const segs=KEYS.map(k=>{const w=(parts[k]||0)/tot*100;
      return w>0?`<i style="width:${w.toFixed(3)}%;background:var(${CVAR[k]})"></i>`:"";}).join("");
    return `<div class="mrow"><div class="mtop"><b title="${esc(m)}">${esc(m)}</b><span>${fmt(val)}</span></div>
      <div class="bar" style="width:${(val/max*100).toFixed(2)}%">${segs}</div>
      <div class="tag" style="margin-top:3px">${num(sl.messages)} turns${sl.fast_messages?` · ${num(sl.fast_messages)} fast`:""}</div></div>`;
  }).join("");
}
let _blend=0;
function trend(daily){
  const days=Object.keys(daily||{}).sort();
  if(days.length<2) return '<div class="empty">Not enough days to plot.</div>';
  const vals=days.map(d=>measure==="cost"?totalOf(daily[d])*_blend:totalOf(daily[d]));
  const max=Math.max(...vals)||1, W=310,H=76,Pd=4;
  const x=i=>Pd+(W-2*Pd)*(days.length===1?0:i/(days.length-1));
  const y=v=>H-Pd-(H-2*Pd)*(v/max);
  const line=vals.map((v,i)=>`${i?"L":"M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return `<svg viewBox="0 0 ${W} ${H+14}" width="100%" height="${H+14}" role="img" aria-label="Usage over time">
    <path d="${line}L${x(vals.length-1).toFixed(1)},${H-Pd}L${x(0).toFixed(1)},${H-Pd}Z" fill="var(--accent)" opacity=".14"/>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-linejoin="round"/>
    <text class="axis" x="${Pd}" y="${H+11}">${esc(days[0])}</text>
    <text class="axis" x="${W-Pd}" y="${H+11}" text-anchor="end">${esc(days[days.length-1])}</text></svg>
    <div class="tag" style="margin-top:2px">peak ${fmt(max)} · ${days.length} active days</div>`;
}
function heatmap(hours){
  const vals=[...Array(24)].map((_,h)=>hours[h]||0);
  const max=Math.max(...vals)||1;
  if(!max) return "";
  const cells=vals.map((v,h)=>`<i style="opacity:${(0.12+0.88*v/max).toFixed(3)}" title="${h}:00 — ${abbr(v)} tokens"></i>`).join("");
  const labs=[...Array(24)].map((_,h)=>`<span>${h%6===0?h:""}</span>`).join("");
  return `<div class="hm">${cells}</div><div class="hml">${labs}</div>
    <div class="note">Tokens by hour of day (local). Peak ${abbr(max)}.</div>`;
}
function classBars(tc){
  const tot=Object.values(tc).reduce((a,b)=>a+b,0);
  if(!tot) return "";
  const C={read:"--c-read",write:"--c-write",exec:"--c-output",other:"--fg-faint"};
  const segs=Object.entries(tc).map(([k,v])=>v?`<i style="width:${(v/tot*100).toFixed(2)}%;background:var(${C[k]})" title="${k}: ${num(v)}"></i>`:"").join("");
  const rows=Object.entries(tc).filter(([,v])=>v).map(([k,v])=>
    `<div class="li"><span class="sw" style="background:var(${C[k]})"></span><span class="nm">${k}</span>
     <span class="vl">${num(v)}</span><span class="pc">${(v/tot*100).toFixed(0)}%</span></div>`).join("");
  return `<div class="bar" style="height:9px">${segs}</div><div class="legend">${rows}</div>`;
}

/* ---------- right panel ---------- */
function renderSide(){
  const sc=scope();
  _blend=sc.total_tokens?sc.cost/sc.total_tokens:0;
  const parts=measure==="cost"?costParts(sc.models):sc.usage;
  const u=sc.usage;
  const cachedIn=u.cache_read+u.cache_creation+u.input;
  const hit=cachedIn?u.cache_read/cachedIn*100:0;
  const thinkPct=sc.turns?sc.thinking_turns/sc.turns*100:0;

  document.getElementById("side").innerHTML=`
    <div class="card"><h3><span>Token consumption</span><span>${sc.list.length} sess</span></h3>
      <h2 style="margin-bottom:2px">${esc(sc.title)}</h2>
      <div class="tag" style="margin-bottom:12px">${measure==="cost"?"estimated cost":"tokens"}</div>
      ${donut(parts,measure==="cost"?"est. cost":"tokens")}</div>
    <div class="card"><h3>By model</h3>${modelBars(sc.models)}</div>
    <div class="card"><h3>Over time</h3>${trend(sc.daily)}</div>
    <div class="card"><h3>Activity by hour</h3>${heatmap(sc.hours)||'<div class="empty">No data.</div>'}</div>
    <div class="card"><h3>Tool mix</h3>${classBars(sc.tool_classes)||'<div class="empty">No tool calls.</div>'}</div>
    <div class="card"><h3>Behaviour</h3>
      <div class="mtop"><b>Cache hit rate</b><span>${hit.toFixed(1)}%</span></div>
      <div class="bar"><i style="width:${hit.toFixed(2)}%;background:var(--c-read)"></i></div>
      <div class="mtop" style="margin-top:10px"><b>Reasoning engaged</b><span>${thinkPct.toFixed(0)}%</span></div>
      <div class="bar"><i style="width:${thinkPct.toFixed(2)}%;background:var(--accent)"></i></div>
      <div class="note">Reasoning = share of turns containing a thinking block.
      Thinking text is omitted by default, so depth isn't measurable — only presence.</div></div>`;
}

/* ---------- savings ---------- */
function recCard(s,p){
  const r=s.recommendation;
  return `<div class="rec ${r.confidence}">
    <div class="rec-h"><b>${esc(s.title||"Untitled session")}</b><span class="save">save ${usd(r.saving)}</span></div>
    <div class="tag">${esc(p?p.name:"")} · <span class="badge ${r.confidence}">${r.confidence} confidence</span></div>
    <ul class="why">${r.reasons.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>
    <div class="swap">${esc(r.from)} → ${esc(r.target)} &nbsp;·&nbsp; ${usd(r.current_cost)} → ${usd(r.projected_cost)}</div>
  </div>`;
}
function savingsSection(list){
  const recs=list.filter(x=>x.s.recommendation)
    .sort((a,b)=>b.s.recommendation.saving-a.s.recommendation.saving);
  const total=recs.reduce((a,x)=>a+x.s.recommendation.saving,0);
  let h=`<div class="card"><h3><span>Cheaper-model suggestions</span><span>${recs.length}</span></h3>`;
  if(!recs.length){
    h+=`<div class="empty">No downgrade candidates in this selection. That's a real
      result, not an empty state: these sessions show reasoning and edit/exec activity
      consistent with work that needs a frontier model.</div></div>`;
    return h;
  }
  h+=`<div class="kpis" style="margin-bottom:11px">
      <div class="kpi"><div class="k">Potential saving</div><div class="v">${usd(total)}</div>
        <div class="s">across ${recs.length} sessions</div></div>
      <div class="kpi"><div class="k">Share of spend</div>
        <div class="v">${(total/(DATA.cost||1)*100).toFixed(1)}%</div><div class="s">of ${usd(DATA.cost)}</div></div>
    </div>
    <div class="warnbox"><b>Read these as prompts to check, not verdicts.</b>
      Atlas sees behaviour (turns, reply length, reasoning frequency, tool mix), never
      whether the answer was hard to produce. A low-confidence row rests on a single
      signal. Trial one session before changing how you work.</div>`;
  h+=recs.slice(0,12).map(x=>recCard(x.s,x.p)).join("");
  if(recs.length>12) h+=`<div class="note">+${recs.length-12} more — narrow the filters to see them.</div>`;
  return h+"</div>";
}
function leversSection(){
  const L=DATA.levers||[];
  if(!L.length) return "";
  return `<div class="card"><h3>Where else the money goes</h3>${
    L.map(l=>`<div class="mrow">
      <div class="mtop"><b>${esc(l.title)}</b><span>${l.amount?usd(l.amount):"—"}</span></div>
      <div class="tag" style="white-space:normal;line-height:1.45">${esc(l.detail)}</div>
      <div class="note" style="margin-top:3px">${l.actionable?"":"ℹ "}${esc(l.note)}</div>
    </div>`).join("")}</div>`;
}

/* ---------- centre ---------- */
function kpis(sc){
  const u=sc.usage,t=sc.total_tokens;
  const avgOut=sc.turns?u.output/sc.turns:0;
  return `<div class="kpis">
    <div class="kpi"><div class="k">Tokens</div><div class="v">${abbr(t)}</div><div class="s">${num(t)}</div></div>
    <div class="kpi"><div class="k">Est. cost</div><div class="v">${usd(sc.cost)}</div><div class="s">list price</div></div>
    <div class="kpi"><div class="k">Turns</div><div class="v">${abbr(sc.turns)}</div>
      <div class="s">${abbr(avgOut)} out/turn</div></div>
    <div class="kpi"><div class="k">Reasoning</div>
      <div class="v">${sc.turns?(sc.thinking_turns/sc.turns*100).toFixed(0):0}%</div>
      <div class="s">${num(sc.thinking_turns)} turns</div></div>
    <div class="kpi"><div class="k">Cache read</div><div class="v">${abbr(u.cache_read)}</div>
      <div class="s">${t?(u.cache_read/t*100).toFixed(1):0}% of tokens</div></div>
    <div class="kpi"><div class="k">Active time</div><div class="v">${dur(sc.duration_minutes)}</div>
      <div class="s">${sc.fast_turns?num(sc.fast_turns)+" fast turns":"standard speed"}</div></div>
  </div>`;
}
const COLS=[
  {k:"title",  t:"Session",  n:false, v:x=>x.s.title||"Untitled session"},
  {k:"project",t:"Project",  n:false, v:x=>x.p.name},
  {k:"model",  t:"Model",    n:false, v:x=>(x.s.primary_model||"").replace("claude-","")},
  {k:"turns",  t:"Turns",    n:true,  v:x=>x.s.turns},
  {k:"think",  t:"Reason",   n:true,  v:x=>x.s.turns?x.s.thinking_turns/x.s.turns:0},
  {k:"tokens", t:"Tokens",   n:true,  v:x=>x.s.total_tokens},
  {k:"cost",   t:"Cost",     n:true,  v:x=>x.s.cost},
  {k:"save",   t:"Save",     n:true,  v:x=>x.s.recommendation?x.s.recommendation.saving:0},
  {k:"ended",  t:"Updated",  n:true,  v:x=>Date.parse(x.s.ended||0)||0},
];
function sessionTable(list){
  const col=COLS.find(c=>c.k===sortBy.key)||COLS[6];
  const rows=[...list].sort((a,b)=>{
    const av=col.v(a),bv=col.v(b);
    return (typeof av==="string"?av.localeCompare(bv):av-bv)*sortBy.dir;
  });
  const head=COLS.map(c=>`<th data-k="${c.k}" class="${c.n?"n":""}">${c.t}${sortBy.key===c.k?(sortBy.dir<0?" ▾":" ▴"):""}</th>`).join("");
  const body=rows.slice(0,300).map(x=>{
    const s=x.s,r=s.recommendation;
    return `<tr data-p="${esc(x.p.id)}" data-s="${esc(s.id)}">
      <td><b>${esc(s.title||"Untitled session")}</b><div class="tag">${esc(s.id.slice(0,8))} · ${bytes(s.size_bytes)}</div></td>
      <td>${esc(x.p.name)}</td>
      <td class="tag">${esc((s.primary_model||"").replace("claude-",""))}</td>
      <td class="n">${num(s.turns)}</td>
      <td class="n">${s.turns?(s.thinking_turns/s.turns*100).toFixed(0):0}%</td>
      <td class="n">${abbr(s.total_tokens)}</td>
      <td class="n">${usd(s.cost)}</td>
      <td class="n" style="color:${r?"var(--good)":"inherit"}">${r?usd(r.saving):"—"}</td>
      <td class="n">${esc(when(s.ended))}</td></tr>`;}).join("");
  return `<div class="card"><h3><span>Sessions</span><span>${rows.length} shown</span></h3>
    <div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    ${rows.length>300?'<div class="note">Showing first 300 — narrow the filters.</div>':""}</div>`;
}
function renderMain(){
  const sc=scope(), list=sc.list;
  let h="";
  if(sc.session){
    const s=sc.session;
    h+=`<div class="card"><h2>${esc(s.title||"Untitled session")}</h2>
      <div class="path">${esc(sc.project.path)}${s.branch?" · branch "+esc(s.branch):""}</div>${kpis(sc)}</div>`;
    if(s.recommendation) h+=`<div class="card"><h3>Suggestion</h3>${recCard(s,sc.project)}</div>`;
    h+=`<div class="card"><h3>Details</h3><table><tbody>
      <tr><td>Session id</td><td class="n">${esc(s.id)}</td></tr>
      <tr><td>Transcript</td><td class="n">${bytes(s.size_bytes)}</td></tr>
      <tr><td>Started</td><td class="n">${esc(when(s.started))}</td></tr>
      <tr><td>Last activity</td><td class="n">${esc(when(s.ended))}</td></tr>
      <tr><td>Duration</td><td class="n">${dur(s.duration_minutes)}</td></tr>
      <tr><td>Turns (user/assistant)</td><td class="n">${num(s.messages.user)} / ${num(s.messages.assistant)}</td></tr>
      <tr><td>Stop reasons</td><td class="n">${esc(Object.entries(s.stop_reasons).map(([k,v])=>k+" "+v).join(" · ")||"—")}</td></tr>
      ${s.version?`<tr><td>Claude Code version</td><td class="n">${esc(s.version)}</td></tr>`:""}
      </tbody></table></div>`;
    if(s.last_prompt) h+=`<div class="card"><h3>Last prompt</h3>
      <div style="font-size:12.5px;color:var(--fg-dim);white-space:pre-wrap;word-break:break-word">${esc(s.last_prompt.slice(0,600))}</div></div>`;
  } else {
    h+=`<div class="card"><h2>${esc(sc.title)}</h2><div class="path">${esc(sc.sub)}</div>${kpis(sc)}</div>`;
    h+=savingsSection(list);
    if(sel.kind==="all") h+=leversSection();
    h+=sessionTable(list);
  }
  const main=document.getElementById("main");
  main.innerHTML=h;
  main.querySelectorAll("tbody tr").forEach(tr=>tr.addEventListener("click",()=>
    select({kind:"session",pid:tr.getAttribute("data-p"),id:tr.getAttribute("data-s")})));
  main.querySelectorAll("th[data-k]").forEach(th=>th.addEventListener("click",()=>{
    const k=th.getAttribute("data-k");
    sortBy = sortBy.key===k?{key:k,dir:-sortBy.dir}:{key:k,dir:-1};
    renderMain();
  }));
}

/* ---------- nav ---------- */
function fileNode(n,d){
  if(n.type==="file") return `<div class="row" style="padding-left:${6+d*11}px"><span class="tw"></span>
    <span class="ico">${n.code?"■":"□"}</span><span class="lbl" title="${esc(n.name)}">${esc(n.name)}</span>
    <span class="tag">${bytes(n.size)}</span></div>`;
  const kids=(n.children||[]).map(c=>fileNode(c,d+1)).join("")
    +(n.truncated?`<div class="sub" style="padding-left:${18+d*11}px">…truncated</div>`:"");
  return `<div class="node"><div class="row dtog" style="padding-left:${6+d*11}px"><span class="tw">▶</span>
    <span class="ico">▸</span><span class="lbl" title="${esc(n.name)}">${esc(n.name)}</span>
    <span class="tag">${(n.children||[]).length}</span></div><div class="kids">${kids}</div></div>`;
}
function renderNav(){
  const vis=visible(), byProj={};
  vis.forEach(x=>(byProj[x.p.id]=byProj[x.p.id]||[]).push(x.s));
  let h=`<div class="sec">Overview</div>
    <div class="row nsel ${sel.kind==="all"?"on":""}" data-k="all"><span class="tw"></span>
      <span class="ico">◈</span><span class="lbl">All projects</span>
      <span class="tag">${abbr(aggregate(vis).total_tokens)}</span></div>`;
  h+=`<div class="sec">Chats</div>`;
  for(const p of DATA.projects){
    const ss=byProj[p.id]||[];
    if(!ss.length) continue;
    const open=(sel.kind==="project"&&sel.id===p.id)||(sel.kind==="session"&&sel.pid===p.id);
    h+=`<div class="node"><div class="row nsel ${sel.kind==="project"&&sel.id===p.id?"on":""}"
        data-k="project" data-p="${esc(p.id)}">
      <span class="tw ${open?"open":""} ptog">▶</span><span class="ico">◉</span>
      <span class="lbl" title="${esc(p.path)}">${esc(p.name)}</span>
      <span class="tag">${ss.length}</span></div>
      <div class="kids ${open?"open":""}">${ss.map(s=>`
        <div class="row nsel ${sel.kind==="session"&&sel.id===s.id?"on":""}" data-k="session"
          data-p="${esc(p.id)}" data-s="${esc(s.id)}" style="padding-left:17px">
          <span class="tw"></span><span class="ico">${s.recommendation?"◆":"○"}</span>
          <span class="lbl" title="${esc(s.title||s.id)}">${esc(s.title||"Untitled session")}</span>
          <span class="tag">${abbr(s.total_tokens)}</span></div>`).join("")}</div></div>`;
  }
  h+=`<div class="sec">Code projects</div>`;
  for(const p of DATA.projects){
    if(!p.tree){h+=`<div class="row" title="${esc(p.path)}"><span class="tw"></span><span class="ico">⊘</span>
      <span class="lbl">${esc(p.name)}</span><span class="tag">n/a</span></div>`;continue;}
    h+=`<div class="node"><div class="row dtog"><span class="tw">▶</span><span class="ico">▸</span>
      <span class="lbl" title="${esc(p.path)}">${esc(p.name)}</span>
      <span class="tag">${(p.tree.children||[]).length}</span></div>
      <div class="kids">${(p.tree.children||[]).map(c=>fileNode(c,1)).join("")}</div></div>`;
  }
  const nav=document.getElementById("nav");
  nav.innerHTML=h;
  nav.querySelectorAll(".row.dtog").forEach(row=>row.addEventListener("click",e=>{
    e.stopPropagation();row.querySelector(".tw").classList.toggle("open");
    row.nextElementSibling.classList.toggle("open");}));
  nav.querySelectorAll(".ptog").forEach(tw=>tw.addEventListener("click",e=>{
    e.stopPropagation();tw.classList.toggle("open");
    tw.closest(".row").nextElementSibling.classList.toggle("open");}));
  nav.querySelectorAll(".row.nsel").forEach(row=>row.addEventListener("click",()=>{
    const k=row.getAttribute("data-k");
    if(k==="all") select({kind:"all"});
    else if(k==="project") select({kind:"project",id:row.getAttribute("data-p")});
    else select({kind:"session",pid:row.getAttribute("data-p"),id:row.getAttribute("data-s")});}));
}

/* ---------- wiring ---------- */
function renderAll(){renderNav();renderMain();renderSide();
  const n=visible().length;
  document.getElementById("fcount").textContent=`${n} of ${ALL.length} sessions`;}
function select(next){sel=next;renderAll();}
function setMeasure(m){measure=m;
  document.getElementById("mTok").setAttribute("aria-pressed",String(m==="tokens"));
  document.getElementById("mCost").setAttribute("aria-pressed",String(m==="cost"));
  renderMain();renderSide();}

document.getElementById("mTok").onclick=()=>setMeasure("tokens");
document.getElementById("mCost").onclick=()=>setMeasure("cost");
document.getElementById("theme").onclick=()=>{
  const cur=document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme",
    cur==="dark"?"light":cur==="light"?"dark":
    (matchMedia("(prefers-color-scheme: dark)").matches?"light":"dark"));};

const projSel=document.getElementById("fproj");
DATA.projects.forEach(p=>projSel.add(new Option(p.name+" ("+p.sessions.length+")",p.id)));
const modelSel=document.getElementById("fmodel");
Object.keys(DATA.models).filter(m=>DATA.models[m].total>0).sort()
  .forEach(m=>modelSel.add(new Option(m.replace("claude-",""),m)));

function bind(id,prop,cast){document.getElementById(id).addEventListener("input",e=>{
  filters[prop]=cast?cast(e.target.value):e.target.value;
  if(sel.kind==="session") sel={kind:"all"};
  renderAll();});}
bind("fq","q");bind("fproj","project");bind("fmodel","model");
bind("frange","days",Number);bind("fcost","minCost",Number);
document.getElementById("frec").onclick=e=>{
  filters.recOnly=!filters.recOnly;
  e.target.setAttribute("aria-pressed",String(filters.recOnly));
  if(sel.kind==="session") sel={kind:"all"};
  renderAll();};
document.getElementById("freset").onclick=()=>{
  Object.assign(filters,{q:"",project:"",model:"",days:0,minCost:0,recOnly:false});
  ["fq","fproj","fmodel"].forEach(i=>document.getElementById(i).value="");
  ["frange","fcost"].forEach(i=>document.getElementById(i).value="0");
  document.getElementById("frec").setAttribute("aria-pressed","false");
  sel={kind:"all"};renderAll();};

document.getElementById("hcount").textContent=
  `· ${DATA.projects.length} projects · ${DATA.session_count} sessions`;
const rec=DATA.recommendations||{count:0,total_saving:0};
document.getElementById("hmeta").textContent=
  `${abbr(DATA.total_tokens)} tokens · ~${usd(DATA.cost)}`
  + (rec.count?` · ${usd(rec.total_saving)} potential saving`:"")
  + ` · scanned ${DATA.generated_at.replace("T"," ").replace("+00:00"," UTC")}`;

renderAll();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the Claude Atlas dashboard.")
    ap.add_argument("--data")
    ap.add_argument("--out", default=str(Path.home() / ".claude" / "atlas" / "dashboard.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--no-tree", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    if args.data:
        raw = Path(args.data).expanduser().read_text(encoding="utf-8")
    else:
        cmd = [sys.executable, str(here / "collect.py"), "--out", "-"]
        if args.no_tree:
            cmd.append("--no-tree")
        raw = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    html = TEMPLATE.replace("__DATA__", raw.replace("</", "<\\/"))
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    d = json.loads(raw)
    r = d.get("recommendations", {})
    print(f"Dashboard: {out}")
    print(f"  {len(d.get('projects', []))} projects, {d.get('session_count', 0)} sessions, "
          f"{d.get('total_tokens', 0):,} tokens, ~${d.get('cost', 0):,.2f}")
    if r.get("count"):
        print(f"  {r['count']} cheaper-model suggestions worth ~${r['total_saving']:,.2f}")
    for lv in d.get("levers", []):
        if lv.get("actionable") and lv.get("amount"):
            print(f"  lever: {lv['title']} ~${lv['amount']:,.2f}")

    if args.open:
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
