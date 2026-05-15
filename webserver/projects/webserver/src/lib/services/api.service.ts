import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Router} from '@angular/router';

@Injectable({
    providedIn: 'root'
})
export class ApiService {
    public static totalRequests = 0;
    apiModuleBusy = document.getElementById('ApiModuleBusy');

    constructor(private http: HttpClient, private router: Router) {}

    emptyResponse = {error: 'Request returned empty response'};

    unauth(): void {
        localStorage.removeItem('authToken');
        if (this.router.url !== '/Login' && this.router.url !== '/Setup') {
            this.router.navigateByUrl('/Login');
        }
    }

    setBusy(): void { this.apiModuleBusy.style.display = 'block'; }
    setNotBusy(): void { this.apiModuleBusy.style.display = 'none'; }

    static extractBaseHref(): string {
        if (window['_app_base']) {
            if (window['_app_base'].endsWith('/')) {
                return window['_app_base'].slice(0, -1);
            }
        }
        return window['_app_base'] || '';
    }

    request(payload: any, callback: (any) => void) {
        this.setBusy();
        let resp;

        this.http.post(`${ApiService.extractBaseHref()}/api/module/request`, payload).subscribe(
            (r: any) => {
                if (r === undefined || r === null) {
                    resp = this.emptyResponse;
                } else if (r.error) {
                    resp = r;
                } else {
                    resp = r.payload;
                }
            },
            (err) => {
                resp = err.error;
                if (err.status === 401) { this.unauth(); }
                this.setNotBusy();
                callback(resp);
            },
            () => {
                this.setNotBusy();
                callback(resp);
            }
        );
        ApiService.totalRequests++;
    }

    APIDownload(fullpath: string, filename: string): void {
        this.http.post(`${ApiService.extractBaseHref()}/api/download`, {filename: fullpath}, {responseType: 'blob'})
            .subscribe((r) => {
                const url = window.URL.createObjectURL(r);
                const a = document.createElement('a');
                document.body.appendChild(a);
                a.setAttribute('style', 'display: none');
                a.href = url;
                a.download = filename;
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            });
    }
}
