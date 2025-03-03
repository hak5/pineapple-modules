import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-Modlishka',
    templateUrl: './Modlishka.component.html',
    styleUrls: ['./Modlishka.component.css']
})
export class ModlishkaComponent implements OnInit {
    constructor(private API: ApiService) { }

    userInput = '';
    apiResponse = 'nothing...';
    configData = '';
    modlishkaLog = '';
    dnsData = '';

    getModlishkaLogs():void {
      this.API.request({
        module: 'Modlishka',
        action: 'get_log'
      }, (response) => {
        this.modlishkaLog = response;
      });
    }

    runModlishka():void {
      this.API.request({
        module: 'Modlishka',
        action: 'run_modlishka'
      }, (response) => {
        this.apiResponse = response;
      });
    }

    stopModlishka():void {
      this.API.request({
        module: 'Modlishka',
        action: 'stop_modlishka'
      }, (response) => {
        this.apiResponse = response;
      });
    }

    setConfig(): void {
      this.API.request({
        module: 'Modlishka',
        action: 'set_config',
        data: this.configData
      }, (response) => {
        this.apiResponse = response;
      });
    }

    setDnsConfig(): void {
      this.API.request({
        module: 'Modlishka',
        action: 'set_dns_config',
        data: this.dnsData
      }, (response) => {
        this.apiResponse = response;
      });
    }

    ngOnInit() {
      this.API.request({
        module: 'Modlishka',
        action: 'get_config'
      }, (response) => {
        this.configData = response;
        console.log('setting data to');
        console.log(response);
      });
      this.API.request({
        module: 'Modlishka',
        action: 'get_dns_config'
      }, (response) => {
        this.dnsData= response;
      });
      this.API.request({
        module: 'Modlishka',
        action: 'get_log'
      }, (response) => {
        this.modlishkaLog = response;
      });
    }
}
