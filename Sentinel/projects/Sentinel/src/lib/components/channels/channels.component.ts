import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { SentinelService } from '../../services/Sentinel.service';

@Component({
    selector: 'lib-sentinel-channels',
    templateUrl: './channels.component.html',
    styleUrls: ['../theme.css', './channels.component.css']
})
export class ChannelsComponent implements OnInit, OnDestroy {
    @Input() status: any;

    report: any = null;
    aps: any[] = [];
    window = 10;
    band: '2.4' | '5' = '2.4';
    private timer: any;
    private alive = true;
    readonly every = 30;
    updated: Date = null;

    readonly windows = [
        { value: 10, label: '10 min' },
        { value: 60, label: '1 h' },
        { value: 240, label: '4 h' },
    ];

    constructor(private sentinel: SentinelService) { }

    ngOnInit(): void {
        this.load();
    }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    setWindow(w: number): void {
        this.window = w;
        this.load();
    }

    /** One round of requests at a time, then the next one (audit 7.3). */
    load(): void {
        clearTimeout(this.timer);
        Promise.all([
            this.sentinel.getChannels(this.window).then((r) => this.report = r).catch(() => { }),
            this.sentinel.request('get_spectrum', { max_age_minutes: this.window })
                .then((a) => this.aps = a || []).catch(() => { }),
        ]).then(() => {
            this.updated = new Date();
            if (this.alive) { this.timer = setTimeout(() => this.load(), this.every * 1000); }
        });
    }

    get live(): boolean {
        return !!this.status && this.status.running && this.status.healthy;
    }

    get reco(): any {
        return this.report && this.report.recommendation && this.report.recommendation[this.band];
    }

    get best(): number {
        return this.reco && this.reco.observed ? this.reco.best : null;
    }

    /** Busiest channels first, only those with something on them. */
    get rows(): any[] {
        const all = (this.report && this.report.channels) || [];
        return all.filter((c) => c.band === this.band && (c.aps || c.frames))
            .sort((a, b) => a.channel - b.channel);
    }

    get maxAps(): number {
        return Math.max(1, ...this.rows.map((r) => r.aps));
    }

    candidateScores(): any[] {
        return (this.reco && this.reco.scores || []).slice().sort((a, b) => a.channel - b.channel);
    }

    trackCh(_: number, row: any): number { return row.channel; }
}
