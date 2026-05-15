import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {ApiService} from '../../../services/api.service';

@Component({
    selector: 'lib-edit-file-dialog',
    templateUrl: './edit-file-dialog.component.html',
    styleUrls: ['./edit-file-dialog.component.css']
})
export class EditFileDialogComponent implements OnInit {

    content = '';
    newFileName = '';
    isLoading = false;
    isSaving = false;
    errorMessage = '';

    constructor(
        public dialogRef: MatDialogRef<EditFileDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: {
            siteName: string;
            filePath: string | null;
            basePath: string;
            isNew: boolean;
            onSaved: () => void;
        },
        private API: ApiService
    ) {}

    get title(): string {
        if (this.data.isNew) { return 'New File'; }
        return 'Edit: ' + this.data.filePath;
    }

    get saveDisabled(): boolean {
        return this.isLoading || this.isSaving || (this.data.isNew && !this.newFileName.trim());
    }

    ngOnInit(): void {
        if (!this.data.isNew) {
            this.isLoading = true;
            this.API.request({
                module: 'webserver',
                action: 'load_file',
                site_name: this.data.siteName,
                file_path: this.data.filePath
            }, (response) => {
                this.isLoading = false;
                if (response.error !== undefined) {
                    this.errorMessage = response.error;
                    return;
                }
                this.content = response.content;
            });
        }
    }

    save(): void {
        const filePath = this.data.isNew
            ? (this.data.basePath
                ? this.data.basePath + '/' + this.newFileName.trim()
                : this.newFileName.trim())
            : this.data.filePath;

        this.isSaving = true;
        this.errorMessage = '';

        this.API.request({
            module: 'webserver',
            action: 'save_file',
            site_name: this.data.siteName,
            file_path: filePath,
            content: this.content
        }, (response) => {
            this.isSaving = false;
            if (response.error !== undefined) {
                this.errorMessage = response.error;
                return;
            }
            this.data.onSaved();
            this.dialogRef.close();
        });
    }
}
