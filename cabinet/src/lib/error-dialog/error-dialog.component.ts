import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

@Component({
    selector: 'cabinet-error-dialog-component',
    templateUrl: './error-dialog.component.html',
    styleUrls: ['./error-dialog.component.css']
})
export class CabinetErrorDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<CabinetErrorDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any) {
        this.errorMessage = data.errorMessage;
    }

    public errorMessage: string;

    closeDialog(): void {
        this.dialogRef.close()
    }

    ngOnInit() {
    }
}
