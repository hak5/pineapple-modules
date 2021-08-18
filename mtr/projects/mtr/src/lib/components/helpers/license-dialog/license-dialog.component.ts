import {Component, OnInit} from '@angular/core';
import {MatDialogRef} from "@angular/material/dialog";

@Component({
    selector: 'lib-license-dialog',
    templateUrl: './license-dialog.component.html',
    styleUrls: ['./license-dialog.component.css']
})
export class LicenseDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<LicenseDialogComponent>) {
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit(): void {
    }

}
