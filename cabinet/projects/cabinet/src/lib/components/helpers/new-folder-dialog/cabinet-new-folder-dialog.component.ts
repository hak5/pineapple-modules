import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {ApiService} from '../../../services/api.service';

@Component({
    selector: 'lib-cabinet-error-dialog-component',
    templateUrl: './cabinet-new-folder-dialog.component.html',
    styleUrls: ['./cabinet-new-folder-dialog.component.css']
})
export class NewFolderDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<NewFolderDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any) {
        this.path = data.path;
    }

    public path: string;
    public directoryName = '';

    preformCreate(): void {
        const onCreate = this.data.onCreate;
        onCreate(this.directoryName);
        this.closeDialog();
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit() {
    }
}
