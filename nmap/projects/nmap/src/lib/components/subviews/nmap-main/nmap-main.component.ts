import {Component, OnDestroy, OnInit} from '@angular/core';
import {ApiService} from '../../../services/api.service';
import { JobResultDTO } from '../../../interfaces/jobresult.interface';
import {MatDialog} from '@angular/material/dialog';
import {UninstallDialogComponent} from '../../helpers/uninstall-dialog/uninstall-dialog.component';
import {
    NmapOptionsState,
    OtherOptions,
    PingOptions,
    ScanOptions,
    ToggleOption,
} from '../../../interfaces/optionstate.interface';
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";
import {LicenseDialogComponent} from "../../helpers/license-dialog/license-dialog.component";

@Component({
  selector: 'lib-nmap-main',
  templateUrl: './nmap-main.component.html',
  styleUrls: ['./nmap-main.component.css']
})
export class NmapMainComponent implements OnInit, OnDestroy {

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    public hasDependencies: boolean = true;
    public scanOutput: string = null;
    public scanOutputFileName: string = null;
    public isFetchingOutput: boolean = false;
    public isScanning: boolean = false;
    public isInstalling: boolean = false;
    private backgroundJobInterval = null;

    public nmapOptions: NmapOptionsState = {
        command: 'nmap ',
        target: '',
        profile: '',
        timing: '',
        tcp: '',
        nontcp: ''
    };

    public scanOptions: ScanOptions = {
        advancedOptions: { toggled: false, value: '-A' },
        osDetection: { toggled: false, value: '-O' },
        versionDetection: { toggled: false, value: '-sV' },
        disableDNS: { toggled: false, value: '-n' },
        ipv6: { toggled: false, value: '-6' }
    };

    public pingOptions: PingOptions = {
        noPingBeforeScanning: { toggled: false, value: '-Pn' },
        icmpPing: { toggled: false, value: '-PE' },
        icmpTimeStamp: { toggled: false, value: '-PP' },
        icmpNetmask: { toggled: false, value: '-PM' },
    };

    public targetOptions: ToggleOption = { toggled: false, value: '-F' };

    public otherOptions: OtherOptions = {
        fragmentPackets: { toggled: false, value: '-f' },
        packetTrace: { toggled: false, value: '--packet-trace' },
        disableRandomized: { toggled: false, value: '-r' },
        traceRoutes: { toggled: false, value: '--traceroute' },
    }

    private handleError(msg: string): void {
        this.dialog.closeAll();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                message: msg
            }
        });
    }

    update(): void {
        if (this.updateProfile() !== '') {
            this.nmapOptions.command = 'nmap ' + this.updateProfile() + this.updateTarget();
        } else {
            this.nmapOptions.command = 'nmap ' + this.updateTiming() + this.updateTcp() + this.updateNontcp() + this.updateOptions() + this.updateTarget();
        }
    }

    updateOptions(): string {
        let returnValue = '';

        for(let option of Object.values(this.scanOptions)) {
            if (option.toggled) {
                returnValue += option.value + ' ';
            }
        }

        for(let option of Object.values(this.pingOptions)) {
            if (option.toggled) {
                returnValue += option.value + ' ';
            }
        }

        if (this.targetOptions.toggled) {
            returnValue += this.targetOptions.value + ' ';
        }

        for(let option of Object.values(this.otherOptions)) {
            if (option.toggled) {
                returnValue += option.value + ' ';
            }
        }

        return returnValue;
    }

    updateTarget(): string {
        return this.nmapOptions.target;
    }

    updateProfile(): string {
        let return_value = '';

        if (this.nmapOptions.profile !== '' && this.nmapOptions.profile !== undefined)
            return_value = this.nmapOptions.profile + ' ';

        return return_value;
    }

    updateTiming(): string {
        let return_value = '';

        if (this.nmapOptions.timing !== '' && this.nmapOptions.timing !== undefined)
            return_value = this.nmapOptions.timing + ' ';

        return return_value;
    }

    updateTcp(): string {
        let return_value = '';

        if (this.nmapOptions.tcp !== '' && this.nmapOptions.tcp !== undefined)
            return_value = this.nmapOptions.tcp + ' ';

        return return_value;
    }

    updateNontcp(): string {
        let return_value = '';

        if (this.nmapOptions.nontcp != '' && this.nmapOptions.nontcp !== undefined)
            return_value = this.nmapOptions.nontcp + ' ';

        return return_value;
    }

    pollBackgroundJob<T>(jobId: string, onComplete: (result: JobResultDTO<T>) => void, onInterval?: Function): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({
                module: 'nmap',
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

    checkForDependencies(): void {
        this.API.request({
            module: 'nmap',
            action: 'check_dependencies'
        }, (response) => {
            if (response.error) {
                this.handleError(response.error);
                return
            }

            this.hasDependencies = response;
        });
    }

    private monitorInstall(jobId: string): void {
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
            module: 'nmap',
            action: 'manage_dependencies',
            install: true
        }, (response) => {
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.monitorInstall(response.job_id);
        });
    }

    showUninstall(): void {
        this.dialog.open(UninstallDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                onComplete: () => { this.checkForDependencies(); }
            }
        });
    }

    getScanOutput(outputFile: string): void {
        if (outputFile === null || outputFile === undefined || outputFile === '') {
            return;
        }

        this.isFetchingOutput = true;
        this.API.request({
            module: 'nmap',
            action: 'get_scan_output',
            output_file: outputFile
        }, (response) => {
            this.isFetchingOutput = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.scanOutput = response;
        });
    }

    downloadOutput(): void {
        this.API.APIDownload('/root/.nmap/' + this.scanOutputFileName, 'nmap-' + this.scanOutputFileName + '.log')
    }

    private monitorScan(jobId: string, outputFile: string): void {
        this.isScanning = true;
        this.scanOutputFileName = outputFile;
        this.pollBackgroundJob(jobId, (result: JobResultDTO<boolean>) => {
            this.isScanning = false;
            this.getScanOutput(this.scanOutputFileName);

            if (result.job_error) {
                this.handleError(result.job_error);
            }
        }, () => {
            this.getScanOutput(this.scanOutputFileName);
        });
    }

    startScan(): void {
        this.API.request({
            module: 'nmap',
            action: 'start_scan',
            command: this.nmapOptions.command
        }, (response) => {
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.monitorScan(response.job_id, response.output_file);
        });
    }

    stopScan(): void {
        this.API.request({
            module: 'nmap',
            action: 'stop_scan'
        }, (response) => {
            if (response.error) {
                this.handleError(response.error);
                return;
            }
            this.isScanning = false;
        });
    }

    rebindLastJob(): void {
        this.API.request({
            module: 'nmap',
            action: 'rebind_last_job'
        }, (response) => {
           if (response.error) {
               this.handleError(response.error);
               return;
           }

           if (response.job_id && response.job_type) {
               switch (response.job_type) {
                   case 'scan':
                       this.monitorScan(response.job_id, response.job_info);
                       break;
                   case 'opkg':
                       this.monitorInstall(response.job_id);
                       break;
               }
           }
        });
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

    ngOnDestroy(): void {
        clearInterval(this.backgroundJobInterval);
    }

}
