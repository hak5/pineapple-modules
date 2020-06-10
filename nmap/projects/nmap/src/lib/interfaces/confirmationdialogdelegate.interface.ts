export interface ConfirmationDialogDelegate {
    title: string;
    message: string;
    handleResponse: (affirmative: boolean) => void;
}
