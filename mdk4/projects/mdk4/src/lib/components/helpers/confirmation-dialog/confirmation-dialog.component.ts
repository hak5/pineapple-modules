import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ConfirmationDialogDelegate} from "../../../interfaces/confirmationdialogdelegate";

@Component({
  selector: 'lib-confirmation-dialog',
  templateUrl: './confirmation-dialog.component.html',
  styleUrls: ['./confirmation-dialog.component.css']
})
export class ConfirmationDialogComponent implements OnInit {

    public title: string;
    public message: string;

    constructor(public dialogRef: MatDialogRef<ConfirmationDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: ConfirmationDialogDelegate) {
        this.title = data.title;
        this.message = data.message;
    }

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
