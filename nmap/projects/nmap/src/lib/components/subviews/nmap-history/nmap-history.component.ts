import {Component, OnInit} from '@angular/core';
import {ApiService} from "../../../services/api.service";
import {MatDialog} from "@angular/material/dialog";
import {ScanResultDialogComponent} from "../../helpers/scan-result-dialog/scan-result-dialog.component";
import {ConfirmationDialogComponent} from "../../helpers/confirmation-dialog/confirmation-dialog.component";
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";

@Component({
    selector: 'lib-nmap-history',
    templateUrl: './nmap-history.component.html',
    styleUrls: ['./nmap-history.component.css']
})
export class NmapHistoryComponent implements OnInit {

    constructor(private API: ApiService,
                private dialog: MatDialog) {
    }

    public isBusy: boolean = false;
    public scanHistory: Array<string> = [];

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

    loadHistory(): void {
        this.isBusy = true;
        this.API.request({
            module: 'nmap',
            action: 'list_scan_history'
        }, (response) => {
            this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.scanHistory = response;
        });
    }

    downloadItem(item: string): void {
        this.API.APIDownload('/root/.nmap/' + item, 'nmap-' + item + '.log')
    }

    private deleteItem(item: string): void {
        this.isBusy = true;
        this.API.request({
            module: 'nmap',
            action: 'delete_result',
            output_file: item
        }, (response) => {
           this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.loadHistory();
        });
    }

    private deleteAll(): void {
        this.isBusy = true;
        this.API.request({
            module: 'nmap',
            action: 'clear_scans'
        }, (response) => {
            this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.loadHistory();
        });
    }

    showScanResults(item: string): void {
        this.dialog.open(ScanResultDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                historyFile: item
            }
        });
    }

    showDeleteDialog(item: string): void {
        this.dialog.open(ConfirmationDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                title: 'Delete?',
                message: 'You are about to delete ' + item + '? This action can not be undone. Are you sure you want to continue?',
                handleResponse: (affirmative: boolean) => {
                    if (affirmative) {
                        this.deleteItem(item);
                    }
                }
            }
        });
    }

    showClearHistoryDialog(): void {
        this.dialog.open(ConfirmationDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                title: 'Delete All?',
                message: 'You are about to delete all scan history. This action can not be undone. Are you sure you want to continue?',
                handleResponse: (affirmative: boolean) => {
                    if (affirmative) {
                        this.deleteAll();
                    }
                }
            }
        })
    }

    ngOnInit(): void {
        this.loadHistory();
    }

}
