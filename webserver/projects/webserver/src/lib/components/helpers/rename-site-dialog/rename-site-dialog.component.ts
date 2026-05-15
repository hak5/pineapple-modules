import {Component, Inject} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

interface SiteRef {
    name: string;
    hostname: string;
    aliases: string[];
}

@Component({
    selector: 'lib-rename-site-dialog',
    templateUrl: './rename-site-dialog.component.html',
})
export class RenameSiteDialogComponent {
    newName: string;
    newHostname: string;
    newAliases: string;

    constructor(
        public dialogRef: MatDialogRef<RenameSiteDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: {
            site: SiteRef;
            onRename: (newName: string, newHostname: string, aliases: string[]) => void;
        }
    ) {
        this.newName     = data.site.name;
        this.newHostname = data.site.hostname;
        this.newAliases  = (data.site.aliases || []).join(', ');
    }

    get isValid(): boolean {
        return this.newName.trim().length > 0 && this.newHostname.trim().length > 0;
    }

    save(): void {
        if (this.isValid) {
            const aliases = this.newAliases
                .split(',')
                .map(a => a.trim().toLowerCase())
                .filter(a => a.length > 0);
            this.data.onRename(this.newName.trim(), this.newHostname.trim(), aliases);
        }
    }
}
