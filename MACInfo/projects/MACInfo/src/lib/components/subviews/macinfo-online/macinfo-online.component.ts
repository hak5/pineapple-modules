import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../../services/api.service';

@Component({
    selector: 'lib-MACInfo-onlinecomponent',
    templateUrl: './macinfo-online.component.html',
    styleUrls: ['../../MACInfo.component.css', './macinfo-online.component.css']
})
export class MACInfoOnlineComponent implements OnInit {
    constructor(private API: ApiService) { }

    userInput : string = '';
    isLoading : boolean = false;

    nomac : string = '';
    company : string = '';
    address : string = '';
    mactype : string = '';
    maccountry : string = '';
    start_hex : string = '';
    end_hex : string = '';
    validMAC: boolean = true;

    check_mac_online(): void {
        this.isLoading = true;
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac_online',
            user_input: this.userInput
        }, (response) => {
            this.isLoading = false;
            this.company = response.company;
            this.address = response.address;
            this.mactype = response.mactype;
            this.maccountry = response.maccountry;
            this.start_hex = response.start_hex;
            this.end_hex = response.end_hex;
            this.nomac = response.nomac;
            if (this.nomac == "Not a valid MAC address"){
                this.validMAC = false;
            }
        })
    }

    ngOnInit() {
    }
}
