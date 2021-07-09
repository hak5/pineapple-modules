import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { locateComponent } from './components/locate.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: locateComponent }
];

@NgModule({
    declarations: [locateComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [locateComponent]
})
export class locateModule { }
