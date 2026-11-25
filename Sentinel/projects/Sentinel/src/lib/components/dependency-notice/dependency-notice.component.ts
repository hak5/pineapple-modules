import { Component, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

/**
 * The python3-sqlite3 dependency, above every tab: missing (a click installs it),
 * installing, failed (with the reason), and any warning left by the install.
 */
@Component({
    selector: 'lib-sentinel-dependency-notice',
    templateUrl: './dependency-notice.component.html',
    styleUrls: ['../theme.css', './dependency-notice.component.css']
})
export class DependencyNoticeComponent implements OnDestroy {
    @Input() status: any;
    @Output() changed = new EventEmitter<void>();

    clicked = false;
    private timer: any;
    private alive = true;

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnDestroy(): void {
        this.alive = false;
        clearTimeout(this.timer);
    }

    get deps(): any { return (this.status && this.status.dependencies) || {}; }

    get state(): string {
        if (this.clicked && this.deps.state !== 'ok' && this.deps.state !== 'failed') { return 'installing'; }
        return this.deps.state || (this.deps.sqlite === false ? 'missing' : 'ok');
    }

    install(): void {
        this.clicked = true;
        this.sentinel.installDependencies()
            .then((r) => this.follow(r.job_id))
            .catch((e) => { this.clicked = false; this.toast(e); this.changed.emit(); });
    }

    /** Follow the opkg job: one request at a time, then the next (audit 7.3). */
    private follow(jobId: string): void {
        if (!this.alive || !jobId) { return; }
        this.sentinel.pollJob(jobId).then((job) => {
            if (job && job.is_complete) {
                this.clicked = false;
                this.toast(job.job_error ? job.job_error : 'python3-sqlite3 installed');
                this.changed.emit();
                return;
            }
            this.timer = setTimeout(() => this.follow(jobId), 3000);
        }).catch(() => { this.clicked = false; this.changed.emit(); });
    }

    toast(msg: any): void { this.snackBar.open(String(msg), 'OK', { duration: 6000 }); }
}
