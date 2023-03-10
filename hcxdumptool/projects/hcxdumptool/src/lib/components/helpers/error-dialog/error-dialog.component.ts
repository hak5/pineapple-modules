import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ErrorDialogData} from "../../../interfaces/errordialogdata.interface";

@Component({
  selector: 'lib-error-dialog',
  templateUrl: './error-dialog.component.html',
  styleUrls: ['./error-dialog.component.css']
})
export class ErrorDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<ErrorDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: ErrorDialogData) {
        this.message = data.message;
    }

    public message: string;

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit(): void {
    }

}
