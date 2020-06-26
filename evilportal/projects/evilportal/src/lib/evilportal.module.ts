import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { EvilPortalComponent } from './components/evilportal.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';

const routes: Routes = [
    { path: '', component: EvilPortalComponent }
];

@NgModule({
    declarations: [EvilPortalComponent, ErrorDialogComponent],
    imports: [
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        CommonModule,
    ],
    exports: [EvilPortalComponent],
    entryComponents: [
        ErrorDialogComponent
    ]
})
export class evilportalModule { }
