import { Component, Input, OnInit } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

/** Alerts sent to a phone through ntfy (assets/engine/notify.py). */
@Component({
    selector: 'lib-sentinel-notifications',
    templateUrl: './notifications.component.html',
    styleUrls: ['../theme.css', './notifications.component.css']
})
export class NotificationsComponent implements OnInit {
    @Input() status: any;

    form: any = null;
    token = '';
    clearToken = false;
    busy = false;
    readonly severities = [
        { value: 'critical', label: 'Critical only' },
        { value: 'high', label: 'High and critical' },
        { value: 'medium', label: 'Medium, high and critical' },
    ];

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnInit(): void {
        this.sentinel.getNotify().then((n) => { this.form = n; }).catch((e) => this.toast(e));
    }

    get sendError(): string {
        return (this.status && this.status.engine && this.status.engine.notify_error) || '';
    }

    get publicServer(): boolean {
        return !!this.form && /^https:\/\/ntfy\.sh\/?$/.test(this.form.server || '');
    }

    /** A topic hard to guess: on ntfy.sh anyone who knows a topic can read it. */
    randomTopic(): void {
        const bytes = new Uint8Array(6);
        window.crypto.getRandomValues(bytes);
        this.form.topic = 'sentinel-' + Array.prototype.map.call(bytes, (b: number) => ('0' + b.toString(16)).slice(-2)).join('');
    }

    save(): Promise<boolean> {
        this.busy = true;
        const settings = Object.assign({}, this.form, { token: this.token, clear_token: this.clearToken });
        delete settings.has_token;
        return this.sentinel.saveNotify(settings).then((n) => {
            this.form = n;
            this.token = '';
            this.clearToken = false;
            this.toast('Saved');
            return true;
        }).catch((e) => { this.toast(e); return false; }).then((ok) => { this.busy = false; return ok; });
    }

    test(): void {
        this.save().then((ok) => {
            if (!ok) { return; }
            this.busy = true;
            this.sentinel.testNotify()
                .then(() => this.toast('Test message sent. Check your phone.'))
                .catch((e) => this.toast(e))
                .then(() => { this.busy = false; });
        });
    }

    toast(msg: any): void { this.snackBar.open(String(msg), 'OK', { duration: 6000 }); }
}
