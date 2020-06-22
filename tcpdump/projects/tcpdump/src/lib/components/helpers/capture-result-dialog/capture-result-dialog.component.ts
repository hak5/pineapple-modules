import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialog, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";
import {ErrorDialogComponent} from "../error-dialog/error-dialog.component";

@Component({
  selector: 'lib-capture-result-dialog',
  templateUrl: './capture-result-dialog.component.html',
  styleUrls: ['./capture-result-dialog.component.css']
})
export class CaptureResultDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<CaptureResultDialogComponent>,
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
            module: 'tcpdump',
            action: 'get_capture_output',
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
