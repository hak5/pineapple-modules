import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../../services/api.service';

@Component({
    selector: 'lib-MACInfo-onlinecomponent',
    templateUrl: './macinfo-online.component.html',
    styleUrls: ['./macinfo-online.component.css']
})
export class MACInfoOnlineComponent implements OnInit {
    constructor(private API: ApiService) { }

    userInput = '';
    apiResponse = '';
    apiOnlineResponse = '';
    public isLoading: boolean = false;
    public isOnline: boolean = false;
    company = '';
    address = '';
    mactype = '';
    maccountry = '';
    start_hex = '';
    end_hex = '';

    check_mac_online(): void {
        this.isOnline = true;
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
        })
    }

    check_mac(): void {
        this.isOnline = false;
        this.isLoading = true;
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac',
            user_input: this.userInput
        }, (response) => {
            this.isLoading = false;
            this.company = response.company;
        })
    }

    ngOnInit() {
    }
}
