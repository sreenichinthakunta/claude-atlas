#!/usr/bin/env python3
"""Render the collected usage model into a single self-contained HTML file.

No external assets: all CSS/JS is inlined and every chart is hand-rolled SVG,
so the file opens from disk with no network access.
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
  --bg:#f6f7f9; --panel:#ffffff; --panel-2:#fbfbfd; --line:#e2e5ea;
  --fg:#16181d; --fg-dim:#5c6472; --fg-faint:#8b93a1;
  --accent:#4c6ef5; --hover:#eef1f7; --sel:#e0e8ff;
  --c-input:#4c6ef5; --c-output:#f08c00; --c-read:#0ca678; --c-write:#ae3ec9;
  --shadow:0 1px 3px rgba(16,20,30,.07),0 8px 24px rgba(16,20,30,.05);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
:root:not([data-theme="light"]){ }
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0e1014; --panel:#161920; --panel-2:#1b1f27; --line:#282d38;
    --fg:#e8eaf0; --fg-dim:#a2abbb; --fg-faint:#6f7889;
    --accent:#748ffc; --hover:#20252f; --sel:#25304a;
    --c-input:#748ffc; --c-output:#ffa94d; --c-read:#38d9a9; --c-write:#da77f2;
    --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --bg:#0e1014; --panel:#161920; --panel-2:#1b1f27; --line:#282d38;
  --fg:#e8eaf0; --fg-dim:#a2abbb; --fg-faint:#6f7889;
  --accent:#748ffc; --hover:#20252f; --sel:#25304a;
  --c-input:#748ffc; --c-output:#ffa94d; --c-read:#38d9a9; --c-write:#da77f2;
  --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
header{
  display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  padding:12px 18px;background:var(--panel);border-bottom:1px solid var(--line);
  position:sticky;top:0;z-index:20;
}
header h1{font-size:15px;margin:0;font-weight:650;letter-spacing:-.01em}
header h1 span{color:var(--fg-faint);font-weight:400}
.spacer{flex:1}
.meta{font-size:12px;color:var(--fg-faint);font-variant-numeric:tabular-nums}
button{
  font:inherit;font-size:12px;color:var(--fg-dim);background:var(--panel-2);
  border:1px solid var(--line);border-radius:7px;padding:5px 11px;cursor:pointer;
}
button:hover{background:var(--hover);color:var(--fg)}
button[aria-pressed="true"]{background:var(--sel);color:var(--fg);border-color:var(--accent)}
.seg{display:inline-flex;gap:0;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.seg button{border:0;border-radius:0;border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}

.layout{display:grid;grid-template-columns:290px minmax(0,1fr) 350px;gap:0;
  height:calc(100vh - 53px);align-items:stretch}
.col{overflow-y:auto;overflow-x:hidden;padding:14px}
#nav{border-right:1px solid var(--line);background:var(--panel)}
#main{background:var(--bg)}
#side{border-left:1px solid var(--line);background:var(--panel)}

.sec{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--fg-faint);margin:14px 0 7px;padding:0 4px}
.sec:first-child{margin-top:0}

.node{border-radius:6px;user-select:none}
.row{display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:6px;
  cursor:pointer;font-size:13px;white-space:nowrap}
.row:hover{background:var(--hover)}
.row.on{background:var(--sel)}
.tw{width:12px;flex:none;color:var(--fg-faint);font-size:9px;text-align:center;
  transition:transform .12s ease}
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
  text-transform:uppercase;color:var(--fg-faint)}
.path{font-family:var(--mono);font-size:11.5px;color:var(--fg-dim);
  word-break:break-all;margin-bottom:10px}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:9px}
.kpi{background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:10px}
.kpi .k{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--fg-faint)}
.kpi .v{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em;margin-top:2px}
.kpi .s{font-size:11px;color:var(--fg-faint);font-variant-numeric:tabular-nums}

table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--fg-faint);font-weight:700;padding:5px 7px;border-bottom:1px solid var(--line)}
td{padding:6px 7px;border-bottom:1px solid var(--line);vertical-align:middle}
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
.li .pc{font-variant-numeric:tabular-nums;color:var(--fg-faint);font-size:11px;
  width:42px;text-align:right}

.bar{height:7px;border-radius:4px;background:var(--panel-2);overflow:hidden;display:flex}
.bar i{display:block;height:100%}
.mrow{margin-bottom:11px}
.mtop{display:flex;justify-content:space-between;align-items:baseline;
  gap:8px;margin-bottom:4px;font-size:12px}
.mtop b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mtop span{font-family:var(--mono);font-size:11px;color:var(--fg-faint);flex:none}

.empty{color:var(--fg-faint);font-size:12.5px;padding:8px 2px}
.note{font-size:11px;color:var(--fg-faint);margin-top:9px;line-height:1.45}
svg{display:block;max-width:100%}
.donut-mid{text-anchor:middle;font-variant-numeric:tabular-nums}
.donut-mid .big{font-size:19px;font-weight:650;fill:var(--fg)}
.donut-mid .small{font-size:9.5px;fill:var(--fg-faint);text-transform:uppercase;
  letter-spacing:.07em}
.axis{font-size:9px;fill:var(--fg-faint)}

@media (max-width:1180px){
  .layout{grid-template-columns:250px minmax(0,1fr);height:auto}
  #side{grid-column:1/-1;border-left:0;border-top:1px solid var(--line)}
  .col{overflow:visible;max-height:none}
  #nav{max-height:60vh;overflow-y:auto}
}
@media (max-width:760px){
  .layout{grid-template-columns:1fr}
  #nav{border-right:0;border-bottom:1px solid var(--line)}
}
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
  <button id="expand">Expand all</button>
  <button id="theme">Theme</button>
  <div class="meta" id="hmeta"></div>
</header>

<div class="layout">
  <div class="col" id="nav"></div>
  <div class="col" id="main"></div>
  <div class="col" id="side"></div>
</div>

<script id="atlas-data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("atlas-data").textContent);

const KEYS  = ["input","output","cache_read","cache_creation"];
const LABEL = {input:"Input",output:"Output",cache_read:"Cache read",cache_creation:"Cache write"};
const CVAR  = {input:"--c-input",output:"--c-output",cache_read:"--c-read",cache_creation:"--c-write"};

let measure = "tokens";          // "tokens" | "cost"
let sel = {kind:"all"};

/* ---------- helpers ---------- */
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function abbr(n){
  n = n || 0;
  if (n >= 1e9) return (n/1e9).toFixed(n < 1e10 ? 2 : 1) + "B";
  if (n >= 1e6) return (n/1e6).toFixed(n < 1e7 ? 2 : 1) + "M";
  if (n >= 1e3) return (n/1e3).toFixed(n < 1e4 ? 1 : 0) + "K";
  return String(n);
}
const num  = n => (n||0).toLocaleString();
const usd  = c => (c||0) < 0.01 ? "$0.00"
                : "$" + (c||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
function bytes(b){
  if (b >= 1e9) return (b/1e9).toFixed(1)+" GB";
  if (b >= 1e6) return (b/1e6).toFixed(1)+" MB";
  if (b >= 1e3) return (b/1e3).toFixed(0)+" KB";
  return b+" B";
}
function when(iso){
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  return d.toLocaleString(undefined,{month:"short",day:"numeric",year:"numeric",
                                     hour:"numeric",minute:"2-digit"});
}
const totalOf = u => KEYS.reduce((s,k)=>s+(u&&u[k]||0),0);

/* Cost of one usage bucket for one model — mirrors collect.py exactly so the
   two never disagree about what a number means. */
function costOf(u, model){
  const P = DATA.pricing, M = P.models;
  let r = M[model];
  if (!r){
    const low = (model||"").toLowerCase();
    for (const t of P.fallback_order){ if (low.includes(t)){ r = M[P.fallback_tiers[t]]; break; } }
    if (!r) r = M[P.fallback_tiers._default];
  }
  return ((u.input||0)*r.input
        + (u.output||0)*r.output
        + (u.cache_read||0)*r.input*P.cache_read_multiplier
        + (u.cache_creation||0)*r.input*P.cache_write_multiplier) / 1e6;
}
/* Per-component cost, so the composition chart can switch to a cost basis. */
function costParts(models){
  const out = {input:0,output:0,cache_read:0,cache_creation:0};
  for (const [m,slot] of Object.entries(models||{})){
    for (const k of KEYS){
      const one = {input:0,output:0,cache_read:0,cache_creation:0};
      one[k] = slot.usage[k]||0;
      out[k] += costOf(one, m);
    }
  }
  return out;
}
const fmt = v => measure === "cost" ? usd(v) : abbr(v);

/* ---------- scope resolution ---------- */
function allScope(){
  return {title:"All projects", sub:DATA.projects.length+" projects · "+DATA.session_count+" sessions",
          usage:DATA.usage, models:DATA.models, daily:DATA.daily, tools:DATA.tools,
          cost:DATA.cost, node:DATA};
}
function scope(){
  if (sel.kind === "all") return allScope();
  if (sel.kind === "project"){
    const p = DATA.projects.find(x=>x.id===sel.id);
    if (!p) return allScope();
    return {title:p.name, sub:p.path, usage:p.usage, models:p.models, daily:p.daily,
            tools:p.tools, cost:p.cost, node:p, project:p};
  }
  const p = DATA.projects.find(x=>x.id===sel.pid);
  const s = p && p.sessions.find(x=>x.id===sel.id);
  if (!s) return allScope();
  return {title:s.title || "Untitled session", sub:p.path, usage:s.usage, models:s.models,
          daily:s.daily, tools:s.tools, cost:s.cost, node:s, project:p, session:s};
}

/* ---------- charts ---------- */
function donut(parts, centerLabel){
  const total = KEYS.reduce((s,k)=>s+(parts[k]||0),0);
  const R=54, r=36, cx=64, cy=64, C=2*Math.PI*((R+r)/2), W=R-r;
  if (!total) return '<div class="empty">No usage recorded.</div>';
  let off=0, arcs="";
  for (const k of KEYS){
    const v = parts[k]||0;
    if (v <= 0) continue;
    const len = C * (v/total);
    arcs += `<circle cx="${cx}" cy="${cy}" r="${(R+r)/2}" fill="none"
      stroke="var(${CVAR[k]})" stroke-width="${W}"
      stroke-dasharray="${len.toFixed(3)} ${(C-len).toFixed(3)}"
      stroke-dashoffset="${(-off).toFixed(3)}" transform="rotate(-90 ${cx} ${cy})"><title>${LABEL[k]}: ${fmt(v)}</title></circle>`;
    off += len;
  }
  const rows = KEYS.map(k=>{
    const v = parts[k]||0;
    const pc = total ? (v/total*100) : 0;
    return `<div class="li"><span class="sw" style="background:var(${CVAR[k]})"></span>
      <span class="nm">${LABEL[k]}</span>
      <span class="vl">${fmt(v)}</span>
      <span class="pc">${pc<0.1&&pc>0?"<0.1":pc.toFixed(1)}%</span></div>`;
  }).join("");
  return `<svg viewBox="0 0 128 128" width="128" height="128" style="margin:0 auto"
      role="img" aria-label="Token composition">${arcs}
      <g class="donut-mid"><text x="64" y="62" class="big">${fmt(total)}</text>
      <text x="64" y="76" class="small">${esc(centerLabel)}</text></g></svg>
    <div class="legend">${rows}</div>`;
}

function modelBars(models){
  const rows = Object.entries(models||{}).map(([m,slot])=>{
    const val = measure === "cost" ? costOf(slot.usage,m) : totalOf(slot.usage);
    return {m, slot, val};
  }).filter(r=>r.val>0).sort((a,b)=>b.val-a.val);
  if (!rows.length) return '<div class="empty">No model activity.</div>';
  const max = rows[0].val;
  return rows.map(({m,slot,val})=>{
    /* Each bar is internally stacked by component, so one glance shows both
       which model dominates and what that model's spend is made of. */
    const segs = KEYS.map(k=>{
      const part = measure === "cost"
        ? costOf({...{input:0,output:0,cache_read:0,cache_creation:0},[k]:slot.usage[k]||0}, m)
        : (slot.usage[k]||0);
      const w = val ? (part/val*100) : 0;
      return w > 0 ? `<i style="width:${w.toFixed(3)}%;background:var(${CVAR[k]})"></i>` : "";
    }).join("");
    return `<div class="mrow">
      <div class="mtop"><b title="${esc(m)}">${esc(m)}</b><span>${fmt(val)}</span></div>
      <div class="bar" style="width:${(val/max*100).toFixed(2)}%" title="${esc(m)}: ${fmt(val)}">${segs}</div>
      <div class="tag" style="margin-top:3px">${num(slot.messages)} messages</div>
    </div>`;
  }).join("");
}

function trend(daily){
  const days = Object.keys(daily||{}).sort();
  if (days.length < 2) return '<div class="empty">Not enough days to plot a trend.</div>';
  const vals = days.map(d=>{
    const u = daily[d];
    return measure === "cost" ? costEstimateDay(u) : totalOf(u);
  });
  const max = Math.max(...vals) || 1;
  const W=310, H=76, P=4;
  const x = i => P + (W-2*P) * (days.length===1?0:i/(days.length-1));
  const y = v => H-P - (H-2*P) * (v/max);
  const line = vals.map((v,i)=>`${i?"L":"M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${line}L${x(vals.length-1).toFixed(1)},${H-P}L${x(0).toFixed(1)},${H-P}Z`;
  return `<svg viewBox="0 0 ${W} ${H+14}" width="100%" height="${H+14}" role="img"
      aria-label="Usage over time">
      <path d="${area}" fill="var(--accent)" opacity=".14"/>
      <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="1.8"
            stroke-linejoin="round" stroke-linecap="round"/>
      <text class="axis" x="${P}" y="${H+11}">${esc(days[0])}</text>
      <text class="axis" x="${W-P}" y="${H+11}" text-anchor="end">${esc(days[days.length-1])}</text>
    </svg>
    <div class="tag" style="margin-top:2px">peak ${fmt(max)} · ${days.length} active days</div>`;
}
/* Daily buckets aren't split by model, so a day's cost is apportioned with the
   scope's blended rate rather than invented per-model. */
let _blend = 1;
function costEstimateDay(u){ return totalOf(u) * _blend; }

function cacheMeter(u){
  const cachedIn = (u.cache_read||0) + (u.cache_creation||0) + (u.input||0);
  if (!cachedIn) return "";
  const hit = (u.cache_read||0) / cachedIn * 100;
  return `<div class="mtop"><b>Cache hit rate</b><span>${hit.toFixed(1)}%</span></div>
    <div class="bar"><i style="width:${hit.toFixed(2)}%;background:var(--c-read)"></i></div>
    <div class="note">Share of input served from cache at ~${DATA.pricing.cache_read_multiplier}×
    the input rate. Higher is cheaper.</div>`;
}

/* ---------- right panel ---------- */
function renderSide(){
  const sc = scope();
  const parts = measure === "cost" ? costParts(sc.models) : sc.usage;
  const tot = totalOf(sc.usage);
  _blend = tot ? (sc.cost/tot) : 0;

  document.getElementById("side").innerHTML = `
    <div class="card">
      <h3>Token consumption</h3>
      <h2 style="margin-bottom:2px">${esc(sc.title)}</h2>
      <div class="tag" style="margin-bottom:12px">${measure==="cost"?"estimated cost":"tokens"}</div>
      ${donut(parts, measure==="cost"?"est. cost":"tokens")}
    </div>
    <div class="card">
      <h3>By model</h3>
      ${modelBars(sc.models)}
    </div>
    <div class="card">
      <h3>Over time</h3>
      ${trend(sc.daily)}
    </div>
    <div class="card">
      <h3>Cache</h3>
      ${cacheMeter(sc.usage) || '<div class="empty">No cache activity.</div>'}
    </div>`;
}

/* ---------- centre pane ---------- */
function kpis(sc){
  const u = sc.usage, t = totalOf(u);
  return `<div class="kpis">
    <div class="kpi"><div class="k">Total tokens</div><div class="v">${abbr(t)}</div>
      <div class="s">${num(t)}</div></div>
    <div class="kpi"><div class="k">Est. cost</div><div class="v">${usd(sc.cost)}</div>
      <div class="s">list price</div></div>
    <div class="kpi"><div class="k">Output</div><div class="v">${abbr(u.output)}</div>
      <div class="s">${t?((u.output/t)*100).toFixed(1):0}% of tokens</div></div>
    <div class="kpi"><div class="k">Cache read</div><div class="v">${abbr(u.cache_read)}</div>
      <div class="s">${t?((u.cache_read/t)*100).toFixed(1):0}% of tokens</div></div>
  </div>`;
}

function toolTable(tools){
  const rows = Object.entries(tools||{}).sort((a,b)=>b[1]-a[1]).slice(0,12);
  if (!rows.length) return "";
  const max = rows[0][1];
  return `<div class="card"><h3>Tool calls</h3>${
    rows.map(([n,c])=>`<div class="mrow">
      <div class="mtop"><b>${esc(n)}</b><span>${num(c)}</span></div>
      <div class="bar" style="width:${(c/max*100).toFixed(2)}%"><i style="width:100%;background:var(--accent)"></i></div>
    </div>`).join("")}</div>`;
}

function renderMain(){
  const sc = scope();
  let html = "";

  if (sel.kind === "all"){
    html += `<div class="card"><h2>All projects</h2>
      <div class="path">${esc(DATA.projects_root)}</div>${kpis(sc)}</div>`;
    html += `<div class="card"><h3>Projects</h3><div class="scroll"><table>
      <thead><tr><th>Project</th><th class="n">Sessions</th><th class="n">Tokens</th>
      <th class="n">Est. cost</th></tr></thead><tbody>${
      DATA.projects.map(p=>`<tr data-p="${esc(p.id)}">
        <td><b>${esc(p.name)}</b><div class="tag">${esc(p.path)}</div></td>
        <td class="n">${p.sessions.length}</td>
        <td class="n">${abbr(p.total_tokens)}</td>
        <td class="n">${usd(p.cost)}</td></tr>`).join("")
      }</tbody></table></div></div>`;
    html += toolTable(DATA.tools);
  }
  else if (sel.kind === "project"){
    const p = sc.project;
    html += `<div class="card"><h2>${esc(p.name)}</h2>
      <div class="path">${esc(p.path)}</div>${kpis(sc)}</div>`;
    html += `<div class="card"><h3>Sessions</h3><div class="scroll"><table>
      <thead><tr><th>Session</th><th class="n">Msgs</th><th class="n">Tokens</th>
      <th class="n">Est. cost</th><th class="n">Updated</th></tr></thead><tbody>${
      p.sessions.map(s=>`<tr data-p="${esc(p.id)}" data-s="${esc(s.id)}">
        <td><b>${esc(s.title||"Untitled session")}</b>
          <div class="tag">${esc(s.id.slice(0,8))} · ${bytes(s.size_bytes)}</div></td>
        <td class="n">${num(s.messages.user)}/${num(s.messages.assistant)}</td>
        <td class="n">${abbr(s.total_tokens)}</td>
        <td class="n">${usd(s.cost)}</td>
        <td class="n">${esc(when(s.ended))}</td></tr>`).join("")
      }</tbody></table></div>
      <div class="note">Msgs shows user/assistant turns.</div></div>`;
    html += toolTable(p.tools);
  }
  else {
    const s = sc.session, p = sc.project;
    html += `<div class="card"><h2>${esc(s.title||"Untitled session")}</h2>
      <div class="path">${esc(p.path)}${s.branch?" · branch "+esc(s.branch):""}</div>
      ${kpis(sc)}</div>`;
    html += `<div class="card"><h3>Details</h3><table><tbody>
      <tr><td>Session id</td><td class="n">${esc(s.id)}</td></tr>
      <tr><td>Transcript</td><td class="n">${bytes(s.size_bytes)}</td></tr>
      <tr><td>Started</td><td class="n">${esc(when(s.started))}</td></tr>
      <tr><td>Last activity</td><td class="n">${esc(when(s.ended))}</td></tr>
      <tr><td>Turns (user/assistant)</td><td class="n">${num(s.messages.user)} / ${num(s.messages.assistant)}</td></tr>
      ${s.version?`<tr><td>Claude Code version</td><td class="n">${esc(s.version)}</td></tr>`:""}
      </tbody></table></div>`;
    if (s.last_prompt)
      html += `<div class="card"><h3>Last prompt</h3>
        <div style="font-size:12.5px;color:var(--fg-dim);white-space:pre-wrap;word-break:break-word">${esc(s.last_prompt.slice(0,600))}</div></div>`;
    html += toolTable(s.tools);
  }
  document.getElementById("main").innerHTML = html;

  document.querySelectorAll("#main tbody tr").forEach(tr=>{
    tr.addEventListener("click", ()=>{
      const p = tr.getAttribute("data-p"), s = tr.getAttribute("data-s");
      select(s ? {kind:"session", pid:p, id:s} : {kind:"project", id:p});
    });
  });
}

/* ---------- left nav ---------- */
function fileNode(n, depth){
  if (n.type === "file"){
    return `<div class="row" style="padding-left:${6+depth*11}px">
      <span class="tw"></span><span class="ico">${n.code?"■":"□"}</span>
      <span class="lbl" title="${esc(n.name)}">${esc(n.name)}</span>
      <span class="tag">${bytes(n.size)}</span></div>`;
  }
  const kids = (n.children||[]).map(c=>fileNode(c, depth+1)).join("")
    + (n.truncated ? `<div class="sub" style="padding-left:${18+depth*11}px">…truncated</div>` : "");
  return `<div class="node"><div class="row dtog" style="padding-left:${6+depth*11}px">
      <span class="tw">▶</span><span class="ico">▸</span>
      <span class="lbl" title="${esc(n.name)}">${esc(n.name)}</span>
      <span class="tag">${(n.children||[]).length}</span></div>
      <div class="kids">${kids}</div></div>`;
}

function renderNav(){
  let h = `<div class="sec">Overview</div>
    <div class="row nsel ${sel.kind==="all"?"on":""}" data-k="all">
      <span class="tw"></span><span class="ico">◈</span>
      <span class="lbl">All projects</span>
      <span class="tag">${abbr(DATA.total_tokens)}</span></div>`;

  h += `<div class="sec">Chats</div>`;
  for (const p of DATA.projects){
    const open = (sel.kind==="project" && sel.id===p.id) || (sel.kind==="session" && sel.pid===p.id);
    h += `<div class="node">
      <div class="row nsel ${sel.kind==="project"&&sel.id===p.id?"on":""}" data-k="project" data-p="${esc(p.id)}">
        <span class="tw ${open?"open":""} ptog">▶</span>
        <span class="ico">◉</span>
        <span class="lbl" title="${esc(p.path)}">${esc(p.name)}</span>
        <span class="tag">${abbr(p.total_tokens)}</span></div>
      <div class="kids ${open?"open":""}">${
        p.sessions.map(s=>`<div class="row nsel ${sel.kind==="session"&&sel.id===s.id?"on":""}"
            data-k="session" data-p="${esc(p.id)}" data-s="${esc(s.id)}" style="padding-left:17px">
          <span class="tw"></span><span class="ico">○</span>
          <span class="lbl" title="${esc(s.title||s.id)}">${esc(s.title||"Untitled session")}</span>
          <span class="tag">${abbr(s.total_tokens)}</span></div>`).join("")
      }</div></div>`;
  }

  h += `<div class="sec">Code projects</div>`;
  for (const p of DATA.projects){
    if (!p.tree){
      h += `<div class="row" title="${esc(p.path)}"><span class="tw"></span>
        <span class="ico">⊘</span><span class="lbl">${esc(p.name)}</span>
        <span class="tag">n/a</span></div>`;
      continue;
    }
    h += `<div class="node"><div class="row dtog">
        <span class="tw">▶</span><span class="ico">▸</span>
        <span class="lbl" title="${esc(p.path)}">${esc(p.name)}</span>
        <span class="tag">${(p.tree.children||[]).length}</span></div>
      <div class="kids">${(p.tree.children||[]).map(c=>fileNode(c,1)).join("")}</div></div>`;
  }

  const nav = document.getElementById("nav");
  nav.innerHTML = h;

  /* Directory twisties: toggle only, never change the selection. */
  nav.querySelectorAll(".row.dtog").forEach(row=>{
    row.addEventListener("click", e=>{
      e.stopPropagation();
      row.querySelector(".tw").classList.toggle("open");
      row.nextElementSibling.classList.toggle("open");
    });
  });
  /* Project twistie expands the session list without selecting the project. */
  nav.querySelectorAll(".ptog").forEach(tw=>{
    tw.addEventListener("click", e=>{
      e.stopPropagation();
      tw.classList.toggle("open");
      tw.closest(".row").nextElementSibling.classList.toggle("open");
    });
  });
  nav.querySelectorAll(".row.nsel").forEach(row=>{
    row.addEventListener("click", ()=>{
      const k = row.getAttribute("data-k");
      if (k === "all") select({kind:"all"});
      else if (k === "project") select({kind:"project", id:row.getAttribute("data-p")});
      else select({kind:"session", pid:row.getAttribute("data-p"), id:row.getAttribute("data-s")});
    });
  });
}

/* ---------- wiring ---------- */
function select(next){ sel = next; renderNav(); renderMain(); renderSide(); }

function setMeasure(m){
  measure = m;
  document.getElementById("mTok").setAttribute("aria-pressed", String(m==="tokens"));
  document.getElementById("mCost").setAttribute("aria-pressed", String(m==="cost"));
  renderSide();
}
document.getElementById("mTok").onclick  = ()=>setMeasure("tokens");
document.getElementById("mCost").onclick = ()=>setMeasure("cost");

document.getElementById("expand").onclick = e=>{
  const on = e.target.getAttribute("aria-pressed") !== "true";
  e.target.setAttribute("aria-pressed", String(on));
  e.target.textContent = on ? "Collapse all" : "Expand all";
  document.querySelectorAll("#nav .kids").forEach(k=>k.classList.toggle("open", on));
  document.querySelectorAll("#nav .tw").forEach(t=>{
    if (t.textContent.trim()) t.classList.toggle("open", on);
  });
};

document.getElementById("theme").onclick = ()=>{
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : cur === "light" ? "dark"
    : (matchMedia("(prefers-color-scheme: dark)").matches ? "light" : "dark");
  document.documentElement.setAttribute("data-theme", next);
};

document.getElementById("hcount").textContent =
  `· ${DATA.projects.length} projects · ${DATA.session_count} sessions`;
document.getElementById("hmeta").textContent =
  `${abbr(DATA.total_tokens)} tokens · ~${usd(DATA.cost)} · scanned ${DATA.generated_at.replace("T"," ").replace("+00:00"," UTC")}`;

select({kind:"all"});
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the Claude Atlas dashboard.")
    ap.add_argument("--data", help="path to collect.py JSON output (default: run collect.py)")
    ap.add_argument("--out", default=str(Path.home() / ".claude" / "atlas" / "dashboard.html"))
    ap.add_argument("--open", action="store_true", help="open in the default browser")
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

    # Guard the closing tag so the payload can't terminate its own <script>.
    safe = raw.replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", safe)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    data = json.loads(raw)
    print(f"Dashboard: {out}")
    print(f"  {len(data.get('projects', []))} projects, "
          f"{data.get('session_count', 0)} sessions, "
          f"{data.get('total_tokens', 0):,} tokens, ~${data.get('cost', 0):,.2f} estimated")

    if args.open:
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
