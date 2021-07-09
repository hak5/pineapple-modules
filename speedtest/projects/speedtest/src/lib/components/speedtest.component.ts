import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-speedtest',
    templateUrl: './speedtest.component.html',
    styleUrls: ['./speedtest.component.css']
})
export class speedtestComponent implements OnInit {

    constructor(private API: ApiService) { }

    poll_interval = null;
    poll_job(action: string, job_id: string): void {
        this.poll_interval = setInterval(
            () => {
                this.API.request(
                    {
                        module: 'speedtest',
                        action: action,
                        job_id: job_id
                    },
                    (response) => {
                        if (response.is_complete) {
                            if (action === 'poll_dependencies') {
                                this.check_dependencies();
                            } else if (action === 'poll_speedtest') {
                                this.speedtest_status = !this.speedtest_status;
                                this.output_speedtest();
                            }
                            clearInterval(this.poll_interval);
                        }
                    }
                )
            }, 5000
        )
    }

    network_interface : string = null;
    network_connected : boolean = null;
    network_status : boolean = false;
    check_network(): void {
        this.API.APIGet(
            '/api/settings/networking/clientmode/status',
            (response) => {
                this.network_interface = response.interfaces[0];
                this.network_connected = response.connected;
                if (response.connected) {
                    this.network_status = !this.network_status;
                }
            }
        )
    }

    dependency_python3_pip : boolean = null;
    dependency_speedtest_cli : boolean = null;
    check_dependencies(): void {
        this.API.request(
            {
                module: 'speedtest',
                action: 'check_dependencies'
            },
            (response) => {
                this.dependency_python3_pip = response.dependency_python3_pip;
                this.dependency_speedtest_cli = response.dependency_speedtest_cli;
            }
        )
    }

    dependencies_status : boolean = true;
    install_dependencies(): void {
        this.dependencies_status = !this.dependencies_status;
        this.API.request(
            {
                module: 'speedtest',
                action: 'install_dependencies'
            },
            (response) => {
                this.poll_job('poll_dependencies', response.job_id);
            }
        )
    }

    speedtest_status : boolean = true;
    output_file: string = null;
    start_speedtest(): void {
        this.speedtest_status = !this.speedtest_status;
        this.speedtest_output = null;
        this.API.request(
            {
                module: 'speedtest',
                action: 'start_speedtest'
            },
            (response) => {
                this.output_file = response.output_file;
                this.poll_job('poll_speedtest', response.job_id)
            }
        )
    }

    speedtest_output : string = null;
    output_speedtest(): void {
        this.API.request(
            {
                module: 'speedtest',
                action: 'output_speedtest',
                output_file: this.output_file
            },
            (response) => {
                this.speedtest_output = response.speedtest_output;
            }
        )
    }

    ngOnInit() {
        this.check_network();
        this.check_dependencies();
    }

    ngOnDestroy() {
        clearInterval(this.poll_interval);
    }
    
}
