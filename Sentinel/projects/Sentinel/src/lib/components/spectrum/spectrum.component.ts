import { AfterViewInit, Component, ElementRef, HostListener, Input, OnChanges } from '@angular/core';

/**
 * The signature view of Sentinel: a spectrum-analyser style screen where
 * every access point is a hump centred on its channel. Height is signal
 * strength, colour is the security grade from the WPA3/PMF audit.
 */

interface Arc {
    bssid: string;
    path: string;
    grade: string;
    title: string;
    peakX: number;
    peakY: number;
    label: string;
    mine: boolean;
}

const CANDIDATES_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165];

@Component({
    selector: 'lib-sentinel-spectrum',
    templateUrl: './spectrum.component.html',
    styleUrls: ['./spectrum.component.css']
})
export class SpectrumComponent implements OnChanges, AfterViewInit {
    @Input() aps: any[] = [];
    @Input() band: '2.4' | '5' = '2.4';
    @Input() recommended: number = null;
    @Input() height = 240;
    @Input() live = false;
    @Input() labels = 5;

    /** Drawing width in px: follows the real width so text keeps the same size everywhere. */
    W = 640;
    readonly left = 40;
    readonly right = 12;
    readonly top = 16;
    readonly bottom = 30;

    arcs: Arc[] = [];
    ticks: { x: number, label: string }[] = [];
    grid: { y: number, label: string }[] = [];
    labelled: Arc[] = [];
    recoX: number = null;
    sweepTo = 680;
    count = 0;

    constructor(private host: ElementRef) { }

    ngAfterViewInit(): void {
        // Measure after the first render, outside the current change detection pass
        setTimeout(() => this.measure());
    }

    @HostListener('window:resize')
    measure(): void {
        const width = Math.round(this.host.nativeElement.clientWidth - 8);
        if (width > 200 && Math.abs(width - this.W) > 2) {
            this.W = width;
            this.ngOnChanges();
        }
    }

    get plotW(): number { return this.W - this.left - this.right; }
    get plotH(): number { return this.height - this.top - this.bottom; }
    get baseY(): number { return this.top + this.plotH; }

    ngOnChanges(): void {
        const list = (this.aps || []).filter((a) => a.band === this.band && a.channel);
        this.count = list.length;

        let xOf: (ch: number) => number;
        let half: number;

        if (this.band === '2.4') {
            xOf = (ch) => this.left + (ch / 14) * this.plotW;
            half = 2 * this.plotW / 14;  // 22 MHz wide: about two channels each side
            this.ticks = [];
            for (let ch = 1; ch <= 13; ch++) {
                this.ticks.push({ x: xOf(ch), label: String(ch) });
            }
        } else {
            const slots = Array.from(new Set(CANDIDATES_5.concat(list.map((a) => a.channel))))
                .sort((a, b) => a - b);
            const n = slots.length;
            const step = this.plotW / n;
            xOf = (ch) => this.left + (slots.indexOf(ch) + 0.5) * step;
            half = step * 0.62;
            this.ticks = slots.map((ch) => ({ x: xOf(ch), label: String(ch) }));
        }

        this.sweepTo = this.W + 40;
        this.grid = [-90, -70, -50, -30].map((dbm) => ({ y: this.yOf(dbm), label: String(dbm) }));

        // Weakest first so strong networks are drawn on top
        const sorted = list.slice().sort((a, b) => (a.rssi || -100) - (b.rssi || -100));
        this.arcs = sorted.map((a) => {
            const xc = xOf(a.channel);
            const peak = this.yOf(a.rssi === null || a.rssi === undefined ? -95 : a.rssi);
            const x0 = xc - half;
            const x1 = xc + half;
            const d = half * 0.55;
            const b = this.baseY;
            const name = a.ssid || '(hidden)';
            return {
                bssid: a.bssid,
                grade: a.grade,
                path: `M${x0.toFixed(1)},${b} C${(x0 + d).toFixed(1)},${b} ${(xc - d).toFixed(1)},${peak.toFixed(1)} ${xc.toFixed(1)},${peak.toFixed(1)} `
                    + `C${(xc + d).toFixed(1)},${peak.toFixed(1)} ${(x1 - d).toFixed(1)},${b} ${x1.toFixed(1)},${b} Z`,
                title: `${name}\nChannel ${a.channel}, ${a.rssi} dBm\n${a.security}`,
                peakX: xc,
                peakY: peak,
                label: name.length > 16 ? name.slice(0, 15) + '…' : name,
                mine: !!a.mine,
            };
        });

        // Label your networks first, then the strongest, without letting labels collide
        const placed: Arc[] = [];
        sorted.slice().reverse().sort((a, b) => (b.mine ? 1 : 0) - (a.mine ? 1 : 0)).forEach((a) => {
            if (placed.length >= this.labels) { return; }
            const arc = this.arcs.find((x) => x.bssid === a.bssid);
            const clash = placed.some((p) => Math.abs(p.peakX - arc.peakX) < 78 && Math.abs(p.peakY - arc.peakY) < 16);
            if (!clash) { placed.push(arc); }
        });
        this.labelled = placed.slice(0, Math.max(2, Math.floor(this.W / 110)));

        this.recoX = this.recommended ? xOf(this.recommended) : null;
        if (this.recoX !== null && isNaN(this.recoX)) { this.recoX = null; }
    }

    yOf(dbm: number): number {
        const clamped = Math.max(-100, Math.min(-20, dbm));
        return this.top + (1 - (clamped + 100) / 80) * this.plotH;
    }

    labelX(arc: Arc): number {
        return Math.max(this.left + 4, Math.min(this.W - this.right - 4, arc.peakX));
    }

    trackArc(_: number, arc: Arc): string { return arc.bssid; }
}
