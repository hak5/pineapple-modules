import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ProxyHelper2Component } from './components/ProxyHelper2.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: ProxyHelper2Component }
];

@NgModule({
    declarations: [ProxyHelper2Component],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [ProxyHelper2Component]
})
export class ProxyHelper2Module { }
