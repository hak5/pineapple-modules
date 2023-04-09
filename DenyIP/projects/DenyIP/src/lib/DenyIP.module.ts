import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { DenyIPComponent } from './components/DenyIP.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: DenyIPComponent }
];

@NgModule({
    declarations: [DenyIPComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [DenyIPComponent]
})
export class DenyIPModule { }
