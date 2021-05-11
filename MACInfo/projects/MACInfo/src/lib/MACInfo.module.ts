import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { MACInfoComponent } from './components/MACInfo.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: MACInfoComponent }
];

@NgModule({
    declarations: [MACInfoComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [MACInfoComponent]
})
export class MACInfoModule { }
