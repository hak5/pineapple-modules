import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {ApiService} from '../../../services/api.service';

@Component({
    selector: 'lib-cabinet-error-dialog-component',
    templateUrl: './cabinet-file-editor-dialog.component.html',
    styleUrls: ['./cabinet-file-editor-dialog.component.css']
})
export class FileEditorDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<FileEditorDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private API: ApiService) {
        this.path = data.path;
        this.fileName = data.fileName;
        this.isNew = data.isNew;
    }

    public path: string = null;
    public isNew = false;
    public title = '';
    public fileName = '';
    public fileContent = '';
    public error: string = null;

    loadFileContent(): void {
        this.API.request({
            module: 'cabinet',
            action: 'read_file',
            file: this.path
        }, (response) => {
            if (response.error !== undefined) {
                this.error = response.error;
                return
            }
            this.fileContent = response;
        })
    }

    preformSave(): void {
        const fileToSave = (this.isNew) ? this.path + '/' + this.fileName : this.path;
        const onSave = this.data.onSave;
        onSave(fileToSave, this.fileContent);
        this.closeDialog();
    }

    handleTabKey(e: KeyboardEvent): boolean {
        if (e.code.toLowerCase() === 'tab') {
            e.preventDefault();
            const target = e.target as HTMLTextAreaElement;
            const start = target.selectionStart;
            const end = target.selectionEnd;
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
