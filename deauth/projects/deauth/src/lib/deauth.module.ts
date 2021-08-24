import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { deauthComponent } from './components/deauth.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: deauthComponent }
];

@NgModule({
    declarations: [deauthComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [deauthComponent]
})
export class deauthModule { }
