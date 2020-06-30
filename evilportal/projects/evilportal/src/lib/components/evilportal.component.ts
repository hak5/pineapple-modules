import {Component, OnDestroy, OnInit} from '@angular/core';
import { ApiService } from '../services/api.service';
import {ErrorDialogComponent} from "./helpers/error-dialog/error-dialog.component";
import {MatDialog} from "@angular/material/dialog";
import {JobResultDTO} from "../interfaces/jobresult.interface";
import {PortalInfoDTO} from "../interfaces/portalinfo.interface";
import {ControlState} from "../interfaces/controlstate.interface";
import {NewPortalDialogComponent} from "./helpers/new-portal-dialog/new-portal-dialog.component";
import {PreviewDialogComponent} from "./helpers/preview-dialog/preview-dialog.component";
import {ConfirmationDialogComponent} from "./helpers/confirmation-dialog/confirmation-dialog.component";
import {DirectoryDTO} from "../interfaces/directorydto.interface";
import {WorkBenchState} from "../interfaces/workbenchstate.interface";
import {LibraryState} from "../interfaces/librarystate.interface";
import {EditFileDialogComponent} from "./helpers/edit-file-dialog/edit-file-dialog.component";
import {RuleEditorDialogComponent} from "./helpers/rule-editor-dialog/rule-editor-dialog.component";
import {ClientListState} from "../interfaces/clientliststate.interface";
import {UninstallDialogComponent} from "./helpers/uninstall-dialog/uninstall-dialog.component";

@Component({
    selector: 'lib-evilportal',
    templateUrl: './evilportal.component.html',
    styleUrls: ['./evilportal.component.css']
})
export class EvilPortalComponent implements OnInit, OnDestroy {

    public controlState: ControlState = { isBusy: false, running: false, autoStart: false };
    public permanentClientState: ClientListState = { isBusy: false, clients: '', selected: ''};
    public allowedClientState: ClientListState = { isBusy: false, clients: '', selected: ''};
    public libraryState: LibraryState = { showLibrary: true, isBusy: false, portals: [] };
    public workbenchState: WorkBenchState = { isBusy: false, portal: null, dirContents: [], inRoot: true, rootDirectory: null };

