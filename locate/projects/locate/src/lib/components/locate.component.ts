import { Component, OnInit } from "@angular/core";
import { ApiService } from "../services/api.service";

@Component({
    selector: "lib-locate",
    templateUrl: "./locate.component.html",
    styleUrls: ["./locate.component.css"],
})
export class locateComponent implements OnInit {
    constructor(private API: ApiService) {}

    userInput = "";
    iplocation = "";
    isLoading: boolean = false;

    lookup_ip = "";
    city = "";
    region = "";
    country = "";
    country_name = "";
    country_capital = "";
    timezone = "";
    languages = "";
    calling_code = "";
    postal = "";
    org = "";
    cordinates = "";
    validIP: boolean = true;
    noip = "";

    locate_ip(): void {
        this.isLoading = true;
        this.API.request(
            {
                module: "locate",
                action: "locate_ip",
                user_input: this.userInput,
            },
            (response) => {
                this.isLoading = false;
                this.iplocation = response.iplocation;
                this.lookup_ip = response.lookup_ip;
                this.city = response.city;
                this.region = response.region;
                this.country = response.country;
                this.postal = response.postal;
                this.country_capital = response.country_capital;
                this.timezone = response.timezone;
                this.calling_code = response.calling_code;
                this.languages = response.languages;
                this.org = response.org;
                this.cordinates = response.cordinates;
                this.noip = response.noip;
                if (this.noip =="Not a valid IP address!"){
                    this.validIP = false;
                }
            }
        );
    }
    ngOnInit() {}
}
