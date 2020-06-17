import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Router} from '@angular/router';

@Injectable({
    providedIn: 'root'
})
export class ApiService {
    public static totalRequests = 0;

    constructor(private http: HttpClient,
                private router: Router) {}

    emptyResponse = {error: 'Request returned empty response'};

    unauth(): void {
        localStorage.removeItem('authToken');

        if (this.router.url !== '/Login' && this.router.url !== '/Setup') {
            this.router.navigateByUrl('/Login');
        }
    }

    request(payload: any, callback: (any) => void) {
        let resp;

        this.http.post('/api/module/request', payload).subscribe((r: any) => {
            if (r === undefined || r === null) {
                resp = this.emptyResponse;
            }

            if (r.payload) {
                resp = r.payload;
            } else {
                resp = r;
            }
        }, (err) => {
            resp = err.error;
            if (err.status === 401) {
                this.unauth();
            }
            callback(resp);
        }, () => {
            callback(resp);
        });

        ApiService.totalRequests++;
    }

    APIGet(path: string, callback: (any) => void): any {
        ApiService.totalRequests++;

        let resp;

        this.http.get(path).subscribe((r) => {
            if (r === undefined || r === null) {
                r = this.emptyResponse;
            }
            resp = r;
        }, (err) => {
            resp = err.error;
            if (err.status === 401) {
                this.unauth();
            }
            callback(resp);
        }, () => {
            callback(resp);
        });
    }

    async APIGetAsync(path: string): Promise<any> {
        ApiService.totalRequests++;

        return await this.http.get(path).toPromise();
    }

    APIPut(path: string, body: any, callback: (any) => void): any {
        ApiService.totalRequests++;

        let resp;

        this.http.put(path, body).subscribe((r) => {
            if (r === undefined || r === null) {
                r = this.emptyResponse;
            }
            resp = r;
        }, (err) => {
            resp = err.error;
            if (err.status === 401) {
                this.unauth();
            }
            callback(resp);
        }, () => {
            callback(resp);
        });
    }

    async APIPutAsync(path: string, body: any): Promise<any> {
        return await this.http.put(path, body).toPromise();
    }

    APIPost(path: string, body: any, callback: (any) => void): any {
        ApiService.totalRequests++;

        let resp;

        this.http.post(path, body).subscribe((r) => {
            if (r === undefined || r === null) {
                resp = this.emptyResponse;
            }
            resp = r;
        }, (err) => {
            resp = err.error;
            if (err.status === 401) {
                this.unauth();
            }
            callback(resp);
        }, () => {
            callback(resp);
        });
    }

    async APIPostAsync(path: string, body: any): Promise<any> {
        return await this.http.post(path, body).toPromise();
    }

    APIDelete(path: string, body: any, callback: (any) => void): any {
        ApiService.totalRequests++;

        const opts = {
            headers: null,
            body: body
        };

        let resp;

        this.http.delete(path, opts).subscribe((r) => {
            if (r === undefined || r === null) {
                r = this.emptyResponse;
            }
            resp = r;
        }, (err) => {
            resp = err.error;
            if (err.status === 401) {
                this.unauth();
            }
            callback(resp);
        }, () => {
            callback(resp);
        });
    }

    async APIDeleteAsync(path: string, body: any): Promise<any> {
        return await this.http.delete(path, body).toPromise();
    }
}
