import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../services/Sentinel.service';

interface Tab {
    id: string;
    label: string;
    soon?: boolean;
}

@Component({
    selector: 'lib-Sentinel',
    templateUrl: './Sentinel.component.html',
    styleUrls: ['./theme.css', './Sentinel.component.css']
})
export class SentinelComponent implements OnInit, AfterViewInit, OnDestroy {
    @ViewChild('root', { static: true }) root: ElementRef<HTMLElement>;
    @ViewChild('probeCard', { static: true, read: ElementRef }) probeCard: ElementRef<HTMLElement>;
    @ViewChild('probePrimary', { static: true, read: ElementRef }) probePrimary: ElementRef<HTMLElement>;

    status: any = null;
    busy = false;
    /** Status requests that failed in a row: the status on screen is then out of date. */
    failures = 0;
    tabIndex = 0;
    dark = false;
    reconHidden = readFlag(RECON_NOTE_KEY);
    private timer: any;

    readonly tabs: Tab[] = [
        { id: 'overview', label: 'Overview' },
        { id: 'channels', label: 'Channels' },
        { id: 'security', label: 'Security' },
        { id: 'wids', label: 'Detection' },
        { id: 'notifications', label: 'Notifications' },
        { id: 'reports', label: 'Reports' },
        { id: 'settings', label: 'Settings' },
    ];

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    private alive = true;

    ngOnInit(): void {
        this.refresh();
    }

    ngAfterViewInit(): void {
        setTimeout(() => this.readHostTheme());
    }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    /** How far the Pineapple's clock is from this computer's, when it matters. */
    get clockDrift(): string { return this.status ? SentinelService.clockDrift() : ''; }

    /** Unread intrusion detection alerts, shown on the Detection tab. */
    get unread(): number {
        return (this.status && this.status.wids_unread) || 0;
    }

    open(id: string): void {
        this.tabIndex = this.tabs.findIndex((t) => t.id === id);
    }

    /** One status request at a time, then the next in 10 s (audit 7.3). */
    refresh(): void {
        clearTimeout(this.timer);
        this.readHostTheme();
        this.sentinel.getStatus()
            .then((s) => {
                if (!s || typeof s !== 'object' || s.running === undefined) {
                    throw new Error('The Pineapple did not answer');
                }
                const first = !this.status;
                this.failures = 0;
                SentinelService.setServerTime(s.server_time);
                this.status = s;
                // First visit with nothing configured yet: open the settings
                if (first && !s.running && !(s.engine && s.engine.heartbeat)) {
                    this.open('settings');
                }
            })
            .catch((e) => {
                // Say it once, then let the header show that the status is out of date
                if (this.failures === 0) { this.toast(e && e.message ? e.message : e); }
                this.failures++;
            })
            .then(() => { if (this.alive) { this.timer = setTimeout(() => this.refresh(), 10000); } });
    }

    /**
     * Read the colours of the active Pineapple theme from hidden Material
     * probes, so the hand-drawn parts of Sentinel match it (light or dark).
     */
    readHostTheme(): void {
        if (!this.root || !this.probeCard || !this.probePrimary) { return; }
        const card = getComputedStyle(this.probeCard.nativeElement);
        const primary = getComputedStyle(this.probePrimary.nativeElement);
        const el = this.root.nativeElement;

        const cardBg = card.backgroundColor;
        const dark = luminance(cardBg) < 0.35;
        this.dark = dark;

        el.style.setProperty('--sn-card', cardBg);
        el.style.setProperty('--sn-text', card.color);
        // The Pineapple's dark theme has a primary colour almost the same as its cards: buttons,
        // switches and checkboxes in that colour vanish. When the contrast with the card is too
        // low, Sentinel uses the text colour instead (the "accent").
        const readable = contrast(primary.backgroundColor, cardBg) >= 3;
        const accent = readable ? primary.backgroundColor : card.color;
        el.style.setProperty('--sn-primary', accent);
        el.style.setProperty('--sn-accent', accent);
        el.style.setProperty('--sn-accent-soft', withAlpha(accent, 0.45));
        // Text on a coloured button: black or white, whichever reads on that colour
        el.style.setProperty('--sn-on-primary', luminance(accent) > 0.45 ? '#111111' : '#ffffff');
    }

    toggleEngine(): void {
        this.busy = true;
        const action = this.status && this.status.running
            ? this.sentinel.stopEngine() : this.sentinel.startEngine();
        action.then((msg) => this.toast(msg))
            .catch((e) => this.toast(e))
            .then(() => {
                this.busy = false;
                this.refresh();
                // The engine needs a few seconds to start: follow it more closely than
                // the regular 5 s refresh
                [2000, 4000, 7000].forEach((delay) => setTimeout(() => this.refresh(), delay));
            });
    }

