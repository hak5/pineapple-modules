import { Component, EventEmitter, OnInit, Output } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';
import { renderReportHtml } from './report-html';

/** How your Wi-Fi did over a period, ready to print (assets/engine/report.py). */
@Component({
    selector: 'lib-sentinel-reports',
    templateUrl: './reports.component.html',
    styleUrls: ['../theme.css', './reports.component.css']
})
export class ReportsComponent implements OnInit {
    @Output() open = new EventEmitter<string>();

    data: any = null;
    loading = false;
    days = 7;
    readonly periods = [{ value: 1, label: '24 h' }, { value: 7, label: '7 days' }, { value: 30, label: '30 days' }];
    readonly severities = ['critical', 'high', 'medium', 'low', 'info'];
    readonly severityLabels = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Info', good: 'Good' };
    readonly kindLabels = {
        evil_twin: 'Imitation of your network', my_ap_conflict: 'Two devices, one address',
        my_ap_downgrade: 'Weaker security', my_ap_changed: 'Access point changed',
        my_ap_channel: 'Channel change', deauth_flood: 'Deauthentication burst',
        beacon_flood: 'Forged access points', karma_ap: 'Answers for any network',
        pmkid_attempt: 'Key collection attempt',
    };

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnInit(): void { this.load(); }

    load(): void {
        this.loading = true;
        this.sentinel.getReport(this.days)
            .then((d) => { this.data = d; })
            .catch((e) => this.snackBar.open(String(e), 'OK', { duration: 5000 }))
            .then(() => { this.loading = false; });
    }

    setDays(days: number): void {
        this.days = days;
        this.load();
    }

    get periodLabel(): string {
        return this.days === 1 ? 'the last 24 hours' : `the last ${this.days} days`;
    }

    get kinds(): { kind: string, count: number }[] {
        const k = (this.data && this.data.alerts && this.data.alerts.by_kind) || {};
        return Object.keys(k).map((kind) => ({ kind, count: k[kind] })).sort((a, b) => b.count - a.count);
    }

    get serious(): number {
        const s = this.data ? this.data.alerts.by_severity : {};
        return (s.critical || 0) + (s.high || 0);
    }

    /** Points of the score line, one per day (SVG coordinates, 0..100 mapped to the height). */
    trendPoints(key: string, width = 560, height = 80): string {
        const t = (this.data && this.data.trend || []).filter((r) => r[key] !== null && r[key] !== undefined);
        if (t.length < 2) { return ''; }
        const step = width / (t.length - 1);
        return t.map((r, i) => `${(i * step).toFixed(1)},${(height - r[key] / 100 * height).toFixed(1)}`).join(' ');
    }

    get trendDays(): number {
        return ((this.data && this.data.trend) || []).length;
    }

    bandLabel(band: string): string {
        return band === '5' ? '5 GHz' : band === '2.4' ? '2.4 GHz' : (band || '');
    }

    best(band: string): any {
        const b = this.data && this.data.channels && this.data.channels.best && this.data.channels.best[band];
        return b && b.observed ? b.best : null;
    }

    yours(band: string): number[] {
        return ((this.data && this.data.channels.yours) || []).filter((c) => c[0] === band).map((c) => c[1]);
    }

    /** Open the report page on its own and print it (or save it as PDF). */
    print(): void {
        const w = window.open('', '_blank');
        if (!w) {
            this.snackBar.open('The browser blocked the new window. Allow pop-ups for the Pineapple.', 'OK', { duration: 6000 });
            return;
        }
        w.document.open();
        w.document.write(this.html());
        w.document.close();
        w.focus();
        setTimeout(() => w.print(), 300);
    }

