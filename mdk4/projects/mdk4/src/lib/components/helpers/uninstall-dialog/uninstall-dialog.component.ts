import {Component, Inject, OnDestroy, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialog, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";
import {ErrorDialogComponent} from "../error-dialog/error-dialog.component";
import {JobResultDTO} from "../../../interfaces/jobresultdto.interface";

@Component({
    selector: 'lib-uninstall-dialog',
    templateUrl: './uninstall-dialog.component.html',
    styleUrls: ['./uninstall-dialog.component.css']
})
export class UninstallDialogComponent implements OnInit, OnDestroy {

    public isBusy: boolean = false;
    private backgroundJobInterval = null;

    constructor(public dialogRef: MatDialogRef<UninstallDialogComponent>,
                private API: ApiService,
                private dialog: MatDialog,
                @Inject(MAT_DIALOG_DATA) public data: any) {
    }

    private pollBackgroundJob<T>(jobId: string, onComplete: (result: JobResultDTO<T>) => void): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({
                module: 'mdk4',
                action: 'poll_job',
                job_id: jobId
            }, (response: JobResultDTO<T>) => {
                if (response.is_complete) {
                    onComplete(response);
                    clearInterval(this.backgroundJobInterval);
                }
            });
        }, 5000);
    }

    private handleError(msg: string): void {
        this.isBusy = false;
        this.closeDialog();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                message: msg
            }
        });
    }

    closeDialog(): void {
        if (this.isBusy) { return; }
        this.dialogRef.close();
    }

    removeDependencies(): void {
        this.API.request({
            module: 'mdk4',
            action: 'manage_dependencies',
            install: false
        }, (response) => {
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.isBusy = true;
            this.pollBackgroundJob(response.job_id, (result: JobResultDTO<boolean>) => {
                this.isBusy = false;

                if (result.job_error !== null) {
                    this.handleError(result.job_error);
                    return;
                }

                this.data.onComplete();
                this.closeDialog();
            });
        });
    }

    ngOnInit(): void {
    }

    ngOnDestroy() {
        clearInterval(this.backgroundJobInterval);
    }
}