    toast(msg: any): void {
        this.snackBar.open(String(msg), 'OK', { duration: 5000 });
    }

    /**
     * What the header shows. `lost` = the Pineapple stopped answering, so whatever
     * was on screen is no longer known to be true.
     */
    get state(): 'on' | 'wait' | 'stalled' | 'off' | 'lost' {
        if (!this.status) { return 'off'; }
        if (this.failures >= 2) { return 'lost'; }
        const backend = { listening: 'on', starting: 'wait', stalled: 'stalled', stopped: 'off' };
        return backend[this.status.state] || 'off';
    }

    /** Listening, but a radio is in error (lost adapter, stuck channel...). */
    get degraded(): boolean {
        return this.state === 'on' && this.radios.some((r) => !!r.error);
    }

    /**
     * While listening, Sentinel holds the radios Recon needs (wlan1mon, and the 5 GHz adapter it
     * takes out of managed mode): a Recon scan then misses networks (audit 3.2, tested in 0.8.0).
     */
    get sharesRecon(): boolean {
        return this.state === 'on' && !this.reconHidden;
    }

    /** The user has read the Recon warning: hide it in this browser. */
    hideReconNote(): void {
        this.reconHidden = true;
        writeFlag(RECON_NOTE_KEY);
    }

    get stateLabel(): string {
        if (!this.status) { return 'Connecting…'; }
        if (this.degraded) { return 'Listening, with a radio problem'; }
        return {
            on: 'Listening', wait: 'Starting…', stalled: 'Not responding',
            off: 'Stopped', lost: 'No answer from the Pineapple'
        }[this.state];
    }

    get stateHint(): string {
        return {
            wait: 'The engine takes a few seconds to start',
            stalled: 'The engine is running but has stopped reporting. Stop it and start again.',
            lost: 'Reload the page if this does not clear up',
        }[this.state] || 'Passive Wi-Fi monitoring';
    }

    /** Live radios as reported by the engine, only while it is known to be listening. */
    get radios(): any[] {
        const e = this.status && this.status.engine;
        if (this.state !== 'on' || !e) { return []; }
        return e.radios || (e.iface ? [{ iface: e.iface, current_channel: e.current_channel }] : []);
    }

    /** Reasons a radio cannot do its job, worth showing above the tabs. */
    get radioProblems(): string[] {
        if (!this.status || !this.status.running) { return []; }
        const warnings = this.status.radio_warnings || {};
        const shown = (this.status.engine && this.status.engine.last_error) || '';
        const fromEngine = this.radios
            .filter((r) => r.error && !warnings[r.iface] && shown.indexOf(r.error) < 0)
            .map((r) => r.error);
        return Object.keys(warnings).map((k) => warnings[k]).concat(fromEngine);
    }

    get canStart(): boolean {
        return !!this.status && !!this.status.dependencies && this.status.dependencies.sqlite;
    }
}

const RECON_NOTE_KEY = 'sentinel.reconNoteHidden';

/** A flag kept in this browser. Storage can be blocked: then the note simply shows again. */
function readFlag(key: string): boolean {
    try { return window.localStorage.getItem(key) === '1'; } catch (e) { return false; }
}

function writeFlag(key: string): void {
    try { window.localStorage.setItem(key, '1'); } catch (e) { /* not kept, nothing else to do */ }
}

/** WCAG contrast ratio (1 .. 21) between two CSS colours. */
function contrast(a: string, b: string): number {
    if (transparent(a) || transparent(b)) { return 1; }   // nothing to see: no contrast
    const la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function transparent(color: string): boolean {
    const m = (color || '').match(/[\d.]+/g);
    return !m || (m.length >= 4 && parseFloat(m[3]) < 0.1);
}

/** The same colour with another opacity, as rgba(). */
function withAlpha(color: string, alpha: number): string {
    const m = (color || '').match(/[\d.]+/g);
    return m && m.length >= 3 ? `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${alpha})` : color;
}

/** Relative luminance (0 dark .. 1 light) of a CSS rgb()/rgba() colour. */
function luminance(color: string): number {
    const m = (color || '').match(/[\d.]+/g);
    if (!m || m.length < 3) { return 1; }
    if (m.length >= 4 && parseFloat(m[3]) === 0) { return 1; }  // transparent: assume light
    const [r, g, b] = m.slice(0, 3).map((v) => {
        const c = parseFloat(v) / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
