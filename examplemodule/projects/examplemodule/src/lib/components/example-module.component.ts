import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-example-module',
    templateUrl: './example-module.component.html',
    styleUrls: ['./example-module.component.css']
})
export class ExampleModuleComponent implements OnInit {
    constructor(private API: ApiService) { }

    ngOnInit() {
    }
}
