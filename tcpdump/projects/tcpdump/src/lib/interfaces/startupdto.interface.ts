export interface StartupDTO {
    error: string;
    has_dependencies: boolean;
    interfaces: Array<string>;
    last_job: StartupLastJob;
}

export interface StartupLastJob {
    job_id: string;
    job_type: string;
    job_info: string;
}
