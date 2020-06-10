import { Component, OnInit } from '@angular/core';
import {MatDialog } from '@angular/material/dialog';

import {ApiService} from '../services/api.service';

import {CabinetDeleteDialogComponent} from './helpers/delete-dialog/cabinet-delete-dialog.component';
import {NewFolderDialogComponent} from './helpers/new-folder-dialog/cabinet-new-folder-dialog.component';
import {FileEditorDialogComponent} from './helpers/file-editor-dialog/cabinet-file-editor-dialog.component';
import {CabinetErrorDialogComponent} from './helpers/error-dialog/cabinet-error-dialog.component';

@Component({
    selector: 'lib-cabinet',
    templateUrl: 'cabinet.component.html',
    styleUrls: ['cabinet.component.css'],
})
export class cabinetComponent implements OnInit {

    public isBusy: boolean = false;
    public currentDirectory: string = '/';
    public directoryContents: Array<object> = [];

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    humanFileSize(byteLength: number): string {
        const kiloBytes = 1024;
        const megaBytes = kiloBytes * kiloBytes;
        const gigaBytes = megaBytes * megaBytes;

        if (byteLength >= kiloBytes && byteLength < megaBytes) {
            return Math.round(byteLength / kiloBytes) + ' KB';
        } else if (byteLength >= megaBytes && byteLength < gigaBytes) {
            return Math.round(byteLength / megaBytes) + ' MB';
        } else if (byteLength >= gigaBytes) {
            return Math.round(byteLength / gigaBytes) + ' GB';
        } else {
            return byteLength + ' bytes';
        }
    }

    getDirectoryContents(path: string, getParent: boolean = false): void {
        this.isBusy = true;

        this.API.request({
            module: 'cabinet',
            action: 'list_directory',
            directory: path,
            get_parent: getParent
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                this.showErrorDialog(response.error);
                return
            }

            this.currentDirectory = response.working_directory;
            this.directoryContents = response.contents.map((item) => {
                item['size'] = this.humanFileSize(item['size']);
                return item;
            });
        });
    }

    deleteItem(path: string): void {
        this.API.request({
            module: 'cabinet',
            action: 'delete_item',
            file_to_delete: path
        }, (response) => {
            if (response.error !== undefined) {
                this.showErrorDialog(response.error);
                return
            }

            this.getDirectoryContents(this.currentDirectory);
        })
    }

    createDirectory(name: string): void {
        this.API.request({
            module: 'cabinet',
            action: 'create_directory',
            path: this.currentDirectory,
            name: name
        }, (response) => {
            if (response.error !== undefined) {
                this.showErrorDialog(response.error);
                return
            }

            this.getDirectoryContents(this.currentDirectory);
        })
    }

    writeFile(path: string, content: string): void {
        this.API.request({
            module: 'cabinet',
            action: 'write_file',
            file: path,
            content: content
        }, (response) => {
            if (response.error !== undefined) {
                this.showErrorDialog(response.error);
                return
            }

            this.getDirectoryContents(this.currentDirectory);
        })
    }

    showDeleteConfirmation(item): void {
        this.dialog.open(CabinetDeleteDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                item: item,
                onDelete: () => {
                    console.log('DELETING ITEM: ' + item.path);
                    this.deleteItem(item.path);
                }
            }
        });
    }

    showCreateDirectory(): void {
        this.dialog.open(NewFolderDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                path: this.currentDirectory,
                onCreate: (name) => {
                    this.createDirectory(name);
                }
            }
        })
    }

    showEditDialog(item): void {
        const data = (item === null) ? {
            path: this.currentDirectory,
            fileName: null,
            isNew: true,
            onSave: (path, content) => {
                this.writeFile(path, content);
            }
        } : {
            path: item.path,
            fileName: item.name,
            isNew: false,
            onSave: (path, content) => {
                this.writeFile(path, content);
            }
        };

        this.dialog.open(FileEditorDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: data
        })
    }

    showErrorDialog(msg: string): void {
        this.dialog.closeAll();
        this.dialog.open(CabinetErrorDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                errorMessage: msg
            }
        });
    }

    ngOnInit(): void {
        this.getDirectoryContents('/');
    }
}
