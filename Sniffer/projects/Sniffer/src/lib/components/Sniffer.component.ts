import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-Sniffer',
    templateUrl: './Sniffer.component.html',
    styleUrls: ['./Sniffer.component.css']
})
export class SnifferComponent implements OnInit {

    public isBusy: boolean = false;
    public snifferEnabled: boolean = false;
    public listening: boolean = false;
    public websocket: WebSocket = null;


    constructor(private API: ApiService) { }

    private handleError(msg: string) {
        console.log('ERROR: ' + msg);
    }

    private createWebsocket(component: SnifferComponent): void {
        component.isBusy = true;
        component.websocket = new WebSocket("ws://" + window.location.hostname + ":9999/");

        component.websocket.onerror = (function() {
            component.websocket.onclose = (function() {});
            console.log('WEBSOCKET ERROR!!!');
            component.startWebsocket();
        });

        component.websocket.onopen = (function() {
            component.websocket.onerror = (function(){
                console.log('WEBSOCKET ERROR 2!!!');
            });
            component.listening = true;
            component.isBusy = false;
        });

        component.websocket.onclose = (function() {
            console.log('WEBSOCKET CLOSED!');
            component.isBusy = false;
            component.listening = false;
        });

        component.websocket.onmessage = (function(message) {
            console.log('GOT MESSAGE!');
            let data = JSON.parse(message.data);
            console.log(data);

            // if (data['image'] !== undefined) {
            //     $("#img_container").prepend('<img src="' + encodeURI(data['image']) +'">');
            // } else {
            //     $("#url_table").prepend("<tr><td>" + data['from'] + "</td><td></td></tr>").children().first().children().last().text(data['url']);
            // }
            // if (data['cookie'] !== undefined) {
            //     $("#cookie_table").prepend("<tr><td>" + data['from'] + "</td><td></td></tr>").children().first().children().last().text(data['cookie']);
            // }
            // if (data['post'] !== undefined) {
            //     $("#post_table").prepend("<tr><td>" + data['from'] + "</td><td></td></tr>").children().first().children().last().text(data['post']);
            // }
        });
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
            module: 'Sniffer',
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
            module: 'Sniffer',
            action: 'toggle',
            enable: enable
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                this.handleError(response);
                return;
            }
            this.loadStatus();
        });
    }

    setup(): void {
        this.API.request({
            module: 'Sniffer',
            action: 'setup'
        }, (response) => {
            if (response.error !== undefined) {
                this.handleError(response);
                return;
            }
            this.loadStatus();
        });
    }

    ngOnInit() {
        this.setup();
    }
}
