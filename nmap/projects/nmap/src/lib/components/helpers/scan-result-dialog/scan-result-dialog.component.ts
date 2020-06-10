import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialog, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";
import {ErrorDialogComponent} from "../error-dialog/error-dialog.component";

@Component({
    selector: 'lib-view-history-dialog',
    templateUrl: './scan-result-dialog.component.html',
    styleUrls: ['./scan-result-dialog.component.css']
})
export class ScanResultDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<ScanResultDialogComponent>,
                private API: ApiService,
                private dialog: MatDialog,
                @Inject(MAT_DIALOG_DATA) public data: any) {
    }

    public isBusy: boolean = false;
    public content: string = null;

    closeDialog(): void {
        this.dialogRef.close();
    }

    private handleError(msg: string): void {
        this.closeDialog();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                message: msg
            }
        });
    }

    private loadContent(): void {
        this.isBusy = true;
        this.API.request({
            module: 'nmap',
            action: 'get_scan_output',
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

    ngOnInit(): void {
        this.loadContent();
    }

}
