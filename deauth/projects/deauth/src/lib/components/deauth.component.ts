import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-deauth',
    templateUrl: './deauth.component.html',
    styleUrls: ['./deauth.component.css']
})
export class deauthComponent implements OnInit {
    constructor(private API: ApiService) { }

    deauth_stats: boolean = false;
    deauth_actions: boolean = false;
    deauth_status: boolean = false;

    previous_scans = [];
    get_previous_scans(): void {
        this.API.APIGet(
            '/api/recon/scans',
            (response) => {
                if (Array.isArray(response)) {
                    this.previous_scans = response;
                }
            }
        );
    }

    accessPoints_clients: any[];
    clients: number;
    check_previous_scan(event: any): void {
        let selected_scan = this.previous_scans.find(
            previous_scan => (previous_scan.date === event.target.value)
        );
        this.API.APIGet(
            ('/api/recon/scans/' + selected_scan.scan_id),
            (response) => {
                if (response.APResults.length > 0) {
                    this.accessPoints_clients = [];
                    this.clients = 0;
                    response.APResults.forEach(
                        (ap: { encryption: number; clients: string | any[]; }) => {
                            if (ap.encryption !== 0 && Array.isArray(ap.clients)) {
                                this.accessPoints_clients.push(ap);
                                this.clients += ap.clients.length;
                            }
                        }
                    );
                    if (this.accessPoints_clients.length > 0) {
                        this.deauth_stats = true;
                        this.deauth_actions = true;
                    }

                }
            }
        );
        
    }

    accessPoints_deauthed: any[];
    deauth_all(): void {
        this.accessPoints_clients.forEach(
            (ap) => {
                this.accessPoints_deauthed = [];

                let clients_mac = [];
                ap.clients.forEach(
                    (client) => {
                        clients_mac.push(client.client_mac)
                    }
                )
                this.API.APIPost(
                    '/api/pineap/deauth/ap',
                    JSON.stringify({
                        "bssid":ap.bssid,
                        "multiplier":7,
                        "channel":ap.channel,
                        "clients":clients_mac
                    }),
                    (response) => {
                        if (response.success) {
                            this.accessPoints_deauthed.push(ap.ssid);
                            this.deauth_status = true;
                        }
                    }
                );
            }
        );
    }

    ngOnInit() {
        this.get_previous_scans();
    }
}
