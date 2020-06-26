import {Component, OnDestroy, OnInit} from '@angular/core';
import { ApiService } from '../services/api.service';
import {ErrorDialogComponent} from "./helpers/error-dialog/error-dialog.component";
import {MatDialog} from "@angular/material/dialog";
import {JobResultDTO} from "../interfaces/jobresult.interface";
import {PortalInfoDTO} from "../interfaces/portalinfo.interface";

@Component({
    selector: 'lib-evilportal',
    templateUrl: './evilportal.component.html',
    styleUrls: ['./evilportal.component.css']
})
export class EvilPortalComponent implements OnInit, OnDestroy {

    public portals: Array<PortalInfoDTO> = [
        {title: "Sample1", type: "Basic", location: "", active: false},
        {title: "Sample2", type: "Targeted", location: "", active: true}
    ];

    public hasDependencies: boolean = false;
    public isInstalling: boolean = false;
    private backgroundJobInterval = null;

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    private handleError(msg: string): void {
        this.dialog.closeAll();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '500px',
            data: {
                message: msg
            }
        });
    }

    private monitorDependencies(jobId: string) {
        this.isInstalling = true;
        this.pollBackgroundJob(jobId, (result: JobResultDTO<boolean>) => {
            this.isInstalling = false;
            if (result.job_error !== null) {
                this.handleError(result.job_error);
            }
            this.checkForDependencies();
        });
    }

    pollBackgroundJob<T>(jobId: string, onComplete: (result: JobResultDTO<T>) => void, onInterval?: Function): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({
                module: 'evilportal',
                action: 'poll_job',
                job_id: jobId
            }, (response: JobResultDTO<T>) => {
                if (response.is_complete) {
                    onComplete(response);
                    clearInterval(this.backgroundJobInterval);
                } else if (onInterval) {
                    onInterval();
                }
            });
        }, 5000);
    }

    installDependencies(): void {
        this.API.request({
            module: 'evilportal',
            action: 'manage_dependencies',
            install: true
        }, (response) => {
            if (response.error !== undefined && response.error !== null) {
                this.handleError(response.error);
                return;
            }

            this.monitorDependencies(response.job_id);
        });
    }

    checkForDependencies(): void {
        this.API.request({
            module: 'evilportal',
            action: 'check_dependencies'
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.hasDependencies = response;
        });
    }

    ngOnInit() {
        this.checkForDependencies();
    }

    ngOnDestroy() {
        clearInterval(this.backgroundJobInterval);
    }
}
