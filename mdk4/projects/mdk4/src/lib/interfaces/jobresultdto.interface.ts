export interface JobResultDTO<T> {
    is_complete: boolean;
    job_error: string,
    result: T
}
