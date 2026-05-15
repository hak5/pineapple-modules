import {Component, OnDestroy, OnInit} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {ApiService} from '../services/api.service';
import {ErrorDialogComponent} from './helpers/error-dialog/error-dialog.component';
import {ConfirmDialogComponent} from './helpers/confirm-dialog/confirm-dialog.component';
import {NewSiteDialogComponent} from './helpers/new-site-dialog/new-site-dialog.component';
import {EditFileDialogComponent} from './helpers/edit-file-dialog/edit-file-dialog.component';
import {DuplicateSiteDialogComponent} from './helpers/duplicate-site-dialog/duplicate-site-dialog.component';
import {RenameSiteDialogComponent} from './helpers/rename-site-dialog/rename-site-dialog.component';

interface SiteInfo {
    name: string;
    hostname: string;
    php: boolean;
    enabled: boolean;
    aliases: string[];
}

interface FileInfo {
    name: string;
    path: string;
    is_dir: boolean;
    size: number;
}

interface ControlState {
    isBusy: boolean;
    running: boolean;
    phpRunning: boolean;
    startAtBoot: boolean;
}

interface LibraryState {
    isBusy: boolean;
    sites: SiteInfo[];
    showLibrary: boolean;
}

interface WorkbenchState {
    isBusy: boolean;
    site: SiteInfo | null;
    files: FileInfo[];
    currentPath: string;
}

interface CredentialEntry {
    site: string;
    timestamp: string;
    ip: string;
    username: string;
    password: string;
}

interface MonitorState {
    isBusy: boolean;
    show: boolean;
    tab: number;
    logSite: string;
    log: string;
    credentials: CredentialEntry[];
}

@Component({
    selector: 'lib-webserver',
    templateUrl: './webserver.component.html',
    styleUrls: ['./webserver.component.css']
})
export class WebserverComponent implements OnInit, OnDestroy {

    public hasDependencies = false;
    public isInstalling    = false;

    public controlState:   ControlState   = {isBusy: false, running: false, phpRunning: false, startAtBoot: false};
    public libraryState:   LibraryState   = {isBusy: false, sites: [], showLibrary: true};
    public workbenchState: WorkbenchState = {isBusy: false, site: null, files: [], currentPath: ''};
    public monitorState:   MonitorState   = {isBusy: false, show: false, tab: 0, logSite: '', log: '', credentials: []};
    public siteStats: {[key: string]: number} = {};

    private backgroundJobInterval: any = null;
    private monitorInterval: any       = null;

    constructor(private API: ApiService, private dialog: MatDialog) {}

    // ── Dependencies ─────────────────────────────────────────────────────────

