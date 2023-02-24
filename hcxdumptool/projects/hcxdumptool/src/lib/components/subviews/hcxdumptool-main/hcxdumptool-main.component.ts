import {Component, OnDestroy, OnInit} from '@angular/core';
import {ApiService} from "../../../services/api.service";
import {MatDialog} from "@angular/material/dialog";
import {StartupDTO, StartupLastJob} from "../../../interfaces/startupdto.interface";
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";
import {JobResultDTO} from "../../../interfaces/jobresult.interface";
import {UninstallDialogComponent} from "../../helpers/uninstall-dialog/uninstall-dialog.component";
import {OtherOptions, HCXDumptoolState} from "../../../interfaces/optionstate.interface";
import {LicenseDialogComponent} from "../../helpers/license-dialog/license-dialog.component";

@Component({
    selector: 'lib-hcxdumptool-main',
    templateUrl: './hcxdumptool-main.component.html',
    styleUrls: ['./hcxdumptool-main.component.css']
})
export class HcxdumptoolMainComponent implements OnInit, OnDestroy {

    public hasDependencies: boolean = true;
    public isInstalling: boolean = false;
    public interfaces: Array<string> = [];
    public isFetchingOutput: boolean = false;
    public isCapturing: boolean = false;
    public captureFileName: string = null;
    public captureOutput: string = null;
    private backgroundJobInterval = null;

    public hcxDumptoolState: HCXDumptoolState = {
        command: 'hcxdumptool --enable_status=3 ',
        selectedInterface: '',
        scanlist: ''
    };

    public optionsState: OtherOptions = {
        disableClientAttacks: { toggled: false, value: '--disable_client_attacks' },
        disableAPAttacks: { toggled: false, value: '--disable_ap_attacks' },
    };

    constructor(private API: ApiService,
                private dialog: MatDialog) {
    }

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

    pollBackgroundJob<T>(jobId: string, onComplete: (result: JobResultDTO<T>) => void, onInterval?: Function): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({
                module: 'hcxdumptool',
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

    getLogContent(): void {
        this.isFetchingOutput = true;
        this.API.request({
            module: 'hcxdumptool',
            action: 'get_log_content',
        }, (response) => {
            this.isFetchingOutput = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.captureOutput = response;
        });
    }

    downloadPcap(): void {
        this.API.APIDownload('/root/.hcxdumptool/' + this.captureFileName, this.captureFileName);
    }

    private monitorCaptureJob(jobId: string, captureFile: string): void {
        this.isCapturing = true;
        this.captureFileName = captureFile;
        this.pollBackgroundJob(jobId, (result: JobResultDTO<boolean>) => {
            this.isCapturing = false;
            this.getLogContent();

            if (result.job_error) {
                this.handleError(result.job_error);
            }
        }, () => {
            this.getLogContent();
        })
    }

    startCapture(): void {
        this.isCapturing = true;
        this.API.request({
            module: 'hcxdumptool',
            action: 'start_capture',
            command: this.hcxDumptoolState.command
        }, (response) => {
            if (response.error !== undefined) {
                this.isCapturing = false;
                this.handleError(response.error);
                return;
            }

            this.monitorCaptureJob(response.job_id, response.output_file);
        });
    }

    stopCapture(): void {
        this.API.request({
            module: 'hcxdumptool',
            action: 'stop_capture'
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }

            this.isCapturing = false
        })
    }

    checkForDependencies(): void {
        this.API.request({
            module: 'hcxdumptool',
            action: 'check_dependencies'
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.hasDependencies = response;
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

    installDependencies(): void {
        this.API.request({
            module: 'hcxdumptool',
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

    showUninstallDialog(): void {
        this.dialog.open(UninstallDialogComponent, {
            hasBackdrop: true,
            width: '700px',
            disableClose: true,
            data: {
                onComplete: () => {
                    this.checkForDependencies();
                }
            }
        });
    }

    update(): void {
        this.hcxDumptoolState.command = 'hcxdumptool --enable_status=3 ' + this.updateInterface() +
            this.updateScanlist() + this.updateOptions()
    }

    private updateInterface(): string {
        const iface = this.hcxDumptoolState.selectedInterface;
        return (iface !== '' && iface !== undefined) ? '-i ' + iface + ' ' : '';
    }

    private updateOptions(): string {
        let returnValue: string = '';

        for (let option of Object.values(this.optionsState)) {
            if (option.toggled) {
                returnValue += option.value + ' ';
            }
        }

        return returnValue;
    }

    private updateScanlist(): string {
        const scanlist = this.hcxDumptoolState.scanlist;
        return (scanlist !== '' && scanlist !== undefined) ? scanlist + ' ' : '';
    }

    private rebind(lastJob: StartupLastJob): void {
        switch (lastJob.job_type) {
            case 'pcap':
                this.monitorCaptureJob(lastJob.job_id, lastJob.job_info);
                this.getLogContent();
                break;
            case 'opkg':
                this.monitorDependencies(lastJob.job_id);
                break;
        }
    }

    private startup(): void {
        this.API.request({
            module: 'hcxdumptool',
            action: 'startup'
        }, (response: StartupDTO) => {
            if (response.error !== undefined && response.error !== null) {
                this.handleError(response.error);
                return;
            }

            this.hasDependencies = response.has_dependencies;
            this.interfaces = response.interfaces;

            if (response.last_job.job_id !== null) {
                this.rebind(response.last_job);
            }
        });
    }

    showLicenseDialog(): void {
        this.dialog.open(LicenseDialogComponent, {
            hasBackdrop: true,
            width: '900px',
        });
    }

    ngOnInit(): void {
        this.startup();
    }

    ngOnDestroy() {
        clearInterval(this.backgroundJobInterval);
    }

}
