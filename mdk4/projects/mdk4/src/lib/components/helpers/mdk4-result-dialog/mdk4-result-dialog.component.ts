import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialog, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";
import {ErrorDialogComponent} from "../error-dialog/error-dialog.component";

@Component({
    selector: 'lib-mdk4-result-dialog',
    templateUrl: './mdk4-result-dialog.component.html',
    styleUrls: ['./mdk4-result-dialog.component.css']
})
export class Mdk4ResultDialogComponent implements OnInit {

    public isBusy: boolean = false;
    public content: string = null;

    constructor(public dialogRef: MatDialogRef<Mdk4ResultDialogComponent>,
                private API: ApiService,
                private dialog: MatDialog,
                @Inject(MAT_DIALOG_DATA) public data: any) {
    }

    private handleError(msg: string): void {
        this.closeDialog();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '400px',
            data: msg
        });
    }

    private loadContent(): void {
        this.isBusy = true;
        this.API.request({
            module: 'mdk4',
            action: 'load_output',
            output_file: this.data.historyFile
        }, (response) => {
            this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.content = response;
        });
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit(): void {
        this.loadContent();
    }

}
