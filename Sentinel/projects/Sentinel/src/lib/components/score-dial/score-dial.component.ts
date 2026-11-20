import { Component, Input } from '@angular/core';

/** A needle gauge, like the meters on a bench instrument, for the security score. */
@Component({
    selector: 'lib-sentinel-score-dial',
    template: `
        <svg viewBox="0 0 200 118" role="img" [attr.aria-label]="'Security score: ' + (score !== null && score !== undefined ? score : 'unknown') + ' out of 100'">
            <path class="seg seg-critical" [attr.d]="arc(0, 40)"></path>
            <path class="seg seg-medium" [attr.d]="arc(40, 60)"></path>
            <path class="seg seg-low" [attr.d]="arc(60, 75)"></path>
            <path class="seg seg-good" [attr.d]="arc(75, 100)"></path>
            <g *ngFor="let t of [0, 25, 50, 75, 100]">
                <line class="tick" [attr.x1]="pt(t, 62).x" [attr.y1]="pt(t, 62).y" [attr.x2]="pt(t, 56).x" [attr.y2]="pt(t, 56).y"></line>
            </g>
            <g *ngIf="score !== null && score !== undefined">
                <line class="needle" x1="100" y1="100" [attr.x2]="pt(score, 70).x" [attr.y2]="pt(score, 70).y"></line>
            </g>
            <circle class="hub" cx="100" cy="100" r="6"></circle>
        </svg>
        <div class="readout">
            <span class="value num">{{ score !== null && score !== undefined ? score : '—' }}</span><span class="of">/100</span>
        </div>
    `,
    styles: [`
        :host { display: block; position: relative; max-width: 240px; }
        svg { display: block; width: 100%; height: auto; }
        .seg { fill: none; stroke-width: 12; }
        .seg-critical { stroke: var(--sn-critical-ink); }
        .seg-medium { stroke: var(--sn-medium); }
        .seg-low { stroke: var(--sn-low-ink); }
        .seg-good { stroke: var(--sn-good-ink); }
        .tick { stroke: currentColor; stroke-opacity: 0.45; stroke-width: 1.5; }
        .needle { stroke: currentColor; stroke-width: 3; stroke-linecap: round; transition: all 0.6s ease; }
        .hub { fill: currentColor; }
        .readout { text-align: center; margin-top: -4px; }
        .value { font-size: 40px; font-weight: 500; line-height: 1; }
        .of { font-size: 16px; opacity: 0.6; margin-left: 2px; }
        .num { font-variant-numeric: tabular-nums; }
    `]
})
export class ScoreDialComponent {
    @Input() score: number = null;

    /** Point on the dial for a score 0..100 at radius r (180° gauge). */
    pt(score: number, r: number): { x: number, y: number } {
        const a = Math.PI * (1 - Math.max(0, Math.min(100, score)) / 100);
        return { x: 100 + r * Math.cos(a), y: 100 - r * Math.sin(a) };
    }

    arc(from: number, to: number): string {
        const r = 82;
        const p0 = this.pt(from, r);
        const p1 = this.pt(to, r);
        return `M${p0.x.toFixed(2)},${p0.y.toFixed(2)} A${r},${r} 0 0 1 ${p1.x.toFixed(2)},${p1.y.toFixed(2)}`;
    }
}
