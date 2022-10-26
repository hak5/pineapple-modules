import { Component, OnInit } from '@angular/core';
import { Handshake } from '../model/handshake';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-wpasec',
    templateUrl: './wpasec.component.html',
    styleUrls: ['./wpasec.component.css']
})
export class wpasecComponent implements OnInit {
    constructor(private API: ApiService) { }

    apiResponse = '';
    apiKey = '';

    handshakes: Handshake[] = [];
    submitted_handshakes: Handshake[] = [];

    selection: Handshake[] = [];
    displayedColumns = ['select', 'mac', 'client', 'timestamp'];
    expandedLesson: Handshake | null;

    saveApiKey(): void {
        this.API.request({
            module: 'wpasec',
            action: 'save_api_key',
            api_key: this.apiKey
        }, (response) => {
            this.apiResponse = JSON.stringify(response);
        });
    }

    toggleArrayItem(array: any[], item: any) {
        const index = array.indexOf(item);
        if (index > -1) {
            array.splice(index, 1);
        } else {
            array.push(item);
        }
    }

    onLessonToggled(lesson: Handshake) {
        this.toggleArrayItem(this.selection, lesson);
        console.log(this.selection);
    }

    onToggleLesson(lesson: Handshake) {
        console.log(lesson);
    }

    isAllSelected() {
        return this.selection.length == this.handshakes.length;
    }

    toggleAll() {
        if (this.isAllSelected()) {
            this.selection = [];
        }
        else {
            this.selection = this.handshakes.slice();
        }
    }

    getWpaHandshakes(): void {
        this.API.APIGet(
            '/api/pineap/handshakes',
            (response) => {
                this.handshakes = response.handshakes;
            }
        )
    }

    submitWpaHandshakes(): void {
        this.API.request({
            module: 'wpasec',
            action: 'submit_handshakes',
            handshakes: this.selection
        }, (response) => {
            this.apiResponse = JSON.stringify(response);
        });
    }

    ngOnInit() {
        this.API.request({
            module: 'wpasec',
            action: 'get_api_key'
        }, (response) => {
            if (response.api_key)
                this.apiKey = response.api_key;
        });
        
        this.getWpaHandshakes();
        //this.getSubmittedHandshakes();
        // Filter out already submitted handshakes from the table
        //this.handshakes = this.handshakes.filter(n => !this.submitted_handshakes.includes(n));
    }
}
