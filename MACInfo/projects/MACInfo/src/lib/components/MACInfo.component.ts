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

    check_mac(): void {
        this.API.request({
            module: 'MACInfo',
            action: 'check_mac',
            user_input: this.userInput
        }, (response) => {
            this.apiResponse = response;
        })
    }

    ngOnInit() {
    }
}
