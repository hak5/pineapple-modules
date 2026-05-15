import {Component, Inject} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

@Component({
    selector: 'lib-confirm-dialog',
    templateUrl: './confirm-dialog.component.html',
    styleUrls: ['./confirm-dialog.component.css']
})
export class ConfirmDialogComponent {
    constructor(
        public dialogRef: MatDialogRef<ConfirmDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: {
            title: string;
            message: string;
            handleResponse: (confirmed: boolean) => void;
        }
    ) {}

    respond(confirmed: boolean): void {
        this.data.handleResponse(confirmed);
        this.dialogRef.close();
    }
}
