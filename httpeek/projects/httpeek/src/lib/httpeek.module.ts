import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { HTTPeekComponent } from './components/httpeek.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import {ErrorDialogComponent} from "./helpers/error-dialog/error-dialog.component";

const routes: Routes = [
    { path: '', component: HTTPeekComponent }
];

@NgModule({
    declarations: [HTTPeekComponent, ErrorDialogComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule
    ],
    exports: [HTTPeekComponent],
    entryComponents: [ErrorDialogComponent]
})
export class httpeekModule { }
