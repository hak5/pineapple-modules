import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-nmap',
    templateUrl: './nmap.component.html',
    styleUrls: ['./nmap.component.css']
})
export class nmapComponent implements OnInit {
    constructor(private API: ApiService) { }

    ngOnInit() {
    }
}
