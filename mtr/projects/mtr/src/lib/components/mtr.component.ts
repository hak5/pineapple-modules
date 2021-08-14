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
    src = "";
    dst = "";

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
                this.getoutput();
                console.log("MTR has finished.");
            },
            () => {
                console.log("MTR still running..");
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
                console.log(response.report);
                this.hubs = response.report.hubs;
                this.dst = response.report.mtr.dst;
                this.src = response.report.mtr.src;
                console.log(this.hubs);
                console.log(this.src);
                console.log(this.dst);
                // response.report.hubs.forEach(thing=>console.log(thing.host))
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
