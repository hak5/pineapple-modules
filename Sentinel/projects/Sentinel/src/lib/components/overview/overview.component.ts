import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { SentinelService } from '../../services/Sentinel.service';

@Component({
    selector: 'lib-sentinel-overview',
    templateUrl: './overview.component.html',
    styleUrls: ['../theme.css', './overview.component.css']
})
export class OverviewComponent implements OnInit, OnDestroy {
    @Input() status: any;
    @Output() open = new EventEmitter<string>();

    data: any = null;
    reco: any = {};
    private timer: any;

    readonly gradeOrder = ['critical', 'high', 'medium', 'low', 'good'];
    readonly gradeLabels = {
        critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', good: 'Good'
    };

    constructor(private sentinel: SentinelService) { }

    private alive = true;
    readonly every = 15;
    updated: Date = null;

    ngOnInit(): void {
        this.load();
    }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    /** One round of requests at a time: the next is scheduled when both answer (audit 7.3). */
    load(): void {
        clearTimeout(this.timer);
        Promise.all([
            this.sentinel.getDashboard().then((d) => { this.data = d; this.updated = new Date(); }).catch(() => { }),
            this.sentinel.getChannels(10).then((r) => this.reco = r.recommendation || {}).catch(() => { }),
        ]).then(() => { if (this.alive) { this.timer = setTimeout(() => this.load(), this.every * 1000); } });
    }

    get live(): boolean {
        return !!this.status && this.status.running && this.status.healthy;
    }

    count(band: string): number {
        return ((this.data && this.data.spectrum) || []).filter((a) => a.band === band).length;
    }

    best(band: string): number {
        const r = this.reco[band];
        return r && r.observed ? r.best : null;
    }

    gradeShare(g: string): number {
        const s = this.data && this.data.security;
        if (!s || !s.total) { return 0; }
        return 100 * (s.summary[g] || 0) / s.total;
    }

    private bandsOf(name: string): string[] {
        const it = ((this.status && this.status.interfaces) || []).find((i) => i.name === name);
        return (it && it.bands) || [];
    }

    /** Some radio receives 5 GHz (built-in radios of the Mark VII do not; the MK7AC does). */
    get has5Radio(): boolean {
        return ((this.status && this.status.interfaces) || []).some((i) => (i.bands || []).indexOf('5') >= 0);
    }

    /** An enabled radio that receives 5 GHz is set to listen on 5 GHz channels. */
    get listens5(): boolean {
        const radios = (this.status && this.status.settings && this.status.settings.radios) || [];
        return radios.some((r) => r.enabled && r.iface && this.bandsOf(r.iface).indexOf('5') >= 0
            && (!r.hopping || (r.channels || []).some((c) => c >= 32)));
    }

    /** The worst level among your networks. */
    get myWorst(): string {
        const s = this.data && this.data.security && this.data.security.my_summary;
        return s ? this.gradeOrder.find((g) => s[g] > 0) || 'good' : 'good';
    }

    ago(ts: number): string { return SentinelService.ago(ts); }
}
