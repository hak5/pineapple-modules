import { Component, OnInit } from "@angular/core";
import { ApiService } from "../services/api.service";
import { JobResultDTO } from "../interfaces/jobresult.interface";

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
    backgroundJobInterval = null;
    fileoutput = "";

    pollBackgroundJob<T>(
        jobId: string,
        onComplete: (result: JobResultDTO<T>) => void,
        onInterval?: Function
    ): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request(
                {
                    module: "mtr",
                    action: "poll_job",
                    job_id: jobId,
                },
                (response: JobResultDTO<T>) => {
                    if (response.is_complete) {
                        onComplete(response);
                        clearInterval(this.backgroundJobInterval);
                    } else if (onInterval) {
                        onInterval();
                    }
                }
            );
        }, 2000);
    }
    private monitormtr(jobId: string): void {
        this.isLoading = true;
        this.pollBackgroundJob(
            jobId,
            (result: JobResultDTO<boolean>) => {
                this.isLoading = false;
                // this.getScanOutput(this.scanOutputFileName);
                this.getoutput()
                console.log("Finished");
            },
            () => {
                console.log("Not finished");
            }
        );
    }

    getoutput(): void {
        this.API.request(
            {
                module: "mtr",
                action: "load_output",
            },
            (response) => {
                this.fileoutput = response;
                console.log(this.fileoutput)
            }
        );
    }

    startmtr(): void {
        this.isLoading = true;
        this.API.request(
            {
                module: "mtr",
                action: "startmtr",
                user_input: this.userInput,
            },
            (response) => {
                this.monitormtr(response.job_id);
            }
        );
    }

    ngOnInit() {}
}
