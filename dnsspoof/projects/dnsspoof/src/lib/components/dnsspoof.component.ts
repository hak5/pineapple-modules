import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-dnsspoof',
    templateUrl: './dnsspoof.component.html',
    styleUrls: ['./dnsspoof.component.css']
})
export class dnsspoofComponent implements OnInit {
    constructor(private API: ApiService) { }

    error = "";
    allocation = "";

    userIP = "";
    userDomain = "";
    backup: boolean = false;
    isAdding: boolean = false;
    isUpdating: boolean = false;
    isResetting: boolean = false;

    handleBackup(): void {
        this.API.request({
            module: 'dnsspoof',
            action: "backup"
        }, (response) => {
            if (response == "ok") {
                this.backup = true;
            } else {
                this.error = response;
            }
        })
    }

    add(): void {
        this.isAdding = true;
        this.API.request({
            module: 'dnsspoof',
            action: "add",
            user_ip: this.userIP,
            user_domain: this.userDomain
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            } else {
                this.userIP = "";
                this.userDomain = "";
                this.get();
            }
            this.isAdding = false;
        })
    }

    get(): void {
        this.API.request({
            module: 'dnsspoof',
            action: "get"
        }, (response) => {
            this.allocation = response;
        })
    }

    update(): void {
        this.isUpdating = true;
        this.API.request({
            module: 'dnsspoof',
            action: "update"
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            }
            this.isUpdating = false;
        })
    }

    reset(): void {
        this.isResetting = true;
        this.API.request({
            module: 'dnsspoof',
            action: "reset"
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            } else {
                this.get();
            }
            this.isResetting = false;
        })
    }

    ngOnInit() {
        this.handleBackup();
        this.get();
    }
}
