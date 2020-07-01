import {Component, OnInit, ViewChild} from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-mdk4',
    templateUrl: './mdk4.component.html',
    styleUrls: ['./mdk4.component.css']
})
export class Mdk4Component implements OnInit {
    navLinks: any[];

    @ViewChild('rla') rla;

    constructor() {
        this.navLinks = [
            {
                label: 'Mdk4',
                link: './',
                index: 0
            },
            {
                label: 'History',
                link: './history',
                index: 1
            },
        ]
    }

    ngOnInit() {
    }
}
