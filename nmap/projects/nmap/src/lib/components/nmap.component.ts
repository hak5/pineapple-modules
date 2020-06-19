import {Component, OnInit, ViewChild} from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-nmap',
    templateUrl: './nmap.component.html',
    styleUrls: ['./nmap.component.css']
})
export class NmapComponent implements OnInit {
    navLinks: any[];

    @ViewChild('rla') rla;

    constructor() {
        this.navLinks = [
            {
                label: 'Nmap',
                link: './',
                index: 0
            },
            {
                label: 'History',
                link: './history',
                index: 1
            },
        ];
    }

    ngOnInit() {
    }
}
