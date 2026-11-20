import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

/** The alerts of the passive intrusion detection (assets/engine/detect.py). */
@Component({
    selector: 'lib-sentinel-detection',
    templateUrl: './detection.component.html',
    styleUrls: ['../theme.css', './detection.component.css']
})
export class DetectionComponent implements OnInit, OnDestroy {
    @Input() status: any;
    @Output() open = new EventEmitter<string>();
    @Output() read = new EventEmitter<void>();

    data: any = null;
    private timer: any;
    private alive = true;
    readonly every = 15;
    updated: Date = null;

    readonly severities = ['critical', 'high', 'medium', 'low', 'info'];
    readonly severityLabels = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Info' };
    readonly kindLabels = {
        evil_twin: 'Imitation of your network', my_ap_conflict: 'Two devices, one address',
        my_ap_downgrade: 'Weaker security', my_ap_changed: 'Access point changed',
        my_ap_channel: 'Channel change', deauth_flood: 'Deauthentication burst',
        beacon_flood: 'Forged access points', karma_ap: 'Answers for any network',
        suppressed: 'Alerts suppressed',
    };
    readonly fieldLabels = {
        ssid: 'Network', channel: 'Channel', band: 'Band', rssi: 'Signal (dBm)', count: 'Frames or names',
        window_s: 'Over (seconds)', expected: 'Reference', observed: 'Seen', reasons: 'Reason codes',
        broadcast: 'Sent to everyone', ssids: 'Names announced',
    };
    /** Rules whose cause is often a router update or a planned change. */
    readonly rebaselineKinds = ['my_ap_changed', 'my_ap_channel'];

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnInit(): void { this.load(); }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    /** One request at a time: the next is scheduled when this one answers (audit 7.3). */
    load(): void {
        clearTimeout(this.timer);
        this.sentinel.getDetection().then((d) => { this.data = d; this.updated = new Date(); }).catch(() => { })
            .then(() => { if (this.alive) { this.timer = setTimeout(() => this.load(), this.every * 1000); } });
    }

    count(severity: string): number {
        return (this.data && this.data.by_severity && this.data.by_severity[severity]) || 0;
    }

    markAllRead(): void {
        this.sentinel.ackEvents().then(() => { this.read.emit(); this.load(); }).catch((e) => this.toast(e));
    }

    isMuted(kind: string): boolean {
        return !!this.data && (this.data.muted || []).indexOf(kind) >= 0;
    }

    /** Alert types that can be muted (not the "alerts suppressed" notice). */
    canMute(kind: string): boolean {
        return kind !== 'suppressed' && !!this.kindLabels[kind];
    }

    setMuted(kind: string, muted: boolean): void {
        this.sentinel.setAlertMuted(kind, muted).then(() => {
            this.toast(muted ? `"${this.kindLabels[kind]}" muted: still recorded, but already marked as read`
                             : `"${this.kindLabels[kind]}" alerts are back`);
            this.read.emit();
            this.load();
        }).catch((err) => this.toast(err));
    }

    rebaseline(e: any): void {
        this.sentinel.rebaselineMyNetwork(e.bssid)
            .then(() => this.toast('Current settings accepted as the reference'))
            .catch((err) => this.toast(err));
    }

    /** The details of an event as label / text pairs. Every value is shown as plain text. */
    fields(e: any): { label: string, value: string }[] {
        let d: any = {};
        try { d = typeof e.details === 'string' ? JSON.parse(e.details) : (e.details || {}); } catch (_) { d = {}; }
        return Object.keys(this.fieldLabels).filter((k) => d[k] !== undefined && d[k] !== null)
            .map((k) => ({ label: this.fieldLabels[k], value: this.text(d[k]) }));
    }

    private text(v: any): string {
        if (Array.isArray(v)) { return v.map((x) => this.text(x)).join(', '); }
        if (v && typeof v === 'object') {
            return Object.keys(v).filter((k) => v[k] !== null && v[k] !== undefined)
                .map((k) => k + ' ' + this.text(v[k])).join(' · ');
        }
        return String(v);
    }

    ago(ts: number): string { return SentinelService.ago(ts); }

    toast(msg: any): void { this.snackBar.open(String(msg), 'OK', { duration: 5000 }); }

    trackEvent(_: number, e: any): number { return e.id; }
}
