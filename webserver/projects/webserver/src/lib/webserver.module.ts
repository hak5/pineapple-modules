import {NgModule} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {RouterModule, ROUTES} from '@angular/router';
import {FlexLayoutModule} from '@angular/flex-layout';

import {MaterialModule} from './modules/material/material.module';
import {WebserverComponent} from './components/webserver.component';
import {ErrorDialogComponent} from './components/helpers/error-dialog/error-dialog.component';
import {ConfirmDialogComponent} from './components/helpers/confirm-dialog/confirm-dialog.component';
import {NewSiteDialogComponent} from './components/helpers/new-site-dialog/new-site-dialog.component';
import {EditFileDialogComponent} from './components/helpers/edit-file-dialog/edit-file-dialog.component';
import {DuplicateSiteDialogComponent} from './components/helpers/duplicate-site-dialog/duplicate-site-dialog.component';
import {RenameSiteDialogComponent} from './components/helpers/rename-site-dialog/rename-site-dialog.component';

@NgModule({
    declarations: [
        WebserverComponent,
        ErrorDialogComponent,
        ConfirmDialogComponent,
        NewSiteDialogComponent,
        EditFileDialogComponent,
        DuplicateSiteDialogComponent,
        RenameSiteDialogComponent,
    ],
    imports: [
        RouterModule,
        MaterialModule,
        FlexLayoutModule,
        CommonModule,
        FormsModule,
    ],
    exports: [WebserverComponent],
    entryComponents: [
        WebserverComponent,
        ErrorDialogComponent,
        ConfirmDialogComponent,
        NewSiteDialogComponent,
        EditFileDialogComponent,
        DuplicateSiteDialogComponent,
        RenameSiteDialogComponent,
    ],
    providers: [
        {provide: ROUTES, useValue: [{path: '', component: WebserverComponent}], multi: true}
    ]
})
export class webserverModule {}
