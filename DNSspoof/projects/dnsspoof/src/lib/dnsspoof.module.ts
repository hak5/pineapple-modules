import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { dnsspoofComponent } from './components/dnsspoof.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: dnsspoofComponent }
];

@NgModule({
    declarations: [dnsspoofComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [dnsspoofComponent]
})
export class dnsspoofModule { }
