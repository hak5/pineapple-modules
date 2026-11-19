import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

/**
 * Thin wrapper around the Pineapple module API so every tab talks to the
 * Sentinel backend the same way.
 */
@Injectable({
    providedIn: 'root'
})
export class SentinelService {
    static readonly MODULE = 'Sentinel';

    constructor(private API: ApiService) { }

    request(action: string, params: any = {}): Promise<any> {
        return new Promise((resolve, reject) => {
            this.API.request(Object.assign({ module: SentinelService.MODULE, action: action }, params),
                (response: any) => {
                    if (response && response.error) {
                        reject(response.error);
                    } else {
                        resolve(response);
                    }
                });
        });
    }

    getStatus(): Promise<any> { return this.request('get_status'); }
    startEngine(): Promise<any> { return this.request('start_engine'); }
    stopEngine(): Promise<any> { return this.request('stop_engine'); }
    saveSettings(settings: any): Promise<any> { return this.request('save_settings', { settings }); }
    createMonitor(iface: string): Promise<any> { return this.request('create_monitor', { iface }); }
    clearData(): Promise<any> { return this.request('clear_data'); }
    installDependencies(): Promise<any> { return this.request('install_dependencies'); }
    pollJob(jobId: string): Promise<any> { return this.request('poll_job', { job_id: jobId }); }

    getDashboard(): Promise<any> { return this.request('get_dashboard'); }
    getChannels(window: number): Promise<any> { return this.request('get_channels', { window }); }
    getAudit(maxAgeMinutes: number): Promise<any> {
        return this.request('get_audit', { max_age_minutes: maxAgeMinutes });
    }
    getEvents(limit: number = 100): Promise<any> { return this.request('get_events', { limit }); }
    ackEvents(): Promise<any> { return this.request('ack_events'); }

    getDetection(): Promise<any> { return this.request('get_detection'); }

    setAlertMuted(kind: string, muted: boolean): Promise<any> { return this.request('set_alert_muted', { kind, muted }); }

    getMyNetworks(): Promise<any> { return this.request('get_my_networks'); }
    setMyNetwork(bssid: string, mine: boolean): Promise<any> {
        return this.request('set_my_network', { bssid, mine });
    }
    setMyNetworks(bssids: string[], mine: boolean): Promise<any> {
        return this.request('set_my_networks', { bssids, mine });
    }
    clearMyNetworks(): Promise<any> { return this.request('clear_my_networks', { confirm: true }); }
    rebaselineMyNetwork(bssid: string): Promise<any> { return this.request('rebaseline_my_network', { bssid }); }
    suggestMyNetworks(bssid: string): Promise<any> { return this.request('suggest_my_networks', { bssid }); }

    /**
     * Pineapple clock minus this computer's clock, in seconds. Timestamps come from the
     * Pineapple, whose clock can be days behind (no battery, often no Internet), so "x ago"
     * is measured on its clock. Set from each get_status answer.
     */
    static clockOffset = 0;

    static setServerTime(serverTime: number): void {
        if (typeof serverTime === 'number' && isFinite(serverTime)) {
            SentinelService.clockOffset = serverTime - Date.now() / 1000;
        }
    }

    /** Now, on the Pineapple's clock. */
    static now(): number { return Date.now() / 1000 + SentinelService.clockOffset; }

    /** Human readable "x min ago", on the Pineapple's clock. */
    static ago(ts: number): string {
        if (!ts) { return '—'; }
        const s = Math.max(0, SentinelService.now() - ts);
        if (s < 60) { return Math.round(s) + ' s ago'; }
        if (s < 3600) { return Math.round(s / 60) + ' min ago'; }
        if (s < 86400) { return Math.round(s / 3600) + ' h ago'; }
        return Math.round(s / 86400) + ' d ago';
    }

    /** "2 d 10 h behind" when the Pineapple's clock is off by more than 10 minutes, else ''. */
    static clockDrift(): string {
        const d = SentinelService.clockOffset;
        if (Math.abs(d) < 600) { return ''; }
        const a = Math.abs(d);
        const text = a >= 86400 ? Math.floor(a / 86400) + ' d ' + Math.round((a % 86400) / 3600) + ' h'
            : a >= 3600 ? Math.round(a / 3600) + ' h' : Math.round(a / 60) + ' min';
        return text + (d < 0 ? ' behind' : ' ahead');
    }
}
