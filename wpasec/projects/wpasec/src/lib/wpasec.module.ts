import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { wpasecComponent } from './components/wpasec.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: wpasecComponent }
];

@NgModule({
    declarations: [wpasecComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [wpasecComponent]
})
export class wpasecModule { }
