import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-wigle',
    templateUrl: './wigle.component.html',
    styleUrls: ['./wigle.component.css']
})
export class wigleComponent implements OnInit {
    constructor(private API: ApiService) { }

    userSSID = "";
    userMAC = "";
    userCC = "";
    userCity = "";
    userKey = "";
    apiResponse: boolean = false;
    isLoading: boolean = false;
    isSubmittingKey: boolean = false;
    hasKey: boolean = true;

    msg = "";
    wiglenet = "https://wigle.net/";
    ssid = "";
    channel = "";
    enc = "";
    mac = "";
    dhcp = "";
    country = "";
    city = "";
    road = "";
    lat = "";
    long = "";

    fetch(): void {
        if ((this.userSSID == "") && (this.userMAC == "") && (this.userCC == "") && (this.userCity == "")) {
            this.msg = "Please specify at least one option...";
            this.apiResponse = false;
        } else {
            this.isLoading = true;
            this.API.request({
                module: "wigle",
                action: "search",
                user_ssid: this.userSSID,
                user_mac: this.userMAC,
                user_cc: this.userCC,
                user_city: this.userCity
            }, (response) => {
                if (response.total > 0) {
                    this.msg = response.Message;
                    this.wiglenet = response.Link;
                    this.ssid = response.SSID;
                    this.channel = response.Channel;
                    this.enc = response.Encryption;
                    this.mac = response.MAC;
                    this.dhcp = response.DHCP;
                    this.country = response.Country;
                    this.city = response.City;
                    this.road = response.Road;
                    this.lat = response.Latitude;
                    this.long = response.Longitude;
                    this.apiResponse = true;
                } else {
                    this.msg = response.Message;
                    this.wiglenet = "https://wigle.net/";
                    this.apiResponse = false;
                }
                this.isLoading = false;
            })
        }
    }

    saveKey(): void {
        this.isSubmittingKey = true;
        this.API.request({
            module: 'wigle',
            action: "save",
            user_key: this.userKey
        }, (response) => {
            if (response == "Key saved") {
                this.hasKey = true;
            } else {
                this.hasKey = false;
            }
            this.isSubmittingKey = false;
        })
    }

    checkKey(): void {
        this.API.request({
            module: 'wigle',
            action: "check"
        }, (response) => {
            if (response == "Key specified") {
                this.hasKey = true;
            } else {
                this.hasKey = false;
            }
        })
    }

    ngOnInit() {
        this.checkKey();
    }
}
