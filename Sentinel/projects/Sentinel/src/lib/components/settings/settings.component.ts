import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

const CH_24 = [1, 6, 11, 2, 7, 3, 8, 4, 9, 5, 10];
const CH_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165];
const CH_5_DFS = [52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144];
// Every 5 GHz channel in frequency order (listening on DFS channels is receive-only)
const CH_5_ALL = CH_5.concat(CH_5_DFS).sort((a, b) => a - b);

@Component({
    selector: 'lib-sentinel-settings',
    templateUrl: './settings.component.html',
    styleUrls: ['../theme.css', './settings.component.css']
})
export class SettingsComponent implements OnChanges {
    @Input() status: any;
    @Output() changed = new EventEmitter<void>();

    form: any = null;
    channelText: string[] = ['', ''];
    saving = false;

    readonly presets = [
        { label: '2.4 GHz', channels: CH_24 },
        { label: '5 GHz, all channels', channels: CH_5_ALL },
        { label: '5 GHz without DFS', channels: CH_5 },
        { label: 'Both bands', channels: CH_24.concat(CH_5_ALL) },
    ];

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnChanges(changes: SimpleChanges): void {
        // Fill the form once, so the 5 s status refresh never erases what is being typed
        if (changes.status && this.status && !this.form) {
            this.resetForm(this.status.settings);
        }
    }

    private resetForm(settings: any): void {
        this.form = JSON.parse(JSON.stringify(settings));
        this.channelText = this.form.radios.map((r) => (r.channels || []).join(', '));
    }

    get interfaces(): any[] {
        return (this.status && this.status.interfaces) || [];
    }

    iface(name: string): any {
        return this.interfaces.find((i) => i.name === name);
    }

    bandsLabel(i: any): string {
        if (!i || !i.bands || !i.bands.length) { return ''; }
        return i.bands.join(' and ') + ' GHz';
    }

    /** A radio able to do 5 GHz that is not used yet: probably the 5 GHz extension. */
    get fiveGhzSuggestion(): any {
        if (!this.form) { return null; }
        const used = this.form.radios.filter((r) => r.enabled).map((r) => r.iface);
        const candidates = this.interfaces.filter((i) => (i.bands || []).indexOf('5') >= 0);
        // Prefer an interface already in monitor mode, then its managed parent
        const pick = candidates.find((i) => i.monitor && used.indexOf(i.name) < 0)
            || candidates.find((i) => !i.monitor && used.indexOf(i.name) < 0
                && used.indexOf(i.name + 'mon') < 0 && !this.iface(i.name + 'mon'));
        return pick || null;
    }

    useSuggestion(): void {
        const s = this.fiveGhzSuggestion;
        const radio = this.form.radios[1];
        radio.enabled = true;
        radio.hopping = true;
        this.channelText[1] = CH_5_ALL.join(', ');
        if (s.monitor) {
            radio.iface = s.name;
            return;
        }
        this.sentinel.createMonitor(s.name).then((r) => {
            radio.iface = r.iface;
            this.toast(`${r.iface} is ready. Save the settings to start capturing 5 GHz.`);
            this.changed.emit();
        }).catch((e) => this.toast(e));
    }

    createMonitor(index: number): void {
        const radio = this.form.radios[index];
        this.sentinel.createMonitor(radio.iface).then((r) => {
            radio.iface = r.iface;
            this.toast(`${r.iface} is ready in monitor mode.`);
            this.changed.emit();
        }).catch((e) => this.toast(e));
    }

    /** '2.4' for a radio that only receives 2.4 GHz, '5' when it receives 5 GHz, '' when unknown. */
    radioKind(name: string): string {
        const it = name ? this.iface(name) : null;
        const bands = (it && it.bands) || [];
        if (bands.indexOf('5') >= 0) { return '5'; }
        return bands.indexOf('2.4') >= 0 ? '2.4' : '';
    }

    parentOf(name: string): string {
        return name && name.slice(-3) === 'mon' ? name.slice(0, -3) : name;
    }

    /** Only the presets this radio can use: no 5 GHz buttons on a 2.4 GHz-only radio. */
    presetsFor(name: string): any[] {
        return this.radioKind(name) === '2.4' ? this.presets.filter((p) => p.channels.every((c) => c <= 14)) : this.presets;
    }

    has5Channels(index: number): boolean {
        return (this.channelText[index] || '').split(/[\s,]+/).some((c) => +c >= 32);
    }

    applyPreset(index: number, channels: number[]): void {
        this.channelText[index] = channels.join(', ');
    }

    save(): void {
        const settings = JSON.parse(JSON.stringify(this.form));
        settings.radios.forEach((r, i) => {
            r.channels = (this.channelText[i] || '').split(/[\s,;]+/)
                .map((c) => parseInt(c, 10)).filter((c) => !isNaN(c));
        });
        this.saving = true;
        this.sentinel.saveSettings(settings)
            .then((r) => {
                this.resetForm(r.settings);
                this.toast(r.restarted ? 'Settings saved. Monitoring restarted.' : 'Settings saved.');
                this.changed.emit();
            })
            .catch((e) => this.toast(e))
            .then(() => this.saving = false);
    }

    clearData(): void {
        if (!confirm('Clear everything Sentinel has collected? Your settings are kept.')) { return; }
        this.sentinel.clearData().then((m) => { this.toast(m); this.changed.emit(); })
            .catch((e) => this.toast(e));
    }

    radioStatus(index: number): any {
        const e = this.status && this.status.engine;
        const name = this.form && this.form.radios[index].iface;
        if (!e || !e.radios || !this.status.running) { return null; }
        return e.radios.find((r) => r.iface === name) || null;
    }

    /** Why this radio cannot change channel, as found when monitoring started. */
    radioWarning(index: number): string {
        const warnings = (this.status && this.status.radio_warnings) || {};
        return warnings[this.form.radios[index].iface] || '';
    }

    toast(msg: any): void {
        this.snackBar.open(String(msg), 'OK', { duration: 5000 });
    }
}