    private pollBackgroundJob(jobId: string, onComplete: (result: any) => void): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({module: 'webserver', action: 'poll_job', job_id: jobId}, (response) => {
                if (response.is_complete) {
                    clearInterval(this.backgroundJobInterval);
                    onComplete(response);
                }
            });
        }, 5000);
    }

    checkForDependencies(): void {
        this.API.request({module: 'webserver', action: 'check_dependencies'}, (response) => {
            if (response.error !== undefined) { this.hasDependencies = false; return; }
            this.hasDependencies = response.installed;
            if (this.hasDependencies) { this.loadStatus(); }
        });
    }

    installDependencies(): void {
        this.isInstalling = true;
        this.API.request({module: 'webserver', action: 'manage_dependencies'}, (response) => {
            if (response.error !== undefined) { this.isInstalling = false; this.handleError(response.error); return; }
            this.pollBackgroundJob(response.job_id, (result) => {
                this.isInstalling = false;
                if (result.job_error) { this.handleError('Installation failed: ' + result.job_error); return; }
                this.checkForDependencies();
            });
        });
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private handleError(msg: string): void {
        this.dialog.closeAll();
        this.dialog.open(ErrorDialogComponent, {hasBackdrop: true, width: '500px', data: {message: msg}});
    }

    // ── Web server controls ───────────────────────────────────────────────────

    loadStatus(): void {
        this.controlState.isBusy = true;
        this.API.request({module: 'webserver', action: 'status'}, (response) => {
            this.controlState.isBusy = false;
            if (response.error !== undefined) { this.handleError(response.error); return; }
            this.controlState.running    = response.nginx_running;
            this.controlState.phpRunning = response.php_running;
            this.controlState.startAtBoot = response.start_at_boot || false;
            this.libraryState.sites      = response.sites || [];
            this.loadStats();
        });
    }

    toggleWebserver(): void {
        this.controlState.isBusy = true;
        this.API.request({module: 'webserver', action: 'toggle_webserver'}, (response) => {
            this.controlState.isBusy = false;
            if (response.error !== undefined) { this.handleError(response.error); return; }
            this.loadStatus();
        });
    }

    toggleStartAtBoot(enabled: boolean): void {
        this.API.request({module: 'webserver', action: 'set_start_at_boot', enabled}, (response) => {
            if (response.error !== undefined) { this.handleError(response.error); this.loadStatus(); return; }
            this.controlState.startAtBoot = response.start_at_boot;
        });
    }

    reloadWebserver(): void {
        this.controlState.isBusy = true;
        this.API.request({module: 'webserver', action: 'reload_webserver'}, (response) => {
            this.controlState.isBusy = false;
            if (response.error !== undefined) { this.handleError(response.error); return; }
            if (!response.success) { this.handleError('Reload failed. Is the web server running?'); }
        });
    }

    // ── Site management ───────────────────────────────────────────────────────

    toggleSite(site: SiteInfo): void {
        this.libraryState.isBusy = true;
        const action = site.enabled ? 'disable_site' : 'enable_site';
        this.API.request({module: 'webserver', action, site_name: site.name}, (response) => {
            this.libraryState.isBusy = false;
            if (response.error !== undefined) { this.handleError(response.error); return; }
            this.loadStatus();
        });
    }

    showNewSiteDialog(): void {
        this.dialog.open(NewSiteDialogComponent, {
            hasBackdrop: true, width: '520px',
            data: {
                onCreate: (siteName: string, hostname: string, php: boolean, template: string, aliases: string[]) => {
                    this.libraryState.isBusy = true;
                    this.API.request(
                        {module: 'webserver', action: 'create_site', site_name: siteName, hostname, php, template, aliases},
                        (response) => {
                            this.libraryState.isBusy = false;
                            if (response.error !== undefined) { this.handleError(response.error); return; }
                            this.dialog.closeAll();
                            this.loadStatus();
                        }
                    );
                }
            }
        });
    }

    showDeleteSiteDialog(site: SiteInfo): void {
        this.dialog.open(ConfirmDialogComponent, {
            hasBackdrop: true, width: '400px',
            data: {
                title: 'Delete Site',
                message: `Delete "${site.name}"? This cannot be undone.`,
                handleResponse: (confirmed: boolean) => {
                    if (!confirmed) { return; }
                    this.libraryState.isBusy = true;
                    this.API.request(
                        {module: 'webserver', action: 'delete_site', site_name: site.name},
                        (response) => {
                            this.libraryState.isBusy = false;
                            if (response.error !== undefined) { this.handleError(response.error); return; }
                            this.loadStatus();
                        }
                    );
                }
            }
        });
    }

    showDuplicateSiteDialog(site: SiteInfo): void {
        this.dialog.open(DuplicateSiteDialogComponent, {
            hasBackdrop: true, width: '440px',
            data: {
                sourceName: site.name,
                onDuplicate: (newName: string, newHostname: string) => {
                    this.libraryState.isBusy = true;
                    this.API.request(
                        {module: 'webserver', action: 'duplicate_site',
                         source_name: site.name, site_name: newName, hostname: newHostname},
                        (response) => {
                            this.libraryState.isBusy = false;
                            if (response.error !== undefined) { this.handleError(response.error); return; }
                            this.dialog.closeAll();
                            this.loadStatus();
                        }
                    );
                }
            }
        });
    }

    showRenameSiteDialog(site: SiteInfo): void {
        this.dialog.open(RenameSiteDialogComponent, {
            hasBackdrop: true, width: '480px',
            data: {
                site,
                onRename: (newName: string, newHostname: string, aliases: string[]) => {
                    this.libraryState.isBusy = true;
                    this.API.request(
                        {module: 'webserver', action: 'rename_site',
                         site_name: site.name, new_name: newName, new_hostname: newHostname, aliases},
                        (response) => {
                            this.libraryState.isBusy = false;
                            if (response.error !== undefined) { this.handleError(response.error); return; }
                            this.dialog.closeAll();
                            if (this.workbenchState.site?.name === site.name) {
                                this.libraryState.showLibrary = true;
                            }
                            this.loadStatus();
                        }
                    );
                }
            }
        });
    }

    // ── Workbench ─────────────────────────────────────────────────────────────

    openWorkbench(site: SiteInfo): void {
        this.workbenchState = {isBusy: true, site, files: [], currentPath: ''};
        this.libraryState.showLibrary = false;
        this.loadDirectory('');
    }

    loadDirectory(path: string): void {
        this.workbenchState.isBusy = true;
        this.API.request(
            {module: 'webserver', action: 'load_directory', site_name: this.workbenchState.site!.name, path},
            (response) => {
                this.workbenchState.isBusy = false;
                if (response.error !== undefined) { this.handleError(response.error); return; }
                this.workbenchState.files       = response.files;
                this.workbenchState.currentPath = response.path;
            }
        );
    }

    navigateUp(): void {
        const parts = this.workbenchState.currentPath.split('/').filter(p => p);
        parts.pop();
        this.loadDirectory(parts.join('/'));
    }

    openFileEditor(file: FileInfo | null): void {
        const isNew = file === null;
        if (!isNew && file!.is_dir) { this.loadDirectory(file!.path); return; }
        this.dialog.open(EditFileDialogComponent, {
            hasBackdrop: true, width: '900px',
            data: {
                siteName: this.workbenchState.site!.name,
                filePath: isNew ? null : file!.path,
                basePath: this.workbenchState.currentPath,
                isNew,
                onSaved: () => { this.loadDirectory(this.workbenchState.currentPath); }
            }
        });
    }

    uploadFile(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (!input.files || !input.files.length) { return; }
        const file   = input.files[0];
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = reader.result as string;
            const b64     = dataUrl.substring(dataUrl.indexOf(',') + 1);
            const filePath = this.workbenchState.currentPath
                ? `${this.workbenchState.currentPath}/${file.name}`
                : file.name;
            this.workbenchState.isBusy = true;
            this.API.request(
                {module: 'webserver', action: 'upload_file',
                 site_name: this.workbenchState.site!.name, file_path: filePath, content_b64: b64},
                (response) => {
                    this.workbenchState.isBusy = false;
                    (event.target as HTMLInputElement).value = '';
                    if (response.error !== undefined) { this.handleError(response.error); return; }
                    this.loadDirectory(this.workbenchState.currentPath);
                }
            );
        };
        reader.readAsDataURL(file);
    }

    showDeleteFileDialog(file: FileInfo): void {
        this.dialog.open(ConfirmDialogComponent, {
            hasBackdrop: true, width: '400px',
            data: {
                title: 'Delete',
                message: `Delete "${file.name}"? This cannot be undone.`,
                handleResponse: (confirmed: boolean) => {
                    if (!confirmed) { return; }
                    this.workbenchState.isBusy = true;
                    this.API.request(
                        {module: 'webserver', action: 'delete_file',
                         site_name: this.workbenchState.site!.name, file_path: file.path},
                        (response) => {
                            this.workbenchState.isBusy = false;
                            if (response.error !== undefined) { this.handleError(response.error); return; }
                            this.loadDirectory(this.workbenchState.currentPath);
                        }
                    );
                }
            }
        });
    }

    // ── Monitor ───────────────────────────────────────────────────────────────

    toggleMonitor(): void {
        this.monitorState.show = !this.monitorState.show;
        if (this.monitorState.show) {
            this.onMonitorTabChange(this.monitorState.tab);
            this.monitorInterval = setInterval(() => {
                if (!this.monitorState.show) { return; }
                if (this.monitorState.tab === 1) { this.loadAccessLog(); }
                if (this.monitorState.tab === 2) { this.loadCredentials(); }
            }, 10000);
        } else {
            clearInterval(this.monitorInterval);
            this.monitorInterval = null;
        }
    }

    onMonitorTabChange(index: number): void {
        this.monitorState.tab = index;
        if (index === 0) { this.loadStats(); }
        if (index === 1) { this.loadAccessLog(); }
        if (index === 2) { this.loadCredentials(); }
    }

    loadStats(): void {
        this.API.request({module: 'webserver', action: 'get_stats'}, (response) => {
            if (response.error === undefined) { this.siteStats = response.stats || {}; }
        });
    }

    loadAccessLog(): void {
        this.monitorState.isBusy = true;
        this.API.request(
            {module: 'webserver', action: 'get_access_log',
             site_name: this.monitorState.logSite, lines: 100},
            (response) => {
                this.monitorState.isBusy = false;
                if (response.error === undefined) { this.monitorState.log = response.log || ''; }
            }
        );
    }

    loadCredentials(): void {
        this.monitorState.isBusy = true;
        this.API.request({module: 'webserver', action: 'get_credentials'}, (response) => {
            this.monitorState.isBusy = false;
            if (response.error === undefined) {
                this.monitorState.credentials = response.credentials || [];
            }
        });
    }

    clearCredentials(): void {
        this.dialog.open(ConfirmDialogComponent, {
            hasBackdrop: true, width: '400px',
            data: {
                title: 'Clear Credentials',
                message: 'Delete all harvested credentials? This cannot be undone.',
                handleResponse: (confirmed: boolean) => {
                    if (!confirmed) { return; }
                    this.API.request({module: 'webserver', action: 'clear_credentials'}, (response) => {
                        if (response.error === undefined) { this.monitorState.credentials = []; }
                    });
                }
            }
        });
    }

    // ── Utils ─────────────────────────────────────────────────────────────────

    formatSize(bytes: number): string {
        if (bytes === 0) { return '—'; }
        if (bytes < 1024) { return bytes + ' B'; }
        if (bytes < 1048576) { return (bytes / 1024).toFixed(1) + ' KB'; }
        return (bytes / 1048576).toFixed(1) + ' MB';
    }

    ngOnInit(): void { this.checkForDependencies(); }

    ngOnDestroy(): void {
        clearInterval(this.backgroundJobInterval);
        clearInterval(this.monitorInterval);
    }
}
