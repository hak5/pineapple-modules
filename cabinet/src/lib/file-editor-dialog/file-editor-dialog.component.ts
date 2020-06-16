import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {Router} from '@angular/router';
import {ApiService} from './api.service';

@Component({
    selector: 'file-editor-dialog-component',
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
    public error: string = null;

    loadFileContent(): void {
        this.API.request({
            module: 'cabinet',
            action: 'read_file',
            file: this.path
        }, (response) => {
            if (response.error != undefined) {
                this.error = response.error;
                return
            }
            this.fileContent = response;
        })
    }

    preformSave(): void {
        let fileToSave = (this.isNew) ? this.path + '/' + this.fileName : this.path;
        let onSave = this.data.onSave;
        onSave(fileToSave, this.fileContent);
        this.closeDialog();
    }

    handleTabKey(e: KeyboardEvent): boolean {
        if (e.code.toLowerCase() === 'tab') {
            e.preventDefault();
            const target = e.target as HTMLTextAreaElement;
            let start = target.selectionStart;
            let end = target.selectionEnd;
            this.fileContent = this.fileContent.substring(0, start) + '    ' + this.fileContent.substring(end);
            return false;
        }
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
