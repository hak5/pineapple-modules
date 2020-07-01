import {Component, OnInit} from '@angular/core';
import {MatDialog} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";
import {ConfirmationDialogComponent} from "../../helpers/confirmation-dialog/confirmation-dialog.component";
import {Mdk4ResultDialogComponent} from "../../helpers/mdk4-result-dialog/mdk4-result-dialog.component";
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";

@Component({
    selector: 'lib-mdk4-history',
    templateUrl: './mdk4-history.component.html',
    styleUrls: ['./mdk4-history.component.css']
})
export class Mdk4HistoryComponent implements OnInit {

    public isBusy: boolean = false;
    public mdk4History: Array<string> = [];

    constructor(private API: ApiService,
                private dialog: MatDialog) {
    }

    private handleError(msg: string): void {
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '400px',
            data: msg
        });
    }

    loadHistory(): void {
        this.isBusy = true;
        this.API.request({
            module: 'mdk4',
            action: 'load_history'
        }, (response) => {
            this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.mdk4History = response;
        });
    }

    private deleteItem(item: string): void {
        this.isBusy = true;
        this.API.request({
            module: 'mdk4',
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
            module: 'mdk4',
            action: 'clear_history'
        }, (response) => {
            this.isBusy = false;
            if (response.error) {
                this.handleError(response.error);
                return;
            }

            this.loadHistory();
        });
    }

    showMdk4Results(item: string): void {
        this.dialog.open(Mdk4ResultDialogComponent, {
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
            width: '400px',
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
            width: '400px',
            data: {
                title: 'Delete All?',
                message: 'You are about to delete all mdk4 history. This action can not be undone. Are you sure you want to continue?',
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
