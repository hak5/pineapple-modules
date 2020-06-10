import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";
import {ApiService} from "../../../services/api.service";

@Component({
    selector: 'lib-rule-editor-dialog',
    templateUrl: './rule-editor-dialog.component.html',
    styleUrls: ['./rule-editor-dialog.component.css']
})
export class RuleEditorDialogComponent implements OnInit {

    constructor(public dialogRef: MatDialogRef<RuleEditorDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private API: ApiService) {
    }

    public isBusy: boolean = false;
    public workingRules = {};
    public ruleData = {};

    closeDialog(): void {
        this.dialogRef.close();
    }

    deleteObject(rule, specifier, index): void {
        console.log('RULE: ' + JSON.stringify(rule) + ' | ' + JSON.stringify(specifier) + ' | ' + index);
        console.log('DELETE: ' + JSON.stringify(this.workingRules[rule][specifier][index]));
        delete this.workingRules[rule][specifier][index];
    }

    insertRule(rule, specifier): void {
        if (this.workingRules[rule][specifier] === undefined) {
            this.workingRules[rule][specifier] = {};
        }

        let highest = 0;

        for (let i in this.workingRules[rule][specifier]) {
            if (parseInt(i) >= highest) {
                highest = parseInt(i) + 1;
            }
        }

        this.workingRules[rule][specifier][highest] = {'key': '', 'destination': ''};
    }

    isObjectEmpty(obj): boolean {
        return (Object.keys(obj).length === 0);
    }

    stringify(obj): string {
        return JSON.stringify(obj);
    }

    loadRules(): void {
        this.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'get_portal_rules',
            portal: this.data.portal
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                console.log('ERROR: ' + response.error);
                return;
            }

            let x = false;
            for (let key in response) {
                // we then create the a object with that key name in our workingData object
                this.workingRules[key] = {};

                // Now its time to loop over each category specifier such as "exact" and "regex"
                for (let specifier in response[key]) {
                    let index = 0;

                    // We then create that specifier in our workingData
                    this.workingRules[key][specifier] = {};

                    // finally we loop over the specific rules defined in the specifier
                    for (let r in response[key][specifier]) {
                        let obj = {};
                        obj['key'] = r;
                        obj['destination'] = response[key][specifier][r];
                        this.workingRules[key][specifier][index] = obj;
                        index++;
                    }
                }
            }
            this.ruleData = response;
        });
    }

    saveRules(): void {
        for (let key in this.ruleData) {
            for (let specifier in this.ruleData[key]) {
                let obj = {};
                for (let i in this.workingRules[key][specifier]) {
                    let rule_key = this.workingRules[key][specifier][i]['key'];
                    let rule_dst = this.workingRules[key][specifier][i]['destination'];

                    if (rule_key === undefined || rule_key === '' || rule_dst === undefined || rule_dst === '') {
                        continue;
                    }

                    obj[rule_key] = rule_dst;
                }
                this.ruleData[key][specifier] = obj;
            }
        }

        this.isBusy = true;
        this.API.request({
            module: 'evilportal',
            action: 'save_portal_rules',
            portal: this.data.portal,
            rules: this.ruleData
        }, (response) => {
            this.isBusy = false;
            if (response.error !== undefined) {
                console.log('ERROR: ' + response.error);
                return;
            }

            this.closeDialog();
        });
    }

    ngOnInit(): void {
        this.loadRules();
    }

}
