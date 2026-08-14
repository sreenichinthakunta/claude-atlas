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
/* wide views hide the nav + side rails */
body.wide .layout{grid-template-columns:minmax(0,1fr)}
body.wide #nav,body.wide #side,body.wide #filters{display:none}

/* savings redesign */
.hero{display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:center;
  padding:16px;border-radius:12px;background:linear-gradient(135deg,
  color-mix(in srgb,var(--good) 13%,transparent),transparent);border:1px solid var(--line)}
.hero .big{font-size:38px;font-weight:700;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums;color:var(--good);line-height:1}
.hero .cap{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--fg-faint)}
.hero .of{font-size:12.5px;color:var(--fg-dim);margin-top:5px}
.gauge{height:9px;border-radius:5px;background:var(--panel-2);overflow:hidden;margin-top:9px;display:flex}
.gauge i{display:block;height:100%;background:var(--good)}

.rc{border:1px solid var(--line);border-radius:11px;padding:0;margin-bottom:10px;
  overflow:hidden;background:var(--panel)}
.rc-top{display:flex;gap:12px;align-items:flex-start;padding:12px 13px;cursor:pointer}
.rc-top:hover{background:var(--hover)}
.rc-rank{font-family:var(--mono);font-size:11px;color:var(--fg-faint);width:18px;
  flex:none;padding-top:2px}
.rc-main{flex:1;min-width:0}
.rc-title{font-size:13.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rc-sub{font-size:11px;color:var(--fg-faint);margin-top:2px;display:flex;gap:7px;
  align-items:center;flex-wrap:wrap}
.rc-right{text-align:right;flex:none}
.rc-save{font-family:var(--mono);font-size:16px;font-weight:650;color:var(--good);line-height:1.15}
.rc-pct{font-size:10.5px;color:var(--fg-faint);font-variant-numeric:tabular-nums}
.flow{display:flex;align-items:center;gap:7px;margin-top:9px;flex-wrap:wrap}
.pill{font-family:var(--mono);font-size:11px;padding:2.5px 8px;border-radius:999px;
  border:1px solid var(--line);background:var(--panel-2);white-space:nowrap}
.pill.to{border-color:var(--good);color:var(--good)}
.arrow{color:var(--fg-faint);font-size:12px}
.rc-body{padding:0 13px 12px 43px;display:none}
.rc.open .rc-body{display:block}
.evid{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:7px;margin:2px 0 10px}
.ev{background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:7px 9px}
.ev .n{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--fg-faint)}
.ev .v{font-size:15px;font-weight:650;font-variant-numeric:tabular-nums;margin-top:1px}
.ev .m{font-size:10px;color:var(--fg-faint)}
.chev{color:var(--fg-faint);font-size:10px;transition:transform .14s;flex:none;padding-top:4px}
.rc.open .chev{transform:rotate(90deg)}

/* context / access */
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.item{border:1px solid var(--line);border-radius:9px;padding:10px 11px;margin-bottom:8px;
  background:var(--panel-2)}
.item h4{margin:0 0 3px;font-size:12.5px;font-weight:650;display:flex;
  justify-content:space-between;gap:8px;align-items:baseline}
.item p{margin:2px 0 0;font-size:11.5px;color:var(--fg-dim);line-height:1.45}
.mono{font-family:var(--mono);font-size:10.5px;color:var(--fg-faint);word-break:break-all}
textarea{width:100%;min-height:230px;font-family:var(--mono);font-size:11.5px;
  line-height:1.55;padding:10px;border-radius:8px;border:1px solid var(--line);
  background:var(--panel-2);color:var(--fg);resize:vertical}
.acts{display:flex;gap:7px;align-items:center;margin-top:8px}
.ok{color:var(--good);font-size:11.5px}
.err{color:var(--bad);font-size:11.5px}
.finding{border-left:3px solid var(--fg-faint);padding:8px 11px;border-radius:0 8px 8px 0;
  background:var(--panel-2);margin-bottom:7px;font-size:12px}
