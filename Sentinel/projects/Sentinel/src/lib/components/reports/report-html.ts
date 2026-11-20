/**
 * The report as one self-contained HTML page: no external font, script or image, so the file
 * opens anywhere, offline, and prints cleanly. Every value that comes from the air (network
 * names, alert titles) goes through esc().
 */

export interface ReportLabels {
    severity: { [k: string]: string };
    kind: { [k: string]: string };
    period: string;
}

const CH24 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13];
const CH5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144,
    149, 153, 157, 161, 165];

export function esc(value: any): string {
    return String(value === null || value === undefined ? '' : value)
        .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function when(ts: number): string {
    const d = new Date(ts * 1000), p = (n: number) => ('0' + n).slice(-2);
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function dash(v: any): string {
    return v === null || v === undefined ? '–' : String(v);
}

/** The level a score reads as, for its colour. */
function scoreGrade(score: number): string {
    if (score === null || score === undefined) { return 'info'; }
    return score < 40 ? 'critical' : score < 60 ? 'high' : score < 75 ? 'medium' : score < 90 ? 'low' : 'good';
}

/** Half-circle gauge, 0 to 100. */
function gauge(score: number, label: string): string {
    const r = 74, cx = 90, cy = 88, v = Math.max(0, Math.min(100, score || 0));
    const a = Math.PI * (1 - v / 100);
    const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
    const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`;
    return `<svg class="gauge" viewBox="0 0 180 104" role="img" aria-label="${esc(label)}: ${esc(dash(score))} out of 100">
        <path d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}" class="g-track"/>
        ${score === null || score === undefined ? '' : `<path d="${arc}" class="g-fill s-${scoreGrade(score)}"/>`}
        <text x="${cx}" y="${cy - 12}" class="g-num">${esc(dash(score))}</text>
        <text x="${cx}" y="${cy + 10}" class="g-unit">/ 100</text>
    </svg>`;
}

/** Score lines (yours, neighbourhood) and alert bars, one column per day. */
function trendChart(trend: any[]): string {
    if (trend.length < 2) {
        return `<p class="muted">The trend shows up after two days of listening: Sentinel keeps one point per day.</p>`;
    }
    const W = 720, H = 220, L = 34, R = 22, T = 10, plotH = 130, barTop = 168, barH = 34;
    const n = trend.length, step = (W - L - R) / (n - 1);
    const x = (i: number) => L + i * step;
    const y = (v: number) => T + plotH - v / 100 * plotH;
    const line = (key: string) => trend.map((t, i) => t[key] === null || t[key] === undefined ? null :
        `${x(i).toFixed(1)},${y(t[key]).toFixed(1)}`).filter((p) => p).join(' ');
    const maxAlerts = Math.max(1, ...trend.map((t) => t.alerts || 0));
    const bw = Math.max(3, Math.min(18, step * 0.5));
    const every = Math.ceil(n / 10);
    const grid = [0, 25, 50, 75, 100].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="c-grid"/>
        <text x="${L - 6}" y="${y(v) + 3}" class="c-axis" text-anchor="end">${v}</text>`).join('');
    const bars = trend.map((t, i) => {
        const h = (t.alerts || 0) / maxAlerts * barH;
        return h ? `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${(barTop + barH - h).toFixed(1)}" width="${bw.toFixed(1)}"
            height="${h.toFixed(1)}" class="${t.alerts_serious ? 'b-serious' : 'b-alerts'}"><title>${esc(t.day)}: ${t.alerts} alerts</title></rect>` : '';
    }).join('');
    const days = trend.map((t, i) => i % every === 0 || i === n - 1
        ? `<text x="${x(i).toFixed(1)}" y="${H - 2}" class="c-axis" text-anchor="middle">${esc(String(t.day).slice(5))}</text>` : '').join('');
    const dots = trend.map((t, i) => t.my_score === null || t.my_score === undefined ? '' :
        `<circle cx="${x(i).toFixed(1)}" cy="${y(t.my_score).toFixed(1)}" r="3" class="c-dot"><title>${esc(t.day)}: ${t.my_score}/100</title></circle>`).join('');
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Scores and alerts per day">
        ${grid}
        <polyline points="${line('area_score')}" class="c-area"/>
        <polyline points="${line('my_score')}" class="c-mine"/>
        ${dots}
        <line x1="${L}" x2="${W - R}" y1="${barTop + barH}" y2="${barTop + barH}" class="c-base"/>
        <text x="${L - 6}" y="${barTop + 6}" class="c-axis" text-anchor="end">${maxAlerts}</text>
        <text x="${L - 6}" y="${barTop + barH}" class="c-axis" text-anchor="end">0</text>
        <text x="${L}" y="${barTop - 8}" class="c-axis">alerts</text>
        ${bars}${days}
    </svg>
    <div class="legend"><span><i class="k-mine"></i>Your networks</span><span><i class="k-area"></i>Neighbourhood</span>
        <span><i class="k-bar"></i>Alerts per day</span><span><i class="k-serious"></i>with a serious one</span></div>`;
}

function channelStrip(channels: number[], best: any, yours: number[]): string {
    return `<div class="strip">${channels.map((c) => {
        const cls = [c === best ? 'is-best' : '', yours.indexOf(c) >= 0 ? 'is-yours' : ''].join(' ').trim();
        return `<span class="ch ${cls}" title="Channel ${c}${c === best ? ', best now' : ''}${yours.indexOf(c) >= 0 ? ', yours' : ''}">${c}</span>`;
    }).join('')}</div>`;
}

export function renderReportHtml(d: any, labels: ReportLabels, helpers: {
    band: (b: string) => string, best: (b: string) => any, yours: (b: string) => number[],
    kinds: { kind: string, count: number }[], serious: number,
}): string {
    const sev = (s: string) => labels.severity[s] || s;
    const chip = (s: string) => `<span class="chip s-${esc(s)}">${esc(sev(s))}</span>`;
    const title = labels.period.charAt(0).toUpperCase() + labels.period.slice(1);
    const maxKind = Math.max(1, ...helpers.kinds.map((k) => k.count));

    const todo = d.mine.todo.length ? `<ol class="todo">${d.mine.todo.map((t) => `
        <li class="edge-${esc(t.severity)}">${chip(t.severity)}<div><b>${esc(t.advice)}</b>
            <span class="muted">${esc(t.networks.join(', '))}</span></div></li>`).join('')}</ol>`
        : `<p class="ok-note">Nothing to change on your networks.</p>`;

    const nets = d.mine.networks.length ? `<div class="scroll"><table class="nets"><thead><tr><th>Network</th><th>Band</th><th>Security</th>
        <th>PMF</th><th>WPS</th><th>Level</th></tr></thead><tbody>${d.mine.networks.map((n) => `<tr>
            <td><b>${esc(n.ssid || '(hidden name)')}</b><div class="mono muted">${esc(n.bssid)}</div></td>
            <td>${esc(helpers.band(n.band))}<div class="muted">channel ${esc(n.channel)}</div></td>
            <td>${esc(n.security)}</td>
            <td><span class="flag ${n.pmf === 'required' ? 'f-good' : n.pmf === 'capable' ? 'f-mid' : 'f-bad'}">${esc(n.pmf || 'none')}</span></td>
            <td><span class="flag ${n.wps ? 'f-bad' : 'f-good'}">${n.wps ? 'on' : 'off'}</span></td>
            <td>${chip(n.grade)}</td></tr>`).join('')}</tbody></table></div>`
        : `<p class="muted">None of your networks was seen in this period.</p>`;
    const notSeen = d.mine.not_seen.length
        ? `<p class="muted small">Not seen in this period: ${esc(d.mine.not_seen.map((x) => x.ssid || x.bssid).join(', '))}.</p>` : '';

    const alerts = d.alerts.total ? `
        <div class="kinds">${helpers.kinds.map((k) => `<div class="kind"><span>${esc(labels.kind[k.kind] || k.kind)}</span>
            <span class="bar"><i style="width:${(k.count / maxKind * 100).toFixed(1)}%"></i></span><b class="num">${k.count}</b></div>`).join('')}</div>
        <h3>The most serious</h3>
        <ul class="alerts">${d.alerts.top.map((a) => `<li>${chip(a.severity)}<span>${esc(a.title)}</span>
            <span class="muted num">${esc(when(a.ts))}</span></li>`).join('')}</ul>`
        : `<p class="ok-note">No alert in this period.</p>`;

    const sevCounts = ['critical', 'high', 'medium', 'low', 'info'].map((s) =>
        `<span class="count"><b class="num t-${s}">${d.alerts.by_severity[s] || 0}</b> ${esc(sev(s))}</span>`).join('');

    return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel Wi-Fi report, ${esc(when(d.generated_at).slice(0, 10))}</title>
<style>
:root {
    --page: #eef1f4; --card: #ffffff; --ink: #16202b; --muted: #5b6775; --line: #dde3ea;
    --head: #0f1f30; --head-2: #1d2b3a; --head-ink: #e8eef5; --head-muted: #9fb0c2; --accent: #3f51b5;
    --critical: #c62f37; --high: #bd5410; --medium: #8a6d00; --low: #2a6fb0; --good: #1d8a64; --info: #6b7785;
    --critical-bg: #fbe9ea; --high-bg: #fdeee3; --medium-bg: #fbf3d6; --low-bg: #e6f0fa; --good-bg: #e3f4ed; --info-bg: #eef1f4;
    --spark: #f0a83a;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--page); color: var(--ink);
    font: 15px/1.5 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.num, .mono { font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
.muted { color: var(--muted); } .small { font-size: 13px; }
.wrap { max-width: 980px; margin: 0 auto; padding: 0 24px 40px; }

header.top { background: linear-gradient(160deg, var(--head) 0%, var(--head-2) 100%); color: var(--head-ink); }
header.top .wrap { padding-top: 28px; padding-bottom: 28px; display: grid; grid-template-columns: 1fr auto; gap: 24px; align-items: center; }
.brand { display: flex; align-items: center; gap: 14px; }
.brand svg { width: 44px; height: 44px; flex: none; }
.brand .shield { fill: var(--accent); } .brand .waves { fill: none; stroke: #fff; stroke-width: 2.6; stroke-linecap: round; }
.brand .dot { fill: #fff; }
h1 { margin: 0; font-size: 26px; font-weight: 650; letter-spacing: -0.01em; }
.period { color: var(--head-muted); font-size: 14px; margin-top: 2px; }
.scores { display: flex; gap: 18px; }
.score { text-align: center; }
.score .cap { color: var(--head-muted); font-size: 13px; margin-top: -4px; }
.gauge { width: 168px; height: 98px; display: block; }
.g-track { fill: none; stroke: rgba(255,255,255,0.12); stroke-width: 14; stroke-linecap: round; }
.g-fill { fill: none; stroke-width: 14; stroke-linecap: round; }
.g-fill.s-critical { stroke: #f0545a; } .g-fill.s-high { stroke: #f08a3c; } .g-fill.s-medium { stroke: #e9c544; }
.g-fill.s-low { stroke: #5aa9e6; } .g-fill.s-good { stroke: #3cc59a; }
.g-num { fill: #fff; font-size: 38px; font-weight: 650; text-anchor: middle; font-variant-numeric: tabular-nums; }
.g-unit { fill: var(--head-muted); font-size: 12px; text-anchor: middle; }

.figs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--line);
    border: 1px solid var(--line); border-radius: 10px; overflow: hidden; margin: -22px 0 22px; position: relative; }
.fig { background: var(--card); padding: 14px 18px; }
.fig b { display: block; font-size: 26px; font-weight: 650; line-height: 1.15; }
.fig span { color: var(--muted); font-size: 13px; }

section { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 20px 24px; margin-top: 16px;
    break-inside: avoid; }
h2 { margin: 0 0 12px; font-size: 17px; font-weight: 650; display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; }
.scroll { overflow-x: auto; }
h2 small { font-size: 13px; font-weight: 400; color: var(--muted); }
h3 { margin: 18px 0 6px; font-size: 13px; font-weight: 600; color: var(--muted); }

.chip { display: inline-flex; align-items: center; gap: 6px; padding: 1px 9px 1px 7px; border-radius: 999px;
    font-size: 12px; font-weight: 600; white-space: nowrap; }
.chip::before { content: ''; width: 7px; height: 7px; border-radius: 2px; background: currentColor; }
.s-critical.chip { color: var(--critical); background: var(--critical-bg); }
.s-high.chip { color: var(--high); background: var(--high-bg); }
.s-medium.chip { color: var(--medium); background: var(--medium-bg); }
.s-low.chip { color: var(--low); background: var(--low-bg); }
.s-good.chip { color: var(--good); background: var(--good-bg); }
.s-info.chip { color: var(--info); background: var(--info-bg); }
.t-critical { color: var(--critical); } .t-high { color: var(--high); } .t-medium { color: var(--medium); }
.t-low { color: var(--low); } .t-info { color: var(--info); }

.chart { width: 100%; height: auto; display: block; }
.c-grid { stroke: var(--line); stroke-dasharray: 3 4; } .c-base { stroke: var(--line); }
.c-axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.c-mine { fill: none; stroke: var(--accent); stroke-width: 2.4; stroke-linejoin: round; }
.c-area { fill: none; stroke: #9aa6b4; stroke-width: 1.6; stroke-dasharray: 5 4; }
.c-dot { fill: var(--card); stroke: var(--accent); stroke-width: 2; }
.b-alerts { fill: #c7cfd9; } .b-serious { fill: var(--high); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 12px; color: var(--muted); margin-top: 6px; }
.legend i { display: inline-block; width: 16px; height: 3px; margin-right: 6px; vertical-align: middle; border-radius: 2px; }
.k-mine { background: var(--accent); } .k-area { background: #9aa6b4; } .k-bar { background: #c7cfd9; height: 8px !important; width: 8px !important; }
.k-serious { background: var(--high); height: 8px !important; width: 8px !important; }

ol.todo { list-style: none; counter-reset: step; padding: 0; margin: 0; }
ol.todo li { counter-increment: step; display: grid; grid-template-columns: 28px auto 1fr; gap: 4px 12px; align-items: baseline;
    padding: 11px 0 11px 12px; border-top: 1px solid var(--line); border-left: 3px solid transparent; }
ol.todo li:first-child { border-top: 0; }
ol.todo li::before { content: counter(step); color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }
ol.todo li div { display: flex; flex-direction: column; }
.edge-critical { border-left-color: var(--critical) !important; } .edge-high { border-left-color: var(--high) !important; }
.edge-medium { border-left-color: #e9c544 !important; } .edge-low { border-left-color: var(--low) !important; }
.edge-info { border-left-color: var(--info) !important; }
.ok-note { margin: 0; color: var(--good); font-weight: 600; }

table.nets { width: 100%; border-collapse: collapse; font-size: 14px; }
.nets th { text-align: left; font-size: 12px; font-weight: 600; color: var(--muted); padding: 0 10px 8px 0; border-bottom: 1px solid var(--line); }
.nets td { padding: 10px 10px 10px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
.nets tr:last-child td { border-bottom: 0; }
.flag { font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 4px; }
.f-good { color: var(--good); background: var(--good-bg); } .f-mid { color: var(--medium); background: var(--medium-bg); }
.f-bad { color: var(--critical); background: var(--critical-bg); }

.counts { display: flex; flex-wrap: wrap; gap: 4px 22px; margin-bottom: 14px; font-size: 13px; color: var(--muted); }
.count b { font-size: 20px; margin-right: 3px; }
.kinds { display: grid; gap: 7px; }
.kind { display: grid; grid-template-columns: 210px 1fr 36px; gap: 12px; align-items: center; font-size: 14px; }
.kind b { text-align: right; }
.bar { height: 8px; background: var(--page); border-radius: 4px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
ul.alerts { list-style: none; margin: 0; padding: 0; }
ul.alerts li { display: grid; grid-template-columns: 96px 1fr auto; gap: 12px; align-items: baseline; padding: 8px 0;
    border-top: 1px solid var(--line); font-size: 14px; }

.band { display: grid; grid-template-columns: 70px 1fr; gap: 12px; align-items: center; margin: 8px 0; }
.band b { font-size: 14px; }
.strip { display: flex; flex-wrap: wrap; gap: 4px; }
.ch { min-width: 30px; padding: 4px 0; text-align: center; font-size: 12px; border-radius: 5px; background: var(--page);
    color: var(--muted); font-variant-numeric: tabular-nums; border: 1.5px solid transparent; }
.ch.is-yours { border-color: var(--accent); color: var(--ink); font-weight: 600; }
.ch.is-best { background: var(--spark); color: #2a1d00; font-weight: 700; }
.chan-legend { display: flex; gap: 18px; font-size: 12px; color: var(--muted); margin-top: 8px; }
.chan-legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -2px; }

footer { color: var(--muted); font-size: 12px; margin-top: 22px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }

@media (max-width: 720px) {
    header.top .wrap { grid-template-columns: 1fr; }
    .figs { grid-template-columns: repeat(2, 1fr); margin-top: 16px; }
    .kind { grid-template-columns: 1fr 70px 30px; }
    ul.alerts li { grid-template-columns: 1fr; gap: 2px; }
    ul.alerts .chip { justify-self: start; }
    .nets .mono { display: none; }
    .wrap { padding-left: 14px; padding-right: 14px; }
    section { padding: 16px; }
}
@media print {
    body { background: #fff; font-size: 12px; }
    .wrap { max-width: none; padding: 0 0 12px; }
    header.top .wrap { padding: 18px 20px; }
    .figs { margin-top: 14px; }
    section { border-color: #cfd6de; padding: 14px 18px; margin-top: 10px; }
    @page { margin: 12mm; }
}
</style></head>
<body>
<header class="top"><div class="wrap">
    <div class="brand">
        <svg viewBox="0 0 48 48" aria-hidden="true"><path class="shield" d="M24,3,7,9.6V22.4c0,10.6,7.2,20,17,22.6,9.8-2.6,17-12,17-22.6V9.6Z"/>
            <path class="waves" d="M15.6,22.6a11.9,11.9,0,0,1,16.8,0M19.3,26.3a6.6,6.6,0,0,1,9.4,0"/><circle class="dot" cx="24" cy="31" r="2.4"/></svg>
        <div><h1>Wi-Fi report</h1>
            <div class="period">${esc(title)}, ${esc(when(d.since))} to ${esc(when(d.generated_at))}</div></div>
    </div>
    <div class="scores">
        <div class="score">${gauge(d.mine.score, 'Your networks')}<div class="cap">Your networks</div></div>
        <div class="score">${gauge(d.area.score, 'Neighbourhood')}<div class="cap">Neighbourhood</div></div>
    </div>
</div></header>

<main class="wrap">
    <div class="figs">
        <div class="fig"><b class="num">${d.mine.seen}<span> of ${d.mine.marked}</span></b><span>access points seen${d.mine.worst ? `, worst ${esc(sev(d.mine.worst).toLowerCase())}` : ''}</span></div>
        <div class="fig"><b class="num">${d.area.total}</b><span>networks around you</span></div>
        <div class="fig"><b class="num ${helpers.serious ? 't-high' : ''}">${d.alerts.total}</b><span>alerts, ${helpers.serious} serious</span></div>
        <div class="fig"><b class="num">${d.deauth.count}</b><span>deauthentication frames, last ${d.deauth.hours} h</span></div>
    </div>

    <section><h2>Day by day <small>scores out of 100, and alerts</small></h2>${trendChart(d.trend)}</section>

    <section><h2>What to change <small>on your router, the most serious first</small></h2>${todo}</section>

    <section><h2>Your networks <small>${d.mine.seen} access point${d.mine.seen === 1 ? '' : 's'}</small></h2>${nets}${notSeen}</section>

    <section><h2>Alerts <small>${d.alerts.total} in this period</small></h2>
        ${d.alerts.total ? `<div class="counts">${sevCounts}</div>` : ''}${alerts}</section>

    <section><h2>Channels <small>last hour</small></h2>
        <div class="band"><b>2.4 GHz</b>${channelStrip(CH24, helpers.best('2.4'), helpers.yours('2.4'))}</div>
        <div class="band"><b>5 GHz</b>${channelStrip(CH5, helpers.best('5'), helpers.yours('5'))}</div>
        <div class="chan-legend"><span><i style="background:var(--spark)"></i>Best channel now</span>
            <span><i style="border:1.5px solid var(--accent)"></i>Your access points</span></div>
    </section>

    <footer><span>Sentinel, a passive Wi-Fi watchdog for the WiFi Pineapple Mark VII. It only listens: channels are
        sampled while hopping, so a very short event can be missed. Times are on the Pineapple's clock.</span></footer>
</main>
</body></html>`;
}
