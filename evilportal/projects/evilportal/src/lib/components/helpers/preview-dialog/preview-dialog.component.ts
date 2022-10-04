import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";

@Component({
    selector: 'lib-preview-dialog',
    templateUrl: './preview-dialog.component.html',
    styleUrls: ['./preview-dialog.component.css']
})
export class PreviewDialogComponent implements OnInit {

    hostname = '';
    hostnamediv = '';

    constructor(public dialogRef: MatDialogRef<PreviewDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any) {}

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit(): void {
        this.hostname = 'http://'+window.location.hostname;
        let hostnamediv = document.getElementById('preview');
        hostnamediv.setAttribute('src', this.hostname);
    }

}