    public hasDependencies: boolean = true;
    public isInstalling: boolean = false;
    private backgroundJobInterval = null;

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    private handleError(msg: string): void {
        this.dialog.closeAll();
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '500px',
            data: {
                message: msg
            }
        });
    }

    private pollBackgroundJob<T>(jobId: string, onComplete: (result: JobResultDTO<T>) => void, onInterval?: Function): void {
        this.backgroundJobInterval = setInterval(() => {
            this.API.request({
                module: 'evilportal',
                action: 'poll_job',
                job_id: jobId
            }, (response: JobResultDTO<T>) => {
                if (response.is_complete) {
                    onComplete(response);
                    clearInterval(this.backgroundJobInterval);
                } else if (onInterval) {
                    onInterval();
                }
            });
        }, 5000);
    }

    private delete(path: string, onSuccess: () => void): void {
        this.API.request({
            module: 'evilportal',
            action: 'delete',
            file_path: path
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }

            console.log('CALLING CALLBACK!');
            onSuccess();
        });
    }

    private monitorDependencies(jobId: string) {
        this.isInstalling = true;
        this.pollBackgroundJob(jobId, (result: JobResultDTO<boolean>) => {
            this.isInstalling = false;
            if (result.job_error !== null) {
                this.handleError(result.job_error);
            }
            this.checkForDependencies();
        });
    }

    private loadDirectoryContent(path: string, onSuccess: (data: Array<DirectoryDTO>) => void) {
        this.API.request({
            module: 'evilportal',
            action: 'load_directory',
            path: path
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }

            onSuccess(response);
        });
    }

    private loadFile(path: string, onComplete: (success: boolean, content: string, error: string) => void) {
        this.API.request({
            module: 'evilportal',
            action: 'load_file',
            path: path
        }, (response) => {
            if (response.error !== undefined) {
                onComplete(false, undefined, response.error);
                return
            }
            onComplete(true, response, undefined);
        });
    }

    showPreviewDialog(): void {
        this.dialog.open(PreviewDialogComponent, {
            hasBackdrop: true,
            data: {}
        });
    }

    togglePortal(portalName: string): void {
        this.libraryState.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'toggle_portal',
            portal: portalName
        }, (response) => {
            this.libraryState.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.loadPortals();
        });
    }

    createPortal(portalName: string, portalType: string): void {
        this.libraryState.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'new_portal',
            name: portalName,
            type: portalType
        }, (response) => {
            this.libraryState.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.loadPortals();
        });
    }

    showDeleteItemDialog(path: string): void {
        this.dialog.open(ConfirmationDialogComponent, {
            hasBackdrop: true,
            width: '500px',
            data: {
                title: "Delete",
                message: "Are you sure you want to delete this this? This action can not be undone.",
                handleResponse: (affimative: boolean) => {
                    if (affimative) {
                        this.workbenchState.isBusy = true;
                        this.delete(path, () => {
                            this.loadPortal(this.workbenchState.portal);
                        });
                    }
                }
            }
        });
    }

    showDeletePortalDialog(path: string): void {
        this.dialog.open(ConfirmationDialogComponent, {
            hasBackdrop: true,
            width: '500px',
            data: {
                title: "Delete Portal?",
                message: "Are you sure you want to delete this portal? This action can not be undone.",
                handleResponse: (affimative: boolean) => {
                    if (affimative) {
                        this.libraryState.isBusy = true;
                        this.delete(path, () => {
                            this.loadPortals();
                        });
                    }
                }
            }
        });
    }

    showNewPortalDialog(): void {
        this.dialog.open(NewPortalDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                onCreate: (portalName: string, portalType: string) => {
                    this.createPortal(portalName, portalType);
                    this.dialog.closeAll();
                }
            }
        });
    }

    editFile(portal: PortalInfoDTO, fileName = null, readonly = false): void {
        this.dialog.open(EditFileDialogComponent, {
            hasBackdrop: true,
            width: '900px',
            data: {
                readonly: readonly,
                path: portal.location,
                fileName: fileName,
                isNew: fileName == null,
                onSaved: () => {
                    this.loadPortal(this.workbenchState.portal);
                }
            }
        });
    }

    showPortalRules(portal: PortalInfoDTO): void {
        this.dialog.open(RuleEditorDialogComponent, {
            hasBackdrop: true,
            data: {
                portal: portal.title
            }
        });
    }

    toggleEvilPortal(): void {
        this.controlState.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'toggle_evilportal'
        }, (response) => {
            this.controlState.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response.error)
                return;
            }

            this.loadControlState();
        });
    }

    loadPortal(portal: PortalInfoDTO): void {
        this.workbenchState.isBusy = true;
        this.loadDirectoryContent(portal.location, (data) => {
            this.workbenchState = {
                isBusy: false,
                portal: portal,
                dirContents: data,
                inRoot: true,
                rootDirectory: portal.location
            };
            this.libraryState.showLibrary = false;
        });
    }

    loadPortals(): void {
        this.libraryState.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'list_portals'
        }, (response) => {
            this.libraryState.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.libraryState.portals = response;
        })
    }

    loadAllowedClients(): void {
        this.allowedClientState.isBusy = true;
        this.loadFile('/tmp/EVILPORTAL_CLIENTS.txt', (success, content, error) => {
            this.allowedClientState.isBusy = false;
            if (!success) {
                return;
            }
            this.allowedClientState.clients = content;
        });
    }

    loadControlState(): void {
        this.controlState.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'status'
        }, (response) => {
            this.controlState.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }

            this.controlState = {
                isBusy: false,
                running: response.running,
                autoStart: response.start_on_boot
            }
        })
    }

    showUninstallDependencies(): void {
        this.dialog.open(UninstallDialogComponent, {
            disableClose: true,
            hasBackdrop: true,
            width: '700px',
            data: {
                onComplete: () => {
                    this.checkForDependencies();
                }
            }
        })
    }

    installDependencies(): void {
        this.API.request({
            module: 'evilportal',
            action: 'manage_dependencies',
            install: true
        }, (response) => {
            if (response.error !== undefined && response.error !== null) {
                this.handleError(response.error);
                return;
            }

            this.monitorDependencies(response.job_id);
        });
    }

    checkForDependencies(): void {
        this.API.request({
            module: 'evilportal',
            action: 'check_dependencies'
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response.error);
                return;
            }
            this.hasDependencies = response;
        });
    }

    ngOnInit() {
        this.checkForDependencies();
        this.loadControlState();
        this.loadPortals();
        this.loadAllowedClients();
    }

    ngOnDestroy() {
        clearInterval(this.backgroundJobInterval);
    }
}
