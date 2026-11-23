import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Routes } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { FlexLayoutModule } from '@angular/flex-layout';

import { MaterialModule } from './modules/material/material.module';

import { SentinelComponent } from './components/Sentinel.component';
import { OverviewComponent } from './components/overview/overview.component';
import { SpectrumComponent } from './components/spectrum/spectrum.component';
import { ScoreDialComponent } from './components/score-dial/score-dial.component';
import { ChannelsComponent } from './components/channels/channels.component';
import { AuditComponent } from './components/audit/audit.component';
import { SettingsComponent } from './components/settings/settings.component';
import { ComingSoonComponent } from './components/coming-soon/coming-soon.component';
import { DetectionComponent } from './components/detection/detection.component';
import { ReportsComponent } from './components/reports/reports.component';
import { NotificationsComponent } from './components/notifications/notifications.component';
import { DependencyNoticeComponent } from './components/dependency-notice/dependency-notice.component';

const routes: Routes = [
    { path: '', component: SentinelComponent }
];

@NgModule({
    declarations: [
        SentinelComponent,
        OverviewComponent,
        SpectrumComponent,
        ScoreDialComponent,
        ChannelsComponent,
        AuditComponent,
        SettingsComponent,
        ComingSoonComponent,
        DetectionComponent,
        ReportsComponent,
        NotificationsComponent,
        DependencyNoticeComponent,
    ],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [SentinelComponent]
})
export class SentinelModule { }
