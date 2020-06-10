import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';
import {MatDialog} from "@angular/material/dialog";
import {ErrorDialogComponent} from "../helpers/error-dialog/error-dialog.component";
import {DisplayModel} from "../interfaces/displaymodel.interface";

@Component({
    selector: 'lib-httpeek',
    templateUrl: './httpeek.component.html',
    styleUrls: ['./httpeek.component.css']
})
export class HTTPeekComponent implements OnInit {
    public isBusy: boolean = false;
    public snifferEnabled: boolean = false;
    public listening: boolean = false;
    public websocket: WebSocket = null;

    public urls: Array<DisplayModel> = [];
    public images: Array<DisplayModel> = [];
    public cookies: Array<DisplayModel> = [];
    public postData: Array<DisplayModel> = [];

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    private handleError(msg: string) {
        this.dialog.closeAll();
        this.dialog.open(ErrorDialogComponent, {
            width: '400px',
            hasBackdrop: true,
            data: msg
        });
    }

    private createWebsocket(component: HTTPeekComponent): void {
        if (this.websocket !== null) {
            this.stopWebsocket();
        }

        component.isBusy = true;
        component.websocket = new WebSocket("ws://" + window.location.hostname + ":9999/");

        component.websocket.onerror = function() {
            component.websocket.onclose = (function() {});
            component.stopWebsocket();
            component.startWebsocket();
        };

        component.websocket.onopen = function() {
            component.listening = true;
            component.isBusy = false;
        };

        component.websocket.onclose = function() {
            component.isBusy = false;
            component.listening = false;
        };

        component.websocket.onmessage = function(message) {
            let data = JSON.parse(message.data);

            if (data['image'] !== undefined) {
                component.images.unshift({
                    client: data['from'],
                    data: data['image']
                });
            } else {
                component.urls.unshift({
                    client: data['from'],
                    data: encodeURI(data['url'])
                });
            }

            if (data['cookie'] !== undefined) {
                component.cookies.unshift({
                    client: data['from'],
                    data: data['cookie']
                });
            }

            if (data['post'] !== undefined) {
                component.postData.unshift({
                    client: data['from'],
                    data: data['post']
                });
            }
        };
    }

    startWebsocket(): void {
        this.createWebsocket(this);
    }

    stopWebsocket(): void {
        if (this.websocket !== null) {
            this.websocket.onclose = (function() {});
            this.websocket.close();
            this.websocket = null;
        }
        this.listening = false;
    }

    loadStatus(): void {
        this.isBusy = true;
        this.API.request({
            module: 'httpeek',
            action: 'status'
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response);
                return;
            }

            this.snifferEnabled = response;
        });
    }

    toggleSniffer(enable: boolean): void {
        this.isBusy = true;

        this.API.request({
            module: 'httpeek',
            action: 'toggle',
            enable: enable
        }, (response) => {
            this.isBusy = false;
            this.loadStatus();
            if (response.error !== undefined) {
                this.handleError(response);
                return;
            }

            if (!enable) {
                this.stopWebsocket();
            }
        });
    }

    ngOnInit() {
        this.loadStatus();
    }

    ngOnDestroy() {
        this.stopWebsocket();
    }
}
