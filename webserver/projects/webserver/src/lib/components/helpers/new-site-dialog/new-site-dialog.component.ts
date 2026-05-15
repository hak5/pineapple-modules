import {Component, Inject} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

export interface TemplateOption {
    id: string;
    label: string;
    description: string;
    requiresPhp: boolean;
}

@Component({
    selector: 'lib-new-site-dialog',
    templateUrl: './new-site-dialog.component.html',
    styleUrls: ['./new-site-dialog.component.css']
})
export class NewSiteDialogComponent {
    siteName = '';
    hostname = '';
    php      = false;
    template = 'basic';
    aliases  = '';

    readonly templates: TemplateOption[] = [
        {id: 'basic',         label: 'Basic Page',           description: 'Minimal blank page to customise from scratch.', requiresPhp: false},
        {id: 'download-page', label: 'Download Page',        description: 'Lure page with a visible Download button. Replace setup.exe with your payload.', requiresPhp: false},
        {id: 'auto-download', label: 'Auto-Download',        description: 'Triggers a file download automatically as soon as the visitor opens the page.', requiresPhp: false},
        {id: 'harvester',     label: 'Credential Harvester', description: 'Google-style login form that saves captured credentials to credentials.log.', requiresPhp: true},
    ];

    constructor(
        public dialogRef: MatDialogRef<NewSiteDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: {
            onCreate: (name: string, hostname: string, php: boolean, template: string, aliases: string[]) => void;
        }
    ) {}

    onTemplateChange(id: string): void {
        const t = this.templates.find(t => t.id === id);
        if (t && t.requiresPhp) { this.php = true; }
    }

    get isValid(): boolean {
        return this.siteName.trim().length > 0 && this.hostname.trim().length > 0;
    }

    create(): void {
        if (this.isValid) {
            const aliasList = this.aliases
                .split(',')
                .map(a => a.trim().toLowerCase())
                .filter(a => a.length > 0);
            this.data.onCreate(
                this.siteName.trim(), this.hostname.trim(),
                this.php, this.template, aliasList
            );
        }
    }
}
