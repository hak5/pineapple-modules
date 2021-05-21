import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { MACInfoComponent } from './components/MACInfo.component';
import { MACInfoOfflineComponent } from './components/subviews/macinfo-offline/macinfo-offline.component';
import { MACInfoOnlineComponent } from './components/subviews/macinfo-online/macinfo-online.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    {
        path: '',
        component: MACInfoComponent,
        children: [
            { path: '', component: MACInfoOfflineComponent, pathMatch: 'full' },
            { path: 'online', component: MACInfoOnlineComponent }
        ]
    }
];

@NgModule({
    declarations: [
        MACInfoComponent,
        MACInfoOfflineComponent,
        MACInfoOnlineComponent
    ],
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
