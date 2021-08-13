import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { mtrComponent } from './components/mtr.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: mtrComponent }
];

@NgModule({
    declarations: [mtrComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [mtrComponent]
})
export class mtrModule { }
