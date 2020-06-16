import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material';
import {Router} from '@angular/router';
import {ApiService} from 'api';

@Component({
    selector: 'new-folder-dialog-component',
    templateUrl: './new-folder-dialog.component.html',
    styleUrls: ['./new-folder-dialog.component.css']
})
export class NewFolderDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<NewFolderDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private router: Router,
                private API: ApiService) {
        this.path = data.path;
    }

    public path: string;
    public directoryName: string = '';

    preformCreate(): void {
        let onCreate = this.data.onCreate;
        onCreate(this.directoryName);
        this.closeDialog();
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit() {
    }
}
