import { Component, OnDestroy, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-PineappleTAK',
    templateUrl: './PineappleTAK.component.html',
    styleUrls: ['./PineappleTAK.component.css']
})
export class PineappleTAKComponent implements OnInit, OnDestroy {
    status: any = null;
    busy = false;
    message = '';
    messageOk = true;
    password = '';
    password2 = '';
    listen = '';
    private timer: any = null;

    constructor(private API: ApiService) { }

    ngOnInit(): void {
        this.refresh();
        this.timer = setInterval(() => { if (!this.busy) { this.refresh(); } }, 5000);
    }

    ngOnDestroy(): void {
        clearInterval(this.timer);
    }

    private call(action: string, extra: any, done?: (resp: any) => void): void {
        this.API.request(Object.assign({ module: 'PineappleTAK', action }, extra || {}), (resp) => {
            if (done) { done(resp); }
        });
    }

    refresh(): void {
        this.call('status', {}, (resp) => {
            if (resp && !resp.error) {
                this.status = resp;
                if (!this.listen) { this.listen = resp.listen || 'all'; }
            }
        });
    }

    private act(action: string, extra?: any): void {
        this.busy = true;
        this.message = '';
        this.call(action, extra, (resp) => {
            this.busy = false;
            this.messageOk = !(resp && resp.error);
            this.message = resp && resp.error ? resp.error : (typeof resp === 'string' ? resp : 'Done');
            this.refresh();
        });
    }

    install(): void { this.act('install'); }
    service(op: string): void { this.act('service', { op }); }
    toggleBoot(on: boolean): void { this.service(on ? 'enable' : 'disable'); }

    setPassword(): void {
        if (this.password.length < 8) { this.messageOk = false; this.message = 'Use at least 8 characters'; return; }
        if (this.password !== this.password2) { this.messageOk = false; this.message = 'The two passwords do not match'; return; }
        this.act('set_password', { password: this.password });
        this.password = '';
        this.password2 = '';
    }

    setListen(): void { this.act('set_listen', { mode: this.listen }); }

    // Opens the console on the same host name or IP as this Pineapple page, so it works however you reached the Pineapple
    get openUrl(): string {
        if (!this.status) { return ''; }
        if (this.status.listen === 'all' && window.location.hostname) {
            return this.status.scheme + '://' + window.location.hostname + ':' + this.status.port;
        }
        return this.status.urls[0];
    }

    uninstall(): void {
        if (confirm('Remove PineappleTAK? Your settings, certificates and loot are kept for a reinstall.')) {
            this.act('uninstall', { keep_data: true });
        }
    }

    get updateAvailable(): boolean {
        return !!this.status && this.status.installed && !!this.status.module_version &&
            this.status.module_version !== this.status.service_version;
    }

    get linkText(): string {
        if (!this.status || !this.status.running) { return 'Stopped'; }
        if (this.status.setup_mode) { return 'Waiting for setup in the console'; }
        const l = this.status.link;
        return l === 'connected' ? 'Connected to the TAK Server' : l === 'connecting' ? 'Connecting to the TAK Server' :
            l === 'disconnected' ? 'Not connected to the TAK Server' : 'Starting';
    }

    get linkClass(): string {
        if (!this.status || !this.status.running) { return 'off'; }
        return this.status.link === 'connected' ? 'ok' : this.status.link === 'disconnected' ? 'bad' : 'wait';
    }
}
