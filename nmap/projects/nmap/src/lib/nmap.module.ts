import { NgModule } from '@angular/core';
import { nmapComponent } from './components/nmap.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

const routes: Routes = [
    { path: '', component: nmapComponent }
];

@NgModule({
    declarations: [nmapComponent],
    imports: [
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule
    ],
    exports: [nmapComponent]
})
export class nmapModule { }
