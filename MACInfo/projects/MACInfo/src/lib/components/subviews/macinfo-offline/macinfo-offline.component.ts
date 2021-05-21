import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../../services/api.service';

@Component({
    selector: 'lib-MACInfo-offlineinfo',
    templateUrl: './macinfo-offline.component.html',
    styleUrls: ['../../MACInfo.component.css', './macinfo-offline.component.css']
})
export class MACInfoOfflineComponent implements OnInit {
    constructor(private API: ApiService) { }

    userInput : string = '';
    company : string = '';
    nomac : string = '';
    isLoading : boolean = false;
    validMAC : boolean = true;

    check_mac(): void {
        this.isLoading = true;
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac',
            user_input: this.userInput
        }, (response) => {
            this.isLoading = false;
            this.company = response.company;
            this.nomac = response.nomac;
            if (this.nomac === "Not a valid MAC address"){
                this.validMAC = false;
            }
        })
    }

    ngOnInit() {
    }
}