    /** The report as CSV: one table, a "section" column to filter on in a spreadsheet. */
    downloadCsv(): void {
        const d = this.data, out: any[][] = [];
        const head = ['section', 'date', 'network', 'bssid', 'band', 'channel', 'security', 'pmf', 'wps',
            'level', 'severity', 'type', 'description', 'value'];
        const row = (o: any) => out.push(head.map((h) => o[h]));
        const day = (ts: number) => isoTime(ts);
        row({ section: 'summary', date: day(d.generated_at), description: 'period_days', value: d.days });
        row({ section: 'summary', description: 'my_networks_score', value: d.mine.score });
        row({ section: 'summary', description: 'my_networks_marked', value: d.mine.marked });
        row({ section: 'summary', description: 'my_networks_seen', value: d.mine.seen });
        row({ section: 'summary', description: 'neighbourhood_score', value: d.area.score });
        row({ section: 'summary', description: 'neighbourhood_networks', value: d.area.total });
        row({ section: 'summary', description: 'alerts', value: d.alerts.total });
        row({ section: 'summary', description: 'alerts_serious', value: this.serious });
        row({ section: 'summary', description: `deauth_frames_last_${d.deauth.hours}h`, value: d.deauth.count });
        d.trend.forEach((t) => {
            row({ section: 'trend', date: t.day, description: 'my_networks_score', value: t.my_score });
            row({ section: 'trend', date: t.day, description: 'neighbourhood_score', value: t.area_score });
            row({ section: 'trend', date: t.day, description: 'alerts', value: t.alerts });
        });
        d.mine.todo.forEach((t) => row({ section: 'to_change', network: t.networks.join('; '), severity: t.severity,
            description: t.advice }));
        d.mine.networks.forEach((n) => row({ section: 'my_network', network: n.ssid, bssid: n.bssid,
            band: this.bandLabel(n.band), channel: n.channel, security: n.security, pmf: n.pmf || 'none',
            wps: n.wps ? 'on' : 'off', level: n.grade, date: day(n.last_seen) }));
        d.mine.not_seen.forEach((x) => row({ section: 'my_network_not_seen', network: x.ssid, bssid: x.bssid }));
        this.kinds.forEach((k) => row({ section: 'alert_count', type: k.kind, description: this.kindLabels[k.kind] || k.kind,
            value: k.count }));
        d.alerts.top.forEach((a) => row({ section: 'alert', date: day(a.ts), severity: a.severity, type: a.kind,
            description: a.title }));
        ['2.4', '5'].forEach((b) => {
            row({ section: 'channel', band: this.bandLabel(b), channel: this.best(b), description: 'best_now' });
            this.yours(b).forEach((c) => row({ section: 'channel', band: this.bandLabel(b), channel: c, description: 'yours' }));
        });
        const text = [head].concat(out).map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
        this.save(text, 'text/csv', 'csv');
    }

