import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { speedtestComponent } from './components/speedtest.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: speedtestComponent }
];

@NgModule({
    declarations: [speedtestComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [speedtestComponent]
})
export class speedtestModule { }
