import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";

@Component({
    selector: 'lib-view-history-dialog',
    templateUrl: './scan-result-dialog.component.html',
    styleUrls: ['./scan-result-dialog.component.css']
})
export class ScanResultDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<ScanResultDialogComponent>,
                private API: ApiService,
                @Inject(MAT_DIALOG_DATA) public data: any) {
    }

    public isBusy: boolean = false;
    public content: string = null;

    closeDialog(): void {
        this.dialogRef.close();
    }

    private handleError(msg: string): void {
        console.log('ERROR: ' + msg);
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
