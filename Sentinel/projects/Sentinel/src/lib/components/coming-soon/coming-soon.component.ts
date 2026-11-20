import { Component, Input } from '@angular/core';

@Component({
    selector: 'lib-sentinel-coming-soon',
    template: `
        <mat-card class="card soon">
            <h2 class="card-title">{{ title }}</h2>
            <p>{{ text }}</p>
            <p class="soft">This part is coming in a future version of Sentinel.</p>
        </mat-card>
    `,
    styleUrls: ['../theme.css'],
    styles: [`
        .soon p { margin: 0 0 8px; font-size: 15px; line-height: 1.5; max-width: 66ch; }
    `]
})
export class ComingSoonComponent {
    @Input() title = '';
    @Input() text = '';
}
