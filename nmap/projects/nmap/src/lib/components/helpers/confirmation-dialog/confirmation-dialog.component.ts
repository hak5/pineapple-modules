import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ConfirmationDialogDelegate} from "../../../interfaces/confirmationdialogdelegate.interface";

@Component({
    selector: 'lib-confirmation-dialog',
    templateUrl: './confirmation-dialog.component.html',
    styleUrls: ['./confirmation-dialog.component.css']
})
export class ConfirmationDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<ConfirmationDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: ConfirmationDialogDelegate) {
        this.title = data.title;
        this.message = data.message;
    }

    public title: string;
    public message: string;

    closeDialog(): void {
        this.dialogRef.close();
    }

    handleResponse(affirmative: boolean): void {
        this.closeDialog();
        this.data.handleResponse(affirmative);
    }

    ngOnInit(): void {
    }

}
