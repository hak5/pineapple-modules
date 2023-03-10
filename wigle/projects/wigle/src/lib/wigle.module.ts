import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { wigleComponent } from './components/wigle.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: wigleComponent }
];

@NgModule({
    declarations: [wigleComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [wigleComponent]
})
export class wigleModule { }
