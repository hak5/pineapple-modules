import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-MACInfo',
    templateUrl: './MACInfo.component.html',
    styleUrls: ['./MACInfo.component.css']
})
export class MACInfoComponent implements OnInit {
    constructor(private API: ApiService) { }

    userInput = '';
    apiResponse = '';
    public isLoading: boolean = false;

    check_mac_online(): void {
        this.isLoading = true;
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac_online',
            user_input: this.userInput
        }, (response) => {
            this.isLoading = false;
            this.apiResponse = response;
        })
    }

    check_mac(): void {
        this.isLoading = true;
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac',
            user_input: this.userInput
        }, (response) => {
            this.isLoading = false;
            this.apiResponse = response;
        })
    }

    ngOnInit() {
    }
}
