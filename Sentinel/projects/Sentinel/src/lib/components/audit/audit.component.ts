import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

@Component({
    selector: 'lib-sentinel-audit',
    templateUrl: './audit.component.html',
    styleUrls: ['../theme.css', './audit.component.css']
})
export class AuditComponent implements OnInit, OnDestroy {
    @Input() status: any;

    audit: any = null;
    maxAge = 60;
    gradeFilter = 'all';
    search = '';
    expanded: { [bssid: string]: boolean } = {};
    /** Access points that probably belong to the network just marked, none ticked by default. */
    suggestions: any[] = [];
    suggestedFor = '';
    picked: { [bssid: string]: boolean } = {};
    private timer: any;
    private alive = true;
    readonly every = 30;
    updated: Date = null;

    readonly ages = [
        { value: 15, label: '15 min' },
        { value: 60, label: '1 h' },
        { value: 1440, label: '24 h' },
    ];
    readonly grades = ['critical', 'high', 'medium', 'low', 'good'];
    readonly gradeLabels = {
        critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Note', good: 'Good'
    };

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnInit(): void {
        this.load();
    }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    setAge(a: number): void {
        this.maxAge = a;
        this.load();
    }

    /** One request at a time: the next one is scheduled when this one answers (audit 7.3). */
    load(): void {
        clearTimeout(this.timer);
        this.sentinel.getAudit(this.maxAge).then((a) => { this.audit = a; this.updated = new Date(); }).catch(() => { })
            .then(() => { if (this.alive) { this.timer = setTimeout(() => this.load(), this.every * 1000); } });
    }

    /** The gauge shows your networks once at least one is marked. */
    get dialScore(): number { return this.audit && this.audit.my_total ? this.audit.my_score : this.audit && this.audit.score; }
    get dialTitle(): string { return this.audit && this.audit.my_total ? 'Your networks' : 'Neighbourhood'; }

    toggleMine(n: any, event: Event): void {
        event.stopPropagation();  // the star sits in the panel header: do not expand it
        const mine = !n.mine;
        this.sentinel.setMyNetwork(n.bssid, mine).then(() => {
            this.toast(mine ? 'Marked as your network' : 'Removed from your networks');
            if (mine) { this.suggest(n); }
            this.load();
        }).catch((e) => this.toast(e));
    }

    suggest(n: any): void {
        this.sentinel.suggestMyNetworks(n.bssid).then((r) => {
            this.suggestions = r.suggestions || [];
            this.suggestedFor = n.ssid || n.bssid;
            this.picked = {};
        }).catch(() => this.suggestions = []);
    }

    get pickedCount(): number { return this.suggestions.filter((s) => this.picked[s.bssid]).length; }

    get allPicked(): boolean { return this.suggestions.length > 0 && this.pickedCount === this.suggestions.length; }

    /** Tick every suggestion, or untick them all when they are all ticked. */
    toggleAllPicked(): void {
        const tick = !this.allPicked;
        this.picked = {};
        if (tick) { this.suggestions.forEach((s) => this.picked[s.bssid] = true); }
    }

    /** The star at the top of the list: state of the networks shown. */
    get shownMarked(): number { return this.networks.filter((n) => n.mine).length; }

    get masterIcon(): string {
        const shown = this.networks.length, marked = this.shownMarked;
        return marked === 0 ? 'star_border' : marked === shown ? 'star' : 'star_half';
    }

    /**
     * Mark every network shown, or unmark them when they are all marked. Shown means after
     * the search and the filters: search for your network's name first, then use this star.
     */
    toggleAllShown(): void {
        const shown = this.networks;
        if (!shown.length) { return; }
        const unmark = this.shownMarked === shown.length;
        const targets = shown.filter((n) => n.mine === unmark).map((n) => n.bssid).slice(0, 64);
        const question = unmark
            ? 'Remove the star from the ' + targets.length + ' network(s) shown?'
            : 'Mark the ' + targets.length + ' network(s) shown as yours? Only if they are all yours: '
              + 'a neighbour marked by mistake would hide an imitation of it. Tip: search for your network\'s name first.';
        if (!window.confirm(question)) { return; }
        this.sentinel.setMyNetworks(targets, !unmark).then((r) => {
            const refused = (r && r.refused) || [];
            this.toast(unmark ? targets.length + ' network(s) unmarked'
                : (targets.length - refused.length) + ' network(s) marked'
                  + (refused.length ? ', ' + refused.length + ' not seen enough yet' : ''));
            this.suggestions = [];
            this.load();
        }).catch((e) => this.toast(e));
    }

    addPicked(): void {
        const chosen = this.suggestions.filter((s) => this.picked[s.bssid]);
        chosen.reduce((p, s) => p.then(() => this.sentinel.setMyNetwork(s.bssid, true)), Promise.resolve())
            .then(() => this.toast(chosen.length + ' access point(s) added to your networks'))
            .catch((e) => this.toast(e))
            .then(() => { this.suggestions = []; this.load(); });
    }

    dismissSuggestions(): void { this.suggestions = []; }

    rebaseline(n: any): void {
        this.sentinel.rebaselineMyNetwork(n.bssid)
            .then(() => this.toast('Current settings accepted as the reference'))
            .catch((e) => this.toast(e));
    }

    toast(msg: any): void { this.snackBar.open(String(msg), 'OK', { duration: 5000 }); }

    get networks(): any[] {
        if (!this.audit) { return []; }
        const q = this.search.trim().toLowerCase();
        return this.audit.networks.filter((n) =>
            (this.gradeFilter === 'all' || (this.gradeFilter === 'mine' ? n.mine : n.grade === this.gradeFilter)) &&
            (!q || (n.ssid || '').toLowerCase().includes(q) || n.bssid.includes(q)));
    }

    pmfShare(kind: string): number {
        if (!this.audit || !this.audit.total) { return 0; }
        return 100 * (this.audit.pmf[kind] || 0) / this.audit.total;
    }

    pmfLabel(pmf: string): string {
        return { required: 'required', capable: 'optional', none: 'missing' }[pmf] || pmf;
    }

    toggleGrade(g: string): void {
        this.gradeFilter = this.gradeFilter === g ? 'all' : g;
    }

    toggle(n: any): void {
        this.expanded[n.bssid] = !this.expanded[n.bssid];
    }

    /** 0 to 4 bars, like a phone's signal indicator. */
    bars(rssi: number): number {
        if (rssi === null || rssi === undefined) { return 0; }
        if (rssi >= -55) { return 4; }
        if (rssi >= -67) { return 3; }
        if (rssi >= -78) { return 2; }
        return 1;
    }

    ago(ts: number): string { return SentinelService.ago(ts); }

    trackNet(_: number, n: any): string { return n.bssid; }
}
