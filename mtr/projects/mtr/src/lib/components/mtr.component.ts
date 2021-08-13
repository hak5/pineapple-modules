import { Component, OnInit } from "@angular/core";
import { ApiService } from "../services/api.service";

@Component({
    selector: "lib-mtr",
    templateUrl: "./mtr.component.html",
    styleUrls: ["./mtr.component.css"],
})
export class mtrComponent implements OnInit {
    constructor(private API: ApiService) {}

    userInput = "";
    isLoading: boolean = false;
    commandfinished: boolean = false;
    hubs = "";

    startmtr(): void {
        this.isLoading = true;
        this.API.request(
            {
                module: "mtr",
                action: "startmtr",
                user_input: this.userInput,
            },
            (response) => {
                this.commandfinished = response.commandfinished;
                if ( this.commandfinished === false ) {
                        console.log("Command has finished.")
                }
                this.isLoading = false;
                this.hubs = response.hubs;
                console.log(this.hubs);
            }
        );
    }

    ngOnInit() {}
}
