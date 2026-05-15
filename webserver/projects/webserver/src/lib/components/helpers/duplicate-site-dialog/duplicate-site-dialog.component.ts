import {Component, Inject} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

@Component({
    selector: 'lib-duplicate-site-dialog',
    templateUrl: './duplicate-site-dialog.component.html',
})
export class DuplicateSiteDialogComponent {
    newName = '';
    newHostname = '';

    constructor(
        public dialogRef: MatDialogRef<DuplicateSiteDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: {
            sourceName: string;
            onDuplicate: (newName: string, newHostname: string) => void;
        }
    ) {}

    get isValid(): boolean {
        return this.newName.trim().length > 0 &&
               this.newHostname.trim().length > 0 &&
               this.newName.trim() !== this.data.sourceName;
    }

    duplicate(): void {
        if (this.isValid) {
            this.data.onDuplicate(this.newName.trim(), this.newHostname.trim());
        }
    }
}
