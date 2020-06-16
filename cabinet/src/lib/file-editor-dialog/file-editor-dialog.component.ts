import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material';
import {Router} from '@angular/router';
import {ApiService} from 'api';

@Component({
    selector: "file-editor-dialog-component",
    templateUrl: './file-editor-dialog.component.html',
    styleUrls: ['./file-editor-dialog.component.css']
})
export class FileEditorDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<FileEditorDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private router: Router,
                private API: ApiService) {
        this.path = data.path;
        this.fileName = data.fileName;
        this.isNew = data.isNew;
    }

    public path: string = null;
    public isNew: boolean = false;
    public title: string = '';
    public fileName: string = '';
    public fileContent: string = '';

    loadFileContent(): void {
        this.API.request({
            module: 'cabinet',
            action: 'read_file',
            file: this.path
        }, (response) => {
            if (response.error != undefined) { return } // TODO: Handle errors
            this.fileContent = response;
        })
    }

    preformSave(): void {
        let fileToSave = (this.isNew) ? this.path + '/' + this.fileName : this.path;
        let onSave = this.data.onSave;
        onSave(fileToSave, this.fileContent);
        this.closeDialog();
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit() {
        this.title = (this.isNew) ? 'Create New File' : 'Edit File';

        if (!this.isNew) {
            this.loadFileContent();
        }
    }
}
