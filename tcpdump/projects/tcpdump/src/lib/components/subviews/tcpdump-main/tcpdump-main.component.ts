import {Component, OnDestroy, OnInit} from '@angular/core';
import {ApiService} from "../../../services/api.service";
import {MatDialog} from "@angular/material/dialog";
import {StartupDTO, StartupLastJob} from "../../../interfaces/startupdto.interface";
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";
import {JobResultDTO} from "../../../interfaces/jobresult.interface";
import {UninstallDialogComponent} from "../../helpers/uninstall-dialog/uninstall-dialog.component";
import {OtherOptions, TCPDumpState} from "../../../interfaces/optionstate.interface";

@Component({
    selector: 'lib-tcpdump-main',
    templateUrl: './tcpdump-main.component.html',
    styleUrls: ['./tcpdump-main.component.css']
})
export class TcpdumpMainComponent implements OnInit, OnDestroy {

    public hasDependencies: boolean = true;
    public isInstalling: boolean = false;
    public interfaces: Array<string> = [];
    public isFetchingOutput: boolean = false;
    public isCapturing: boolean = false;
    public captureFileName: string = null;
    public captureOutput: string = null;
    private backgroundJobInterval = null;

    public tcpDumpState: TCPDumpState = {
        command: 'tcpdump ',
        selectedInterface: '',
        filter: '',
        timestamp: '',
        resolve: '',
        verbose: ''
    };

    public optionsState: OtherOptions = {
        dontPrintHostName: { toggled: false, value: '-N' },
        showHexAndASCII: { toggled: false, value: '-X' },
        printAbsoluteNumbers: { toggled: false, value: '-S' },
        getEthernetHeaders: { toggled: false, value: '-e' },
        lessProtocolInfo: { toggled: false, value: '-q' },
        monitorMode: { toggled: false, value: '-I' },
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
                module: 'tcpdump',
                action: 'check_background_job',
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
            module: 'tcpdump',
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
            module: 'tcpdump',
            action: 'start_capture',
            command: this.tcpDumpState.command
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
            module: 'tcpdump',
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
            module: 'tcpdump',
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
            module: 'tcpdump',
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
        })
    }

    update(): void {
        this.tcpDumpState.command = 'tcpdump ' + this.updateInterface() + this.updateVerbose() +
            this.updateResolve() + this.updateTimestamp() + this.updateOptions()

        if (this.tcpDumpState.filter !== '' && this.tcpDumpState.filter !== undefined) {
            this.tcpDumpState.command += '\'' + this.tcpDumpState.filter + '\'';
        }
    }

    appendFilter(value: string): void {
        let filter = this.tcpDumpState.filter;
        if (filter.substr(filter.length -1) != ' ' && filter.length != 0) {
            this.tcpDumpState.filter = filter + ' ' + value;
        } else {
            this.tcpDumpState.filter = filter + value;
        }

        this.update();
    }

    private updateInterface(): string {
        const iface = this.tcpDumpState.selectedInterface;
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

    private updateVerbose(): string {
        const verbose = this.tcpDumpState.verbose;
        return (verbose !== '' && verbose !== undefined) ? verbose + ' ' : '';
    }

    private updateResolve(): string {
        const resolve = this.tcpDumpState.resolve;
        return (resolve !== '' && resolve !== undefined) ? resolve + ' ' : '';
    }

    private updateTimestamp(): string {
        const timestamp = this.tcpDumpState.timestamp;
        return (timestamp !== '' && timestamp !== undefined) ? timestamp + ' ' : '';
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
            module: 'tcpdump',
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

    ngOnInit(): void {
        this.startup();
    }

    ngOnDestroy() {
        clearInterval(this.backgroundJobInterval);
    }

}