.finding.warn{border-left-color:var(--warn)}
.finding.info{border-left-color:var(--accent)}

/* charts */
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
  <div class="seg" role="tablist" id="views">
    <button data-v="usage"   aria-pressed="true">Usage</button>
    <button data-v="savings" aria-pressed="false">Savings</button>
    <button data-v="context" aria-pressed="false">Context</button>
    <button data-v="access"  aria-pressed="false">Access</button>
  </div>
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
  <span class="spacer"></span>
  <button id="fcsv" title="Export the currently filtered sessions as CSV">Export CSV</button>
  <button id="fjson" title="Export the currently filtered sessions as JSON">Export JSON</button>
  <span class="chip" id="fcount"></span>
</div>

<div class="layout">
  <div class="col" id="nav"></div>
  <div class="col" id="main"></div>
  <div class="col" id="side"></div>
</div>

<script id="atlas-data" type="application/json">__DATA__</script>
<script id="atlas-env" type="application/json">__ENV__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
let ENV = JSON.parse(document.getElementById("atlas-env").textContent);
/* Editing is available only when served by server.py, which supplies a token
   in the URL. Opened as a plain file:// page, LIVE is false and everything
   below falls back to read-only against the data embedded at build time. */
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const LIVE = location.protocol.startsWith("http") && !!TOKEN;
const api = (p, q) => `${p}?t=${encodeURIComponent(TOKEN)}${q ? "&" + q : ""}`;
const P = DATA.pricing;
const KEYS  = ["input","output","cache_read","cache_creation"];
const LABEL = {input:"Input",output:"Output",cache_read:"Cache read",cache_creation:"Cache write"};
const CVAR  = {input:"--c-input",output:"--c-output",cache_read:"--c-read",cache_creation:"--c-write"};

let measure = "tokens";
let view = "usage";
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