    /** The report as Markdown, to paste in notes or a ticket. */
    downloadMarkdown(): void {
        const d = this.data, m = md;
        const sev = (s: string) => this.severityLabels[s] || s;
        const lines: string[] = [];
        lines.push('# Sentinel: Wi-Fi report', '');
        lines.push(`${this.periodLabel.charAt(0).toUpperCase() + this.periodLabel.slice(1)}, from ${isoTime(d.since)} ` +
            `to ${isoTime(d.generated_at)} (Pineapple's clock).`, '');
        lines.push('| | |', '|---|---|');
        lines.push(`| Your networks | ${orDash(d.mine.score)}/100 (${d.mine.seen} of ${d.mine.marked} seen) |`);
        lines.push(`| Neighbourhood | ${orDash(d.area.score)}/100 (${d.area.total} networks) |`);
        lines.push(`| Alerts | ${d.alerts.total}, ${this.serious} serious |`);
        lines.push(`| Deauthentication frames | ${d.deauth.count} in the last ${d.deauth.hours} h |`, '');
        if (d.trend.length) {
            lines.push('## Trend', '', '| Day | Your networks | Neighbourhood | Alerts |', '|---|---|---|---|');
            d.trend.forEach((t) => lines.push(`| ${t.day} | ${orDash(t.my_score)} | ${orDash(t.area_score)} | ${t.alerts} |`));
            lines.push('');
        }
        lines.push('## What to change', '');
        if (d.mine.todo.length) {
            d.mine.todo.forEach((t) => lines.push(`- **${sev(t.severity)}.** ${m(t.advice)} (${m(t.networks.join(', '))})`));
        } else {
            lines.push('Nothing to change on your networks.');
        }
        lines.push('', '## Your networks', '');
        if (d.mine.networks.length) {
            lines.push('| Network | BSSID | Band | Security | PMF | WPS | Level |', '|---|---|---|---|---|---|---|');
            d.mine.networks.forEach((n) => lines.push(`| ${m(n.ssid || '(hidden name)')} | ${n.bssid} | ` +
                `${this.bandLabel(n.band)}, ch. ${n.channel} | ${m(n.security)} | ${m(n.pmf || 'none')} | ` +
                `${n.wps ? 'on' : 'off'} | ${sev(n.grade)} |`));
        } else {
            lines.push('None of your networks was seen in this period.');
        }
        if (d.mine.not_seen.length) {
            lines.push('', `Not seen in this period: ${m(d.mine.not_seen.map((x) => x.ssid || x.bssid).join(', '))}.`);
        }
        lines.push('', '## Alerts', '');
        if (d.alerts.total) {
            this.kinds.forEach((k) => lines.push(`- ${k.count} × ${this.kindLabels[k.kind] || k.kind}`));
            lines.push('', '| When | Severity | Alert |', '|---|---|---|');
            d.alerts.top.forEach((a) => lines.push(`| ${isoTime(a.ts)} | ${sev(a.severity)} | ${m(a.title)} |`));
        } else {
            lines.push('No alert in this period.');
        }
        lines.push('', '## Channels', '');
        ['2.4', '5'].forEach((b) => lines.push(`- ${this.bandLabel(b)}: best channel now ${orText(this.best(b), 'not known yet')}, ` +
            `yours ${this.yours(b).join(', ') || 'none'}`));
        lines.push('', '_Sentinel only listens. Channels are sampled while hopping: a very short event can be missed._', '');
        this.save(lines.join('\n'), 'text/markdown', 'md');
    }

    private save(text: string, type: string, ext: string): void {
        const blob = new Blob([text], { type: `${type};charset=utf-8` });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `sentinel-report-${isoTime(this.data.generated_at).slice(0, 10)}-${this.days === 1 ? '24h' : this.days + 'd'}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    /** The designed report page (report-html.ts), shared by the HTML download and printing. */
    private html(): string {
        return renderReportHtml(this.data, {
            severity: this.severityLabels, kind: this.kindLabels, period: this.periodLabel,
        }, {
            band: (b) => this.bandLabel(b), best: (b) => this.best(b), yours: (b) => this.yours(b),
            kinds: this.kinds, serious: this.serious,
        });
    }

    downloadHtml(): void {
        this.save(this.html(), 'text/html', 'html');
    }
}

/** Local date and time, YYYY-MM-DD HH:MM (the Pineapple's clock, as given). */
function isoTime(ts: number): string {
    const d = new Date(ts * 1000), p = (n: number) => ('0' + n).slice(-2);
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * One CSV cell. Network names come from anyone in radio range: a name starting with = + - @
 * (or a tab / carriage return) would run as a formula in a spreadsheet, so it gets a leading quote.
 */
function csvCell(value: any): string {
    let s = value === null || value === undefined ? '' : String(value);
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(s)) {
        s = "'" + s;
    }
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

/** Text inside Markdown: no table break, no formatting, no link or HTML from a network name. */
function md(value: any): string {
    return String(value === null || value === undefined ? '' : value)
        .replace(/[\r\n]+/g, ' ')
        .replace(/([\\`*_{}\[\]()#+!|<>~])/g, '\\$1');
}

function orText(value: any, text: string): any {
    return value === null || value === undefined ? text : value;
}

function orDash(value: any): any {
    return orText(value, '–');
}

