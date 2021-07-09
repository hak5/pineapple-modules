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
    country_neighbours = "";
    country_phone = "";
    country_flag = "";
    org = "";
    coordinates = "";
    validIP: boolean = true;

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
                this.country_neighbours = response.country_neighbours;
                this.country_capital = response.country_capital;
                this.timezone = response.timezone;
                this.country_phone = response.country_phone;
                this.country_flag = response.country_flag;
                this.org = response.org;
                this.coordinates = response.coordinates;
                if (response.error){
                    this.validIP = false;
                }
            }
        );
    }
    ngOnInit() {}
}