/* ---------- savings (redesigned) ---------- */
const EVID=[
  {k:"turns", n:"Turns", f:m=>num(m.turns), m:()=>"conversation length"},
  {k:"avg_output", n:"Avg reply", f:m=>abbr(m.avg_output), m:()=>"output tokens/turn"},
  {k:"thinking_rate", n:"Reasoning", f:m=>(m.thinking_rate*100).toFixed(0)+"%", m:()=>"of turns"},
  {k:"heavy_tool_ratio", n:"Edit / exec", f:m=>(m.heavy_tool_ratio*100).toFixed(0)+"%", m:()=>"of tool calls"},
];
function recCard(s,p,rank){
  const r=s.recommendation, m=r.metrics;
  const pct=r.current_cost?(r.saving/r.current_cost*100):0;
  return `<div class="rc" data-rc>
    <div class="rc-top">
      <span class="rc-rank">${rank}</span>
      <span class="rc-main">
        <span class="rc-title">${esc(s.title||"Untitled session")}</span>
        <span class="rc-sub"><span>${esc(p?p.name:"")}</span>
          <span class="badge ${r.confidence}">${r.confidence}</span>
          <span>${num(m.turns)} turns</span></span>
        <span class="flow"><span class="pill">${esc(r.from.replace("claude-",""))}</span>
          <span class="arrow">→</span>
          <span class="pill to">${esc(r.target.replace("claude-",""))}</span>
          <span class="mono">${usd(r.current_cost)} → ${usd(r.projected_cost)}</span></span>
      </span>
      <span class="rc-right"><span class="rc-save">${usd(r.saving)}</span>
        <span class="rc-pct">−${pct.toFixed(0)}%</span></span>
      <span class="chev">▶</span>
    </div>
    <div class="rc-body">
      <div class="evid">${EVID.map(e=>`<div class="ev"><div class="n">${e.n}</div>
        <div class="v">${e.f(m)}</div><div class="m">${e.m()}</div></div>`).join("")}</div>
      <div class="tag" style="margin-bottom:4px">Why this was flagged</div>
      <ul class="why">${r.reasons.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>
      <div class="note">Confidence is <b>${r.confidence}</b> because
        ${r.reasons.length} independent signal${r.reasons.length===1?"":"s"} support this.
        ${r.reasons.length===1?"A single signal is weak evidence — verify before acting.":""}</div>
      <div class="acts">
        <button data-copy="/model ${esc(r.target)}">Copy switch command</button>
        <span class="msg"></span>
        <span class="note" style="margin:0">Nothing is changed automatically — this
          copies the command to run yourself, next time you'd start a session like this.</span>
      </div>
    </div></div>`;
}
async function copyText(text){
  try{ await navigator.clipboard.writeText(text); return true; }
  catch(e){
    try{
      const ta=document.createElement("textarea");
      ta.value=text; ta.style.position="fixed"; ta.style.opacity="0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      const ok=document.execCommand("copy"); ta.remove();
      return ok;
    }catch(e2){ return false; }
  }
}
function wireRecs(root){
  root.querySelectorAll("[data-rc] .rc-top").forEach(t=>t.addEventListener("click",()=>
    t.parentElement.classList.toggle("open")));
  root.querySelectorAll("[data-copy]").forEach(b=>b.addEventListener("click",async()=>{
    const msg=b.nextElementSibling;
    const ok=await copyText(b.getAttribute("data-copy"));
    if(msg){msg.textContent=ok?"copied":"couldn't copy — select and copy manually";
      msg.className=ok?"msg ok":"msg err";
      setTimeout(()=>{if(msg)msg.textContent="";},2500);}
  }));
}
function savingsSection(list,expanded){
  const recs=list.filter(x=>x.s.recommendation)
    .sort((a,b)=>b.s.recommendation.saving-a.s.recommendation.saving);
  const total=recs.reduce((a,x)=>a+x.s.recommendation.saving,0);
  const spend=aggregate(list).cost||1;
  if(!recs.length) return `<div class="card"><h3>Cheaper-model suggestions</h3>
    <div class="empty"><b>No downgrade candidates here.</b><br>That's a finding, not an
    empty state — these sessions show reasoning and edit/exec activity consistent with
    work that needs a frontier model. Atlas only suggests a change when it can state a
    reason that is literally true of the data.</div></div>`;
  const byTier={};
  recs.forEach(x=>{const t=x.s.recommendation.target;
    byTier[t]=(byTier[t]||0)+x.s.recommendation.saving;});
  const share=total/spend*100;
  let h=`<div class="card">
    <div class="hero">
      <div><div class="cap">Potential saving</div><div class="big">${usd(total)}</div>
        <div class="of">${recs.length} of ${list.length} sessions · ${share.toFixed(1)}% of ${usd(spend)}</div>
        <div class="gauge"><i style="width:${Math.min(share,100).toFixed(1)}%"></i></div></div>
      <div>${Object.entries(byTier).sort((a,b)=>b[1]-a[1]).map(([t,v])=>`
        <div class="mrow"><div class="mtop"><b>→ ${esc(t.replace("claude-",""))}</b><span>${usd(v)}</span></div>
        <div class="bar"><i style="width:${(v/total*100).toFixed(1)}%;background:var(--good)"></i></div></div>`).join("")}
        <div class="note">Estimated by repricing the same tokens at the target model's rates.</div></div>
    </div>
    <div class="warnbox" style="margin-top:12px"><b>These are prompts to check, not verdicts.</b>
      Atlas reads behaviour — turns, reply length, how often reasoning fired, read vs
      edit tool mix. It cannot see whether a task was hard. Expand any row for the
      evidence, and trial one session before changing how you work.</div>`;
  const show=expanded?recs:recs.slice(0,8);
  h+=show.map((x,i)=>recCard(x.s,x.p,i+1)).join("");
  if(recs.length>show.length)
    h+=`<div class="note">+${recs.length-show.length} more — open the Savings tab or narrow filters.</div>`;
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
function monthProjection(daily){
  const now=new Date(), ym=now.toISOString().slice(0,7);
  const daysInMonth=new Date(now.getFullYear(),now.getMonth()+1,0).getDate();
  const todayDay=now.getDate();
  let tokensSoFar=0, activeDays=0;
  for(const [d,u] of Object.entries(daily||{}))
    if(d.slice(0,7)===ym){tokensSoFar+=totalOf(u);activeDays++;}
  if(activeDays<2) return null;
  const costSoFar=tokensSoFar*_blend;
  return {costSoFar, projected:costSoFar/todayDay*daysInMonth, daysElapsed:todayDay, daysInMonth, activeDays};
}
function kpis(sc){
  const u=sc.usage,t=sc.total_tokens;
  const avgOut=sc.turns?u.output/sc.turns:0;
  const mp=monthProjection(sc.daily);
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
    <div class="kpi"><div class="k">Month pace</div>
      <div class="v">${mp?usd(mp.projected):"—"}</div>
      <div class="s">${mp?`${usd(mp.costSoFar)} thru day ${mp.daysElapsed}/${mp.daysInMonth}`:"too few days yet"}</div></div>
  </div>`;
}
function toCSV(list){
  const cols=["Title","Project","Model","Turns","Reasoning %","Tokens","Cost","Suggested saving","Updated"];
  const esc2=v=>{const s=String(v==null?"":v);
    return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
  const rows=list.map(({s,p})=>[
    s.title||"Untitled session", p.name, (s.primary_model||"").replace("claude-",""),
    s.turns, s.turns?(s.thinking_turns/s.turns*100).toFixed(1):0,
    s.total_tokens, s.cost.toFixed(2),
    s.recommendation?s.recommendation.saving.toFixed(2):"",
    s.ended||""
  ].map(esc2).join(","));
  return [cols.join(","), ...rows].join("\n");
}
function downloadBlob(filename,mime,content){
  const blob=new Blob([content],{type:mime});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url; a.download=filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),4000);
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
/* ---------- context view: MCP + memories ---------- */
function renderContext(){
  const M=ENV.memories||{groups:[],total:0,globals:[],dangling_links:[]};
  const C=ENV.mcp||{servers:[],projects:[],notes:[]};
  let h=`<div class="card"><h2>Context Claude is carrying</h2>
    <div class="path">MCP servers, per-project trust, and saved memories</div>
    <div class="kpis">
      <div class="kpi"><div class="k">MCP servers</div><div class="v">${C.servers.length}</div>
        <div class="s">across all scopes</div></div>
      <div class="kpi"><div class="k">Memories</div><div class="v">${M.total}</div>
        <div class="s">${M.groups.length} projects</div></div>
      <div class="kpi"><div class="k">Trusted dirs</div>
        <div class="v">${C.projects.filter(p=>p.trusted).length}</div>
        <div class="s">of ${C.projects.length} known</div></div>
      <div class="kpi"><div class="k">Dangling links</div>
        <div class="v">${M.dangling_links.length}</div><div class="s">[[refs]] with no file</div></div>
    </div>
    ${LIVE?"":`<div class="note">Read-only. Run <b>/atlas-edit</b> to edit memories in place.</div>`}
  </div>`;

  if((M.secret_flags||[]).length) h+=`<div class="warnbox">
    <b>Possible credentials in memory files</b> — Atlas never reads or displays the
    matched value, only its location. Review and rotate if real:
    <ul class="why">${M.secret_flags.map(f=>
      `<li>${esc(f.location)}, line ${f.line}: looks like a <b>${esc(f.pattern)}</b></li>`).join("")}</ul>
  </div>`;

  h+=`<div class="card"><h3><span>MCP servers</span><span>${C.servers.length}</span></h3>`;
  if(!C.servers.length){
    h+=`<div class="empty">${esc((C.notes||[]).join(" ")||"None configured.")}</div>`;
  } else {
    h+=C.servers.map(s=>`<div class="item">
      <h4><span>${esc(s.name)}</span><span class="tag">${esc(s.scope)} · ${esc(s.type)}</span></h4>
      ${s.url?`<p class="mono">${esc(s.url)}</p>`:""}
      ${s.command?`<p class="mono">${esc(s.command)} ${esc((s.args||[]).join(" "))}</p>`:""}
      ${s.env_keys.length?`<p>env: <span class="mono">${s.env_keys.map(esc).join(", ")}</span>
        ${s.env_secret_count?`<span class="badge low">${s.env_secret_count} secret-like</span>`:""}</p>`:""}
      <p class="mono">${esc(s.source)}</p></div>`).join("");
  }
  h+=`</div>`;

  h+=`<div class="card"><h3><span>Project trust</span><span>${C.projects.length}</span></h3>
    <div class="scroll"><table><thead><tr><th>Directory</th><th>Trusted</th>
    <th class="n">Allowed tools</th><th class="n">MCP</th><th>On disk</th></tr></thead><tbody>${
    C.projects.map(p=>`<tr><td class="mono">${esc(p.path)}</td>
      <td>${p.trusted?'<span class="badge high">yes</span>':'<span class="badge">no</span>'}</td>
      <td class="n">${p.allowed_tools.length}</td><td class="n">${p.server_count}</td>
      <td>${p.exists?"✓":'<span class="badge low">missing</span>'}</td></tr>`).join("")
    }</tbody></table></div>
    <div class="note">Trust is granted per directory and persists. Entries marked
      missing no longer exist on disk and can be pruned.</div></div>`;

  h+=`<div class="card"><h3><span>Memories</span><span>${M.total}</span></h3>`;
  if(!M.total) h+=`<div class="empty">No memory files found.</div>`;
  M.groups.forEach(g=>{
    h+=`<div style="margin-bottom:14px"><div class="mtop"><b>${esc(g.project_id)}</b>
      <span>${g.count} files · ${(g.bytes/1024).toFixed(1)} KB</span></div>
      <div class="mono" style="margin-bottom:6px">${esc(g.dir)}</div>`;
    g.files.forEach(f=>{
      h+=`<div class="item"><h4><span>${f.is_index?"📑 ":""}${esc(f.name)}</span>
        <span class="tag">${(f.size/1024).toFixed(1)} KB</span></h4>
        ${f.description?`<p>${esc(f.description)}</p>`:""}
        ${f.links.length?`<p class="tag">links: ${f.links.map(esc).join(", ")}</p>`:""}
        <div class="acts">
          <button data-mem="${esc(f.file)}">${LIVE?"Edit":"View"}</button>
          <span class="mono">${esc(f.file)}</span></div>
        <div data-editor="${esc(f.file)}"></div></div>`;
    });
    h+=`</div>`;
  });
  if(M.dangling_links.length) h+=`<div class="note"><b>Dangling links:</b> ${
    M.dangling_links.map(l=>`${esc(l.from)} → [[${esc(l.to)}]]`).join(", ")}
    — these point at memories that don't exist yet.</div>`;
  return h+`</div>`;
}

async function openMemory(file, host){
  if(host.dataset.open==="1"){host.innerHTML="";host.dataset.open="0";return;}
  host.dataset.open="1";
  let text="", err="";
  const local=(ENV.memories.groups.flatMap(g=>g.files).find(f=>f.file===file)||{}).raw||"";
  if(LIVE){
    try{ const r=await fetch(api("/api/memory","file="+encodeURIComponent(file)));
      const j=await r.json(); if(j.error) err=j.error; else text=j.text; }
    catch(e){ err=String(e); }
  } else { text=local; }
  if(err){host.innerHTML=`<div class="err">${esc(err)}</div>`;return;}
  host.innerHTML=`<textarea ${LIVE?"":"readonly"}>${esc(text)}</textarea>
    <div class="acts">${LIVE?`<button data-save="${esc(file)}">Save</button>`:
      `<span class="note">Read-only — start <b>/atlas-edit</b> to edit. Showing an
       embedded snapshot (first 8 KB).</span>`}<span class="msg"></span></div>`;
  const btn=host.querySelector("[data-save]");
  if(btn) btn.addEventListener("click",async()=>{
    const ta=host.querySelector("textarea"), msg=host.querySelector(".msg");
    msg.textContent="saving…"; msg.className="msg";
    try{
      const r=await fetch(api("/api/memory"),{method:"POST",
        headers:{"Content-Type":"application/json","X-Atlas-Token":TOKEN},
        body:JSON.stringify({file,text:ta.value})});
      const j=await r.json();
      if(j.ok){msg.textContent=`saved ${j.bytes} bytes (.bak kept)`;msg.className="msg ok";}
      else {msg.textContent=j.error||"failed";msg.className="msg err";}
    }catch(e){msg.textContent=String(e);msg.className="msg err";}
  });
}

/* ---------- access view ---------- */
function renderAccess(){
  const A=ENV.access||{rules:[],sources:[],hooks:[],findings:[],counts:{},trusted_dirs:[]};
  const byTool={};
  A.rules.filter(r=>r.effect==="allow").forEach(r=>byTool[r.tool]=(byTool[r.tool]||0)+1);
  const tools=Object.entries(byTool).sort((a,b)=>b[1]-a[1]);
  const mx=tools.length?tools[0][1]:1;
  let h=`<div class="card"><h2>What Claude is allowed to do</h2>
    <div class="path">Effective permissions across every settings layer on this machine</div>
    <div class="kpis">
      <div class="kpi"><div class="k">Allow rules</div><div class="v">${A.counts.allow||0}</div>
        <div class="s">skip confirmation</div></div>
      <div class="kpi"><div class="k">Deny rules</div><div class="v">${A.counts.deny||0}</div>
        <div class="s">hard blocks</div></div>
      <div class="kpi"><div class="k">Ask rules</div><div class="v">${A.counts.ask||0}</div>
        <div class="s">force a prompt</div></div>
      <div class="kpi"><div class="k">Trusted dirs</div><div class="v">${A.trusted_dirs.length}</div>
        <div class="s">persist across sessions</div></div>
      <div class="kpi"><div class="k">Hooks</div><div class="v">${A.hooks.length}</div>
        <div class="s">run automatically</div></div>
      <div class="kpi"><div class="k">Plugins</div><div class="v">${(A.enabled_plugins||[]).length}</div>
        <div class="s">${(A.marketplaces||[]).length} marketplaces</div></div>
    </div></div>`;

  if(A.findings.length) h+=`<div class="card"><h3>Findings</h3>${
    A.findings.map(f=>`<div class="finding ${esc(f.level)}">${esc(f.text)}</div>`).join("")}</div>`;

  h+=`<div class="card"><h3><span>Allow rules by tool</span><span>${A.counts.allow||0}</span></h3>`;
  h+=tools.length?tools.slice(0,18).map(([t,c])=>`<div class="mrow">
      <div class="mtop"><b>${esc(t)}</b><span>${num(c)}</span></div>
      <div class="bar" style="width:${(c/mx*100).toFixed(1)}%"><i style="width:100%;background:var(--accent)"></i></div>
    </div>`).join(""):'<div class="empty">No allow rules.</div>';
  h+=`<div class="note">Each allow rule lets a matching command run without asking.
    Review anything that can write, delete, or reach the network.</div></div>`;

  if(A.hooks.length) h+=`<div class="card"><h3>Hooks</h3>${A.hooks.map(x=>`<div class="item">
    <h4><span>${esc(x.event)}</span><span class="tag">${esc(x.type||"")}</span></h4>
    <p class="mono">${esc(x.command)}</p><p class="tag">${esc(x.source)}</p></div>`).join("")}
    <div class="note">Hooks execute automatically. Treat them as trusted code.</div></div>`;

  h+=`<div class="card"><h3><span>Settings layers</span><span>${A.sources.length}</span></h3>
    <div class="scroll"><table><thead><tr><th>Source</th><th>Path</th><th>Keys</th></tr></thead><tbody>${
    A.sources.map(s=>`<tr><td>${esc(s.label)}${s.managed?' <span class="badge low">managed</span>':""}</td>
      <td class="mono">${esc(s.path)}</td><td class="tag">${esc(s.keys.join(", "))}</td></tr>`).join("")
    }</tbody></table></div>
    <div class="note">Later layers override earlier ones; managed org policy wins over all.</div></div>`;
  return h;
}

function renderMain(){
  const sc=scope(), list=sc.list;
  let h="";
  if(view==="context"){document.getElementById("main").innerHTML=renderContext();
    document.querySelectorAll("[data-mem]").forEach(b=>b.addEventListener("click",()=>
      openMemory(b.getAttribute("data-mem"),
        b.closest(".item").querySelector("[data-editor]"))));
    return;}
  if(view==="access"){document.getElementById("main").innerHTML=renderAccess();return;}
  if(view==="savings"){
    const m=document.getElementById("main");
    m.innerHTML=savingsSection(list,true)+leversSection();
    wireRecs(m); return;}
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
  wireRecs(main);
  main.querySelectorAll("tbody tr[data-s]").forEach(tr=>tr.addEventListener("click",()=>
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
const WIDE=new Set(["context","access"]);
function renderAll(){
  document.body.classList.toggle("wide", WIDE.has(view));
  if(!WIDE.has(view)){renderNav();renderSide();}
  renderMain();
  const n=visible().length;
  document.getElementById("fcount").textContent=`${n} of ${ALL.length} sessions`;
}
function setView(v){
  view=v;
  document.querySelectorAll("#views button").forEach(b=>
    b.setAttribute("aria-pressed",String(b.getAttribute("data-v")===v)));
  renderAll();
}
document.getElementById("views").addEventListener("click",e=>{
  const b=e.target.closest("button[data-v]"); if(b) setView(b.getAttribute("data-v"));});
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
const stamp=()=>new Date().toISOString().slice(0,10);
document.getElementById("fcsv").onclick=()=>
  downloadBlob(`claude-atlas-sessions-${stamp()}.csv`,"text/csv",toCSV(visible()));
document.getElementById("fjson").onclick=()=>
  downloadBlob(`claude-atlas-sessions-${stamp()}.json`,"application/json",
    JSON.stringify(visible().map(({s,p})=>({...s,project:p.name,project_path:p.path})),null,2));

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

    # Environment inventory is embedded so the static file works standalone;
    # live mode re-fetches it from /api/env for fresh state.
    try:
        sys.path.insert(0, str(here))
        import inspect_env
        env_raw = json.dumps(inspect_env.collect(), separators=(",", ":"))
    except Exception as exc:  # never let inventory failure break the dashboard
        env_raw = json.dumps({"error": str(exc), "mcp": {"servers": [], "projects": [], "notes": []},
                              "memories": {"groups": [], "total": 0, "globals": [], "dangling_links": []},
                              "access": {"rules": [], "sources": [], "hooks": [], "findings": [],
                                         "counts": {"allow": 0, "deny": 0, "ask": 0},
                                         "trusted_dirs": [], "enabled_plugins": [], "marketplaces": []}})

    html = (TEMPLATE
            .replace("__DATA__", raw.replace("</", "<\\/"))
            .replace("__ENV__", env_raw.replace("</", "<\\/")))
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
