import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-DenyIP',
    templateUrl: './DenyIP.component.html',
    styleUrls: ['./DenyIP.component.css']
})
export class DenyIPComponent implements OnInit {
    constructor(private API: ApiService) { }

    error = "";
    addresses4 = "";
    addresses6 = "";

    userIP = "";
    userType = "";
    hasIpset: boolean = true;
    hasInit: boolean = false;
    isInstalling: boolean = false;
    isAdding: boolean = false;
    isResetting: boolean = false;
    isUpdating: boolean = false;

    ipsetCheck(): void {
        this.API.request({
            module: 'DenyIP',
            action: "ipsetCheck"
        }, (response) => {
            if (response == "ok") {
                this.hasIpset = true;
                this.init();
            } else {
                this.hasIpset = false;
            }
        })
    }

    ipsetInstall(): void {
        this.isInstalling = true;
        this.API.request({
            module: 'DenyIP',
            action: "ipsetInstall"
        }, (response) => {
            if (response == "ok") {
                this.ipsetCheck()
            } else {
                this.error = response;
            }
            this.isInstalling = false;
        })
    }

    init(): void {
        this.API.request({
            module: 'DenyIP',
            action: "init"
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            } else {
                this.hasInit = true;
                this.get4();
                this.get6();
            }
        })
    }

    get4(): void {
        this.API.request({
            module: 'DenyIP',
            action: "get4"
        }, (response) => {
            this.addresses4 = response;
        })
    }

    get6(): void {
        this.API.request({
            module: 'DenyIP',
            action: "get6"
        }, (response) => {
            this.addresses6 = response;
        })
    }

    add(): void {
        this.isAdding = true;
        this.API.request({
            module: 'DenyIP',
            action: "add",
            user_ip: this.userIP,
            user_type: this.userType
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            } else {
                this.userIP = "";
                this.get4();
                this.get6();
            }
            this.isAdding = false;
        })
    }

    clear(): void {
        this.isResetting = true;
        this.API.request({
            module: 'DenyIP',
            action: "clear"
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            } else {
                this.get4();
                this.get6();
            }
            this.isResetting = false;
        })
    }

    update(): void {
        this.isUpdating = true;
        this.API.request({
            module: 'DenyIP',
            action: "update"
        }, (response) => {
            if (response != "ok") {
                this.error = response;
            }
            this.isUpdating = false;
        })
    }

    ngOnInit() {
        this.ipsetCheck();
    }
}
