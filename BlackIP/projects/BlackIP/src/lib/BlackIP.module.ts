import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { BlackIPComponent } from './components/BlackIP.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: BlackIPComponent }
];

@NgModule({
    declarations: [BlackIPComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [BlackIPComponent]
})
export class BlackIPModule { }
