import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";

@Component({
    selector: 'lib-edit-file-dialog',
    templateUrl: './edit-file-dialog.component.html',
    styleUrls: ['./edit-file-dialog.component.css']
})
export class EditFileDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<EditFileDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private API: ApiService) {
        this.readonly = data.readonly;
        this.path = data.path;
        this.fileName = data.fileName;
        this.isNew = data.isNew;
    }

    public readonly: boolean = false;
    public isBusy: boolean = false;
    public path: string = null;
    public isNew = false;
    public title = '';
    public fileName = '';
    public fileContent = '';
    public error: string = null;

    private loadFileContent(path: string): void {
        this.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'load_file',
            path: path
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                this.error = response.error;
                return
            }
            this.fileContent = response;
        });
    }

    private saveFileContent(path: string): void {
        this.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'save_file',
            path: path,
            content: this.fileContent
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                this.error = response.error;
                return;
            }
            this.closeDialog();
            this.data.onSaved();
        });
    }

    preformSave(): void {
        const fileToSave = this.path + '/' + this.fileName;
        this.saveFileContent(fileToSave);
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
        if (this.isBusy) {
            return;
        }

        this.dialogRef.close();
    }

    ngOnInit() {
        this.title = (this.isNew) ? 'Create New File' : 'Edit File';

        if (!this.isNew) {
            this.loadFileContent(this.path + '/' + this.fileName);
        }
    }

}
