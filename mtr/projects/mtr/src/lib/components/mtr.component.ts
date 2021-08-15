import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';
import { JobResultDTO } from '../interfaces/jobresult.interface';
import { MatDialog } from '@angular/material/dialog';
import {LicenseDialogComponent} from './helpers/license-dialog/license-dialog.component';

@Component({
    selector: 'lib-mtr',
    templateUrl: './mtr.component.html',
    styleUrls: ['./mtr.component.css'],
})
export class mtrComponent implements OnInit {
    constructor(private API: ApiService, private dialog: MatDialog) {}

    userInput = '';
    isLoading: boolean = false;
    commandfinished: boolean = false;
    hubs = '';
    backgroundJobInterval = null;
    hasDependencies: boolean = true;
    isInstalling: boolean = false;
    fileoutput = '';
    src = '';
    dst = '';

    pollBackgroundJob<T>(
        jobId: string,
        onComplete: (result: JobResultDTO<T>) => void,
        onInterval?: Function
    ): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request(
                {
                    module: 'mtr',
                    action: 'poll_job',
                    job_id: jobId,
                },
                (response: JobResultDTO<T>) => {
                    if (response.is_complete) {
                        onComplete(response);
                        clearInterval(this.backgroundJobInterval);
                    } else if (onInterval) {
                        onInterval();
                    }
                }
            );
        }, 2000);
    }
    checkForDependencies(): void {
        this.API.request(
            {
                module: 'mtr',
                action: 'check_dependencies',
            },
            (response) => {
                this.hasDependencies = response;
            }
        );
    }
    private monitorInstall(jobId: string): void {
        this.isInstalling = true;
        this.pollBackgroundJob(jobId, (result: JobResultDTO<boolean>) => {
            this.isInstalling = false;
            this.checkForDependencies();
        });
    }

    rebindLastJob(): void {
        this.API.request(
            {
                module: 'mtr',
                action: 'rebind_last_job',
            },
            (response) => {
                if (response.job_id && response.job_type) {
                    switch (response.job_type) {
                        case 'opkg':
                            this.monitorInstall(response.job_id);
                            break;
                    }
                }
            }
        );
    }
    installDependencies(): void {
        this.API.request(
            {
                module: 'mtr',
                action: 'manage_dependencies',
                install: true,
            },
            (response) => {
                this.monitorInstall(response.job_id);
            }
        );
    }

    private monitormtr(jobId: string): void {
        this.isLoading = true;
        this.pollBackgroundJob(
            jobId,
            (result: JobResultDTO<boolean>) => {
                this.isLoading = false;
                this.getoutput();
                console.log('MTR has finished.');
            },
            () => {
                console.log('MTR still running..');
            }
        );
    }

    getoutput(): void {
        this.API.request(
            {
                module: 'mtr',
                action: 'load_output',
            },
            (response) => {
                console.log(response.report);
                this.hubs = response.report.hubs;
                console.log(this.hubs);
            }
        );
    }

    startmtr(): void {
        this.isLoading = true;
        this.API.request(
            {
                module: 'mtr',
                action: 'startmtr',
                user_input: this.userInput,
            },
            (response) => {
                this.monitormtr(response.job_id);
            }
        );
    }
    showLicenseDialog(): void {
        this.dialog.open(LicenseDialogComponent, {
            hasBackdrop: true,
            width: '900px',
        });
    }

    ngOnInit() {
        this.checkForDependencies();
        this.rebindLastJob();
    }
}
